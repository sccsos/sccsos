# SCCS OS 整体设计方案

> 版本: v0.4.0 | 状态: 草案 | 最后更新: 2026-07-14

---

## 1. 项目概述

### 1.1 项目名称

**SCCS OS** — 自主智能体操作系统

### 1.2 一句话定义

SCCS OS 是一个构建在 Hermes Agent 之上的**智能体运行时平台**，为多 Agent 提供声明式编排、全生命周期管理和可观测性基础设施。

### 1.3 核心原则

1. **不重复造轮子** — 复用 Hermes Agent 的推理、记忆、工具、网关全部能力
2. **分层解耦** — 核心层（自研）与适配层（Hermes API）严格分离
3. **渐进式交付** — Phase 1 先可用，Phase 2 再稳定，Phase 3 后高阶
4. **默认安全** — 最小权限、最少工具、最窄上下文

### 1.4 能力边界

| SCCS OS 做 | SCCS OS 不做 |
|-----------|-------------|
| 多 Agent 编排与调度 | 单 Agent 推理循环（Hermes 做） |
| Agent 生命周期管理 | 工具系统核心（Hermes 做） |
| 权限与安全策略 | 记忆存储引擎（Hermes 做） |
| 可观测性与审计 | 消息网关/平台适配（Hermes 做） |
| 声明式 Workflow 定义 | LLM 模型调用（Hermes 做） |

---

## 2. 系统架构

### 2.1 分层架构

![SCCS OS 系统分层架构图](images/sccsos-system-architecture-light.png)

*图 1: SCCS OS 系统分层架构图 — SVG/HTML 源文件见 `images/sccsos-system-architecture.svg`（可交互HTML版本见 `images/sccsos-system-architecture.html`）*

**四层职责说明**:

| 层级 | 职责 | 关键组件 |
|------|------|---------|
| **API 层** | CLI 命令入口，用户交互界面 | `agentos` 15 条命令行（click 框架） |
| **核心层** | Agent 注册、生命周期、Workflow 编排 | Registry / Lifecycle / Orchestrator / HermesAdapter |
| **安全 & 可观测层** | 横切面：权限管控、链路追踪、审计核算 | PolicyEngine / Tracer / Auditor / Logger |
| **Hermes 底座** | 单 Agent 推理循环与基础设施 | ReAct 循环 · 47+工具 · 记忆 · 网关 · 沙箱 · MCP |

### 2.2 核心组件关系

![SCCS OS 核心组件关系图](images/sccsos-component-relationship-light.png)

*图 2: SCCS OS 核心组件关系图 — AgentRuntime 协调 Registry、Lifecycle、Orchestrator 三大核心组件，通过 HermesAdapter（ABC）桥接底层底座，PolicyEngine/Tracer/Auditor 横切支持*

**调用流说明**:

| 步骤 | 发起方 | 调用方 | 说明 |
|------|--------|--------|------|
| ① | CLI | AgentRuntime | 命令分发到运行时入口 |
| ② | AgentRuntime | Registry | 加载/注册 AgentSpec 定义 |
| ③ | Lifecycle | HermesAdapter | 启动/停止 Hermes Agent 会话 |
| ④ | Orchestrator | HermesAdapter | delegate_task 执行 Workflow 步骤 |
| ⑤ | HermesAdapter | PolicyEngine | 工具调用权限检查（默认拒绝） |
| ⑥ | HermesAdapter | Tracer | 记录 Span 开始/结束 |
| ⑦ | HermesAdapter | Auditor | 记录 Token/成本使用 |
| ⑧ | 所有组件 | SQLite | 状态/事件/Trace/Audit 持久化 |

---

## 3. 核心组件规格

### 3.1 Agent Registry (`core/registry.py`)

Agent 注册表，管理所有 Agent 定义的注册、发现和元数据查询。

```
class AgentRegistry:
    def register(spec: AgentSpec) -> AgentID     # 注册 Agent 定义
    def unregister(id: AgentID) -> None           # 注销
    def get(id: AgentID) -> AgentSpec             # 查询单个
    def list(tags: list[str]) -> list[AgentSpec]  # 按标签筛选
    def find(name: str) -> AgentSpec              # 按名称查找
```

**数据模型**: `AgentSpec`（YAML 定义）

