# Changelog

## [0.14.2] — 2026-07-26

### Added

- **Skill rating system**: `SkillRatingManager` with 1-5 star ratings, re-rating, aggregated stats (avg + distribution), user rating lookup, install count tracking, top-rated / most-installed / popular rankings, category-based grouping
- **Skill rating API**: 8 new endpoints — POST `/skills/{name}/rate`, GET `/skills/{name}/rating`, GET `/skills/{name}/user-rating`, GET `/skills/ratings/top`, GET `/skills/popular`, GET `/skills/most-installed`, GET `/skills/categories`, GET `/skills/categories/{category}`
- **Skill rating EventBus**: `skill.rated` event emitted on rating, broadcast via WebSocket to Dashboard real-time event log
- **Vue frontend — 🔥 Popular tab**: New tab in Skills.vue showing top-rated skills (with star rendering) and most-installed skills in a 2-column grid layout
- **DB schema migration v7/v8**: New `skill_ratings` table + `install_count`/`category` columns on `skill_market` (SQLite + PostgreSQL)
- **Install count tracking**: `SkillMarket.install()` now auto-increments `install_count` via `SkillRatingManager`
- **Fault tolerance drill suite**: 26 tests in `tests/test_fault_tolerance.py` covering DB concurrent writes, connection recovery, Supervisor heartbeat drop, rapid crash-restart, 50-process supervision, 1000-registration stress, AgentProcess edge cases (pre-start, post-stop, double start/stop, pause/resume, rapid 20-request queue), EventBus handler isolation, Kafka broker-unavailable fallback, thread/resource leak detection
- **CONTRIBUTING.md**: Complete 12-chapter developer contribution guide — environment setup, project structure, coding standards, testing requirements, PR workflow, API integration, custom skill/plugin development, ADR conventions, FAQ
- **GitHub Issues templates**: 3 templates — Bug report, Feature request, Usage question
- **App.vue responsive sidebar**: Hamburger menu toggle + overlay + CSS transition for mobile screens ≤ 768px

### Changed

- Version: 0.14.1 → 0.14.2 (11 files synced)
- `sccsos/core/db/schema.py`: Added `skill_ratings` table, `install_count`/`category` columns to `skill_market`, PostgreSQL equivalents, migration v7/v8
- `sccsos/skill_market/__init__.py`: `install()` now tracks install count
- `sccsos/skill_rating.py`: Emits `skill.rated` EventBus event on rate
- `frontend/src/App.vue`: Replaced static sidebar with responsive collapsible layout
- `frontend/src/views/Skills.vue`: Added 🔥 Popular tab, star rendering, topRated/mostInstalled data
- `frontend/src/views/Dashboard.vue`: Added `skill.rated` WebSocket event listener
- `frontend/src/api.js`: Added 7 new API methods for skill ratings and rankings

### Coverage

| Module | Coverage | Status |
|--------|----------|--------|
| `skill_rating` | 98% (112 stmts) | ✅ |
| `skill_market` | 95% | ✅ |
| **Fault tolerance drills** | 26 tests | ✅ |

Test count: 915 → 943 passed, 4 skipped (0 failed, 0 errors)

## [0.14.1] — 2026-07-22

### Added

- **Skill review enhancement**: Threaded review comments (add/list/reply), review audit history trail, version diff comparison (field-by-field + content diff), reset-to-draft workflow
- **Billing test coverage**: 12 integration tests for `BillingExporter` (CSV export, summary, tenant/agent filtering, edge cases)
- **Kafka throughput benchmark**: `scripts/benchmark_kafka.py` with dry-run support, throughput measurement (msg/s), latency tracking, event integrity verification
- **Targeted coverage tests**: 36 tests covering error paths in `step_executor` (condition skip, injection guard, personality wrap, failure handling), `templates` (filter error paths, sandbox env, render errors), and `otel_tracer` (span lifecycle, fallback, mocked OTel)
- **Admin panel — real-time WebSocket events**: Agent lifecycle events (created/started/stopped/paused/failed/resumed) and skill market events (submitted/approved/rejected) now broadcast to Dashboard via WebSocket
- **Dashboard — token trend sparkline**: SVG real-time token consumption chart (60s rolling window) with peak tracking
- **Dashboard — skill market summary**: Live stats card (total/approved/pending/installed skills)
- **Grafana dashboard template**: `deploy/grafana/sccsos-dashboard.json` with 10 panels (agent stats, token/cost trends, error rate, API calls, latency), importable via Grafana UI
- **Release CI**: `.github/workflows/release.yml` — auto-extracts CHANGELOG sections, builds wheel+sdist, creates GitHub Release with notes
- **Install wizard**: `sccsos init --interactive` with 3-step guided setup (database type + PostgreSQL DSN, admin user creation, pricing tier selection)
- **Generic API client**: `api.get(path)` for arbitrary API endpoint calls from Vue frontend

