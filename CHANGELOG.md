# Changelog

## [0.16.6] — 2026-07-27

### Fixed

- **`sccsos hermes install` 自定义 home/code_path 修复**: script 模式向 `install.sh` 子进程 env 注入 `HERMES_HOME` + `HERMES_CODE_PATH`，git 模式向 `pip install -e` 注入两个 env var，安装到指定路径而非默认 `~/.hermes`
- **`_get_hermes_code_path()` fallback 修复**: 使用 `_get_hermes_home()` 解析基于自定义 home 的 code_path fallback，而非硬编码 `~/.hermes/hermes-agent`
- **`HermesManager._resolve_code_path()` fallback 修复**: 同上，使用 `HermesManager._resolve_home()` 查找
- **`_ensure_hermes_home()` 新增**: 安装后自动创建自定义 `HERMES_HOME` 目录结构（profiles/skills/memories/sessions/cron + config.yaml）
- **版本同步**: 全项目文件版本号 `0.16.5` → `0.16.6`

## [0.16.5] — 2026-07-26

### Added

- **hermes-installer 默认智能体**: `sccsos init` 默认生成 `agents/hermes-installer.yaml`，封装 Hermes 安装配置完整流程
- **Personality/Agent 模板**: `SAMPLE_PERSONALITY_HERMES_INSTALL` + `SAMPLE_AGENT_HERMES_INSTALL`

### Changed

- **`sccsos init` Agent 策略**: `architect.yaml` 仅在 `--samples` 时生成，默认改为 `hermes-installer`
- **版本同步**: 全项目 46 文件版本号 `0.16.4` → `0.16.5`

## [0.16.4] — 2026-07-26

### Changed

- **Profile 克隆增加 `.env` 同步**: 创建新 profile 时自动复制 `~/.hermes/.env` → profile 目录
- **版本同步**: 全项目 46 文件版本号 `0.16.3` → `0.16.4`

## [0.16.3] — 2026-07-26

### Added

- **`.env` 密钥文件同步**: `_auto_apply_config()` 安装后自动将 `DEEPSEEK_API_KEY` 和 `DEEPSEEK_BASE_URL` 写入 `~/.hermes/.env` 和 `~/.hermes/profiles/<name>/.env`（`_ensure_env_file()` 新函数）

### Changed

- **Profile 克隆修复**: 新 profile 创建时完整复制默认配置（~22 个顶层键），而非仅有 `model.*`
- **版本同步**: 全项目 46 文件版本号 `0.16.2` → `0.16.3`

## [0.16.2] — 2026-07-26

### Changed

- **`_auto_apply_config()` API Key 同步**: 安装后自动从环境变量读取 API Key 并同步到 Hermes profile（方案 A：`DEEPSEEK_API_KEY` → `model.api_key`）
- **`_write_model_config()` 扩展**: 新增 `api_key` 参数，同步到默认配置和 profile 配置
- **交叉校验容错**: `api_key` 仅 profile 有的情况不算不一致（Hermes 默认用 `.env` 存储）
- **版本同步**: 全项目 46 文件版本号 `0.16.1` → `0.16.2`

## [0.16.1] — 2026-07-26

### Changed

- **架构审计报告产出**: 深度分析 24,649 行 / 108 源文件，修正健康评分 9.2 → 8.7
- **AgentMessageBus 死代码确认**: 228 行实现、零生产引用，标记为 Deprecated
- **版本同步**: 全项目 46 文件版本号 `0.16.0` → `0.16.1`

## [0.16.0] — 2026-07-26

### Changed

- **`_auto_apply_config()` 策略重构**: 先写默认配置（`~/.hermes/config.yaml`），再从默认克隆到目标 profile
- **`doctor` 新增配置一致性检查**: 验证 `sccsos.yaml` ↔ Hermes profile 配置是否一致，`doctor --fix` 自动同步
- **`_get_profile_config_path()` 健壮性提升**: 处理 `HERMES_HOME` 指向 `profiles/<name>` 子目录的异常情况
- **版本同步**: 全项目 44 文件版本号 `0.15.9` → `0.16.0`

## [0.15.9] — 2026-07-26

### Added

- **`--china-mirror` 支持 git 和 docker 模式**: 国内镜像覆盖三种安装方式
  - git: `https://cnb.cool/hermesagent-cn/hermes-agent-cn-mirror.git`
  - docker: `docker.xuanyuan.run/nousresearch/hermes-agent:{tag}`
  - script: `https://res1.hermesagent.org.cn/install.sh`
- **安装后自动配置**: `install()` 完成后调用 `_auto_apply_config()`，将 `sccsos.yaml` 的 model/provider/base_url 同步到 Hermes profile，无需再手动运行 `setup`

### Changed

- **版本同步**: 全项目 44 文件版本号 `0.15.8` → `0.15.9`

## [0.15.6] — 2026-07-26

### Changed

- **`sccsos hermes install` 超时优化**: 三个安装模式全部改为实时流输出，用户可见下载/安装进度而非静默等待
  - `_install_script`: curl `-fsSL` → `-fL --progress-bar`，超时 300s→600s，`capture_output=True`→实时终端输出
  - `_install_git`: pip install -e 超时 120s→300s，clone 超时 120s→180s，fetch/pull 60s→120s；clone + pip install 改为实时输出
  - `_install_docker`: docker pull 超时 300s→600s，实时输出 layer 下载进度
- **版本同步**: 全项目 35+ 文件版本号 `0.15.5` → `0.15.6`（Python 源码 / YAML / Docker / K8s / Helm / 文档 / 测试断言）

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

- **Architecture audit (P0+P1)**: Deep architecture audit completed — 7-domain verification, 5 Major + 6 Minor findings identified, health score corrected 9.2→9.0
- **Thread management**: WorkflowRuntime background tasks consolidated from bare `threading.Thread(daemon=True)` into shared `ThreadPoolExecutor(max_workers=4)` — controlled concurrency, named threads, no unbounded thread growth
- **Config deprecation**: `runtime_observability.py` now emits `logger.warning` when old `cfg.tracing.pricing_path` is used; new path is `cfg.pricing.path`
- **API version documentation**: `fastapi_app.py` route registration section annotated with v1/v2 namespace guidance for future API evolution
- Version: 0.14.1 → 0.14.2 (11 files synced)

### Fixed

- **PolicyEngine silent failure**: WorkflowEngine.__init__ PolicyEngine construction failure now emits logger.critical with exception detail — previously silently swallowed by bare except Exception (security degradation without notification)
- **AgentRuntime init logging**: Exception handler in initialize() switched from bare logging.getLogger() to project's structured get_logger() — init failures now recorded in JSON log channel
- **CommandWhitelist shell-quote awareness**: Pattern matching in `check()` now strips `'...'` / `"..."` quoted content before checking all three pattern branches (multi-word, alphanumeric, symbolic). Fixes false positives on chaining operators (`;`, `$()`, `\`\``, `|`) and dangerous words (`passwd`, `sudo`) inside quoted string arguments — e.g. `python3 -c "import sys; print(sys.version)"` is correctly allowed.
- **test_security_audit.py**: Updated `test_sandbox_command_chaining` to split cases: outside-quote chaining blocked (correct), inside-quote chaining allowed (shell treats them as literals).
- **AGENTS.md**: Stats sync — 994 tests / 176 classes / 52 files / 71% coverage (up from 761 / 977).
- **tests/CONVENTIONS.md**: Stats sync + new principle #4 (sandbox quoting awareness).
- **Full test report**: Generated `输出/SCCS OS v0.14.2 全量测试报告.md` with per-module coverage breakdown.
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
