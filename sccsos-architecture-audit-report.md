# SCCS OS 架构深度分析报告 — 核心模块依赖与接线验证

> 日期: 2026-07-26 | 目标: 7-Domain 框架对照 + 接线验证 + "存在但未接线"风险清单

---

## 1. 7-Domain 架构框架 vs 实际代码对照表

| # | 域 | 声明的关键接口 | 实际接线状态 | 依赖方向 |
|---|-----|--------------|-------------|---------|
| 1 | **多智能体编排** | `WorkflowEngine`, `StepExecutor`, `DAGResolver`, `WorkflowRunContext` | ✅ 全部接线。`WorkflowRuntime` → `WorkflowEngineBuilder` → 组装全部依赖 | `runtime_workflow.py` → `core/workflow/engine.py` → `core/step_executor.py` |
| 2 | **工具增强型 LLM** | `HermesAdapter(ABC)`, `HermesSubprocessAdapter`, `PersonalityRegistry` | ✅ Adapter 在 `RuntimeCore` 中创建（含 sandbox）。`PersonalityRegistry` 在 `WorkflowRuntime` 中加载 | `RuntimeCore` 创建 → `WorkflowRuntime` 注入到 Engine |
| 3 | **Agent 生命周期** | `LifecycleManager`, `AgentStatus`, `AgentInstance`, `AgentRunner`, `AgentProcess` | ✅ 全部在 `RuntimeCore.initialize()` 中创建。DB 恢复实例（`_restore_instances`） | `RuntimeCore` → `LifecycleManager` + `AgentRunner` + `Supervisor` |
| 4 | **可观测性** | `Tracer`, `Logger`, `Auditor`, `PricingTable`, `WebhookNotifier`, `AlertManager` | ✅ 全部在 `ObservabilityRuntime` 中创建。通过 EventBus 接线到 WorkflowEngine | `ObservabilityRuntime` → `WorkflowRuntime` (通过 `runtime_workflow.py`) |
| 5 | **安全沙箱** | `PolicyEngine`, `CommandWhitelist`, `BudgetTracker` | ⚠️ 部分接线。`CommandWhitelist` 在 `RuntimeCore` 中创建并注入 adapter。`PolicyEngine` 在 `WorkflowRuntime` 中创建。**`RateLimiter` 和 `PromptInjectionGuard` 仅存在于测试中，未接入 runtime** | `RuntimeCore` → sandbox注入adapter；`WorkflowRuntime` → PolicyEngine → WorkflowEngine |
| 6 | **记忆系统** | `KnowledgeBase`, `VectorStore`, `MemoryStore` | ✅ `MemoryStore` 在 `RuntimeCore` 中创建。`KnowledgeBase` 在条件满足时创建（wiki_path存在）。`VectorStore` 惰性加载 | `RuntimeCore` → `MemoryStore`/`KnowledgeBase` → 注入 `AgentRunner` 和 `WorkflowEngine` |
| 7 | **提示工程** | `AgentSpec`, `Jinja2 SandboxedEnvironment`, `PersonalityRegistry`, `templates.py` | ✅ `PersonalityRegistry` 在 `WorkflowRuntime` 中加载。`templates.py` 被 `StepExecutor` 的 `ContextBuilder` 使用 | `WorkflowRuntime` → `PersonalityRegistry` → `WorkflowEngine` |

### 依赖方向分析（`from sccsos` 子串搜索，100+ 条匹配）

依赖层级总体健康：**CLI → Core → (DB | Memory | Observability)**，无逆向依赖。

```
CLI         → core/agent_runtime, core/config, core/registry          ✅
CLI         → observability/logger                                     ✅
Core/Runtime → core/db, core/registry, core/lifecycle 等               ✅
Observability → core/db (tracer, auditor)                              ✅
Memory      → core/db (memory_store)                                   ✅
API routes  → core/agent_runtime, core/quota_manager 等                ✅
```

