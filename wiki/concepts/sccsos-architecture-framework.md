# SCCS OS Architecture Framework — 7-Domain Design

> 版本: v0.6.0 | 最后更新: 2026-07-19
> 对应: ADR-003, ADR-004

## 核心原则

1. **不重复造轮子** — 复用 Hermes Agent 的推理、记忆、工具、网关全部能力
2. **分层解耦** — 核心层（自研）与适配层（Hermes API）严格分离
3. **渐进式交付** — 先可用、再稳定、后高阶
4. **默认安全** — 最小权限、最少工具、最窄上下文
5. **多租户原生** — 从 schema 层开始支持租户隔离

## 7-Domain 架构框架

| # | 域 | 职责 | 关键接口 |
|---|-----|------|---------|
| 1 | 多智能体编排 | DAG 拓扑排序、并行 ThreadPool 执行、Jinja2 模板引擎、条件分支 | `WorkflowEngine`, `StepExecutor`, `DAGResolver`, `WorkflowDef` |
| 2 | 工具增强型 LLM | ABC 适配层、子进程桥接 Hermes CLI、策略注入、Personality 注入 | `HermesAdapter(ABC)`, `HermesSubprocessAdapter`, `PersonalityRegistry` |
| 3 | Agent 生命周期 | 5 状态状态机、DB 持久化、从 DB 恢复、后台进程管理 | `LifecycleManager`, `AgentStatus`, `AgentInstance`, `AgentRunner` |
| 4 | 可观测性 | Span 链路追踪、JSON 结构化日志、Token 审计、成本报告、Webhook 通知、阈值告警 | `Tracer`, `Logger`, `Auditor`, `PricingTable`, `WebhookNotifier`, `AlertManager` |
| 5 | 安全沙箱 | Budget 预算、工具 ACL、命令白名单、per-agent 策略覆盖、危险模式可配置 | `PolicyEngine`, `CommandWhitelist`, `BudgetTracker` |
| 6 | 记忆系统 | 冷记忆桥接、TF-IDF 向量检索、KB → 模板注入、跨会话 KV 持久记忆 | `KnowledgeBase`, `VectorStore`, `MemoryStore` |
| 7 | 提示工程 | Agent 定义（personality/profile/model/tenant）、模板变量注入、Personality 系统提示 | `AgentSpec`, `Jinja2`, `PersonalityRegistry` |

## 当前评分（v0.6.0）

| 域 | 权重 | 评分 | 说明 |
|----|------|------|------|
| 多智能体编排 | 20% | 9.0 | StepExecutor 拆分 + Schema 校验 + 条件分支 |
| 工具增强型 LLM | 15% | 7.5 | Personality 注入 + timeout 参数化，缺容器化 Hermes |
| Agent 生命周期 | 15% | 9.5 | 5状态FSM + 后台进程管理 + 策略/模型透传 |
| 可观测性 | 15% | 9.5 | 追踪/审计/日志/Webhook/告警 五维一体 |
| 安全沙箱 | 10% | 8.5 | 三层防线 + per-agent 覆盖 + 危险模式可配置 |
| 记忆系统 | 10% | 8.0 | 知识库 + 向量检索 + 跨会话 KV 持久化 |
| 提示工程 | 5% | 8.0 | Personality 系统 + AgentSpec 完整字段 |
| 多租户隔离 | 10% | 6.0 | Schema + API 就绪，缺 Web UI 和 CLI flag |
| 测试质量 | 10% | 9.5 | 152 用例覆盖核心+边缘场景 |
| **总分** | 100% | **~8.3/10** | — |

## 数据流

```
CLI / API (X-Tenant-ID)
  └→ AgentRuntime
       ├→ AgentRegistry — 加载 YAML Agent 定义 (tenant-aware)
       ├→ LifecycleManager — 5 状态状态机 + DB 持久化
       ├→ WorkflowEngine — DAG 解析 + 并行执行
       │    ├→ StepExecutor — 单步执行 (模板/条件/重试/Personality/审计)
       │    │    └→ PersonalityRegistry — system prompt 注入
       │    └→ HermesAdapter.delegate_task
       │         ├→ PolicyEngine (budget + tool_access, tenant-aware)
       │         ├→ CommandWhitelist (危险模式 + 白名单 + 扩展模式)
       │         └→ subprocess.run("hermes -p ... -z ...")
       ├→ AlertManager — 阈值评估 → Webhook 告警
       ├→ KnowledgeBase — TF-IDF 语义检索 → {{ knowledge }}
       ├→ MemoryStore — KV 持久记忆 → {{ memory }}
       ├→ Tracer / Auditor — Span 追踪 + JSON 导出 + 审计报告
       └→ WebhookNotifier — 工作流事件 + 告警事件推送
```

## 配置层次

```yaml
sccsos.yaml
  ├── project: name / version
  ├── database: path
  ├── defaults: hermes_profile / max_turns / timeout
  ├── logging: level / format / directory / retention_days
  ├── tracing: enabled / export_path / pricing_path
  ├── agents: path / wiki_path / personalities_path
  └── policies:
       ├── default: 全局默认策略 (dangerous_patterns)
       └── named: 命名策略
```

## 新增模块 (v0.6.0)

| 模块 | 文件 | 行数 | 职责 |
|------|------|------|------|
| StepExecutor | `core/step_executor.py` | ~295 | 从 WorkflowEngine 拆分出的单步执行器 |
| Personality | `core/personality.py` | ~138 | 角色定义、YAML 加载、system prompt 注入 |
| AlertManager | `observability/alert_manager.py` | ~195 | 错误率/失败数阈值评估 + Webhook 告警推送 |
| MemoryStore | `memory/memory_store.py` | ~130 | 跨会话 KV 持久记忆，per-tenant per-agent 隔离 |
| 容器化 | `Dockerfile` + `docker-compose.yaml` | ~74 | 多阶段构建 + 健康检查 + 编排 |
| 测试验证指南 | `输出/SCCS OS 测试验证与操作手册.md` | ~700 | 完整操作手册 + 验证案例 |
