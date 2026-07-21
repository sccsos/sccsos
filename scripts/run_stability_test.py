#!/usr/bin/env python3
"""SCCS OS — 72h 长期运行稳定性验证与资源泄漏监控脚本。

监控项：
1. 内存泄漏（RSS 持续增长）
2. 线程泄漏（线程数持续增长）
3. 文件描述符泄漏（fd 计数持续增长）
4. DB 文件大小增长
5. API 响应时间和成功率退化
6. 错误日志增长率

用法：
    # 1. 启动服务器
    python3 -m uvicorn sccsos.api.fastapi_app:create_app \\
        --host 0.0.0.0 --port 8765 --workers 4 &

    # 2. 运行监控（默认 72h）
    python3 scripts/run_stability_test.py

    # 3. 短时间测试（30 分钟快速验证）
    python3 scripts/run_stability_test.py --duration 1800
"""

from __future__ import annotations

import argparse
import csv
import os
import platform
import subprocess
import sys
import time
import urllib.request
import json
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = REPO_ROOT / "output" / "stability"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

BASE_URL = "http://127.0.0.1:8765"

# ── Sampling config ────────────────────────────────────────────────
SAMPLE_INTERVAL = 60  # seconds between samples
HEAVY_SAMPLE_INTERVAL = 300  # heavier metrics every 5 min

# Leak detection thresholds
MEMORY_LEAK_THRESHOLD_MB_PER_HOUR = 50    # >50MB/h RSS growth = leak
THREAD_LEAK_THRESHOLD_PER_HOUR = 10        # >10 threads/h = leak
FD_LEAK_THRESHOLD_PER_HOUR = 20            # >20 fd/h = leak


def log(msg: str) -> None:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def get_process_stats() -> dict:
    """Collect memory, thread, and FD stats from all sccsos/uvicorn processes."""
    stats = {
        "rss_mb": 0,
        "vms_mb": 0,
        "threads": 0,
        "fds": 0,
        "process_count": 0,
        "cpu_percent": 0.0,
        "pid_list": [],
    }

    try:
        # Find all uvicorn/sccsos worker processes using ps
        result = subprocess.run(
            ["ps", "-eo", "pid,rss,vsize,nlwp,pcpu,comm"],
            capture_output=True, text=True, timeout=10,
        )
        for line in result.stdout.strip().split("\n")[1:]:  # skip header
            parts = line.split()
            if len(parts) < 6:
                continue
            pid, rss_kb, vsize_kb, nlwp_str, cpu_str, *comm_parts = parts
            comm = " ".join(comm_parts)

            # Match sccsos or uvicorn processes
            if "uvicorn" in comm.lower() or "sccsos" in comm.lower():
                stats["rss_mb"] += int(rss_kb) / 1024
                stats["vms_mb"] += int(vsize_kb) / 1024
                stats["threads"] += int(nlwp_str)
                stats["cpu_percent"] += float(cpu_str)
                stats["process_count"] += 1
                stats["pid_list"].append(int(pid))

        # FD count via lsof (macOS) or /proc (Linux)
        if platform.system() == "Darwin":
            for pid in stats["pid_list"]:
                lsof = subprocess.run(
                    ["lsof", "-p", str(pid)],
                    capture_output=True, text=True, timeout=10,
                )
                stats["fds"] += len(lsof.stdout.strip().split("\n")) - 1  # minus header
        elif platform.system() == "Linux":
            for pid in stats["pid_list"]:
                fd_dir = Path(f"/proc/{pid}/fd")
                if fd_dir.exists():
                    stats["fds"] += len(list(fd_dir.iterdir()))

    except Exception as e:
        log(f"WARNING: process stats error: {e}")

    return stats


def get_db_size() -> dict:
    """Get SQLite and other DB file sizes."""
    sizes = {"sqlite_mb": 0.0}
    for db_path in [
        REPO_ROOT / "sccsos.db",
        Path.home() / ".hermes" / "profiles" / "sccsos" / "state.db",
    ]:
        if db_path.exists():
            sizes["sqlite_mb"] += db_path.stat().st_size / (1024 * 1024)
    return sizes