### Changed

- `sccsos/core/db/schema.py`: Added `review_comments` and `review_history` tables
- `sccsos/core/skill_review.py`: Added `add_comment()`, `list_comments()`, `get_history()`, `version_diff()`, `reset_to_draft()` with reviewer tracking, review audit trail recording
- `sccsos/api/routes/skills.py`: Added POST/GET `/skills/{name}/comments`, GET `/skills/{name}/history`, GET `/skills/{name}/diff` endpoints
- `sccsos/api/routes/ws.py`: Extended EventBus wiring to broadcast agent lifecycle and skill market events
- `frontend/src/views/Dashboard.vue`: Added sparkline chart, skill market summary, live agent event handling, clear button
- `scripts/test-kafka-integration.sh`: Updated to use the new benchmark script as primary throughput test
- `sccsos/core/config.py`: Default version updated to 0.14.1
- `sccsos/cli/__init__.py`: Default YAML template version updated to 0.14.1

### Coverage Improvements

| Module | Before | After | Target | Status |
|--------|--------|-------|--------|--------|
| `step_executor` | 78% | **96%** | 85% | ✅ |
| `templates` | 81% | **92%** | 90% | ✅ |
| `otel_tracer` | 27% | **75%** | 60% | ✅ |
| **Total** | 71.31% | **73%** | 70% | ✅ |

Test count: 866 passed, 4 skipped (0 failed, 0 errors)

### Added

- **Security audit**: Full-chain attack simulation test suite (27 tests covering injection/policy/sandbox/rate-limit/RBAC)
- **E2E API tests**: 18 FastAPI route-level integration tests (skill CRUD, RBAC auth, multi-tenant, error handling)
- **Performance benchmark**: locustfile.py for load testing all major API endpoints
- **Production ops docs**: ops/production-checklist.md with deployment checklist, DR procedures, monitoring guide

### Changed

- Version: 0.13.0 → 0.14.0

### Architecture

```
v0.13.0 → v0.14.0  (Production Readiness)

Security:
  ├─ test_security_audit.py (27 tests, full-chain attack simulation)
  └─ All 6 security layers validated end-to-end

E2E:
  ├─ test_api_e2e.py (18 tests, FastAPI TestClient)
  ├─ Skill market full lifecycle (create→list→submit→approve→install→remove)
  ├─ RBAC authorization (admin/operator/viewer header enforcement)
  └─ Multi-tenant isolation (X-Tenant-ID)

Operations:
  ├─ tests/locustfile.py — Locust benchmark (read/write mixed workload)
  └─ ops/production-checklist.md — Checklist, DR procedures, monitoring config
```

Test count: 838 passed, 4 skipped (0 failed, 0 errors)

# Changelog

## [0.13.0] — 2026-07-22

### Added

- **Skill marketplace**: 5 API endpoints (publish/install/remove/search), Vue 4-tab UI
- **RBAC system**: 3 roles (admin/operator/viewer) × 14 permissions, FastAPI auth dependency
- **CLI test coverage**: First CLI tests for version/init/help commands
- **K8s deploy docs**: Full deployment guide with HPA verification, Helm, troubleshooting

### Changed

- Version: 0.12.1 → 0.13.0
- `security/rbac.py` imported into agent/skills API routes for route-level authorization
- `SkillMarket.list_skills()` supports `query` param for full-text search
- `SkillMarket.create_skill()` added for inline skill creation (API layer)

### Fixed

- `SkillMarket.list_installed()` SQLite Row compatibility bug (AttributeError: no `.get()`)
- `AGENTS.md` outdated test count, version, and project structure

### Architecture

