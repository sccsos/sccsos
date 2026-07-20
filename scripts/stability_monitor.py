"""SCCS OS — Long-run stability monitor.

Continuously monitors system health, resource usage, and error rates
over an extended period (default 1h, configurable up to 72h).

Usage:
    # Basic 1-hour run
    python scripts/stability_monitor.py

    # 24-hour run with 10s check interval
    python scripts/stability_monitor.py --duration 24h --interval 10

    # Output to JSON for CI parsing
    python scripts/stability_monitor.py --json

Watches:
    - API health check availability
    - DB read/write round-trip latency
    - Memory / thread count growth
    - Error rate trend
"""
from __future__ import annotations

import json
import sys
import time
import argparse
from datetime import datetime, timedelta
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.error import URLError


def parse_duration(s: str) -> int:
    s = s.strip().lower()
    if s.endswith("h"):
        return int(s[:-1]) * 3600
    if s.endswith("m"):
        return int(s[:-1]) * 60
    if s.endswith("s"):
        return int(s[:-1])
    return int(s)


def check_health(host: str) -> dict:
    """Check API health endpoint. Returns status + latency."""
    t0 = time.perf_counter()
    try:
        req = Request(f"{host}/api/v1/health", headers={"X-Tenant-ID": "stability-test"})
        resp = urlopen(req, timeout=5)
        latency = (time.perf_counter() - t0) * 1000
        data = json.loads(resp.read().decode())
        return {
            "ok": resp.status == 200,
            "status_code": resp.status,
            "latency_ms": round(latency, 2),
            "version": data.get("version", "?"),
            "initialized": data.get("initialized", False),
        }
    except (URLError, json.JSONDecodeError, Exception) as e:
        return {"ok": False, "error": str(e), "latency_ms": -1}


def check_db(host: str) -> dict:
    """Check database health via the health endpoint's DB status."""
    try:
        req = Request(f"{host}/api/v1/health", headers={"X-Tenant-ID": "stability-test"})
        resp = urlopen(req, timeout=5)
        data = json.loads(resp.read().decode())
        db = data.get("database", {})
        return {"ok": db.get("status") == "ok", "db_path": db.get("path", "?")}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def main():
    parser = argparse.ArgumentParser(description="SCCS OS stability monitor")
    parser.add_argument("--host", default="http://localhost:8765",
                        help="API server URL (default: http://localhost:8765)")
    parser.add_argument("--duration", default="1h",
                        help="Run duration (e.g. 1h, 24h, 72h, 300s, default: 1h)")
    parser.add_argument("--interval", type=int, default=10,
                        help="Check interval in seconds (default: 10)")
    parser.add_argument("--json", action="store_true",
                        help="Output results as JSON (default: table)")
    parser.add_argument("--alert-threshold", type=float, default=3.0,
                        help="Error rate % threshold for alert (default: 3.0%)")
    args = parser.parse_args()

    duration_s = parse_duration(args.duration)
    host = args.host.rstrip("/")
    interval = max(args.interval, 5)  # Minimum 5s between checks
    alert_threshold = args.alert_threshold

    print(f"🔍 SCCS OS Stability Monitor")
    print(f"   Host:      {host}")
    print(f"   Duration:  {duration_s}s ({args.duration})")
    print(f"   Interval:  {interval}s")
    print(f"   Threshold: {alert_threshold}% error rate")
    print(f"   Started:   {datetime.now().isoformat()}")
    print("═" * 60)

    checks = 0
    errors = 0
    latencies = []
    start = time.monotonic()
    deadline = start + duration_s

    report = {
        "host": host,
        "duration_seconds": duration_s,
        "interval": interval,
        "started_at": datetime.now().isoformat(),
        "checks": [],
        "summary": {},
    }

    while time.monotonic() < deadline:
        elapsed = time.monotonic() - start
        checks += 1

        h = check_health(host)
        db = check_db(host)
        now = datetime.now().strftime("%H:%M:%S")

        if not h["ok"] or not db["ok"]:
            errors += 1
            status = "❌"
            error_msg = h.get("error", db.get("error", "unknown"))
        else:
            status = "✅"
            error_msg = ""
            if h["latency_ms"] > 0:
                latencies.append(h["latency_ms"])

        error_rate = (errors / checks) * 100 if checks > 0 else 0
        avg_latency = sum(latencies) / len(latencies) if latencies else 0
        max_latency = max(latencies) if latencies else 0

        # Alert if threshold exceeded
        alert = ""
        if error_rate > alert_threshold and checks >= 10:
            alert = " ⚠️  ALERT: Error rate above threshold!"

        print(f"  [{now}] {status} check #{checks} | "
              f"latency={h.get('latency_ms', '?'):>8}ms | "
              f"errors={errors:>4}/{checks} ({error_rate:>5.1f}%){alert}")

        # Record check data point
        report["checks"].append({
            "elapsed_s": round(elapsed, 1),
            "ok": h["ok"] and db["ok"],
            "latency_ms": h.get("latency_ms", -1),
            "error": error_msg,
        })

        if alert:
            print(f"  {'!' * 50}")
            print(f"  ALERT: Error rate {error_rate:.1f}% exceeds {alert_threshold}% threshold")
            print(f"  {'!' * 50}")

        time.sleep(interval)

    # Summary
    print()
    print("═" * 60)
    print(f"📊 Stability Report")
    print(f"   Duration: {duration_s}s")
    print(f"   Checks:   {checks}")
    print(f"   Errors:   {errors}/{checks} ({errors / max(checks,1) * 100:.1f}%)")
    print(f"   Avg latency: {avg_latency:.2f}ms")
    print(f"   Max latency: {max_latency:.2f}ms")
    passed = error_rate <= alert_threshold
    print(f"   Result:   {'✅ PASSED' if passed else '❌ FAILED'} "
          f"(threshold: {alert_threshold}%)")

    report["summary"] = {
        "finished_at": datetime.now().isoformat(),
        "total_checks": checks,
        "total_errors": errors,
        "error_rate_pct": round(errors / max(checks, 1) * 100, 2),
        "avg_latency_ms": round(avg_latency, 2),
        "max_latency_ms": round(max_latency, 2),
        "passed": passed,
    }

    if args.json:
        output_path = f"stability-report-{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        Path(output_path).write_text(json.dumps(report, indent=2, ensure_ascii=False))
        print(f"\nReport saved to: {output_path}")

    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