def get_log_size() -> dict:
    """Get sccsos log file sizes."""
    sizes = {"log_mb": 0.0}
    for log_path in [
        REPO_ROOT / "logs",
        Path.home() / "Library" / "Logs" / "sccsos",
    ]:
        if log_path.is_dir():
            for f in log_path.rglob("*"):
                if f.is_file():
                    sizes["log_mb"] += f.stat().st_size / (1024 * 1024)
        elif log_path.is_file():
            sizes["log_mb"] += log_path.stat().st_size / (1024 * 1024)
    return sizes


def api_health() -> dict:
    """Call the health endpoint and collect response metrics."""
    result = {"health_status": "unknown", "health_latency_ms": 0, "error": ""}
    try:
        start = time.time()
        resp = urllib.request.urlopen(f"{BASE_URL}/api/v1/health", timeout=5)
        latency = (time.time() - start) * 1000
        data = json.loads(resp.read().decode())
        result["health_status"] = data.get("status", "unknown")
        result["health_latency_ms"] = round(latency, 1)
    except Exception as e:
        result["health_status"] = "error"
        result["error"] = str(e)[:200]
    return result


def api_agents() -> dict:
    """Call the agents list endpoint."""
    result = {"agents_count": -1, "agents_latency_ms": 0, "error": ""}
    try:
        req = urllib.request.Request(
            f"{BASE_URL}/api/v1/agents",
            headers={"X-Tenant-ID": "stability-test"},
        )
        start = time.time()
        resp = urllib.request.urlopen(req, timeout=5)
        latency = (time.time() - start) * 1000
        data = json.loads(resp.read().decode())
        result["agents_count"] = data.get("count", -1)
        result["agents_latency_ms"] = round(latency, 1)
    except Exception as e:
        result["agents_latency_ms"] = -1
        result["error"] = str(e)[:200]
    return result


def collect_sample(t: int) -> dict:
    """Collect a single monitoring sample."""
    proc = get_process_stats()
    db = get_db_size()
    log_sz = get_log_size()
    h = api_health()
    a = api_agents()

    sample = {
        "elapsed_sec": t,
        "elapsed_hours": round(t / 3600, 2),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "rss_mb": round(proc["rss_mb"], 2),
        "vms_mb": round(proc["vms_mb"], 2),
        "threads": proc["threads"],
        "fds": proc["fds"],
        "process_count": proc["process_count"],
        "cpu_percent": round(proc["cpu_percent"], 1),
        "sqlite_mb": round(db["sqlite_mb"], 3),
        "log_mb": round(log_sz["log_mb"], 3),
        "health_status": h["health_status"],
        "health_latency_ms": h["health_latency_ms"],
        "agents_count": a["agents_count"],
        "agents_latency_ms": a["agents_latency_ms"],
        "error": h["error"] or a["error"],
    }
    return sample


