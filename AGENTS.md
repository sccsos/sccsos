# SCCS OS — 自研智能体操作系统

> 基于 Hermes Agent 运行时的智能体操作系统平台。
>
| **当前版本**: v0.12.1 (2026-07-22)
| **架构基线**: Python ~32K 行 + Vue 3 SPA (7 页面) + 测试 548 用例 / 36 文件
> **健康评分**: 8.5/10 (9 维度)
> **许可证**: MIT

## 项目概述

SCCS OS 是面向多智能体集群的统一管控平台，底层复用 Hermes Agent 运行时内核（推理循环、记忆、技能沙箱），上层自研操作系统级能力。采用**三层子运行时架构**解耦核心、可观测性与工作流编排。

| 维度 | 能力 |
|------|------|
| **编排引擎** | DAG 拓扑排序 + 条件分支 + 并行 ThreadPool + 退避重试 + Jinja2 模板 |
| **生命周期** | 5 状态状态机 + pause/resume/restart CLI |
| **可观测性** | OTEL Span 链路追踪 + JSON 结构化日志 + Token 审计 + Webhook 通知 + 阈值告警 |
| **安全策略** | 预算引擎 + 命令白名单 + 工具权限 ACL + per-agent 策略覆盖 + Prompt 注入防护 + 速率限制 |
| **事件总线** | EventBusABC 抽象 + LocalEventBus 实现（可扩展分布式适配器）|
| **记忆系统** | 文件知识库 + TF-IDF 向量语义检索 + 模板注入 + 跨会话 KV 持久记忆 |
| **Agent 运行时** | 后台进程管理 + Supervisor 心跳检测 + 自动重启 |
| **API 层** | FastAPI HTTP + WebSocket (推荐) / http.server (已废弃) |
| **模型路由** | 多模型动态调度池 |
| **容器化** | Docker 多阶段构建 + docker-compose + K8s 部署 + HPA 弹性扩缩容 |

## 架构概览

```
AgentRuntime（统一入口）
  ├── RuntimeCore                    # 核心：DB/Registry/Adapter/Runner/Session/Supervisor
  │   ├── Database (SQLite WAL)      # 持久层 + FTS5 + 自动迁移
  │   ├── HermesAdapter              # Hermes CLI 适配 + 三层安全防线
  │   ├── AgentRunner                # 后台线程进程管理
  │   ├── LifecycleManager           # 5 状态状态机
  │   ├── AgentSessionManager        # 会话管理
  │   ├── Supervisor                 # 心跳检测 + 自动重启
  │   ├── AgentRegistry              # Agent 定义注册
  │   ├── MemoryStore                # 跨会话 KV 记忆
  │   └── ModelRouter                # 多模型路由
  │
  ├── ObservabilityRuntime           # 可观测：追踪/审计/日志/告警/Webhook
  │   ├── Tracer (OTEL/Span)         # 链路追踪
  │   ├── Auditor                    # Token + 操作审计
  │   ├── Logger (JSON)              # 结构化日志
  │   ├── AlertManager               # 阈值告警
  │   ├── Webhook                    # HTTP 回调
  │   └── Pricing                    # LLM 定价表
  │
  └── WorkflowRuntime                # 工作流/策略/事件
      ├── WorkflowEngine             # DAG 编排引擎
      ├── PersonalityRegistry        # 角色配置
      ├── PolicyEngine               # 安全策略
      └── EventBus                   # 事件总线 + 持久化

基础设施层: Docker / K8s / SQLite / Jinja2 / YAML
```

## 快速上手指南

```bash
# 安装
pip install sccsos[all]

# 初始化项目
cd my-project
sccsos init

# 注册并启动 Agent（后台进程）
sccsos agent create architect
sccsos agent start architect
sccsos agent list              # Runner 列显示运行状态
sccsos agent status architect

# 直接对话
sccsos agent ask architect "设计一个认证模块"

# 运行 Workflow（支持条件分支和输入传递）
sccsos workflow run workflows/架构评审.yaml -i "设计用户认证模块"

# 异步运行
sccsos workflow run workflows/每日巡检.yaml --async

# 查看审计
sccsos audit report
sccsos health

# 启动 API 服务器（FastAPI 模式）
python -m sccsos.api.fastapi_app --port 8765
curl -H "X-Tenant-ID: my-tenant" http://localhost:8765/api/v1/agents

# Docker 部署
docker build -t sccsos:0.11.4 .
docker run -d -p 8765:8765 sccsos:0.11.4
```

## 项目结构

