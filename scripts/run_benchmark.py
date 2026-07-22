#!/usr/bin/env python3
"""SCCS OS — Multi-level performance benchmark runner.

Runs Locust at 4 concurrency levels (50, 100, 250, 500) against a
multi-worker FastAPI server, then generates a consolidated baseline report.

Usage:
    python3 scripts/run_benchmark.py

Output:
    output/benchmark/locust_{50,100,250,500}.csv  (raw stats per level)
    output/benchmark/性能基线报告_v2.md              (consolidated report)
"""

from __future__ import annotations

import csv
import json
import os
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = REPO_ROOT / "output" / "benchmark"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# ── Config ──────────────────────────────────────────────────────────
HOST = "127.0.0.1"
PORT = 8765
BASE_URL = f"http://{HOST}:{PORT}"

# Concurrency levels to test (users, spawn_rate, run_time_seconds)
SCENARIOS = [
    (50, 10, 60, "Light load"),
    (100, 20, 90, "Medium load"),
    (250, 50, 120, "Heavy load"),
    (500, 50, 120, "Peak load"),
]

# uvicorn workers: macOS recommendation = 2-4 per physical core
WORKERS = 4

LOG = False  # set to True for verbose output


def log(msg: str) -> None:
    print(f"  {msg}", flush=True)


def run_server() -> subprocess.Popen:
    """Start FastAPI with multiple workers."""
    cmd = [
        sys.executable, "-m", "uvicorn",
        "sccsos.api.fastapi_app:create_app",
        "--host", HOST,
        "--port", str(PORT),
        "--workers", str(WORKERS),
        "--log-level", "warning",
    ]
    log(f"Starting server: {' '.join(cmd)}")
    proc = subprocess.Popen(
        cmd,
        cwd=REPO_ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    # Wait for server to be ready
    import urllib.request
    for _ in range(30):
        try:
            urllib.request.urlopen(f"{BASE_URL}/api/v1/health", timeout=2)
            log("Server is ready.")
            return proc
        except Exception:
            time.sleep(1)
    proc.kill()
    raise RuntimeError("Server failed to start")


def stop_server(proc: subprocess.Popen) -> None:
    proc.terminate()
    try:
        proc.wait(timeout=10)
        log("Server stopped.")
    except subprocess.TimeoutExpired:
        proc.kill()
        log("Server killed.")


def run_locust(users: int, rate: int, runtime: int, label: str) -> Path:
    """Run Locust in headless mode at a given concurrency level."""
    csv_prefix = str(OUTPUT_DIR / f"locust_{users}")
    cmd = [
        sys.executable, "-m", "locust",
        "-f", str(REPO_ROOT / "tests" / "locustfile.py"),
        "--headless",
        "-u", str(users),
        "-r", str(rate),
        "--run-time", f"{runtime}s",
        "--host", BASE_URL,
        "--csv", csv_prefix,
        "--html", str(OUTPUT_DIR / f"report_{users}.html"),
        "--only-summary",
    ]
    log(f"[{label}] locust -u {users} -r {rate} -t {runtime}s")
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=runtime + 30)
    if LOG:
        print(result.stdout[-2000:] if result.stdout else "")
        if result.stderr:
            print("STDERR:", result.stderr[-1000:], file=sys.stderr)
    return Path(f"{csv_prefix}_stats.csv")