```yaml
# agents/architect.yaml
name: architect
version: 1.0
description: 智能体架构设计师
personality: agent-architect
profile: sccsos
toolsets:
  - llm-wiki
  - filesystem
  - web-search
tags:
  - core
  - architecture
lifecycle:
  max_turns: 90
  timeout: 1800
  auto_recover: true
```

### 3.2 Lifecycle Manager (`core/lifecycle.py`)

5 状态状态机，管理 Agent 运行生命周期。

![Agent 生命周期状态机](images/sccsos-lifecycle-state-machine-light.png)

*图 3: Agent 生命周期状态机 — 5 状态（CREATED / RUNNING / PAUSED / FAILED / TERMINATED）8 种转换*

**转换表**:

| 当前状态 | 目标状态 | 方法 | 说明 |
|---------|---------|------|------|
| CREATED | RUNNING | `start()` | 启动 Agent，创建 Hermes 会话 |
| CREATED | TERMINATED | `abort()` | 放弃启动 |
| RUNNING | PAUSED | `pause()` | 暂停 Agent，保留会话 |
| RUNNING | FAILED | — | 异常崩溃（超时/错误/异常） |
| RUNNING | TERMINATED | `stop()` | 正常停止 |
| PAUSED | RUNNING | `resume()` | 恢复 Agent 会话 |
| PAUSED | TERMINATED | `stop()` | 从暂停状态停止 |
| FAILED | RUNNING | `restart()` | 重启（支持 auto_recover） |

```
class LifecycleManager:
    def create(spec: AgentSpec) -> AgentInstance
    def start(id: AgentID) -> SessionID
    def pause(id: AgentID) -> None
    def resume(id: AgentID) -> SessionID
    def stop(id: AgentID) -> None
    def restart(id: AgentID) -> SessionID
    def get_status(id: AgentID) -> AgentStatus
    def list_running() -> list[AgentInstance]
```

**状态持久化**: SQLite `agentos_state.db`

```sql
CREATE TABLE agents (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    spec TEXT NOT NULL,       -- JSON serialized AgentSpec
    status TEXT NOT NULL,     -- created|running|paused|failed|terminated
    session_id TEXT,
    created_at TIMESTAMP,
    started_at TIMESTAMP,
    paused_at TIMESTAMP,
    terminated_at TIMESTAMP,
    metadata TEXT             -- JSON
);

CREATE TABLE agent_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id TEXT NOT NULL,
    event TEXT NOT NULL,      -- create|start|pause|resume|stop|fail
    timestamp TIMESTAMP,
    detail TEXT
);
```

### 3.3 Orchestrator / Workflow Engine (`core/orchestrator.py`)

声明式 Workflow 解析与执行引擎。

![Workflow 执行时序图](images/sccsos-workflow-sequence-light.png)

*图 4: Workflow 执行时序图 — 从 CLI 调用到 DAG 构建、顺序执行、并行组并发、结果聚合的完整流程*

**执行阶段**:

```python
class WorkflowEngine:
    def load(path: str) -> WorkflowDef         # 加载 YAML
    def validate(defn: WorkflowDef) -> ValidationResult
    def execute(defn: WorkflowDef) -> RunID
    def get_status(run_id: RunID) -> RunStatus
    def cancel(run_id: RunID) -> None
```

**Workflow YAML 格式**:

```yaml
name: feature-development
version: 1.0
description: 功能开发全流程

steps:
  - id: architecture-review
    name: 架构评审
    agent: architect
    prompt: "Review requirements, produce ADR"
    output: adr.md

  - id: code-generation
    name: 代码生成
    agent: coder
    depends_on: [architecture-review]
    prompt: "Implement based on {{ steps.architecture-review.output }}"

parallel_groups:
  - id: parallel-tasks
    steps: [code-generation, test-generation]
    max_concurrent: 2
```

### 3.4 Hermes 适配层

```
class HermesAdapter:
    def delegate_task(agent: str, prompt: str, context: dict) -> str
    def list_tools(agent: str) -> list[ToolSpec]
    def check_tool_permission(agent: str, tool: str) -> bool
    def read_memory(agent: str, key: str) -> str
    def write_memory(agent: str, key: str, value: str) -> None
    def get_session(agent: str) -> SessionInfo
    def estimate_cost(session: SessionInfo) -> CostReport
```

