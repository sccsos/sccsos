# Changelog

All notable changes to SCCS OS are documented here.

## [0.8.1] — 2026-07-22

### Fixed

- **Pricing file warning**: `sccsos init` now creates `config/` directory
  and a default `config/pricing.json` sample file, so the
  "pricing.json not found" warning no longer appears on first run.
  Warning downgraded to INFO (PricingTable falls back to built-in
  defaults when no file is configured).

### Changed

- Version: 0.8.0 → 0.8.1

## [0.8.0] — 2026-07-22

### Added

- **EventBus**: Lightweight pub/sub event bus decouples WorkflowEngine from
  observers (WebhookNotifier, AlertManager). (ADR-007)
- **Supervisor**: AgentProcess monitoring with heartbeat + auto-restart
  (max 3 restarts, 30s heartbeat timeout). (ADR-008)
- **Config auto-merge**: `_from_dict()` replaced by generic `_auto_merge()`
  using dataclass field introspection — new config fields need only a
  dataclass definition. (ADR-009)
- **Config hot-reload**: `sccsos config reload` CLI command, `reload_config()`
  API, `get_config(force_reload=True)` support.
- **Workflow schema versioning**: `schema_version` field on `WorkflowDef`
  with decorator-based migration system (`@_register_migration`).
- **Custom Jinja2 filters**: `json_parse`, `json_dumps`, `pick`, `strptime`,
  `strftime`, `truncate_cn` for workflow templates.
- **CLI structure**: Single monolithic `cli.py` (1139 lines) split into
  `cli/{__init__,agent_cmd,workflow_cmd,system_cmd}`.
- **EventBus unit tests**: 12 test cases for pub/sub semantics.
- **Supervisor unit tests**: 10 test cases including auto-restart verification.
- **Schema migration tests**: 5 test cases for legacy-to-current migration.
- **Custom filter tests**: 15 test cases for all 6 custom Jinja2 filters.
- **Config reload tests**: 3 test cases for `reload_config()` / `force_reload`.

### Fixed

- **DB connection leak**: 9 `conn.execute()` calls in `auditor.py` (5),
  `alert_manager.py` (3), and `policy.py` (1) replaced with `self._db.execute()`
  — fixes thread-safety in all DB access paths.
- **Trace span double-close**: `Tracer.end_span()` now returns `None` for
  already-ended spans (defensive pattern preventing cascading `KeyError`).
- **WorkflowEngine span ordering**: `trace_span.end_span()` moved to last
  position in the success path, so notification/alert failures still have
  an active span for error status.

### Changed

- Version: 0.7.1 → 0.8.0
- `WorkflowEngine.execute()` emits `workflow.started/completed/failed`
  events via EventBus instead of calling WebhookNotifier/AlertManager directly.
- AgentRuntime wires EventBus subscribers in `initialize()`.
- Existing workflow YAML files updated with `schema_version: '1.1'`.

### Architecture

```
v0.7.1 → v0.8.0  (P0+P1+P2 complete)

P0 (Bug fixes):
  ├─ DB connection leak (3 files, 9 fixes)
  ├─ CLI monolithic (1 file → 4 modules)
  └─ Tracer span crash (defensive pattern)

P1 (Architecture):
  ├─ EventBus (pub/sub decoupling)
  ├─ Config auto-merge (generic introspection)
  ├─ Core test coverage (+30 tests)
  └─ Supervisor (heartbeat + auto-restart)

P2 (Features):
  ├─ Custom Jinja2 filters (6 filters)
  ├─ Schema versioning (migration system)
  └─ Config hot-reload (CLI + API)
```

Test count: 195 → 246 (51 new, 0 regressions)

## [0.7.1] — 2026-07-20

- Initial published release
- Agent definition system (AgentSpec + AgentRegistry)
- DAG-based WorkflowEngine with parallel execution
- Lifecycle state machine (CREATED/RUNNING/PAUSED/FAILED/TERMINATED)
- Policy engine (budget + tool access control)
- Hermes CLI adapter (subprocess + mock)
- Tracer/Auditor/Webhook/Alert observability stack
- KnowledgeBase with TF-IDF vector search
- MemoryStore with TTL expiration
- Personality system for system prompt injection
- API server (stdlib http.server)
- Session manager (conversation history persistence)
- 195 tests, ~5,700 LOC