**注意：** `security/ratelimit.py`、`security/injection.py` 在 `sccsos/` 内无任何 `from sccsos.security` 导入（仅在测试中）。

---

## 2. AgentRuntime 子模块初始化验证

### `RuntimeCore.initialize()` 创建了以下子模块：

| 子模块 | 创建行 | 是否被消费方使用 |
|--------|-------|---------------|
| `Database` | 99 | ✅ AgentRunner, LifecycleManager, MemoryStore, SessionManager, Tracer, Auditor, AlertManager, ModelRouter |
| `AgentRegistry` | 105 | ✅ LifecycleManager, WorkflowEngine, `agent_cmd.py` |
| `HermesAdapter` | 119 | ✅ AgentRunner, WorkflowEngine, `health()` |
| `MemoryStore` | 126 | ✅ AgentRunner, WorkflowEngine (ContextBuilder), CLI memory cmd |
| `AgentSessionManager` | 127 | ✅ AgentRunner |
| `ModelRouter` | 130 | ✅ AgentRunner, WorkflowEngine |
| `KnowledgeBase` | 137 | ✅ AgentRunner, WorkflowEngine (ContextBuilder) |
| `Supervisor` | 146 | ✅ AgentRunner → 心跳守护 |
| `AgentRunner` | 147 | ✅ `agent_cmd.py` (CLI), API routes |
| `LifecycleManager` | 157 | ✅ `agent_cmd.py` (CLI), API routes, `get_runtime().lifecycle` |

### `ObservabilityRuntime.initialize()` 创建了：

| 子模块 | 创建行 | 是否被消费方使用 |
|--------|-------|---------------|
| `Tracer` | 75 | ✅ WorkflowEngine, StepExecutor |
| `PricingTable` | 90 | ✅ Auditor |
| `Auditor` | 94 | ✅ WorkflowEngine, StepExecutor |
| `WebhookNotifier` | 95 | ✅ AlertManager, EventBus 事件监听 |
| `AlertManager` | 96 | ✅ EventBus `WORKFLOW_COMPLETED/FAILED` |

### `WorkflowRuntime.initialize()` 创建/接线了：

| 子模块 | 创建行 | 是否被消费方使用 |
|--------|-------|---------------|
| `PersonalityRegistry` | 55 | ✅ WorkflowEngine (→ StepExecutor) |
| `PolicyEngine` | 66 | ✅ WorkflowEngine (budget/tool ACL) |
| `WorkflowEngine` | 73 | ✅ `agent_runtime.py` → CLI/API |
| EventBus 持久化 | 91 | ✅ `crud.insert_event_queue_item` |
| EventBus Webhook 事件 | 107-134 | ✅ WebhookNotifier + AlertManager 回调 |

---

## 3. `cli/hermes_cmd.py` God Function 分析

**文件总行数: 1276 行** — 本身即为 God File。

### 问题 1：`setup()` 函数 — ~163 行 God Function（第 921-1084 行）

`setup()` 在单一函数中串行执行 5 个独立关注点：

```
1. Step 1 (line 943):  检查/安装 Hermes CLI
2. Step 2 (line 962):  解析 provider + model
3. Step 3 (line 978):  解析 API Key
4. Step 4 (line 1001): 设置环境变量（含 shell rc 文件写入）
5. Step 5 (line 1035): 创建/更新 Hermes Profile
6. 验证 (line 1070):   E2E 连通性测试
```

**建议拆分：** `_ensure_hermes_installed()` / `_resolve_llm_config()` / `_inject_env_vars()` / `_configure_profile()` / `_validate_connectivity()`

### 问题 2：重复的 CLI 帮助模式

- `doctor()`（681 行，~90 行）和 `show()`（868 行，~44 行）有大量重叠的环境变量检查、profile 检查逻辑
- `_report_install_status()`、`_check_hermes_installed()`、doctor 中重复的 `subprocess.run` 调用模式
- `install()`（1126 行）和 `postinstall()`（1208 行）各自有自己的安装后验证流程，但部分重叠