```
sccsos/
├── __init__.py              # 包入口
├── __main__.py              # python -m sccsos
├── _version.py              # 版本单源
│
├── core/                    # 核心运行时 (~3,500 行)
│   ├── agent_runtime.py     # 统一入口 Runtime（Facade）
│   ├── agent_runner.py      # Agent 后台进程管理
│   ├── config.py            # YAML 配置加载 + 数据类
│   ├── db/                  # 持久层（包）
│   │   ├── schema.py        # 表定义 + 迁移
│   │   └── crud.py          # DAO 操作
│   ├── event_bus.py         # EventBusABC + LocalEventBus
│   ├── events.py            # 事件常量
│   ├── hermes_adapter.py    # Hermes CLI 适配器 + 安全防线
│   ├── context_builder.py   # Jinja2 上下文装配
│   ├── retry_policy.py      # 指数退避重试策略
│   ├── lifecycle.py         # 5 状态状态机
│   ├── model_router.py      # 多模型调度
│   ├── personality.py       # Personality 注册与加载
│   ├── personality_version.py # 版本化 Personality
│   ├── registry.py          # Agent 定义注册表
│   ├── runtime_core.py      # 核心子运行时
│   ├── runtime_observability.py # 可观测子运行时
│   ├── runtime_workflow.py  # 工作流子运行时
│   ├── session.py           # 会话管理
│   ├── step_executor.py     # 工作流步骤执行器
│   ├── supervisor.py        # 心跳检测 + 自动重启
│   ├── templates.py         # Jinja2 沙箱模板
│   └── workflow/            # 工作流引擎包
│       ├── definition.py    # 工作流定义
│       ├── dag.py           # DAG 拓扑排序
│       ├── context.py       # 运行上下文
│       └── engine.py        # 工作流引擎
│
├── api/                     # HTTP API
│   ├── fastapi_app.py       # FastAPI (推荐)
│   ├── models.py            # Pydantic 模型
│   ├── server.py            # http.server (已废弃)
│   └── routes/              # 路由模块
│       ├── agents.py        # Agent CRUD
│       ├── audit.py         # 审计
│       ├── health.py        # 健康检查
│       ├── sessions.py      # 会话
│       ├── traces.py        # 追踪
│       ├── workflows.py     # 工作流
│       └── ws.py            # WebSocket
│
├── cli/                     # Click CLI（9 个子命令）
│   ├── __init__.py          # 入口 + 顶层命令
│   ├── agent_cmd.py         # agent 子命令
│   ├── audit_cmd.py         # audit 子命令
│   ├── memory_cmd.py        # memory 子命令
│   ├── personality_cmd.py   # personality 子命令
│   ├── session_cmd.py       # session 子命令
│   ├── system_cmd.py        # system 子命令
│   ├── trace_cmd.py         # trace 子命令
│   └── workflow_cmd.py      # workflow 子命令
│
├── memory/                  # 记忆系统
│   ├── knowledge_base.py    # 冷记忆桥接 (wiki)
│   ├── memory_store.py      # 跨会话 KV 持久记忆
│   └── vector_store.py      # TF-IDF 语义搜索
│
├── observability/           # 可观测性
│   ├── alert_manager.py     # 阈值告警
│   ├── auditor.py           # Token/操作审计
│   ├── logger.py            # JSON 结构化日志
│   ├── otel_tracer.py       # OpenTelemetry 追踪
│   ├── pricing.py           # LLM 定价表
│   ├── tracer.py            # Span 追踪
│   └── webhook.py           # HTTP 回调
│
├── security/                # 安全体系
│   ├── base.py              # 安全抽象基类
│   ├── injection.py         # Prompt 注入防护
│   ├── policy.py            # 预算/工具权限策略
│   ├── ratelimit.py         # 速率限制器
│   └── sandbox.py           # 命令白名单
│
├── agents/                  # Agent YAML 定义
├── workflows/               # Workflow YAML 定义
├── personalities/           # Personality YAML
├── tests/                   # 15 文件, 322 测试用例
│
├── deploy/k8s/              # K8s 部署清单 + HPA
├── Dockerfile               # 多阶段容器构建
├── docker-compose.yaml      # 容器编排
├── sccsos.yaml              # 项目配置
├── pyproject.toml           # 构建配置
└── README.md                # 项目文档
```

## 三阶段落地路线

基于可行性技术方案文档的分阶段规划：

| 阶段 | 完成度 | 说明 |
|------|--------|------|
| **Phase 1 (P0)** 基础适配与最小可用 | 100% | Hermes 适配/租户隔离/Agent 管控就绪 ✅ |
| **Phase 2 (P1)** 能力完善与生产稳定 | 95% | 安全/可观测/PostgreSQL/Chroma/技能审批全到位 ✅ |
| **Phase 3 (P2)** 集群高阶与商业化 | 55% | EventBus/模型路由/CI/CD 就绪，技能市场/计费待建 |

## 开发约定

- **代码风格**: PEP 8, Google-style docstrings, `from __future__ import annotations`
- **测试框架**: pytest (374 tests, ~50s), 覆盖率 ≥70% CI 门禁
- **版本管理**: 单源 `_version.py`，语义化版本 v0.11.4
- **决策记录**: ADR 格式记录在 wiki
- **额外依赖**: `[dev]` / `[api]` / `[otel]` / `[all]` 分组
- **构建**: `setuptools` + `pyproject.toml`
- **入口**: `sccsos` CLI (click) / `sc` 别名

## 相关链接

- 测试验证与操作手册: `输出/SCCS OS 测试验证与操作手册.md`
- 可行性技术方案: `输出/9-可行性技术方案文档.md`
- Wiki: `wiki/concepts/sccsos-architecture-framework.md`
- CHANGELOG: `CHANGELOG.md`