def parse_stats(csv_path: Path) -> dict:
    """Parse Locust CSV stats into a dict keyed by endpoint name."""
    stats = {}
    if not csv_path.exists():
        log(f"  WARNING: {csv_path} not found")
        return stats
    with open(csv_path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = row["Name"]
            stats[name] = {
                "requests": int(row["Request Count"]),
                "failures": int(row["Failure Count"]),
                "failure_pct": round(
                    int(row["Failure Count"]) / max(int(row["Request Count"]), 1) * 100, 2
                ),
                "p50_ms": float(row["50%"]),
                "p95_ms": float(row["95%"]),
                "p99_ms": float(row["99%"]),
                "avg_ms": round(float(row["Average Response Time"]), 1),
                "rps": round(float(row["Requests/s"]), 1),
            }
    return stats


def generate_report(results: dict) -> str:
    """Generate a consolidated markdown baseline report."""
    lines = []
    lines.append("# SCCS OS 性能基线报告 v2")
    lines.append("")
    lines.append(f"> **版本**: v0.16.5 | **日期**: {time.strftime('%Y-%m-%d')}")
    lines.append(f"> **工具**: Locust 2.46.0")
    lines.append(f"> **服务器**: uvicorn --workers {WORKERS}")
    lines.append(f"> **后端**: SQLite WAL")
    lines.append(f"> **主机**: macOS (Apple Silicon)")
    lines.append("")

    lines.append("## 压测配置")
    lines.append("")
    lines.append("| 参数 | 值 |")
    lines.append("|------|-----|")
    lines.append(f"| uvicorn workers | {WORKERS} |")
    lines.append("| 每个 worker 并发模型 | sync (FastAPI 默认) |")
    lines.append("| 后端数据库 | SQLite WAL |")
    lines.append("")

    lines.append("## 多级并发结果")
    lines.append("")
    lines.append("| 并发级别 | 用户数 | 运行时长 | 总请求 | 成功率 | 吞吐量(RPS) | P50 | P95 | P99  |")
    lines.append("|---------|:-----:|:-------:|:-----:|:------:|:----------:|:---:|:---:|:----:|")

    # Aggregate per-scenario
    for users, rate, runtime, desc in SCENARIOS:
        stats = results.get(str(users), {})
        agg = stats.get("Aggregated", {})
        total_req = agg.get("requests", 0)
        total_fail = agg.get("failures", 0)
        success_pct = round(
            (total_req - total_fail) / max(total_req, 1) * 100, 2
        )
        p50 = agg.get("p50_ms", 0)
        p95 = agg.get("p95_ms", 0)
        p99 = agg.get("p99_ms", 0)
        rps = agg.get("rps", 0)
        lines.append(
            f"| {desc} | {users} | {runtime}s | {total_req} | "
            f"{success_pct}% | {rps} | {p50}ms | {p95}ms | {p99}ms |"
        )

    lines.append("")
    lines.append("## 端点级指标（500 并发）")
    lines.append("")
    lines.append("| 端点 | 请求数 | 成功率 | P50 | P95 | P99 | 平均 | RPS |")
    lines.append("|------|:-----:|:------:|:---:|:---:|:---:|:----:|:---:|")

    peak_stats = results.get(str(500), {})
    for ep_name in [
        "GET /health",
        "GET /agents",
        "GET /agents/{name}",
        "GET /traces",
        "GET /workflows",
        "GET /sessions",
        "GET /audit/report",
        "GET /billing/summary",
        "GET /quotas/{tenant_id}",
        "POST /agents/register",
        "POST /agents/{name}/start",
        "POST /agents/{name}/stop",
    ]:
        s = peak_stats.get(ep_name, {})
        if not s:
            continue
        success_pct = round(100 - s.get("failure_pct", 0), 2)
        lines.append(
            f"| `{ep_name}` | {s.get('requests', 0)} | {success_pct}% | "
            f"{s.get('p50_ms', '-')}ms | {s.get('p95_ms', '-')}ms | "
            f"{s.get('p99_ms', '-')}ms | {s.get('avg_ms', '-')}ms | "
            f"{s.get('rps', '-')} |"
        )

    lines.append("")
    lines.append("## 分析与建议")
    lines.append("")
    lines.append("### 对比 v1 基线")
    lines.append("")
    lines.append("v1 基线（单 worker）在 500 并发下 97.89% 失败（ConnectionResetError）。")
    lines.append("v2 使用多 worker 部署以消除基础设施瓶颈，获取真实应用层性能数据。")
    lines.append("")
    lines.append("### 判断标准")
    lines.append("")
    lines.append("| 指标 | 目标 | 状态 |")
    lines.append("|------|------|------|")
    lines.append("| 500 并发成功率 | ≥99% | — |")
    lines.append("| P95 响应时间 | ≤500ms | — |")
    lines.append("| 吞吐量 | ≥500 RPS | — |")
    lines.append("| 零 5xx 错误 | 是 | — |")
    lines.append("| 零内存泄漏 | 72h 验证 | — |")

    return "\n".join(lines)


def main():
    print(f"\n{'='*60}")
    print(f"  SCCS OS 性能基线压测 v2")
    print(f"  服务器: uvicorn x{WORKERS} workers")
    print(f"  输出: {OUTPUT_DIR}")
    print(f"{'='*60}\n")

    server_proc = run_server()

    try:
        results = {}
        for users, rate, runtime, desc in SCENARIOS:
            print(f"\n--- [{desc}] {users} users @ {rate}/s for {runtime}s ---")
            csv_path = run_locust(users, rate, runtime, desc)
            stats = parse_stats(csv_path)
            results[str(users)] = stats

            # Print quick summary
            agg = stats.get("Aggregated", {})
            if agg:
                success_pct = round(
                    (agg["requests"] - agg["failures"]) / max(agg["requests"], 1) * 100, 2
                )
                print(f"  => {agg['requests']} req, {success_pct}% success, "
                      f"{agg['rps']} RPS, P95={agg['p95_ms']}ms")

        # Generate report
        report = generate_report(results)
        report_path = OUTPUT_DIR / "性能基线报告_v2.md"
        report_path.write_text(report)
        print(f"\n{'='*60}")
        print(f"  ✅ 基线报告生成: {report_path}")
        print(f"{'='*60}\n")

    finally:
        stop_server(server_proc)


if __name__ == "__main__":
    main()
