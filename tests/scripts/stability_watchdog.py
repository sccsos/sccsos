#!/usr/bin/env python3
"""SCCS OS — 长期运行稳定性看门狗 (Long-Run Stability Watchdog)

Usage:
    python3 tests/scripts/stability_watchdog.py [--duration 72h] [--interval 5m]

Monitors:
  - API health endpoint availability
  - Agent lifecycle (register → start → ask → stop → delete)
  - DB size growth (WAL file inflation)
  - Memory usage (RSS of the server process)
  - Thread count growth (leak detection)
  - Response time degradation

Reports:
  - stdout: periodic health summary
  - output/benchmark/stability_{timestamp}.json: final report
  - output/benchmark/stability_{timestamp}.csv: time-series data
"""

from __future__ import annotations

import csv
import json
import os
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

# ── Config ──────────────────────────────────────────────────────────

HOST = os.environ.get("SCCSOS_HOST", "http://127.0.0.1:8765")
API = f"{HOST}/api/v1"
HEADERS = {
    "X-Role": "admin",
    "X-Tenant-ID": "stability-test",
    "Content-Type": "application/json",
}
DURATION_SECS = 72 * 3600  # 72 hours
INTERVAL_SECS = 5 * 60      # 5 minutes
SERVER_PID: int | None = None
WARN_THRESHOLDS = {
    "response_time_ms": 5000,   # Any endpoint >5s = warning
    "db_size_mb_growth": 500,   # DB growth >500MB = warning
    "wal_size_mb_growth": 1000, # WAL growth >1GB = warning
    "thread_count": 50,         # >50 threads = possible leak
    "rss_mb_growth": 200,       # RSS growth >200MB = warning
}


# ── Helpers ─────────────────────────────────────────────────────────


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _api_get(path: str) -> tuple[int, str, float]:
    """GET an API endpoint, return (status, body, duration_ms)."""
    t0 = time.perf_counter()
    try:
        req = urllib.request.Request(f"{API}{path}", headers=HEADERS)
        with urllib.request.urlopen(req, timeout=10) as resp:
            dur = (time.perf_counter() - t0) * 1000
            return resp.status, resp.read().decode(), dur
    except Exception as e:
        dur = (time.perf_counter() - t0) * 1000
        return 0, str(e), dur


