# sccsos — 自主智能体操作系统

> 构建在 Hermes Agent 之上的 Agent Runtime 平台
>
> **当前版本**: v0.7.1 (2026-07-22)
> **架构基线**: 代码 ~8K 行 + 测试 157 用例 / 5 文件
> **健康评分**: 8.7/10（P0: API-Runner 联动 + agent list 状态修复 + step_outputs 线程安全 + 测试 Mock 注入 | P1: tenant 过滤 cancel/list + Pricing 配置独立 + StepExecutor 上下文提取）

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
docker build -t sccsos:0.6.4 .
docker run -d -p 8765:8765 sccsos:0.6.4
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

## 新增特性 (v0.7.1)

| 特性 | 模块 | 说明 |
|------|------|------|
| **API-Runner 联动** | api/server.py | 所有生命周期 API handler 同步启动/停止/暂停/恢复后台 runner 进程 |
| **agent list 状态修复** | cli.py | 按 name 匹配 Lifecycle 实例，准确显示 RUNNING/PAUSED/FAILED 状态 |
| **step_outputs 线程安全** | step_executor.py | 跳过路径的 dict 写入移至 DB 锁内，消除并行步骤竞态风险 |
| **多租户隔离完善** | orchestrator.py | cancel_run() / list_runs() 新增 tenant_id 过滤参数 |
| **Pricing 配置独立** | config.py | 新增 pricing.path 独立配置节，向后兼容 tracing.pricing_path |
| **模板上下文提取** | step_executor.py | _build_context() 方法拆分，降低 _execute_step 复杂度 |

## 新增特性 (v0.7.0)

| 特性 | 模块 | 说明 |
|------|------|------|
| **PAUSED 真实化** | agent_runner.py, cli.py | AgentRunner pause/resume 同步停启后台线程, ask 暂停时返回错误 |
| **agent ask 记忆注入** | agent_runner.py, agent_runtime.py | 直通路径在 delegate_task 前注入 {{ memory }} 上下文, MemoryStore 持久化 |
| **线程安全编排引擎** | orchestrator.py | WorkflowRunContext 替代 per-run 实例变量, execute() 支持并发调用 |
| **API 状态守卫** | api/server.py | pause/resume/restart/stop 按 AgentStatus 匹配实例, 注册自动创建 Lifecycle 实例 |
| **统一 DB 操作** | database.py | 新增 fetchone/fetchall 便捷方法, 核心模块迁移至 db.execute() |
| **模板引擎可注入** | step_executor.py | StepExecutor 接受 template_engine 参数, 测试可 mock 渲染器 |
| **配置一致性检查** | agent_runtime.py | 启动时校验 pricing_path 文件存在性 |
| **主动过期清理** | memory_store.py | purge_expired() 批量删除 TTL 过期的记忆条目 |
| **agent list 暂停状态** | cli.py | agent list 显示 paused 列

## 开发约定

- **代码风格**: PEP 8, Google-style docstrings
- **测试框架**: pytest (152 tests, ~13s)
- **版本管理**: 语义化版本 v0.6.4+
- **决策记录**: ADR 格式记录在 wiki

## 相关链接

- 测试验证与操作手册: `输出/SCCS OS 测试验证与操作手册.md`
- Wiki: `wiki/concepts/sccsos-architecture-framework.md` — 7 大关注域设计框架
- Wiki: `wiki/concepts/ADR-003-sccsos-p0-p1-p2-evolution.md` — 架构演进文档