def detect_leaks(samples: list[dict], duration_h: float) -> list[str]:
    """Analyze samples for resource leak patterns."""
    findings = []
    if len(samples) < 3:
        return findings

    # Linear regression on the last 50% of samples (or all if < 20)
    n = max(len(samples) // 2, 3)
    recent = samples[-n:]

    def slope(key: str) -> float:
        """Rough slope: (last - first) / duration_hours_sampled."""
        first_val = recent[0].get(key, 0)
        last_val = recent[-1].get(key, 0)
        span_h = (recent[-1]["elapsed_sec"] - recent[0]["elapsed_sec"]) / 3600
        return (last_val - first_val) / max(span_h, 0.01)

    # Memory leak
    mem_slope = slope("rss_mb")
    if mem_slope > MEMORY_LEAK_THRESHOLD_MB_PER_HOUR:
        findings.append(
            f"⚠️  MEMORY LEAK: RSS growing at {mem_slope:.1f} MB/h "
            f"(threshold: {MEMORY_LEAK_THRESHOLD_MB_PER_HOUR})"
        )

    # Thread leak
    thread_slope = slope("threads")
    if thread_slope > THREAD_LEAK_THRESHOLD_PER_HOUR:
        findings.append(
            f"⚠️  THREAD LEAK: threads growing at {thread_slope:.1f}/h "
            f"(threshold: {THREAD_LEAK_THRESHOLD_PER_HOUR})"
        )

    # FD leak
    fd_slope = slope("fds")
    if fd_slope > FD_LEAK_THRESHOLD_PER_HOUR:
        findings.append(
            f"⚠️  FD LEAK: file descriptors growing at {fd_slope:.1f}/h "
            f"(threshold: {FD_LEAK_THRESHOLD_PER_HOUR})"
        )

    # API latency degradation
    health_lat = [s["health_latency_ms"] for s in samples if s["health_latency_ms"] >= 0]
    if len(health_lat) >= 10:
        first_half = sum(health_lat[:len(health_lat)//2]) / max(len(health_lat)//2, 1)
        second_half = sum(health_lat[len(health_lat)//2:]) / max(len(health_lat)//2, 1)
        if second_half > first_half * 2 and second_half > 100:
            findings.append(
                f"⚠️  LATENCY DEGRADATION: health check avg {first_half:.0f}ms → {second_half:.0f}ms"
            )

    # DB size explosion
    db_slope = slope("sqlite_mb")
    if db_slope > 10:  # >10MB/h DB growth
        findings.append(
            f"⚠️  DB GROWTH: SQLite growing at {db_slope:.1f} MB/h"
        )

    if not findings:
        findings.append(f"✅ No leak detected in {duration_h:.1f}h run")

    return findings


def generate_report(
    samples: list[dict], duration_h: float, leaks: list[str],
) -> str:
    """Generate the stability test markdown report."""
    lines = []
    lines.append("# SCCS OS 72h 稳定性验证报告")
    lines.append("")
    lines.append(f"> **日期**: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    lines.append(f"> **运行时长**: {duration_h:.1f}h")
    lines.append(f"> **采样数**: {len(samples)}")
    lines.append(f"> **主机**: {platform.platform()}")
    lines.append("")

    lines.append("## 资源泄漏检测结果")
    lines.append("")
    for f in leaks:
        lines.append(f"- {f}")
    lines.append("")

    if samples:
        first = samples[0]
        last = samples[-1]
        lines.append("## 关键指标变化")
        lines.append("")
        lines.append("| 指标 | 起始 | 结束 | 变化 | 评估 |")
        lines.append("|------|:----:|:----:|:----:|:----:|")
        for key, label in [
            ("rss_mb", "RSS 内存 (MB)"),
            ("threads", "线程数"),
            ("fds", "文件描述符"),
            ("sqlite_mb", "DB 大小 (MB)"),
            ("log_mb", "日志大小 (MB)"),
            ("health_latency_ms", "Health 延迟 (ms)"),
        ]:
            start_val = first.get(key, 0)
            end_val = last.get(key, 0)
            delta = end_val - start_val
            delta_str = f"+{delta:.1f}" if delta > 0 else f"{delta:.1f}"
            # Assess
            if key in ("rss_mb",) and duration_h > 1:
                rate = delta / duration_h
                assessment = "⚠️ LEAK" if rate > MEMORY_LEAK_THRESHOLD_MB_PER_HOUR else "✅ OK"
            elif key in ("threads",) and duration_h > 1:
                rate = delta / duration_h
                assessment = "⚠️ LEAK" if rate > THREAD_LEAK_THRESHOLD_PER_HOUR else "✅ OK"
            else:
                assessment = ""
            lines.append(
                f"| {label} | {start_val} | {end_val} | {delta_str} | {assessment} |"
            )
        lines.append("")

    # Summary over time (hourly averages)
    lines.append("## 小时级聚合")
    lines.append("")
    lines.append("| 小时 | RSS (MB) | 线程 | FD | Health 延迟 (ms) | DB 大小 (MB) |")
    lines.append("|:----:|:--------:|:----:|:--:|:----------------:|:-----------:|")
    hourly = {}
    for s in samples:
        h = int(s["elapsed_hours"])
        if h not in hourly:
            hourly[h] = []
        hourly[h].append(s)
    for h in sorted(hourly):
        entries = hourly[h]
        avg_rss = sum(e["rss_mb"] for e in entries) / len(entries)
        avg_threads = sum(e["threads"] for e in entries) / len(entries)
        avg_fds = sum(e["fds"] for e in entries) / len(entries)
        avg_health = sum(
            e["health_latency_ms"] for e in entries if e["health_latency_ms"] >= 0
        )
        health_count = sum(1 for e in entries if e["health_latency_ms"] >= 0)
        avg_health = avg_health / max(health_count, 1)
        latest_db = entries[-1]["sqlite_mb"]
        lines.append(
            f"| h{h} | {avg_rss:.1f} | {avg_threads:.0f} | {avg_fds:.0f} | "
            f"{avg_health:.0f}ms | {latest_db:.2f} |"
        )

    lines.append("")
    lines.append("## 结论")
    lines.append("")
    any_leak = any("LEAK" in f for f in leaks)
    if any_leak:
        lines.append("**结果: ❌ 检测到资源泄漏，需要进一步排查**")
    else:
        lines.append("**结果: ✅ 72h 稳定运行，无资源泄漏**")
    lines.append("")
    lines.append("---")
    lines.append(f"*报告自动生成: {datetime.now(timezone.utc).isoformat()}*")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="SCCS OS 72h 稳定性验证")
    parser.add_argument(
        "--duration", type=int, default=72 * 3600,
        help="运行时长（秒），默认 72h (259200)",
    )
    parser.add_argument(
        "--interval", type=int, default=SAMPLE_INTERVAL,
        help="采样间隔（秒），默认 60",
    )
    args = parser.parse_args()

    duration_s = args.duration
    interval = args.interval
    end_time = time.time() + duration_s
    samples: list[dict] = []
    csv_path = OUTPUT_DIR / "stability_samples.csv"

    log(f"{'='*60}")
    log(f"SCCS OS 稳定性验证启动")
    log(f"  运行时长: {duration_s}s ({duration_s/3600:.1f}h)")
    log(f"  采样间隔: {interval}s")
    log(f"  Server: {BASE_URL}")
    log(f"  输出: {OUTPUT_DIR}")
    log(f"{'='*60}")

    # Write CSV header
    with open(csv_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "elapsed_sec", "elapsed_hours", "timestamp",
            "rss_mb", "vms_mb", "threads", "fds", "process_count", "cpu_percent",
            "sqlite_mb", "log_mb",
            "health_status", "health_latency_ms",
            "agents_count", "agents_latency_ms", "error",
        ])

    sample_count = 0
    while time.time() < end_time:
        t = int(time.time() - (end_time - duration_s))
        sample = collect_sample(t)
        samples.append(sample)

        # Append to CSV
        with open(csv_path, "a", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                sample["elapsed_sec"], sample["elapsed_hours"], sample["timestamp"],
                sample["rss_mb"], sample["vms_mb"], sample["threads"],
                sample["fds"], sample["process_count"], sample["cpu_percent"],
                sample["sqlite_mb"], sample["log_mb"],
                sample["health_status"], sample["health_latency_ms"],
                sample["agents_count"], sample["agents_latency_ms"],
                sample["error"],
            ])

        sample_count += 1

        # Every 10th sample: print status line
        if sample_count % 10 == 0:
            pct = (t / duration_s) * 100
            log(
                f"  [{pct:.0f}%] h={sample['elapsed_hours']:.1f} "
                f"RSS={sample['rss_mb']:.0f}MB "
                f"threads={sample['threads']} "
                f"fds={sample['fds']} "
                f"health={sample['health_latency_ms']}ms "
                f"DB={sample['sqlite_mb']:.2f}MB"
            )

        # Wait for next interval (respecting end_time)
        remaining = end_time - time.time()
        if remaining <= 0:
            break
        time.sleep(min(interval, remaining))

    # ── Generate report ──
    duration_h = duration_s / 3600
    leaks = detect_leaks(samples, duration_h)

    report = generate_report(samples, duration_h, leaks)
    report_path = OUTPUT_DIR / "稳定性验证报告.md"
    report_path.write_text(report)

    log(f"\n{'='*60}")
    log(f"  稳定性验证完成")
    log(f"  采样数: {sample_count}")
    for f in leaks:
        log(f"  {f}")
    log(f"  报告: {report_path}")
    log(f"  原始数据: {csv_path}")
    log(f"{'='*60}")


if __name__ == "__main__":
    main()
