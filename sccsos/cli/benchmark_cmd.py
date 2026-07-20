"""sccsos CLI — benchmark automation commands.

Run predefined benchmark suites and generate formatted reports.
Usage:

    sccsos benchmark run              # Run all benchmark suites
    sccsos benchmark run --suite agent # Run only agent lifecycle benchmarks
    sccsos benchmark report           # Generate/print last benchmark report
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import click


BENCHMARK_DIR = Path(tempfile.gettempdir()) / "sccsos_benchmarks"
REPORT_FILE = BENCHMARK_DIR / "latest_report.json"


# ── Data classes ─────────────────────────────────────────────────────


@dataclass
class BenchmarkResult:
    suite: str
    name: str
    duration_ms: float
    success: bool
    detail: str = ""
    throughput: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class BenchmarkReport:
    timestamp: str = ""
    total_suites: int = 0
    total_tests: int = 0
    passed: int = 0
    failed: int = 0
    total_duration_ms: float = 0.0
    results: list[dict[str, Any]] = field(default_factory=list)
    summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ── Benchmark suites ─────────────────────────────────────────────────


def _bench_agent_lifecycle() -> list[BenchmarkResult]:
    """Benchmark agent create → start → stop → delete cycle."""
    results: list[BenchmarkResult] = []
    from sccsos.core.agent_runtime import get_runtime
    from sccsos.core.registry import AgentSpec

    runtime = get_runtime()
    if not runtime.initialize():
        return [BenchmarkResult("agent-lifecycle", "init-check", 0, False, "Runtime not initialized")]

    spec = AgentSpec(
        name="bench-agent",
        description="Benchmark agent",
        tenant_id="bench",
    )

    # — register —
    t0 = time.perf_counter()
    try:
        runtime.registry.register(spec)
        dur = (time.perf_counter() - t0) * 1000
        results.append(BenchmarkResult("agent-lifecycle", "register", round(dur, 2), True))
    except Exception as e:
        dur = (time.perf_counter() - t0) * 1000
        results.append(BenchmarkResult("agent-lifecycle", "register", round(dur, 2), False, str(e)))

    # — start —
    t0 = time.perf_counter()
    try:
        runtime.lifecycle.start("bench-agent")
        dur = (time.perf_counter() - t0) * 1000
        results.append(BenchmarkResult("agent-lifecycle", "start", round(dur, 2), True))
    except Exception as e:
        dur = (time.perf_counter() - t0) * 1000
        results.append(BenchmarkResult("agent-lifecycle", "start", round(dur, 2), False, str(e)))

    # — pause —
    t0 = time.perf_counter()
    try:
        runtime.lifecycle.pause("bench-agent")
        dur = (time.perf_counter() - t0) * 1000
        results.append(BenchmarkResult("agent-lifecycle", "pause", round(dur, 2), True))
    except Exception as e:
        dur = (time.perf_counter() - t0) * 1000
        results.append(BenchmarkResult("agent-lifecycle", "pause", round(dur, 2), False, str(e)))

    # — resume —
    t0 = time.perf_counter()
    try:
        runtime.lifecycle.resume("bench-agent")
        dur = (time.perf_counter() - t0) * 1000
        results.append(BenchmarkResult("agent-lifecycle", "resume", round(dur, 2), True))
    except Exception as e:
        dur = (time.perf_counter() - t0) * 1000
        results.append(BenchmarkResult("agent-lifecycle", "resume", round(dur, 2), False, str(e)))

    # — stop —
    t0 = time.perf_counter()
    try:
        runtime.lifecycle.stop("bench-agent")
        dur = (time.perf_counter() - t0) * 1000
        results.append(BenchmarkResult("agent-lifecycle", "stop", round(dur, 2), True))
    except Exception as e:
        dur = (time.perf_counter() - t0) * 1000
        results.append(BenchmarkResult("agent-lifecycle", "stop", round(dur, 2), False, str(e)))

    return results


def _bench_workflow_engine() -> list[BenchmarkResult]:
    """Benchmark DAG resolver — topology sort for workflows of various sizes."""
    results: list[BenchmarkResult] = []
    from sccsos.core.workflow.definition import WorkflowDef, WorkflowStepDef
    from sccsos.core.workflow.dag import DAGResolver

    def _make_linear_dag(n: int, prefix: str = "s") -> WorkflowDef:
        steps = []
        for i in range(n):
            dep = [f"{prefix}{i-1}"] if i > 0 else []
            steps.append(WorkflowStepDef(id=f"{prefix}{i}", depends_on=dep))
        return WorkflowDef(steps=steps, name=f"bench-{n}")

    for label, n in [("5n", 5), ("50n", 50), ("500n", 500)]:
        wf = _make_linear_dag(n)
        t0 = time.perf_counter()
        try:
            resolver = DAGResolver(wf)
            order = resolver.get_execution_order()
            dur = (time.perf_counter() - t0) * 1000
            nodes = len(order) if order else 0
            throughput = nodes / (dur / 1000) if dur > 0 else 0
            results.append(BenchmarkResult("workflow", f"dag-sort-{label}", round(dur, 2), True, throughput=round(throughput, 2)))
        except Exception as e:
            dur = (time.perf_counter() - t0) * 1000
            results.append(BenchmarkResult("workflow", f"dag-sort-{label}", round(dur, 2), False, str(e)))

    return results


def _bench_api_throughput() -> list[BenchmarkResult]:
    """Benchmark FastAPI endpoint throughput via TestClient (no network).

    NOTE: This suite requires the API server to NOT have WebSocket routes
    registered (TestClient incompatibility).  May hang with full app.
    """
    results: list[BenchmarkResult] = []
    try:
        # Try a minimal app creation — wrap in timeout via process isolation
        import http.client
        import json

        # Option A: Test against a running server
        try:
            conn = http.client.HTTPConnection("localhost", 8765, timeout=5)
            conn.request("GET", "/api/v1/health", headers={"X-Tenant-ID": "bench", "X-Role": "admin"})
            resp = conn.getresponse()
            if resp.status == 200:
                results.append(BenchmarkResult("api-throughput", "health-check", 0, True, detail="Server at localhost:8765"))
            conn.close()
        except (ConnectionRefusedError, TimeoutError, OSError):
            results.append(BenchmarkResult("api-throughput", "health-check", 0, False, detail="Server not running (start with `python -m sccsos.api.fastapi_app --port 8765`)"))
    except Exception as e:
        results.append(BenchmarkResult("api-throughput", "all", 0, False, str(e)))

    return results


def _bench_memory_system() -> list[BenchmarkResult]:
    """Benchmark TF-IDF vector store — indexing + search throughput."""
    results: list[BenchmarkResult] = []
    try:
        from sccsos.memory.vector_store import TFIDFVectorStore

        vs = TFIDFVectorStore()
        docs = [f"Document {i} about artificial intelligence and machine learning applications." for i in range(100)]

        # — Index 100 docs —
        t0 = time.perf_counter()
        for i, doc in enumerate(docs):
            vs.add_document(f"doc-{i}", doc)
        dur = (time.perf_counter() - t0) * 1000
        throughput = round(100 / (dur / 1000), 2)
        results.append(BenchmarkResult("memory", "index-100-docs", round(dur, 2), True, throughput=throughput))

        # — Search 20x —
        query = "artificial intelligence"
        t0 = time.perf_counter()
        for _ in range(20):
            vs.search(query, top_k=5)
        dur = (time.perf_counter() - t0) * 1000
        throughput = round(20 / (dur / 1000), 2)
        results.append(BenchmarkResult("memory", "search-20x", round(dur, 2), True, throughput=throughput))

    except Exception as e:
        results.append(BenchmarkResult("memory", "all", 0, False, str(e)))

    return results


# ── Suite registry ──────────────────────────────────────────────────


BENCHMARK_SUITES: dict[str, callable] = {
    "agent-lifecycle": _bench_agent_lifecycle,
    "workflow": _bench_workflow_engine,
    "api-throughput": _bench_api_throughput,
    "memory": _bench_memory_system,
}


# ── Report formatting ────────────────────────────────────────────────


def _format_report(report: BenchmarkReport) -> str:
    """Format benchmark report as human-readable table."""
    lines: list[str] = []
    lines.append("=" * 72)
    lines.append("  SCCS OS 基准测试报告")
    lines.append(f"  时间: {report.timestamp}")
    lines.append("=" * 72)
    lines.append("")
    lines.append(f"  总套数: {report.total_suites} | 总测试: {report.total_tests}")
    lines.append(f"  通过: {report.passed} | 失败: {report.failed}")
    lines.append(f"  总耗时: {report.total_duration_ms:.0f}ms")
    lines.append("")

    current_suite = ""
    for r in report.results:
        if r["suite"] != current_suite:
            current_suite = r["suite"]
            lines.append(f"── [{current_suite}] {'─' * (60 - len(current_suite))}")
        status = "✅" if r["success"] else "❌"
        dur = r["duration_ms"]
        tp = f" | {r['throughput']} ops/s" if r.get("throughput") else ""
        detail = f" — {r['detail']}" if r.get("detail") else ""
        lines.append(f"  {status} {r['name']:<25} {dur:>8.0f}ms{tp}{detail}")

    lines.append("")
    if report.summary:
        lines.append(f"  总结: {report.summary}")
    lines.append("=" * 72)
    return "\n".join(lines)


# ── CLI commands ─────────────────────────────────────────────────────


@click.group()
def benchmark():
    """Run benchmark suites and generate performance reports."""
    pass


@benchmark.command(name="run")
@click.option("--suite", "-s", default="all", help="Benchmark suite to run (default: all)")
def benchmark_run(suite: str):
    """Run benchmark suites and save report."""
    click.echo("Running benchmark suites...\n")

    BENCHMARK_DIR.mkdir(parents=True, exist_ok=True)

    report = BenchmarkReport()
    report.timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    t_start = time.perf_counter()

    if suite == "all":
        suites_to_run = list(BENCHMARK_SUITES.keys())
    elif suite in BENCHMARK_SUITES:
        suites_to_run = [suite]
    else:
        click.echo(f"Unknown suite: {suite}. Available: {', '.join(BENCHMARK_SUITES.keys())}")
        return

    report.total_suites = len(suites_to_run)

    for suite_name in suites_to_run:
        click.echo(f"  [{suite_name}] ", nl=False)
        try:
            suite_results = BENCHMARK_SUITES[suite_name]()
            for r in suite_results:
                report.results.append(r.to_dict())
                report.total_tests += 1
                if r.success:
                    report.passed += 1
                else:
                    report.failed += 1
            click.echo(f"{len(suite_results)} tests")
        except Exception as e:
            click.echo(f"ERROR: {e}")
            report.results.append(
                BenchmarkResult(suite_name, "suite-error", 0, False, str(e)).to_dict()
            )
            report.total_tests += 1
            report.failed += 1

    report.total_duration_ms = round((time.perf_counter() - t_start) * 1000, 2)

    if report.failed == 0:
        report.summary = f"All {report.passed} tests passed in {report.total_duration_ms:.0f}ms."
    else:
        report.summary = f"{report.passed} passed, {report.failed} failed in {report.total_duration_ms:.0f}ms."

    REPORT_FILE.write_text(json.dumps(report.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
    click.echo(f"\nReport saved to: {REPORT_FILE}")
    click.echo("")
    click.echo(_format_report(report))


@benchmark.command(name="report")
def benchmark_report():
    """Show the last benchmark report."""
    if not REPORT_FILE.exists():
        click.echo("No benchmark report found. Run 'sccsos benchmark run' first.")
        return

    data = json.loads(REPORT_FILE.read_text(encoding="utf-8"))
    results_raw = data.pop("results", [])
    report = BenchmarkReport(**data)
    report.results = results_raw
    click.echo(_format_report(report))