### 问题 3：非 Click 辅助函数膨胀

文件前 670 行是纯辅助函数（41 个私有函数），占文件 52% 的篇幅。其中：
- `_install_git()` / `_install_script()` / `_install_docker()` — 安装逻辑共 300+ 行
- `_check_browser_engine()` / `_check_cua_driver()` / `_install_browser_engine()` / `_install_cua_driver()` — 约 100 行
- `_auto_apply_config()` / `_get_profile_config_path()` / `_sync_config_to_profile()` — 约 80 行

**建议：** 将安装相关逻辑提取到 `core/hermes_manager.py`（已存在但未充分使用），将检查逻辑提取到独立的 `cli/hermes_doctor.py`。

---

## 4. "存在但未接线" 模块风险清单

### 🔴 P0 — 完全死代码（仅自引用 + 测试）

| 模块 | 文件 | 风险说明 |
|------|------|---------|
| **AgentMessageBus** | `core/agent_message_bus.py` | 仅在自己的文件（第 21 行惰性 import）和测试中引用。没有在 AgentRuntime、WorkflowRuntime 或其他核心流程中初始化。ADR-019 声明的跨实例通信能力未接线。 |
| **DistributedSupervisor** | `core/supervisor_distributed.py` | 仅在自己的文件和 `supervisor_base.py` 注释中引用。实际使用的是 `Supervisor`（本地版）。分布式 Supervisor 从未被创建。 |
| **RateLimiter** | `security/ratelimit.py` | 仅在测试中使用 (`test_ratelimit.py`, `test_security_audit.py`)。未集成到 PolicyEngine、API 中间件或任何核心流程。 |
| **PromptInjectionGuard** | `security/injection.py` | 仅在测试中使用 (`test_injection.py`, `test_security_audit.py`)。未集成到 `StepExecutor`、`HermesAdapter` 或 API 输入管道。 |

### 🟡 P1 — API/CLI 层隔离（未接入 Runtime）

这些模块仅通过 CLI 命令或 API 路由按需加载，从未在 AgentRuntime 初始化链中创建：

| 模块 | 文件 | 风险说明 |
|------|------|---------|
| **BillingExporter** | `observability/billing.py` | 架构文档声称有计费系统（v0.14.1 评分 9.0），但仅在 `api/routes/billing.py` 和 `cli/billing_cmd.py` 中使用。`SubscriptionManager` 也未接入 Runtime。每次 CLI 调用都会重新创建实例，没有共享单例。 |
| **QuotaManager** | `core/quota_manager.py` | 仅在 `api/routes/quotas.py` 和 `cli/quota_cmd.py` 中使用。没有注入到 PolicyEngine 或其他运行时策略决策点。Quota 检查逻辑独立于 BudgetTracker。 |
| **MaintenanceScheduler** | `core/maintenance.py` | 仅在 `api/routes/maintenance.py` 和 `cli/maintenance_cmd.py` 中使用。没有常驻后台守护。 |
| **SkillReviewManager** | `core/skill_review.py` | 仅在 `cli/skill_cmd.py` 中使用。没有注入到 WorkflowEngine 或技能执行链。 |
| **PersonalityVersionManager** | `core/personality_version.py` | 仅在 `cli/skill_cmd.py` 中使用。Personality 版本管理未集成到 PersonlityRegistry 或 WorkflowEngine。 |
| **SkillRatingManager** | `skill_rating.py` | 仅在 `api/routes/skills.py` 中使用。评分数据仅通过 API 手动触发。 |

### 🟢 P2 — 惰性加载 / 可选适配器（设计上按需）

这些模块的设计本身就是按需加载，但接线路径分散：

