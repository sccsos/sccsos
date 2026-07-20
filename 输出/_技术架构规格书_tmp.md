# SCCS OS 技术架构规格书

> 版本: v0.4.0 | 对应: ADR-002 | 最后更新: 2026-07-14

---

## 1. 数据模型

### 1.1 AgentSpec（Agent 定义）

```yaml
name: string                  # 唯一标识名
version: semver               # 语义化版本
description: string           # 描述
personality: string           # 映射到 Hermes personality 键
profile: string               # Hermes profile 名称
toolsets: list[string]        # 启用的工具集
tags: list[string]            # 分类标签
lifecycle:
  max_turns: integer          # 最大对话轮次
  timeout: integer            # 超时秒数
  auto_recover: boolean       # 崩溃是否自动恢复
policy:                       # 可选，覆盖默认策略
  allowed_tools: list[string]
  blocked_tools: list[string]
  max_tokens_per_session: integer
  max_cost_usd: float
metadata: dict                # 自定义元数据
```

### 1.2 WorkflowDef（Workflow 定义）

```yaml
name: string
version: semver
description: string
steps:
  - id: string                # 步骤唯一 ID
    name: string              # 步骤名称
    agent: string             # 执行 Agent 名称
    prompt: string            # 执行提示词（支持模板）
    input: string             # 可选，输入文件路径
    output: string            # 可选，输出文件路径
    depends_on: list[string]  # 前置依赖步骤 ID
    timeout: integer          # 可选，步骤级超时
    retry: integer            # 可选，失败重试次数
parallel_groups:              # 可选，并行组
  - id: string
    steps: list[string]       # 组内步骤 ID
    max_concurrent: integer
```

### 1.3 AgentInstance（运行时实例）

```yaml
id: uuid4                     # 实例唯一 ID
name: string                  # Agent 名称
spec_version: semver          # 所基于的 Spec 版本
status: enum                  # created|running|paused|failed|terminated
session_id: string            # Hermes 会话 ID（仅 running）
hermes_profile: string        # 对应 Hermes profile
created_at: timestamp
started_at: timestamp         # 最近一次启动时间
paused_at: timestamp          # 最近一次暂停时间
terminated_at: timestamp
total_runtime_seconds: integer
total_tokens: integer
total_cost_usd: float
error_count: integer
last_error: string
metadata: dict
```

---


![SCCS OS 核心组件关系图](images/sccsos-component-relationship-light.png)

*图 1: SCCS OS 核心组件关系图 — Registry、Lifecycle、Orchestrator 三大核心通过 HermesAdapter 桥接 Hermes 底座*

## 2. 接口定义

### 2.1 CLI 接口

```
sccsos init                         # 初始化当前目录为 sccsos 项目
sccsos agent create <name>          # 创建 Agent 定义
sccsos agent list                   # 列出所有 Agent
sccsos agent start <name>           # 启动 Agent
sccsos agent stop <name>            # 停止 Agent
sccsos agent status <name>          # 查询状态
sccsos agent logs <name>            # 查看日志

sccsos workflow validate <file>     # 验证 Workflow YAML
sccsos workflow run <file>          # 执行 Workflow
sccsos workflow status <run_id>     # 查询 Workflow 运行状态
sccsos workflow cancel <run_id>     # 取消 Workflow

sccsos trace list                   # 列出追踪记录
sccsos trace show <trace_id>        # 查看追踪详情
sccsos audit report                 # 生成审计报告

sccsos version                      # 显示版本
```

### 2.2 Python API

```python
from sccsos import AgentRuntime

# 初始化
rt = AgentRuntime(hermes_profile="sccsos")

# 注册 Agent
spec = rt.registry.load("agents/architect.yaml")
rt.registry.register(spec)

# 启动
instance = rt.lifecycle.start("architect")
print(f"Agent {instance.id} started, session: {instance.session_id}")

# 运行 Workflow
run = rt.orchestrator.execute("workflows/feature-dev.yaml")
print(f"Workflow run: {run.id}")

# 查询追踪
trace = rt.tracer.get_trace(run.trace_id)
for span in trace:
    print(f"  {span.name}: {span.duration_ms}ms")

# 审计报告
report = rt.auditor.generate_report(since="2026-07-01")
print(f"Total cost: ${report.total_cost:.2f}")

# 停止
rt.lifecycle.stop("architect")
```

---


![Agent 生命周期状态机](images/sccsos-lifecycle-state-machine-light.png)