```
v0.12.1 → v0.13.0  (Phase 3: Skill Market + RBAC + Coverage)

Skill Market:
  ├─ Market API: GET/POST /skills, GET/POST/DELETE installed
  ├─ Frontend: 4-tab Skills.vue (browse/search/install/publish/review)
  └─ Coverage: skill_market 60% → 96%

RBAC:
  ├─ Security module: rbac.py (3 roles × 14 permissions)
  ├─ Integration: agents.py, skills.py (require_permission decorator)
  └─ Tests: 22 test cases (all roles/permission combinations)

Coverage Sprint:
  ├─ webhook.py: 69% → 100%
  ├─ tracer.py: 82% → 96%
  ├─ CLI tests: first 5 tests (version/init/help)
  └─ Total: 61% → 71% (CI gate met ✅)
```

Test count: 766 passed, 4 skipped (0 failed, 0 errors)

All notable changes to SCCS OS are documented here.

## [0.12.1] — 2026-07-22

### Changed

- Version: 0.12.0 → 0.12.1
- Synced version string across 20+ files (pyproject.toml, Docker/K8s/Helm
  deploy manifests, test assertions, config defaults, docs).

### Fixed

- Test assertions in `test_comprehensive.py`, `test_api_server.py`,
  `test_event_bus.py` now match the current release version.

Test count: 548 passed, 4 skipped (0 failed, 0 errors)

## [0.12.0] — 2026-07-22

### Added

- **Vue SPA Admin Dashboard**: Replaced legacy `admin.html` with full Vue 3 SPA (7 pages).
  Pinia state management, WebSocket real-time events, lazy-loaded routes.
  (Sprint 2)
- **WebSocket real-time event stream**: New `ws.js` composable with auto-reconnect,
  wired to Dashboard auto-refresh on workflow events. (Sprint 1)
- **Skills approval workflow UI**: Publish / submit / approve / reject / install
  full lifecycle from Vue Skills page. (Sprint 2)
- **Agents lifecycle actions**: Start / pause / resume / stop buttons with status
  indicators on Agents page. (Sprint 2)
- **Billing CSV export API**: `GET /api/v1/billing/export` returns CSV with
  `Content-Disposition` download header. (Sprint 3)
- **Billing page with CSV download**: Date range filter, model/agent breakdown,
  daily cost table, one-click CSV export. (Sprint 3)
- **Quota configuration API + UI**: `POST /api/v1/quotas/{tenant}` for updating
  limits, inline config editor on Quota page. (Sprint 3)
- **Webhook management API + UI**: `GET/POST/DELETE /api/v1/webhooks` endpoints
  + toggle, dedicated Webhooks page with add/list/remove. (Sprint 3)
- **Traces page enhancements**: Span detail expand, status filter, WebSocket
  auto-refresh. (Sprint 2)
- **Pinia stores**: `app.js` (global state), `agents.js` (agent list cache)
  for shared reactive state. (Sprint 2)
- **Test coverage**: 9 new test cases for billing/export, quota/update,
  and webhook API routes. (Sprint 4)
- **Test conventions doc**: `tests/CONVENTIONS.md` — temp DB isolation rules,
  integration test skipif patterns, CLI run commands. (Sprint 1)

### Fixed

- **SQLite locking in tests**: `test_skill_review_api.py` now uses temp DB +
  `set_runtime()` injection, eliminates "database is locked" errors in
  full test suite runs. (Sprint 1)
- **Test ordering dependencies**: `test_reject` no longer depends on
  `test_approve_valid` execution order. (Sprint 1)
- **pytest-cov CI dependency**: Added `pytest-cov>=4.0` to `[dev]` extras
  in `pyproject.toml`. (Sprint 1)

### Changed

- Version: 0.11.4 → 0.12.0
- `App.vue` now uses Pinia store + WebSocket connection status
  (instead of HTTP health check) for sidebar online indicator.
- `Dashboard.vue` redesigned: Agent status distribution bar chart,
  real-time event log, WS-driven auto-refresh.
- `Billing.vue` enhanced: daily cost table, model/agent breakdown bars,
  CSV download button.
- `Quota.vue` enhanced: inline config editor with save-to-API.
- `Traces.vue` enhanced: span detail expansion, status filter.

### Architecture