| 模块 | 文件 | 风险说明 |
|------|------|---------|
| **DockerHermesAdapter** | `core/hermes_docker_adapter.py` | 仅在 `hermes_adapter.py:433` 和 `hermes_manager.py:376` 惰性加载。只有当 `cfg.hermes.adapter == 'docker'` 时才会创建。 |
| **RemoteHermesAdapter** | `core/hermes_remote_adapter.py` | 同上，`adapter == 'remote'` 时创建。架构文档中宣称已集成。 |
| **ChromaVectorStore** | `memory/chroma_store.py` | 惰性导入 + `sccsos[chroma]` 可选 extras。当 pip install 带 chroma 时才会使用。设计合理。 |

---

## 5. 接线完整度评分（按域）

| 域 | 评分 | 接线问题 |
|----|:----:|---------|
| 多智能体编排 | 9.0/10 | ✅ 全部接线 |
| 工具增强型 LLM | 8.5/10 | ✅ 全部接线；Docker/Remote 适配器惰性加载 — 设计合理 |
| Agent 生命周期 | 9.0/10 | ✅ 全部接线；DistributedSupervisor 未接（但本地 Supervisor 工作正常） |
| 可观测性 | 8.0/10 | ✅ Tracer/Auditor/Alert/Webhook 全部接线；⚠️ Billing 未接入 Runtime |
| 安全沙箱 | 6.0/10 | ⚠️ CommandWhitelist + PolicyEngine 已接线；❌ RateLimiter 和 InjectionGuard 仅在测试中 |
| 记忆系统 | 8.5/10 | ✅ MemoryStore + KnowledgeBase + VectorStore 全部接线 |
| 提示工程 | 8.0/10 | ✅ PersonalityRegistry + templates 接线；⚠️ PersonalityVersionManager 未集成 |
| **综合** | **~8.4/10** | - |

---

## 6. 总结与建议

### 关键发现：

1. **核心 Runtime 三层架构设计良好** — `AgentRuntime` → `RuntimeCore + ObservabilityRuntime + WorkflowRuntime` 的拆分清晰，子模块的委托属性模式（properties delegation）正确。

2. **AgengMessageBus 是最大的 "存在但未接线" 模块** — 228 行的完整实现完全未被任何生产代码引入。ADR-019 宣称的跨实例通信能力尚未激活。

3. **安全域有 2 个完全未接线的模块** — `RateLimiter` 和 `PromptInjectionGuard` 仅在测试中存在。架构文档对安全沙箱评分 9.5，但如果考虑实际接线状态则应下调。

4. **`cli/hermes_cmd.py:setup()` 是典型的 God Function** — ~163 行串行执行 5 个独立步骤，包含交互式 CLI 逻辑、shell rc 文件编辑、YAML 写入等多种关注点，难以测试和维护。

5. **计费/配额/维护模块仅在 API/CLI 层存活** — 没有进入 Runtime 初始化链意味着它们无法在运行时策略决策点（如 PolicyEngine、StepExecutor）中被使用。

### 建议修复排序：

| 优先级 | 修复项 | 工作量 |
|--------|-------|-------|
| P0 | 将 `RateLimiter` 集成到 `PolicyEngine` 或 API 中间件 | 小 |
| P0 | 将 `PromptInjectionGuard` 集成到 `HermesAdapter.delegate_task()` 或 `StepExecutor` | 小 |
| P1 | 将 `BillingExporter` 注册到 `ObservabilityRuntime` 或 `AlertManager` 的决策链 | 中 |
| P1 | 将 `QuotaManager` 注入 `PolicyEngine`，使配额在步骤执行前检查 | 中 |
| P1 | 拆分 `cli/hermes_cmd.py:setup()` 为 5 个私有方法 | 小 |
| P2 | 激活 `AgentMessageBus`（ADR-019）- 至少接入 `WorkflowRuntime` 作为可选 EventBus | 大 |
| P2 | 将 `DistributedSupervisor` 作为可选 Supervisor 实现接入 `RuntimeCore` | 中 |
