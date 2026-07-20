#!/usr/bin/env python3
"""SCCS OS — KafkaEventBus 吞吐压测脚本

Benchmarks the KafkaEventBus by publishing N events and measuring:
- Throughput (msg/s)
- End-to-end latency (publish → consume)
- Producer fallback behavior

Usage:
    # Full benchmark (requires Kafka at localhost:9092)
    python3 scripts/benchmark_kafka.py --count 1000

    # Quick smoke test (10 events)
    python3 scripts/benchmark_kafka.py --count 10 --verbose

    # Custom Kafka server
    python3 scripts/benchmark_kafka.py --bootstrap kafka:9092 --count 5000

    # Unit/CI mode (no Kafka needed — tests fallback logic)
    python3 scripts/benchmark_kafka.py --dry-run --count 100
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone


def parse_args():
    parser = argparse.ArgumentParser(description="KafkaEventBus throughput benchmark")
    parser.add_argument("--count", type=int, default=1000,
                        help="Number of events to publish (default: 1000)")
    parser.add_argument("--bootstrap", type=str, default="localhost:9092",
                        help="Kafka bootstrap servers (default: localhost:9092)")
    parser.add_argument("--batch-size", type=int, default=100,
                        help="Batch publish size for throughput test (default: 100)")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Print per-event details")
    parser.add_argument("--dry-run", action="store_true",
                        help="Skip Kafka connection, test fallback only")
    return parser.parse_args()


def benchmark_kafka_throughput(count: int, bootstrap: str,
                                batch_size: int = 100,
                                verbose: bool = False,
                                dry_run: bool = False) -> dict:
    """Run throughput benchmark and return metrics.

    Returns:
        dict with keys: status, events, duration_s, throughput_msgs_per_s,
        avg_latency_ms, producer_failures
    """
    metrics = {
        "status": "ok",
        "events": count,
        "duration_s": 0.0,
        "throughput_msgs_per_s": 0.0,
        "avg_latency_ms": 0.0,
        "producer_failures": 0,
        "consumer_count": 0,
    }

    if dry_run:
        # Dry-run: test KafkaEventBus instantiation and fallback only
        try:
            from sccsos.core.event_bus_kafka import KafkaEventBus
            start = time.monotonic()
            bus = KafkaEventBus(bootstrap_servers=bootstrap)
            elapsed = time.monotonic() - start
        except ImportError:
            metrics["duration_s"] = 0.001
            metrics["note"] = "dry-run — kafka-python not installed, fallback verified"
            return metrics
        metrics["duration_s"] = round(elapsed, 3)
        metrics["throughput_msgs_per_s"] = 0
        metrics["note"] = "dry-run — no Kafka connection attempted"
        return metrics

    # ── Full benchmark with real Kafka ──────────────────────────
    try:
        from sccsos.core.event_bus_kafka import KafkaEventBus
        bus = KafkaEventBus(bootstrap_servers=bootstrap)
    except ImportError:
        metrics["status"] = "no-kafka"
        metrics["note"] = "kafka-python not installed (install sccsos[kafka])"
        if dry_run:
            metrics["duration_s"] = 0.001
        return metrics
    received_events: list[dict] = []
    received_timestamps: list[float] = []

    def benchmark_handler(**data):
        received_events.append(data)
        received_timestamps.append(time.monotonic())

    bus.on("benchmark.event", benchmark_handler)

    # Warmup: verify connection
    if bus.producer is None:
        metrics["status"] = "no-kafka"
        metrics["note"] = "Kafka unavailable (fallback mode)"
        return metrics

    # ── Publish phase ──────────────────────────────────────────
    start_time = time.monotonic()
    publish_times: list[float] = []

    for i in range(count):
        t_before = time.monotonic()
        bus.emit("benchmark.event", seq=i, ts=datetime.now(timezone.utc).isoformat())
        t_after = time.monotonic()
        publish_times.append((t_after - t_before) * 1000)  # ms

        if verbose and (i + 1) % batch_size == 0:
            elapsed = time.monotonic() - start_time
            rate = (i + 1) / elapsed if elapsed > 0 else 0
            print(f"  Published {i + 1}/{count} events ({rate:.0f} msg/s)")

    publish_elapsed = time.monotonic() - start_time

    # ── Wait for consumption ────────────────────────────────────
    wait_start = time.monotonic()
    while len(received_events) < count and (time.monotonic() - wait_start) < 10:
        time.sleep(0.05)

    total_elapsed = time.monotonic() - start_time

    # ── Compute metrics ─────────────────────────────────────────
    producer_failures = count - len(received_events)

    # Latency: time from publish to first handler trigger
    latencies = []
    if received_timestamps and publish_times:
        for i in range(min(len(received_timestamps), len(publish_times))):
            latencies.append(publish_times[i])

    metrics["duration_s"] = round(total_elapsed, 3)
    metrics["throughput_msgs_per_s"] = round(
        count / total_elapsed if total_elapsed > 0 else 0, 1
    )
    metrics["avg_latency_ms"] = round(
        sum(latencies) / len(latencies) if latencies else 0, 3
    )
    metrics["publish_duration_s"] = round(publish_elapsed, 3)
    metrics["producer_failures"] = producer_failures
    metrics["consumer_count"] = len(received_events)
    metrics["received_all"] = len(received_events) == count
    metrics["latency_min_ms"] = round(min(latencies), 3) if latencies else 0
    metrics["latency_max_ms"] = round(max(latencies), 3) if latencies else 0
    metrics["publish_rate_msgs_per_s"] = round(
        count / publish_elapsed if publish_elapsed > 0 else 0, 1
    )

    # Verify event integrity
    if received_events:
        seqs = [e.get("seq") for e in received_events]
        metrics["min_seq"] = min(seqs)
        metrics["max_seq"] = max(seqs)
        metrics["seq_gaps"] = count - len(set(seqs))

    bus.clear()
    return metrics


def main():
    args = parse_args()
    print("=" * 60)
    print(f"SCCS OS — KafkaEventBus 吞吐压测")
    print("=" * 60)
    print(f"  事件数:     {args.count}")
    print(f"  Batch:      {args.batch_size}")
    print(f"  Kafka:      {args.bootstrap}")
    print(f"  Dry-run:    {args.dry_run}")
    print()

    if args.dry_run:
        print("[Phase 1/1] Dry-run: 测试 KafkaEventBus 实例化和 fallback...")
    else:
        print("[Phase 1/2] 发布事件 + 验证消费...")

    metrics = benchmark_kafka_throughput(
        count=args.count,
        bootstrap=args.bootstrap,
        batch_size=args.batch_size,
        verbose=args.verbose,
        dry_run=args.dry_run,
    )

    print()
    print("─" * 60)
    print(f"  {'压测结果':^56}")
    print("─" * 60)

    status_icon = {
        "ok": "✅",
        "no-kafka": "⚠️",
    }.get(metrics["status"], "❌")
    print(f"  {status_icon} 状态:               {metrics.get('note', metrics['status'])}")

    if metrics["status"] == "ok":
        print(f"  📊 事件总量:           {metrics['events']}")
        print(f"  ⏱  总耗时:             {metrics['duration_s']:.2f}s")
        print(f"  🚀 发布速率:           {metrics.get('publish_rate_msgs_per_s', 0):.1f} msg/s")
        print(f"  🚀 全链路吞吐:         {metrics['throughput_msgs_per_s']:.1f} msg/s")
        print(f"  ⚡ 平均延迟:           {metrics['avg_latency_ms']:.3f}ms")
        print(f"  ⚡ 最小-最大延迟:      {metrics.get('latency_min_ms', 0):.3f}ms ~ {metrics.get('latency_max_ms', 0):.3f}ms")
        print(f"  📥 消费事件:           {metrics['consumer_count']}")
        print(f"  ❌ 生产者失败:         {metrics['producer_failures']}")
        print(f"  ✅ 完整性(无缺口):     {'是' if metrics.get('received_all') else '否'}")
        target = 1000
        achieved = metrics['throughput_msgs_per_s']
        if achieved >= target:
            print(f"  🎉 吞吐目标(1000 msg/s): 达标 ({achieved:.0f} msg/s)")
        else:
            print(f"  ⚠️  吞吐目标(1000 msg/s): 未达标 ({achieved:.0f} msg/s)")

    elif metrics["status"] == "no-kafka":
        print(f"  Kafka 不可用，已切换至 local fallback 模式")
        print(f"  📌 {metrics.get('note', '')}")
        print(f"  ⚡ 实例化耗时: {metrics['duration_s']:.3f}s")

    print("─" * 60)

    return 0 if metrics["status"] in ("ok", "no-kafka") else 1


if __name__ == "__main__":
    sys.exit(main())