```
v0.11.4 → v0.12.0  (Sprint 1-4: Stable + Vue SPA + Commercial)

Sprint 1 (Stability):
  ├─ SQLite lock fix (temp DB + set_runtime)
  ├─ pytest-cov CI dep
  └─ Test conventions doc

Sprint 2 (Vue SPA):
  ├─ Pinia stores (app, agents)
  ├─ WebSocket composable + Dashboard auto-refresh
  ├─ Dashboard redesign (status bar, event log)
  ├─ Agents lifecycle actions UI
  ├─ Traces span detail + filter
  └─ Skills approval workflow UI

Sprint 3 (Commercial):
  ├─ Billing CSV export API + UI
  ├─ Quota config API + UI
  └─ Webhook management API + UI (7 pages)

Sprint 4 (Release):
  ├─ 9 new API route tests
  ├─ Coverage 60.66% → 61.00%
  └─ v0.12.0 release
```

Test count: 548 passed, 4 skipped (0 failed, 0 errors)

## [0.11.1] — 2026-07-22

### Added

- **CLI `config show`**: Display full configuration tree with optional `--webhooks`
  and `--policies` filters.
- **CLI `config webhook`**: Manage webhook endpoints via `list`, `add`, `remove`,
  and `test` subcommands. Add/remove writes `sccsos.yaml` and hot-reloads config.
- **CLI `init --samples`** (`-s`): Generate 11 sample files including 3 personalities
  (`agent-architect`, `doc-writer`, `code-reviewer`), 3 agents, 5 workflows (smoke
  test, architecture review, conditional branch, parallel search, daily inspection),
  and a full `sccsos.yaml` with `model_pool` and `webhooks` sections.
- **`cli/sample_templates.py`**: New module housing all sample template constants,
  replacing inline `_SAMPLE_AGENT` / `_SAMPLE_PRICING` in `cli/__init__.py`.

### Changed

- Version: 0.11.0 → 0.11.1
- `cli/__init__.py`: Inline `_SAMPLE_AGENT` and `_SAMPLE_PRICING` constants moved
  to `cli/sample_templates.py` for single-source maintainability.

Test count: 374 (no regressions)

## [0.11.0] — 2026-07-22

### Added

- **`RetryPolicy`**: Extracted standalone retry module (`sccsos/core/retry_policy.py`).
  Configurable exponential-backoff, cancellation support, non-retryable pattern
  detection, and DB event logging. Reusable by any component, not just workflows.
- **`ContextBuilder`**: Extracted template context assembly
  (`sccsos/core/context_builder.py`). Builds Jinja2 context from step outputs,
  knowledge base (wiki), and persistent memory.
- **Per-tenant Runtime Factory**: `get_runtime(tenant_id)` now supports
  per-tenant AgentRuntime instances via a `_RUNTIMES` dict, thread-safe with
  `threading.Lock()`. `reset_runtime(tenant_id=None)` supports single-tenant
  or full reset. All existing callers continue to work unchanged (default to
  `"default"` tenant).
- **CRUD expansion**: 11 new functions in `sccsos/core/db/crud.py` covering
  workflow steps (`insert_workflow_step`, `update_workflow_step`,
  `get_workflow_steps`), workflow runs (`insert_workflow_run`,
  `update_workflow_run_status`, `get_workflow_run`, `list_workflow_runs`),
  sessions (`insert_session`, `update_session`, `insert_session_message`),
  personality versions (`insert_personality_version`), and event queue
  (`insert_event_queue_item`).

### Changed

- Version: 0.10.0 → 0.11.0
- **20 raw SQL calls eliminated**: `step_executor.py` (6), `session.py` (5),
  `workflow/engine.py` (7), `personality_version.py` (1), `runtime_workflow.py` (1)
  replaced with `crud.*()` calls. All DB access now goes through `crud.py`.
- **StepExecutor reduced from 345→180 lines**: Retry logic extracted to
  `RetryPolicy`; context assembly extracted to `ContextBuilder`.
- **pyproject.toml**: Removed `ignore::DeprecationWarning:sccsos.api.server`
  filter — the legacy http.server deprecation warning is now visible.
- **`serve --legacy`** help text tagged with `(DEPRECATED)`.
- **`set_runtime()`** accepts optional `tenant_id` parameter for test injection
  into multi-tenant factory.

### Removed

- **3 deprecated shim files**: `sccsos/core/database.py`, `sccsos/core/orchestrator.py`,
  `sccsos/cli.py` — all were pure re-export wrappers that imported from the new
  package locations. Zero consumers remained on the old import paths.

### Architecture