*图 2: Agent 生命周期状态机 — 5 状态 8 种转换，所有状态转换持久化到 SQLite agent_events 表*

## 3. 数据库 Schema

```sql
-- Agent 实例表
CREATE TABLE agents (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    spec TEXT NOT NULL,
    spec_version TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'created',
    session_id TEXT,
    hermes_profile TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    started_at TIMESTAMP,
    paused_at TIMESTAMP,
    terminated_at TIMESTAMP,
    total_runtime_seconds INTEGER DEFAULT 0,
    total_tokens INTEGER DEFAULT 0,
    error_count INTEGER DEFAULT 0,
    last_error TEXT,
    metadata TEXT DEFAULT '{}'
);

-- Agent 事件日志
CREATE TABLE agent_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id TEXT NOT NULL,
    event TEXT NOT NULL,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    detail TEXT
);

-- Workflow 运行记录
CREATE TABLE workflow_runs (
    id TEXT PRIMARY KEY,
    workflow_name TEXT NOT NULL,
    workflow_content TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    started_at TIMESTAMP,
    finished_at TIMESTAMP,
    trace_id TEXT,
    error TEXT
);

-- Workflow 步骤记录
CREATE TABLE workflow_steps (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    step_id TEXT NOT NULL,
    agent_name TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    started_at TIMESTAMP,
    finished_at TIMESTAMP,
    duration_ms INTEGER,
    output TEXT,
    error TEXT
);

-- 追踪 Span
CREATE TABLE traces (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trace_id TEXT NOT NULL,
    span_id TEXT NOT NULL,
    parent_span_id TEXT,
    name TEXT NOT NULL,
    agent_name TEXT,
    start_time TIMESTAMP,
    end_time TIMESTAMP,
    duration_ms INTEGER,
    status TEXT,
    events TEXT DEFAULT '[]',
    UNIQUE(trace_id, span_id)
);

-- 审计日志
CREATE TABLE audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    agent_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    tool_name TEXT,
    model_name TEXT,
    tokens_used INTEGER DEFAULT 0,
    cost_usd REAL DEFAULT 0.0,
    duration_ms INTEGER,
    success BOOLEAN DEFAULT 1,
    detail TEXT
);

-- 索引
CREATE INDEX idx_agent_events_agent ON agent_events(agent_id);
CREATE INDEX idx_workflow_steps_run ON workflow_steps(run_id);
CREATE INDEX idx_traces_trace ON traces(trace_id);
CREATE INDEX idx_audit_agent ON audit_log(agent_id);
CREATE INDEX idx_audit_timestamp ON audit_log(timestamp);
```

---

## 4. 错误处理规范

```python
# 所有 sccsos 异常继承自 SCCS OSError

class SCCS OSError(Exception):
    """Base exception for all sccsos errors."""

class AgentNotFoundError(SCCS OSError):
    """Agent spec not found in registry."""

class AgentAlreadyRunningError(SCCS OSError):
    """Attempted to start an already running agent."""

class AgentNotRunningError(SCCS OSError):
    """Operation requires running agent."""

class WorkflowValidationError(SCCS OSError):
    """Workflow YAML is invalid."""

class WorkflowExecutionError(SCCS OSError):
    """Workflow step failed."""

class PolicyViolationError(SCCS OSError):
    """Tool call or resource access denied."""

class BudgetExceededError(SCCS OSError):
    """Token or cost budget exceeded."""

class HermesAdapterError(SCCS OSError):
    """Hermes Agent API communication failed."""
```

---

## 5. 配置规范

### pyproject.toml

```toml
[project]
name = "sccsos"
version = "0.4.0"
description = "Autonomous Agent Operating System"
requires-python = ">=3.11"
dependencies = [
    "pyyaml>=6.0",
    "click>=8.0",
]

[project.scripts]
sccsos = "sccsos.cli:main"
```

### sccsos.yaml（项目配置）

```yaml
# ~/hermesws/sccsos/sccsos.yaml
project:
  name: sccsos
  version: 0.4.0

database:
  path: ./data/sccsos.db

defaults:
  hermes_profile: sccsos
  max_turns: 90
  timeout: 1800

logging:
  level: INFO
  format: json
  directory: ./logs
  retention_days: 30

tracing:
  enabled: true
  export_path: ./traces/

policies:
  default:
    max_tokens_per_session: 100000
    max_cost_usd: 5.0
    allowed_tools:
      - read_file
      - search_files
      - web_search
      - web_extract
      - terminal
    blocked_tools: []
```