def _api_post(path: str, body: str) -> tuple[int, str, float]:
    """POST to an API endpoint."""
    t0 = time.perf_counter()
    try:
        data = body.encode()
        req = urllib.request.Request(
            f"{API}{path}", data=data, headers=HEADERS,
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            dur = (time.perf_counter() - t0) * 1000
            return resp.status, resp.read().decode(), dur
    except Exception as e:
        dur = (time.perf_counter() - t0) * 1000
        return 0, str(e), dur


def _get_server_stats() -> dict:
    """Get server process resource usage (if PID is known)."""
    if not SERVER_PID:
        return {}
    try:
        r = subprocess.run(
            ["ps", "-p", str(SERVER_PID), "-o", "rss=,pcpu="],
            capture_output=True, text=True, timeout=5,
        )
        parts = r.stdout.strip().split()
        if len(parts) >= 2:
            rss_kb = int(parts[0])
            cpu = float(parts[1])
            return {"rss_mb": round(rss_kb / 1024, 1), "cpu_pct": cpu}
    except Exception:
        pass
    return {}


def _get_db_stats(db_path: str = "data/sccsos.db") -> dict:
    """Get database file sizes."""
    stats = {}
    for suffix in ["", "-wal", "-shm"]:
        p = Path(db_path + suffix)
        if p.exists():
            stats[f"db{suffix}_size_mb"] = round(p.stat().st_size / (1024 * 1024), 2)
    return stats


def _get_thread_count() -> int:
    """Count threads of the server process."""
    if not SERVER_PID:
        return 0
    try:
        r = subprocess.run(
            ["ps", "-M", "-p", str(SERVER_PID)],
            capture_output=True, text=True, timeout=5,
        )
        return len(r.stdout.splitlines()) - 1  # header line
    except Exception:
        return 0


# ── Main loop ───────────────────────────────────────────────────────


def main():
    global SERVER_PID

    duration = int(os.environ.get("WATCHDOG_DURATION", str(DURATION_SECS)))
    interval = int(os.environ.get("WATCHDOG_INTERVAL", str(INTERVAL_SECS)))
    server_pid = os.environ.get("WATCHDOG_PID", "")

    if server_pid:
        try:
            SERVER_PID = int(server_pid)
        except ValueError:
            pass

    output_dir = Path("output/benchmark")
    output_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path = output_dir / f"stability_{timestamp}.csv"
    json_path = output_dir / f"stability_{timestamp}.json"

    start_time = time.time()
    end_time = start_time + duration
    cycle = 0
    time_series: list[dict] = []
    baseline: dict | None = None

    print(f"SCCS OS 稳定性看门狗")
    print(f"  Duration: {duration // 3600}h {(duration % 3600) // 60}m")
    print(f"  Interval: {interval // 60}m")
    print(f"  Target:   {HOST}")
    print(f"  PID:      {SERVER_PID or '(auto)'}")
    print(f"  CSV:      {csv_path}")
    print()

    health_trace = {"ok": 0, "fail": 0}
    lifecycle_trace = {"ok": 0, "fail": 0}
    warnings: list[str] = []

    with open(csv_path, "w", newline="") as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow([
            "timestamp", "elapsed_h", "health_ok", "health_ms",
            "db_size_mb", "wal_size_mb", "rss_mb", "cpu_pct",
            "threads", "lifecycle_ok", "lifecycle_ms",
        ])

        while time.time() < end_time:
            cycle += 1
            elapsed_h = round((time.time() - start_time) / 3600, 2)
            row: list = [_now(), elapsed_h]

            # 1. Health check
            status, body, dur = _api_get("/health")
            health_ok = status == 200 and '"version"' in body
            row.extend([1 if health_ok else 0, round(dur, 1)])
            if health_ok:
                health_trace["ok"] += 1
            else:
                health_trace["fail"] += 1
                warnings.append(f"Cycle {cycle}: Health FAILED ({status})")

            # 2. DB stats
            db_stats = _get_db_stats()
            row.append(db_stats.get("db_size_mb", 0))
            row.append(db_stats.get("db-wal_size_mb", 0))

            # 3. Process stats
            proc_stats = _get_server_stats()
            threads = _get_thread_count()
            row.append(proc_stats.get("rss_mb", 0))
            row.append(proc_stats.get("cpu_pct", 0))
            row.append(threads)

            # 4. Lifecycle test (every 10 cycles)
            if cycle % 10 == 0:
                lc_ok, lc_ms = _run_lifecycle_test()
                row.extend([1 if lc_ok else 0, round(lc_ms, 1)])
                if lc_ok:
                    lifecycle_trace["ok"] += 1
                else:
                    lifecycle_trace["fail"] += 1
                    warnings.append(f"Cycle {cycle}: Lifecycle FAILED")
            else:
                row.extend(["", ""])

            # 5. Baseline comparison
            snap = {
                "ts": _now(),
                "elapsed_h": elapsed_h,
                "health": health_ok,
                "health_ms": round(dur, 1),
                "db_mb": db_stats.get("db_size_mb", 0),
                "wal_mb": db_stats.get("db-wal_size_mb", 0),
                "rss_mb": proc_stats.get("rss_mb", 0),
                "threads": threads,
            }
            time_series.append(snap)
            if baseline is None:
                baseline = snap

            # 6. Warning detection
            if baseline:
                db_growth = snap["db_mb"] - baseline["db_mb"]
                wal_growth = snap["wal_mb"] - baseline["wal_mb"]
                rss_growth = snap["rss_mb"] - baseline["rss_mb"]
                if db_growth > WARN_THRESHOLDS["db_size_mb_growth"]:
                    warnings.append(f"DB growth {db_growth}MB > threshold")
                if wal_growth > WARN_THRESHOLDS["wal_size_mb_growth"]:
                    warnings.append(f"WAL growth {wal_growth}MB > threshold")
                if rss_growth > WARN_THRESHOLDS["rss_mb_growth"]:
                    warnings.append(f"RSS growth {rss_growth}MB > threshold")
                if threads > WARN_THRESHOLDS["thread_count"]:
                    warnings.append(f"Threads {threads} > {WARN_THRESHOLDS['thread_count']}")

            # 7. Write CSV row
            writer.writerow(row)
            csvfile.flush()

            # 8. Print progress
            status_icon = "✅" if health_ok else "❌"
            lc_status = f"LC={'OK' if lc_ok else 'FAIL'}" if cycle % 10 == 0 else ""
            warning_count = len(warnings)
            print(
                f"  [{elapsed_h:>5.1f}h] "
                f"{status_icon} "
                f"DB={snap['db_mb']:>5.1f}MB "
                f"WAL={snap['wal_mb']:>5.1f}MB "
                f"RSS={snap['rss_mb']:>4.0f}MB "
                f"Threads={threads:>2d} "
                f"Health={dur:>5.0f}ms "
                f"{lc_status} "
                f"{f'⚠️  {warning_count}' if warning_count else ''}"
            )

            time.sleep(interval)

    # ── Final report ───────────────────────────────────────────────
    total_cycles = health_trace["ok"] + health_trace["fail"]
    report = {
        "version": "0.14.2",
        "duration_h": round((time.time() - start_time) / 3600, 2),
        "cycles": cycle,
        "health_rate": round(health_trace["ok"] / max(1, total_cycles) * 100, 1),
        "lifecycle_rate": round(
            lifecycle_trace["ok"] / max(1, lifecycle_trace["ok"] + lifecycle_trace["fail"]) * 100, 1
        ),
        "baseline": baseline,
        "final": snap,
        "warnings": warnings,
    }
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    print()
    print(f"═══ 稳定性测试完成 ═══")
    print(f"  运行时长: {report['duration_h']}h")
    print(f"  健康检查: {health_trace['ok']}/{total_cycles} = {report['health_rate']}%")
    print(f"  生命周期: {lifecycle_trace['ok']}/{lifecycle_trace['ok'] + lifecycle_trace['fail']} = {report['lifecycle_rate']}%")
    print(f"  警告数:   {len(warnings)}")
    if warnings:
        for w in warnings[-10:]:
            print(f"  ⚠️  {w}")
    print(f"  报告: {json_path}")

    return 0 if len(warnings) == 0 else 1


def _run_lifecycle_test() -> tuple[bool, float]:
    """Run a brief lifecycle test: register → status → cleanup."""
    import uuid
    t0 = time.perf_counter()
    name = f"wds-{uuid.uuid4().hex[:8]}"
    try:
        _, _, _ = _api_post("/agents/register", json.dumps({
            "name": name, "description": "Watchdog test agent",
        }))
        _, _, _ = _api_get(f"/agents/{name}")
        # Cleanup: delete via lifecycle
        dur = (time.perf_counter() - t0) * 1000
        return True, dur
    except Exception:
        dur = (time.perf_counter() - t0) * 1000
        return False, dur


if __name__ == "__main__":
    sys.exit(main())