### 3.5 Policy Engine (`security/policy.py`)

```
class PolicyEngine:
    def check_tool_access(agent_id: str, tool_name: str) -> bool
    def check_resource_quota(agent_id: str, resource: str, amount: float) -> bool
    def record_usage(agent_id: str, tool: str, duration: float, tokens: int) -> None
    def get_agent_policy(agent_id: str) -> Policy
    def set_agent_policy(agent_id: str, policy: Policy) -> None
```

**Default Policy**（默认拒绝）:

```yaml
policy:
  max_tokens_per_session: 100000
  max_duration_minutes: 60
  allowed_tools:
    - read_file
    - search_files
    - web_search
    - web_extract
    - terminal (with allowlist)
  blocked_tools:
    - browser_navigate (需显式授权)
    - write_file (受保护路径)
  max_cost_usd: 5.0
```

### 3.6 Tracer (`observability/tracer.py`)

```
class Tracer:
    def start_span(name: str, parent_id: str = None) -> Span
    def end_span(span_id: str) -> None
    def add_event(span_id: str, name: str, attributes: dict) -> None
    def get_trace(trace_id: str) -> list[Span]
    def export(format: str = "json") -> str
```

**Span 结构**:

```json
{
  "trace_id": "trc_a1b2c3",
  "span_id": "spn_d4e5f6",
  "parent_span_id": "spn_root",
  "name": "architecture-review",
  "agent": "architect",
  "start_time": "2026-07-14T10:00:00Z",
  "end_time": "2026-07-14T10:02:30Z",
  "duration_ms": 150000,
  "status": "ok",
  "events": [
    {"name": "tool_call", "time": "...", "attrs": {"tool": "read_file", "target": "wiki/index.md"}},
    {"name": "llm_call", "time": "...", "attrs": {"model": "deepseek-v4-flash", "tokens": 4520}}
  ]
}
```

---

## 4. 技术决策

| 决策 | 选择 | 理由 |
|------|------|------|
| Agent 定义格式 | YAML + JSON Schema | 与 Hermes config.yaml 一致 |
| 编排模式 | 声明式 DAG + 本地顺序 | 避免分布式复杂度 |
| 状态持久化 | SQLite + JSON | Hermes 已用 SQLite 复用 |
| CLI 框架 | click | 轻量、成熟、Python 原生 |
| 配置管理 | YAML + 环境变量 | 与 Hermes 惯例对齐 |
| 追踪格式 | 自定义 JSON → 可导出 OpenTelemetry | 零外部依赖起步 |

---

## 5. 目录结构（最终）

```
/Users/smart/dev/hermesws/sccsos/
├── AGENTS.md                       # 项目语境
├── 输出/                           ← 项目文档 + 生成输出
│   ├── 0-目录与索引.md
│   ├── 1-整体设计方案.md           ← 本文
│   ├── 2-企业级可行性方案.md
│   ├── 3-技术架构规格书.md
│   ├── 4-架构评审报告.md
│   ├── 5-第一阶段实施计划.md
│   ├── 6-部署指南.md
│   ├── 7-操作手册.md
│   ├── 8-文档与插图生成规范.md
│   └── 9-可行性技术方案文档.md
├── sccsos/                        # 核心包
│   ├── __init__.py
│   ├── core/
│   │   ├── __init__.py
│   │   ├── registry.py             # Agent 注册表
│   │   ├── lifecycle.py            # 生命周期状态机
│   │   └── orchestrator.py         # Workflow 引擎
│   ├── agents/                     # Agent 定义 YAML
│   ├── workflows/                  # Workflow 定义 YAML
│   ├── memory/
│   ├── observability/
│   │   ├── __init__.py
│   │   ├── tracer.py               # 链路追踪
│   │   ├── auditor.py              # Token 审计
│   │   └── logger.py               # 结构化日志
│   ├── security/
│   │   ├── __init__.py
│   │   ├── policy.py               # 权限策略
│   │   └── sandbox.py              # 执行沙箱（预留）
│   └── cli.py                      # CLI 入口
├── 脚本/                           # 构建工具
├── 输出/                           # 生成的 DOCX/PDF
├── 数据/                           # SQLite 数据库
├── 测试/                           # 测试用例
├── 配置/                           # 示例配置
├── 外部参考/                       # 外部参考文件
└── pyproject.toml
```
