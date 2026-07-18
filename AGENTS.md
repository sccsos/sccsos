# sccsos — 自主智能体操作系统

> 构建在 Hermes Agent 之上的 Agent Runtime 平台
>
> **当前版本**: v0.6.0 (2026-07-19)
> **架构基线**: 代码 ~7.8K 行 + 测试 152 用例 / 5 文件
> **健康评分**: 7.8/10（按可行性方案标准）

## 项目概述

sccsos 是一个智能体运行时环境，提供多 Agent 编排、生命周期管理、可观测性、安全策略和开发者接口。

| 维度 | 能力 |
|------|------|
| **编排引擎** | DAG 拓扑排序 + 条件分支 + 并行 ThreadPool + 退避重试 + Jinja2 模板 |
| **生命周期** | 5 状态状态机 + pause/resume/restart CLI |
| **可观测性** | Span 链路追踪 + JSON 结构化日志 + Token 审计 + Webhook 通知 + 阈值告警 |
| **安全策略** | 预算引擎 + 命令白名单 + 工具权限 ACL + per-agent 策略覆盖 + 危险模式扩展 |
| **Personality** | YAML 定义角色 + system prompt 注入 + 可配置模型与温度 |
| **记忆系统** | 文件知识库 + TF-IDF 向量语义检索 + 模板注入 + 跨会话 KV 持久记忆 |
| **Agent 运行时** | 后台进程管理 + 直接对话 + 策略引擎透传 |
| **API 层** | 零依赖 HTTP API 服务器 + 多租户隔离 (X-Tenant-ID) |
| **容器化** | Docker 多阶段构建 + docker-compose + 健康检查 |

## 快速上手指南

```bash
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

# 启动 API 服务器（多租户模式）
python -m sccsos.api.server --port 8765
curl -H "X-Tenant-ID: my-tenant" http://localhost:8765/agents

# Docker 部署
docker build -t sccsos:0.6.0 .
docker run -d -p 8765:8765 sccsos:0.6.0
```

## 技术栈

- **语言**: Python 3.11+
- **运行时**: Hermes Agent (Nous Research)
- **数据库**: SQLite (WAL 模式) + FTS5 + 自动迁移
- **模板**: Jinja2 (Sandboxed)
- **CLI**: Click
- **记忆**: TF-IDF 向量检索 (零外部依赖) + SQLite KV 存储

## 项目结构

```
sccsos/
├── core/                       # 核心运行时 (~3,000 行)
│   ├── agent_runtime.py        # 统一入口 Runtime
│   ├── agent_runner.py         # Agent 后台进程管理
│   ├── orchestrator.py         # 并行 DAG 引擎 + 条件分支
│   ├── step_executor.py        # 单步执行器（模板/条件/重试/审计）
│   ├── lifecycle.py            # 5 状态状态机
│   ├── hermes_adapter.py       # Hermes CLI 适配器 + 三层安全防线
│   ├── templates.py            # Jinja2 沙箱模板引擎
│   ├── personality.py          # Personality 角色定义与注入
│   ├── registry.py             # Agent 定义注册表
│   ├── database.py             # SQLite 持久层 + 自动迁移
│   └── config.py               # YAML 配置加载
├── agents/                     # Agent YAML 定义
├── workflows/                  # Workflow YAML 定义
├── api/
│   └── server.py               # HTTP API (零依赖, 多租户)
├── memory/
│   ├── knowledge_base.py       # 冷记忆桥接 (wiki)
│   ├── memory_store.py         # 跨会话 KV 持久记忆
│   └── vector_store.py         # TF-IDF 语义搜索
├── observability/
│   ├── tracer.py               # Span 链路追踪
│   ├── auditor.py              # Token 审计 + 成本核算
│   ├── alert_manager.py        # 阈值告警评估
│   ├── pricing.py              # 外部定价表(JSON)
│   ├── logger.py               # JSON 结构化日志
│   └── webhook.py              # HTTP 回调通知
├── security/
│   ├── policy.py               # 预算 + 工具权限策略
│   └── sandbox.py              # 命令白名单守卫
├── cli.py                      # Click CLI (~830 行)
├── Dockerfile                  # 多阶段容器构建
├── docker-compose.yaml         # 容器编排
├── README.md                   # 项目文档
├── docs/
│   └── test-verification-guide.md  # 测试验证与操作手册
├── personalities/              # Personality YAML 定义
├── tests/                      # 152 测试用例
└── config/
    └── pricing.json            # LLM 定价数据
```

## 新增特性 (v0.6.0)

| 特性 | 模块 | 说明 |
|------|------|------|
| **多租户隔离** | database.py, api/server.py | DB schema 级 tenant_id 隔离 + X-Tenant-ID API 头 |
| **阈值告警** | alert_manager.py | 错误率/失败次数阈值评估 + Webhook 推送 |
| **持久记忆** | memory_store.py | 跨会话 KV 存储 + per-tenant per-agent 隔离 |
| **Personality 系统** | personality.py | YAML 定义角色 + system prompt 注入 |
| **容器化部署** | Dockerfile, docker-compose.yaml | 多阶段构建 + 健康检查 |
| **Schema 自动迁移** | database.py | 新增字段/表自动 ALTER TABLE |
| **StepExecutor 拆分** | step_executor.py | WorkflowEngine 职责拆分 |
| **Workflow Schema 校验** | orchestrator.py | from_yaml 完整字段校验 |
| **危险模式可配置** | sandbox.py | dangerous_patterns 从配置加载 |

## 开发约定

- **代码风格**: PEP 8, Google-style docstrings
- **测试框架**: pytest (152 tests, ~13s)
- **版本管理**: 语义化版本 v0.6.0+
- **决策记录**: ADR 格式记录在 wiki

## 相关链接

- 测试验证与操作手册: `输出/SCCS OS 测试验证与操作手册.md`
- Wiki: `wiki/concepts/sccsos-architecture-framework.md` — 7 大关注域设计框架
- Wiki: `wiki/concepts/ADR-003-sccsos-p0-p1-p2-evolution.md` — 架构演进文档
