#!/usr/bin/env python3
"""SCCS OS — 72h 长期运行稳定性监控脚本

使用方式:
    # 启动服务器
    python3 -m sccsos.api.fastapi_app --port 8765 &

    # 本脚本每 5 分钟采集一次系统 + 应用指标
    python3 scripts/stability_monitor.py --duration 72h --interval 5m

输出: output/stability/ 目录下 CSV + JSON 报告
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


# ── Metrics collection ──────────────────────────────────────────────


def collect_system_metrics() -> dict:
    """Collect OS-level resource metrics."""
    import psutil

    proc = psutil.Process()
    mem = proc.memory_info()
    return {
        "rss_mb": mem.rss / 1024 / 1024,
        "vms_mb": mem.vms / 1024 / 1024,
        "cpu_percent": proc.cpu_percent(interval=0.1),
        "open_fds": proc.num_fds(),
        "threads": proc.num_threads(),
        "ctx_switches": proc.num_ctx_switches().voluntary,
        "system_cpu": psutil.cpu_percent(interval=0.1),
        "system_mem_percent": psutil.virtual_memory().percent,
    }


def collect_app_metrics(base_url: str, timeout: int = 5) -> dict:
    """Collect application-level health metrics."""
    metrics = {}
    endpoints = {
        "health": f"{base_url}/api/v1/health",
        "agents": f"{base_url}/api/v1/agents",
        "traces": f"{base_url}/api/v1/traces",
        "sessions": f"{base_url}/api/v1/sessions",
    }
    headers = {"X-Role": "admin"}

    for name, url in endpoints.items():
        try:
            t0 = time.monotonic()
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                elapsed = time.monotonic() - t0
                data = json.loads(resp.read().decode())
                metrics[f"{name}_status"] = resp.status
                metrics[f"{name}_latency_ms"] = round(elapsed * 1000, 1)
                if name == "agents" and "agents" in data:
                    metrics["agent_count"] = len(data["agents"])
        except Exception as e:
            metrics[f"{name}_status"] = 0
            metrics[f"{name}_error"] = str(e)[:100]

    return metrics


def collect_db_metrics(base_url: str) -> dict:
    """Collect DB-level metrics from health endpoint."""
    try:
        req = urllib.request.Request(
            f"{base_url}/api/v1/health",
            headers={"X-Role": "admin"},
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())
            db = data.get("database", {})
            return {
                "db_status": db.get("status", "unknown"),
                "db_agent_count": db.get("agent_count", -1),
            }
    except Exception as e:
        return {"db_status": "error", "db_error": str(e)[:100]}


# ── Main loop ───────────────────────────────────────────────────────


def run_monitor(base_url: str, interval_sec: int, duration_sec: int, output_dir: Path):
    """Continuous monitoring loop."""
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "stability_metrics.csv"
    json_path = output_dir / "stability_alerts.json"

    # Write CSV header
    with open(csv_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "timestamp", "elapsed_hours",
            "rss_mb", "vms_mb", "cpu_pct", "open_fds", "threads",
            "system_cpu", "system_mem_pct",
            "health_status", "health_latency_ms",
            "agent_count", "db_agent_count",
            "site_up",
        ])

    alerts = []
    start_time = time.monotonic()
    tick = 0
    site_up_count = 0
    site_down_count = 0

    print(f"Stability monitor started at {datetime.now(timezone.utc).isoformat()}")
    print(f"  Target: {base_url}")
    print(f"  Interval: {interval_sec}s × {duration_sec // interval_sec} ticks")
    print(f"  Output: {csv_path}")
    print(f"  {'─' * 60}")

    while True:
        elapsed = time.monotonic() - start_time
        if elapsed > duration_sec:
            break

        tick += 1
        ts = datetime.now(timezone.utc).isoformat()
        elapsed_hours = round(elapsed / 3600, 2)

        # Collect metrics
        sys_metrics = collect_system_metrics()
        app_metrics = collect_app_metrics(base_url)
        db_metrics = collect_db_metrics(base_url)

        health_ok = app_metrics.get("health_status") == 200
        if health_ok:
            site_up_count += 1
        else:
            site_down_count += 1

        # Check for anomalies
        alerts_this_tick = []
        if sys_metrics["rss_mb"] > 500:
            alerts_this_tick.append(f"MEM_HIGH: RSS={sys_metrics['rss_mb']:.0f}MB")
        if sys_metrics["open_fds"] > 500:
            alerts_this_tick.append(f"FD_LEAK: open_fds={sys_metrics['open_fds']}")
        if sys_metrics["threads"] > 200:
            alerts_this_tick.append(f"THREAD_LEAK: threads={sys_metrics['threads']}")
        if not health_ok:
            alerts_this_tick.append(f"SITE_DOWN: health returned {app_metrics.get('health_status')}")

        for alert in alerts_this_tick:
            alerts.append({"timestamp": ts, "elapsed_hours": elapsed_hours, "alert": alert})
            print(f"  ⚠ [{elapsed_hours:.2f}h] {alert}")

        # Append to CSV
        with open(csv_path, "a", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                ts, elapsed_hours,
                round(sys_metrics["rss_mb"], 1),
                round(sys_metrics["vms_mb"], 1),
                round(sys_metrics["cpu_percent"], 1),
                sys_metrics["open_fds"],
                sys_metrics["threads"],
                round(sys_metrics["system_cpu"], 1),
                round(sys_metrics["system_mem_percent"], 1),
                app_metrics.get("health_status", 0),
                app_metrics.get("health_latency_ms", -1),
                app_metrics.get("agent_count", -1),
                db_metrics.get("db_agent_count", -1),
                1 if health_ok else 0,
            ])

        # Progress every 6 ticks
        if tick % 6 == 0 or alerts_this_tick:
            site_pct = site_up_count / (site_up_count + site_down_count) * 100 if (site_up_count + site_down_count) > 0 else 0
            print(f"  [{elapsed_hours:.2f}h] tick={tick} RSS={sys_metrics['rss_mb']:.0f}MB "
                  f"FD={sys_metrics['open_fds']} THR={sys_metrics['threads']} "
                  f"CPU={sys_metrics['cpu_percent']:.1f}% uptime={site_pct:.0f}%")

        # Save alerts
        with open(json_path, "w") as f:
            json.dump(alerts, f, indent=2, ensure_ascii=False)

        time.sleep(interval_sec)

    # Final report
    site_pct = site_up_count / (site_up_count + site_down_count) * 100 if (site_up_count + site_down_count) > 0 else 0
    print(f"  {'─' * 60}")
    print(f"Monitor finished at {datetime.now(timezone.utc).isoformat()}")
    print(f"  Duration: {elapsed/3600:.2f}h ({tick} ticks)")
    print(f"  Site uptime: {site_up_count}/{site_up_count + site_down_count} = {site_pct:.1f}%")
    print(f"  Alerts: {len(alerts)}")
    print(f"  Peak RSS: see CSV for max(rss_mb)")
    print(f"  Results: {csv_path}")
    print(f"  Alerts:  {json_path}")


# ── Entry point ─────────────────────────────────────────────────────


def parse_duration(s: str) -> int:
    """Parse '72h', '30m', '3600s' to seconds."""
    s = s.strip().lower()
    if s.endswith("h"):
        return int(s[:-1]) * 3600
    elif s.endswith("m"):
        return int(s[:-1]) * 60
    elif s.endswith("s"):
        return int(s[:-1])
    else:
        return int(s)


def parse_interval(s: str) -> int:
    """Parse '5m', '30s' to seconds."""
    return parse_duration(s)


def main():
    parser = argparse.ArgumentParser(description="SCCS OS 72h 稳定性监控")
    parser.add_argument("--base-url", default="http://localhost:8765", help="API base URL")
    parser.add_argument("--duration", default="72h", help="Monitoring duration (72h, 24h, 3600s)")
    parser.add_argument("--interval", default="5m", help="Collection interval (5m, 30s)")
    parser.add_argument("--output", default="output/stability", help="Output directory")
    args = parser.parse_args()

    duration_sec = parse_duration(args.duration)
    interval_sec = parse_interval(args.interval)
    output_dir = Path(args.output)

    run_monitor(args.base_url, interval_sec, duration_sec, output_dir)


if __name__ == "__main__":
    main()