```
v0.10.0 → v0.11.0  (P0 cleanup + P1 architecture hardening)

P0 (Cleanup):
  ├─ Remove 3 deprecated shim files
  └─ Rewrite AGENTS.md (v0.7.1 → v0.10.0)

P1 (Architecture):
  ├─ Unified data access layer (20 raw SQL → crud.py)
  ├─ RetryPolicy + ContextBuilder extraction
  ├─ FastAPI default entry (deprecation warning visible)
  └─ Per-tenant RuntimeFactory (dict + Lock)
```

Test count: 322 → 342 (20 new, 0 regressions)

## [0.10.0] — 2026-07-22

### Added

- **ModelRouter wiring**: `ModelRouter` is now injected into `AgentRunner` and
  `WorkflowEngine`/`StepExecutor` — automatically resolves model when not
  explicitly set by the caller or AgentSpec. (P0-1)
- **KnowledgeBase in agent ask**: `agent ask` prompts now include KB (wiki)
  context as Layer 0, matching the same context injection available in
  Workflow steps. (P0-2)
- **Config `model_pool` field**: `AgentOSConfig.model_pool` declared as
  dataclass field, with sample section in `sccsos.yaml`.
- **`ModelRouter.resolve_for_agent()`**: Convenience method with
  (agent_name, capability, preferred) signature.

### Changed

- Version: 0.9.0 → 0.10.0
- `AgentRunner.__init__()`: accepts `model_router` and `knowledge_base`
  parameters.
- `AgentProcess.__init__()`: accepts `knowledge_base` parameter.
- `WorkflowEngine.__init__()`: accepts `model_router` parameter.
- `StepExecutor.__init__()`: accepts `model_router` parameter.
- KnowledgeBase initialization moved earlier in `AgentRuntime.initialize()`
  so it's available when AgentRunner starts.

### Fixed

- ModelRouter was fully implemented but had zero consumers — agent and
  workflow model selection remained manual.
- KnowledgeBase context was only injected in Workflow steps, not in
  `agent ask` direct conversation path.

### Architecture

```
v0.9.0 → v0.10.0  (P0 fixes)

P0 (Functionality):
  ├─ ModelRouter wiring to AgentRunner + StepExecutor
  ├─ KB context injection in AgentProcess._build_prompt
  └─ Version file synchronization (CHANGELOG + wiki)
```

Test count: 312 → 322 (10 new, 0 regressions)

## [0.9.0] — 2026-07-22

### Added

- **Session persistence**: `AgentSessionManager` + `agent_sessions` and
  `session_messages` tables for conversation history. (ADR-010)
  - `agent ask` now records user/assistant turns in DB
  - PAUSED saves session context; RESUME carries summary forward
  - History is injected as context on subsequent `agent ask` calls
- **Model Router**: `ModelRouter` module with `select()`, `fallback()`,
  `estimate_cost()` and `from_config()` — task-aware model selection
  from a configurable pool. (ADR-011)
- **FastAPI async server**: `api/fastapi_app.py` with 29 routes + WebSocket
  event streaming + auto OpenAPI docs. Optional `[api]` extras.
  (ADR-012)
- **OTel tracer bridge**: `observability/otel_tracer.py` for optional
  OpenTelemetry trace export (requires `sccsos[otel]` extras).
- **Personality version management**: `personality_versions` DB table
  with CLI `sccsos personality {list,save,show,rollback}` commands.
  (ADR-013)
- **CLI session commands**: `sccsos session` group with list/show commands
  for conversation history.

### Changed

- Version: 0.8.1 → 0.9.0
- `sccsos serve` auto-detects FastAPI with `--legacy` fallback to http.server
- `AgentOSConfig.dataclass`: added `model_pool` field (auto-merge support)

### Fixed

- Session history was lost on every `agent ask` — now persisted in DB
- Model selection had no centralized routing mechanism

### Architecture

```
v0.8.1 → v0.9.0  (P1 + P2)

P1 (Architecture):
  ├─ Session persistence (DB tables + AgentSessionManager)
  ├─ ModelRouter (task-aware model selection)
  └─ FastAPI server (async + WebSocket)

P2 (Features):
  ├─ OTel tracer bridge (optional extras)
  ├─ Personality version management (DB + CLI)
  └─ CLI session commands (conversation history)
```

Test count: 246 → 312 (66 new, 0 regressions)

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
