---
title: ADR-004 — SCCS OS 深度架构设计
created: 2026-07-19
updated: 2026-07-19
type: concept
tags: [sccsos, architecture, adr, deep-design]
confidence: high
---

# ADR-004: SCCS OS 深度架构设计

> **状态**: ✅ 已实施 (v0.6.4)
> **领域**: sccsos — 自主智能体操作系统
> **前置**: [[需求分析-SCCS-OS-需求规格说明书]], [[sccsos-architecture-framework]], [[ADR-002-sccsos-feasibility-plan]]

---

## 目录

1. [总体架构](#1-总体架构)
2. [分层架构设计](#2-分层架构设计)
3. [核心组件设计](#3-核心组件设计)
4. [数据流设计](#4-数据流设计)
5. [组件交互设计](#5-组件交互设计)
6. [状态管理与持久化](#6-状态管理与持久化)
7. [安全架构](#7-安全架构)
8. [可观测性架构](#8-可观测性架构)
9. [部署架构](#9-部署架构)
10. [演进路线](#10-演进路线)

---

## 1. 总体架构

### 1.1 架构全景

```
┌──────────────────────────────────────────────────────────────────────┐
│                          用户接口层                                    │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────────┐   │
│  │  CLI (Click)  │  │ HTTP API     │  │  Personaities (YAML定义)  │   │
│  │  sccsos agent │  │ REST + SSE   │  │  agent-architect         │   │
│  │  sccsos wf    │  │ X-Tenant-ID  │  │  code-reviewer           │   │
│  │  sccsos audit │  │ /agents, /wf │  │  doc-writer              │   │
│  └──────┬────────┘  └──────┬───────┘  └──────────────────────────┘   │
│         │                  │                                           │
├─────────┼──────────────────┼──────────────────────────────────────────┤
│         ▼                  ▼                                           │
│                    编排编排层（Orchestration Layer）                      │
│  ┌──────────────────────────────────────────────────────────────┐    │
│  │  WorkflowEngine (orchestrator.py)                             │    │
│  │  ┌────────────┐  ┌────────────┐  ┌────────────┐              │    │
│  │  │ DAG 解析器  │  │ 并行执行器  │  │ 条件求值器  │              │    │
│  │  │ 拓扑排序    │  │ ThreadPool │  │ 表达式引擎  │              │    │
│  │  └────────────┘  └────────────┘  └────────────┘              │    │
│  │  ┌────────────┐  ┌────────────┐  ┌────────────┐              │    │
│  │  │ 模板引擎    │  │ 结果聚合器  │  │ 退避重试器  │              │    │
│  │  │ Jinja2沙箱  │  │ 变量注入    │  │ 指数回退    │              │    │
│  │  └────────────┘  └────────────┘  └────────────┘              │    │
│  └──────────────────────────────────────────────────────────────┘    │
│  ┌──────────────────────────────────────────────────────────────┐    │
│  │  StepExecutor (step_executor.py) — 单步执行引擎                │    │
│  │  输入 → 模板渲染 → 条件校验 → Hermes调用 → 审计记录 → 输出     │    │
│  └──────────────────────────────────────────────────────────────┘    │
│                                                                      │
├──────────────────────────────────────────────────────────────────────┤
│                       Agent 管理层（Agent Layer）                        │
│  ┌──────────────────────────────────────────────────────────────┐    │
│  │  AgentRegistry (registry.py)                                  │    │
│  │  ┌────────────┐  ┌────────────┐  ┌────────────┐              │    │
│  │  │ YAML解析    │  │ Schema校验  │  │ 注册/发现   │              │    │
│  │  └────────────┘  └────────────┘  └────────────┘              │    │
│  └──────────────────────────────────────────────────────────────┘    │
│  ┌──────────────────────────────────────────────────────────────┐    │
│  │  LifecycleManager (lifecycle.py)                               │    │
│  │  ┌─────────┐  ┌──────────┐  ┌──────────┐  ┌───────────┐      │    │
│  │  │ CREATED  │→ │ RUNNING  │→ │ PAUSED   │→ │ TERMINATED│      │    │
│  │  └─────────┘  └──────────┘  └──────────┘  └───────────┘      │    │
│  │               │  ↕         │  ↕                               │    │
│  │               │  FAILED    │  RESTART                         │    │
│  │               └────────────┘                                  │    │
│  └──────────────────────────────────────────────────────────────┘    │
│  ┌──────────────────────────────────────────────────────────────┐    │
│  │  AgentRunner (agent_runner.py) — 后台进程管理                  │    │
│  │  subprocess.Popen → pid跟踪 → stdout/stderr → 自动重启        │    │
│  └──────────────────────────────────────────────────────────────┘    │
│  ┌──────────────────────────────────────────────────────────────┐    │
│  │  PersonalityRegistry (personality.py)                          │    │
│  │  YAML定义 → system prompt注入 → 模型配置 → 温度参数            │    │
│  └──────────────────────────────────────────────────────────────┘    │
│                                                                      │
├──────────────────────────────────────────────────────────────────────┤
│                   基础设施与运行 (Infrastructure Layer)                   │
│  ┌──────────────────────────────────────────────────────────────┐    │
│  │  HermesAdapter (hermes_adapter.py)                             │    │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐        │    │
│  │  │ CLI子进程管理  │  │ 三层安全防线   │  │ 策略透传     │        │    │
│  │  │ stdin/stdout  │  │ 预算/命令/工具 │  │ PolicyEngine│        │    │
│  │  └──────────────┘  └──────────────┘  └──────────────┘        │    │
│  └──────────────────────────────────────────────────────────────┘    │
│  ┌──────────────────────────────────┐  ┌────────────────────────┐   │
│  │  Database (SQLite + WAL + FTS5)  │  │  Config (YAML 加载)    │   │
│  │  自动迁移 · 多租户隔离 ·  查询    │  │  sccsos.yaml → Dataclass│   │
│  └──────────────────────────────────┘  └────────────────────────┘   │
│                                                                      │
├──────────────────────────────────────────────────────────────────────┤
│                    可观测性层 (Observability Layer)                     │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐  │
│  │ Tracer   │ │ Auditor  │ │ Logger   │ │AlertMgr  │ │Webhook   │  │
│  │ Span追踪  │ │ Token审计 │ │ JSON日志  │ │阈值告警   │ │HTTP回调   │  │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘ └──────────┘  │
│                                                                      │
├──────────────────────────────────────────────────────────────────────┤
│                      安全策略层 (Security Layer)                        │
│  ┌──────────────────────────────────────────────────────────────┐    │
│  │  PolicyEngine (policy.py)   +   Sandbox (sandbox.py)          │    │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌─────────────┐     │    │
│  │  │ 预算封顶  │ │ 工具 ACL  │ │命令白名单 │ │危险模式检测   │     │    │
│  │  └──────────┘ └──────────┘ └──────────┘ └─────────────┘     │    │
│  └──────────────────────────────────────────────────────────────┘    │
│                                                                      │
├──────────────────────────────────────────────────────────────────────┤
│                      Hermes Agent 核心层                               │
│  ┌──────────┐ ┌──────────────┐ ┌────────────────────┐              │
│  │ 工具系统  │ │ 记忆系统      │ │ 消息网关 + 平台适配 │              │
│  │ 47+ 内置  │ │ 热/温/冷     │ │ 15+ 平台           │              │
│  │ MCP 扩展  │ │ FTS5检索     │ │ Gateway 路由       │              │
│  └──────────┘ └──────────────┘ └────────────────────┘              │
│                                                                      │
├──────────────────────────────────────────────────────────────────────┤
│                    LLM Provider 层                                     │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │  DeepSeek v4 Flash/Pro · OpenRouter · 本地模型               │    │
│  └─────────────────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────────────┘
```

### 1.2 架构原则实例化

| 原则 | 在 SCCS OS 中的体现 |
|------|-------------------|
| **边界驱动设计** | 7 个关注域各为独立包（core/ / security/ / observability/ / memory/ / api/），通过 Runtime 统一入口组装 |
| **可逆性优先** | Workflow YAML 优先于代码固化，条件分支可在不修改代码的前提下调整路径 |
| **可观测性即功能** | 每个 StepExecutor 自动插入 Tracer + Auditor，无需业务代码感知 |
| **复杂度不消灭，只转移** | 编排复杂度从代码转移到 Workflow YAML，Hermes 适配复杂度封装到 Adapter |
| **默认拒绝** | PolicyEngine 默认拒绝所有工具（allowed_tools 白名单机制）。命令白名单仅允许预置命令 |

### 1.3 依赖图谱

```
AgentRuntime (入口)
 ├── Config (YAML → Dataclass)
 ├── Database (SQLite 持久化)
 ├── AgentRegistry (AgentSpec 管理)
 │    └── PersonalityRegistry (角色定义)
 ├── LifecycleManager (状态管理)
 │    └── AgentRunner (子进程管理)
 ├── WorkflowEngine (DAG 编排)
 │    └── StepExecutor (单步执行)
 │         ├── HermesAdapter (Hermes 调用)
 │         │    ├── PolicyEngine (前置安全检查)
 │         │    └── Sandbox (命令过滤)
 │         ├── Tracer (跨 Span)
 │         └── Auditor (Token 审计)
 ├── MemoryStore (跨会话记忆)
 ├── Tracer (链路追踪)
 ├── Auditor (Token 审计)
 ├── WebhookNotifier (外部通知)
 ├── AlertManager (阈值告警)
 └── PricingTable (外部定价)
```

---

## 2. 分层架构设计

### 2.1 层级定义

| 层 | 模块 | 职责 | 依赖方向 |
|----|------|------|---------|
| L1 — 用户接口层 | cli.py, api/server.py | CLI 交互、HTTP API 暴露 | → L2 |
| L2 — 编排层 | orchestrator.py, step_executor.py | Workflow DAG 解析、执行、聚合 | → L3 |
| L3 — Agent 管理层 | registry.py, lifecycle.py, agent_runner.py, personality.py | Agent 定义、生命周期、进程管理 | → L4 |
| L4 — 基础设施层 | hermes_adapter.py, database.py, config.py | Hermes 桥接、持久化、配置 | → L5 |
| L5 — 可观测性层 | tracer.py, auditor.py, logger.py, alert_manager.py, webhook.py | 追踪、审计、告警 | 水平 |
| L5 — 安全策略层 | policy.py, sandbox.py | 预算、ACL、白名单 | 水平 |
| L6 — Hermes 核心 | Hermes Agent | Agent 运行时、工具系统、记忆 | 外部依赖 |
| L7 — LLM 服务 | DeepSeek API 等 | 大模型推理 | 外部服务 |

### 2.2 层间通信契约

```
L1 ──CLI 解析──→ L2: WorkflowDef, AgentSpec
L1 ──HTTP──→ L2: JSON API 请求/响应

L2 ──StepExec──→ L3: Agent 执行请求（角色 + 提示词 + 参数）
L3 ──start/stop──→ L4: 进程启动/停止命令
L3 ──register──→ L4: Agent 定义持久化

L4 ──hermes run──→ L6: Hermes CLI 子进程调用
L4 ──query/write──→ SQLite: 数据持久化

L2/L3 ──事件──→ L5: span 记录、审计写入、告警评估
L2/L4 ──检查──→ L5: 预算校验、工具 ACL、命令过滤
```

### 2.3 严格分层约束

| 规则 | 描述 | 违反后果 |
|------|------|---------|
| L1 不可直接调用 L3/L4 | CLI/API 必须经过编排层 | 绕过安全检查 |
| L4 不可反向依赖 L1/L2 | 基础设施层不知晓上层业务 | 循环依赖 |
| L5 层仅观察不阻断（安全除外） | 可观测性层只读状态 | 写操作污染 |
| L5 安全层可阻断 L4 调用 | PolicyEngine 可拒绝 Hermes 执行 | 安全失效 |
| L6/L7 外部依赖通过 Adapter 隔离 | Adapter 模式封装 Hermes | 测试困难 |

---

## 3. 核心组件设计

### 3.1 AgentRuntime — 统一入口

```
类: AgentRuntime

职责:
  - 统一管理所有核心服务的生命周期
  - 懒加载初始化：Runtime 对象可提前创建，initialize() 延迟实际初始化
  - 依赖注入：所有子服务通过 Runtime 传递，无全局变量

属性:
  config       → AgentOSConfig       (配置)
  db           → Database            (数据库)
  registry     → AgentRegistry       (Agent 注册表)
  lifecycle    → LifecycleManager    (生命周期)
  adapter      → HermesAdapter       (Hermes 桥接)
  engine       → WorkflowEngine      (编排引擎)
  runner       → AgentRunner         (进程管理)
  tracer       → Tracer              (追踪)
  auditor      → Auditor             (审计)
  pricing      → PricingTable        (定价)
  memory_store → MemoryStore         (持久记忆)
  webhook      → WebhookNotifier     (通知)
  alert_mgr    → AlertManager        (告警)

生命周期:
  __init__()          → 创建 Runtime 对象（无副作用）
  initialize()        → 按需初始化所有子服务
  close()             → 优雅关闭所有资源
```

### 3.2 WorkflowEngine — DAG 编排引擎

```
类: WorkflowEngine

输入: WorkflowDef (从 YAML 解析)
输出: WorkflowResult (每步响应 + trace + audit)

核心流程:
  1. parse_yaml() → WorkflowDef (字段校验 + 默认值填充)
  2. build_dag()  → 拓扑排序 (Kahn 算法, 循环依赖检测)
  3. execute()    → 按拓扑序执行
     ├── 并行组 → ThreadPoolExecutor (max_workers 可配置)
     ├── 条件分支 → 表达式求值 (condition 字段)
     ├── 模板注入 → Jinja2 SandboxedEnvironment
     └── 退避重试 → 指数回退 (3 次, base=2s)
  4. aggregate()  → WorkflowResult (收集所有步骤响应)

数据结构:
  WorkflowDef:
    - name: str
    - steps: list[StepDef]
    - parallel_groups: list[ParallelGroup] (可选)
    - timeout: int (可选)
    - max_retries: int (可选)

  StepDef:
    - id: str (唯一标识, 下划线风格)
    - agent: str (Agent 名称)
    - prompt: str (Jinja2 模板)
    - depends_on: list[str] (可选)
    - condition: str (可选, Python 表达式)
    - output: str (可选, 文件输出路径)

  ParallelGroup:
    - id: str
    - steps: list[str] (step id 列表)
    - max_concurrent: int (可选)
```

### 3.3 StepExecutor — 单步执行引擎

```
类: StepExecutor

输入: StepDef + context (变量字典)
输出: StepResult (response + trace_id + audit_id + timing)

核心流程:
  1. render_template()     → Jinja2 渲染 prompt
  2. evaluate_condition()  → 条件分支求值
  3. pre_flight_check()    → PolicyEngine 预算 + 工具检查
  4. execute_hermes()      → HermesAdapter.run()
  5. record_audit()        → Auditor.record()
  6. record_span()         → Tracer.end_span()
  7. cache_output()        → 结果缓存供下游步骤使用

设计要点:
  - 每次执行自动生成新 trace_id + audit_id
  - 失败上报至 WorkflowEngine 决定是否重试
  - 所有输出统一为字符串，支持文件写入
```

### 3.4 HermesAdapter — Hermes 桥接

```
类: HermesAdapter

职责:
  - 通过 Hermes CLI 子进程执行 Agent 对话
  - 三层安全防线（预算封顶 / 命令白名单 / 工具 ACL）
  - Prompt 预处理（Personality 注入 + 策略注入）

架构:
  ┌─────────────────────────────────────────┐
  │ HermesAdapter                            │
  │  ┌──────────────────────────────────┐   │
  │  │ pre_flight_check()                │   │
  │  │  → PolicyEngine.budget_ok()       │   │
  │  │  → PolicyEngine.tool_allowed()    │   │
  │  └──────────┬───────────────────────┘   │
  │             ▼                            │
  │  ┌──────────────────────────────────┐   │
  │  │ execute(agent_spec, prompt)       │   │
  │  │  → run_hermes_cli()              │   │
  │  │  → Sandbox.validate_command()    │   │
  │  └──────────┬───────────────────────┘   │
  │             ▼                            │
  │  ┌──────────────────────────────────┐   │
  │  │ post_process()                    │   │
  │  │  → 提取 response                 │   │
  │  │  → 记录 tokens                   │   │
  │  └──────────────────────────────────┘   │
  └─────────────────────────────────────────┘

三层安全防线:
  Layer 1 (Adapter 入口): 预算 → PolicyEngine.budget_ok()
  Layer 2 (Adapter 内部): 工具 → PolicyEngine.tool_allowed()
  Layer 3 (Hermes CLI): 命令 → Sandbox.validate_command()
```

### 3.5 LifecycleManager — 状态机

```
状态定义:
  CREATED    — Agent spec 已注册，未启动
  RUNNING    — Agent 有活跃会话或后台进程
  PAUSED     — Agent 暂停，上下文保留
  FAILED     — Agent 异常，需人工介入
  TERMINATED — Agent 终止，资源释放

状态转换:
  CREATED ─── start() ───→ RUNNING     [校验: 名称存在、非重复启动]
  RUNNING ─── pause() ───→ PAUSED      [校验: Agent 在运行]
  PAUSED  ─── resume() ──→ RUNNING     [校验: Agent 已暂停]
  RUNNING ─── fail() ────→ FAILED      [校验: 来自 Hermes 错误信号]
  RUNNING ─── stop() ────→ TERMINATED  [清理: 进程终止 + 资源释放]
  PAUSED  ─── stop() ────→ TERMINATED  [清理: 上下文丢弃]
  FAILED  ─── restart() ─→ RUNNING     [策略: 最多重试 3 次]
  FAILED  ─── stop() ────→ TERMINATED  [清理: 记录失败原因]

持久化:
  - 状态变更即时写入 SQLite
  - 每个状态转换记录时间戳 + 原因 + 事件 ID
  - 重启后从 SQLite 重建状态（Terminated/Failed 不重建）
```

### 3.6 PolicyEngine — 策略引擎

```
类: PolicyEngine

预检方法:
  budget_ok(tenant_id, agent_name) → bool
    - 从 audit_log 汇总 tenant+agent 累计成本
    - 对比 AgentSpec.policy.max_cost_usd
    - 超限 → PolicyViolation + 记录告警

  tool_allowed(tool_name, agent_name) → bool
    - 检查工具是否在 allowed_tools 中
    - 检查是否在 blocked_tools 中
    - 默认拒绝：不在白名单中的工具视为禁止

  command_allowed(command) → bool
    - Sandbox.validate_command() 代理
    - 命令前缀匹配白名单
    - 危险模式检测（; 管道 重定向 等）

策略覆盖优先级:
  1. AgentSpec.policy (per-agent 细粒度配置)
  2. sccsos.yaml policies.default (全局默认)
  3. 内置 DEFAULT_ALLOWED_TOOLS (代码级回退)

设计要点:
  - 每次 delegate_task 前执行
  - 不修改 Hermes 核心代码（外部 wrapper 模式）
  - per-agent 策略覆盖粒度（不同 Agent 不同约束）
```

### 3.7 Tracer — 链路追踪

```
类: Tracer

数据结构:
  Span:
    - span_id: str        (UUID v4)
    - parent_span_id: str (可选, 用于构建追踪树)
    - trace_id: str       (根 span 共享)
    - name: str           (操作名称)
    - start_time: str     (ISO 8601)
    - end_time: str       (ISO 8601)
    - status: str         (OK / ERROR)
    - events: list[SpanEvent] (工具调用、LLM 调用等)
    - attributes: dict    (自定义属性)

核心方法:
  start_span(name, parent_id=None) → Span
  end_span(span, status="OK") → None
  add_event(span, name, attributes={}) → None
  export(trace_id) → JSON 文件写入

追踪树示例:
  Trace: workflow-run-abc123
    ├── Span: workflow-execute (root)
    │   ├── Span: step-requirements_analysis
    │   │   ├── Event: hermes-call (耗时 3.2s)
    │   │   └── Event: audit-record (tokens=1423)
    │   ├── Span: step-architecture_design
    │   │   └── Event: hermes-call (耗时 5.1s)
    │   └── Span: step-synthesis
    │       └── Event: hermes-call (耗时 2.1s)

设计要点:
  - 线程安全（threading.local + Lock）
  - 导出为 JSON 可读格式
  - 支持未来集成 OpenTelemetry
```

### 3.8 MemoryStore — 持久记忆

```
类: MemoryStore

数据结构:
  MemoryEntry:
    - key: str          (命名空间:agent:key)
    - value: str        (JSON 序列化)
    - tenant_id: str    (多租户隔离)
    - agent_name: str   (Agent 范围)
    - ttl: int          (过期秒数, 0=永久)
    - created_at: str   (ISO 8601)
    - updated_at: str   (ISO 8601)

核心方法:
  put(key, value, ttl=0) → None
  get(key) → str | None
  delete(key) → None
  list(prefix="") → list[MemoryEntry]
  expire() → int (清理过期条目)

使用场景:
  - 跨会话 Agent 偏好保存
  - Workflow 中间结果缓存
  - 用户会话状态保持

设计要点:
  - Per-tenant per-agent 隔离 (复合 key)
  - TTL 后台清理 (惰性 + 主动)
  - SQLite 持久化，重启不丢失
  - 零外部依赖（不依赖 Redis 等）
```

---

## 4. 数据流设计

### 4.1 主数据流：Workflow 执行

```
用户 (CLI/API)
  │
  │  sccsos workflow run 架构评审.yaml -i "设计认证模块"
  ▼
┌─────────────────────┐
│  CLI (cli.py)        │ ① 解析输入参数
│  → load_workflow()   │    加载 YAML → WorkflowDef
│  → Runtime.engine    │
└─────────┬───────────┘
          │ WorkflowDef
          ▼
┌─────────────────────┐
│  WorkflowEngine      │ ② DAG 解析
│  → build_dag()       │    拓扑排序 + 循环检测
│  → execute()         │    遍历拓扑序列
└─────────┬───────────┘
          │ StepDef + Context
          ▼
┌─────────────────────┐
│  StepExecutor        │ ③ 单步执行
│  → render_template() │    Jinja2 模板渲染
│  → check_condition() │    条件分支判断
│  → execute_step()    │    调用 HermesAdapter
│  → cache_result()    │    结果缓存
└─────────┬───────────┘
          │ AgentSpec + RenderedPrompt
          ▼
┌─────────────────────┐
│  HermesAdapter       │ ④ Hermes 调用
│  → pre_flight_check  │    预算 + 工具检查
│  → run_hermes_cli()  │    子进程执行
│  → parse_response()  │    响应提取
└─────────┬───────────┘
          │ Hermes CLI
          ▼
┌─────────────────────┐
│  Hermes Agent        │ ⑤ Agent 执行
│  → 加载 Personality  │    system prompt 注入
│  → LLM 调用          │    DeepSeek API
│  → 工具调用          │    按需使用工具
│  → 返回响应          │
└─────────┬───────────┘
          │ Agent Response
          ▼
┌─────────────────────┐
│  结果回传路径         │ ⑥ 逐层返回
│  Adapter → Executor   │    响应 + tokens + timing
│  → Engine → CLI       │    聚合到 WorkflowResult
└─────────────────────┘
```

### 4.2 数据流：安全校验路径

```
    HermesAdapter.run()
         │
         ├──→ PolicyEngine.budget_ok()
         │      Query: SELECT SUM(cost) FROM audit_log
         │      WHERE tenant=? AND agent=?
         │      Decision: cost ≤ max_cost_usd ?
         │       │
         │       ├── True → 继续
         │       └── False → PolicyViolation ✋
         │
         ├──→ PolicyEngine.tool_allowed()
         │      Check: tool_name IN allowed_tools
         │      Check: tool_name NOT IN blocked_tools
         │       │
         │       ├── True → 继续
         │       └── False → PolicyViolation ✋
         │
         ├──→ Sandbox.validate_command()
         │      Match: command PREFIX any entry in whitelist
         │      Detect: shell escape chars in dangerous_patterns
         │       │
         │       ├── Pass → 执行
         │       └── Fail → 拒绝执行 ✋
         │
         └──→ Hermes CLI (已安全校验)
```

### 4.3 数据流：可观测性路径

```
每个可执行路径自动烘焙可观测性:

StepExecutor.execute_step()
  │
  ├──→ Tracer.start_span("step-{step_id}")
  │      ├── add_event("pre_flight_check", {result})
  │      ├── add_event("hermes_call", {model, tokens})
  │      └── add_event("step_complete", {status, duration})
  │
  ├──→ Auditor.record(tenant, agent, model, tokens, cost)
  │      INSERT INTO audit_log ...
  │       │
  │       └──→ AlertManager.evaluate()
  │              Check: error_rate > threshold ?
  │              Check: fail_count > threshold ?
  │               │
  │               └──→ WebhookNotifier.notify()
  │                      POST {event, tenant, metric} → URL
  │
  └──→ Logger.info("step_executed", {step_id, status, duration})
         JSON {timestamp, level, event, data}

导出路径:
  traces/ → {trace_id}.json     [Span 树完整导出]
  logs/   → sccsos-{date}.log   [JSON Lines 格式]
  Audit   → SQLite audit_log    [可查询 + 可聚合]
```

### 4.4 数据流：生命周期管理

```
用户: sccsos agent start architect
  │
  ├──→ LifecycleManager.start("architect")
  │      校验: 当前状态 = CREATED
  │       │
  │       ├── True → AgentRunner.spawn()
  │       │          subprocess.Popen(["hermes", "agent", "run", ...])
  │       │          pid → SQLite agent_instances.pid
  │       │
  │       └── False → StateTransitionError
  │
  ├──→ 状态变更: CREATED → RUNNING
  │      UPDATE agent_instances SET status='RUNNING', pid=? WHERE name=?
  │
  ├──→ Auditor.record("lifecycle", "start", agent_name)
  │
  └──→ 返回: {"status": "RUNNING", "pid": 12345}

用户: sccsos agent status architect
  ├──→ LifecycleManager.get_status("architect")
  │      SELECT status, pid, started_at FROM agent_instances WHERE name=?
  │       │
  │       └──→ AgentRunner.is_alive(pid)
  │              如果子进程已死 → 状态标记 FAILED
  │
  └──→ 返回: {"status": "RUNNING", "pid": 12345, "uptime": "2h13m"}
```

---

## 5. 组件交互设计

### 5.1 AgentRuntime 初始化时序

```
用户  AgentRuntime  Config  Database  Registry  Lifecycle  Adapter  Tracer
 │      │            │        │          │          │         │        │
 │   initialize()   │        │          │          │         │        │
 │──────►           │        │          │          │         │        │
 │      │ 加载配置   │        │          │          │         │        │
 │      ├──────────►│        │          │          │         │        │
 │      │◄──────────┤        │          │          │         │        │
 │      │ 连接数据库 │        │          │          │         │        │
 │      ├──────────────────►│          │          │         │        │
 │      │◄──────────────────┤          │          │         │        │
 │      │ 自动迁移   │        │          │          │         │        │
 │      ├──────────────────►│          │          │         │        │
 │      │◄──────────────────┤          │          │         │        │
 │      │ 加载Agent  │        │          │          │         │        │
 │      ├─────────────────────────────►│          │         │        │
 │      │◄─────────────────────────────┤          │         │        │
 │      │ 初始化状态  │        │          │          │         │        │
 │      ├──────────────────────────────────────►│         │        │
 │      │◄──────────────────────────────────────┤         │        │
 │      │ 创建Adapter │        │          │          │         │        │
 │      ├───────────────────────────────────────────────►│        │
 │      │ 创建Tracer  │        │          │          │         │        │
 │      ├───────────────────────────────────────────────────────►│
 │      │ 全部就绪    │        │          │          │         │        │
 │◄─────┤            │        │          │          │         │        │
```

### 5.2 Workflow 执行时序（并行场景）

```
CLI  WorkflowEngine  StepExecutor-1  StepExecutor-2  HermesAdapter  Tracer  Auditor
 │        │                │               │              │           │       │
 │ run()  │                │               │              │           │       │
 ├───────►│                │               │              │           │       │
 │        │ build_dag()    │               │              │           │       │
 │        │───────┐        │               │              │           │       │
 │        │ 拓扑排序        │               │              │           │       │
 │        │◄──────┘        │               │              │           │       │
 │        │ 并行组执行      │               │              │           │       │
 │        ├────────────────►│ (step-1)      │              │           │       │
 │        ├─────────────────│──────────────►│ (step-2)      │           │       │
 │        │                │               │              │           │       │
 │        │                │ start_span()  │              │           │       │
 │        │                ├─────────────────────────────►│           │       │
 │        │                │               │ start_span() │           │       │
 │        │                │               ├─────────────────────────►│       │
 │        │                │ execute()     │              │           │       │
 │        │                ├──────────────────────────────►│           │       │
 │        │                │               │ execute()    │           │       │
 │        │                │               ├───────────────────────►│       │
 │        │                │               │              │           │       │
 │        │                │   [并行执行中, 各步骤独立]     │           │       │
 │        │                │               │              │           │       │
 │        │                │◄──────────────┤              │           │       │
 │        │                │               │◄─────────────┤           │       │
 │        │                │               │              │           │       │
 │        │ 等待所有并行完成 │               │              │           │       │
 │        │◄───────────────┼───────────────┤              │           │       │
 │        │ 顺序步(step-3)  │               │              │           │       │
 │        ├────────────────►│ (step-3)      │              │           │       │
 │        │                │ ...            │              │           │       │
 │        │                │◄───────────────┤              │           │       │
 │        │ 聚合结果        │               │              │           │       │
 │        │───────┐        │               │              │           │       │
 │        │ 生成报告        │               │              │           │       │
 │        │◄──────┘        │               │              │           │       │
 │◄───────┤                │               │              │           │       │
 │ 结果   │                │               │              │           │       │
```

### 5.3 安全策略交互时序

```
HermesAdapter           PolicyEngine              Sandbox              Database
     │                       │                      │                    │
     │ budget_ok()           │                      │                    │
     ├──────────────────────►│                      │                    │
     │                       │ 查询累计成本          │                    │
     │                       ├───────────────────────────────► audit_log
     │                       │◄───────────────────────────────┤
     │                       │ 成本 ≤ max_cost_usd ?           │
     │                       │──┐                             │
     │                       │  │ True/False                  │
     │◄──────────────────────┤  │                             │
     │                       │   │                             │
     │ tool_allowed(tool)    │   │                             │
     ├──────────────────────►│   │                             │
     │                       │ tool IN allowed_tools ?         │
     │                       │ tool NOT IN blocked_tools ?     │
     │◄──────────────────────┤   │                             │
     │                       │   │                             │
     │ validate_command(cmd) │   │                             │
     ├───────────────────────│───│──────────────────────────►│
     │                       │   │                             │ Sandbox
     │                       │   │                             │──┐
     │                       │   │                             │  │ 检查
     │◄──────────────────────│───│─────────────────────────────┤  │
     │                       │   │                             │◄─┘
     │ 三重校验通过          │   │                             │
     │──┐                    │   │                             │
     │  │ 执行 Hermes CLI    │   │                             │
     │◄─┘                    │   │                             │
```

---

## 6. 状态管理与持久化

### 6.1 SQLite Schema 设计

```
-- Agent 定义表
CREATE TABLE agent_specs (
    name            TEXT PRIMARY KEY,
    version         TEXT NOT NULL,
    description     TEXT,
    personality     TEXT NOT NULL,
    profile         TEXT NOT NULL DEFAULT 'sccsos',
    config          TEXT NOT NULL DEFAULT '{}',       -- JSON: toolsets, lifecycle
    policy          TEXT,                              -- JSON: per-agent policy
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now')),
    tenant_id       TEXT NOT NULL DEFAULT 'default'
);

-- Agent 实例表（运行时状态）
CREATE TABLE agent_instances (
    id              TEXT PRIMARY KEY,                  -- UUID
    agent_name      TEXT NOT NULL REFERENCES agent_specs(name),
    status          TEXT NOT NULL DEFAULT 'CREATED',   -- CREATED|RUNNING|PAUSED|FAILED|TERMINATED
    pid             INTEGER,                           -- 后台进程 ID
    session_id      TEXT,                              -- Hermes 会话 ID
    started_at      TEXT,
    stopped_at      TEXT,
    error_message   TEXT,
    tenant_id       TEXT NOT NULL DEFAULT 'default',
    FOREIGN KEY (agent_name) REFERENCES agent_specs(name)
);

-- Workflow 执行记录
CREATE TABLE workflow_runs (
    id              TEXT PRIMARY KEY,                  -- UUID
    workflow_name   TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'PENDING',    -- PENDING|RUNNING|COMPLETED|FAILED
    input_context   TEXT,
    result          TEXT,                               -- JSON: 各步骤响应
    trace_id        TEXT,
    started_at      TEXT,
    completed_at    TEXT,
    tenant_id       TEXT NOT NULL DEFAULT 'default'
);

-- 审计日志（核心表）
CREATE TABLE audit_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp       TEXT NOT NULL DEFAULT (datetime('now')),
    tenant_id       TEXT NOT NULL DEFAULT 'default',
    agent_name      TEXT,
    workflow_id     TEXT,
    model           TEXT,
    tokens_in       INTEGER DEFAULT 0,
    tokens_out      INTEGER DEFAULT 0,
    cost_usd        REAL DEFAULT 0.0,
    operation       TEXT,                               -- lifecycle|workflow|hermes
    status          TEXT,                                -- OK|ERROR|VIOLATION
    duration_ms     INTEGER,
    metadata        TEXT                                -- JSON
);
CREATE INDEX idx_audit_tenant ON audit_log(tenant_id);
CREATE INDEX idx_audit_agent ON audit_log(agent_name);
CREATE INDEX idx_audit_time ON audit_log(timestamp);

-- 持久记忆表
CREATE TABLE memory_store (
    key             TEXT PRIMARY KEY,
    value           TEXT NOT NULL,
    tenant_id       TEXT NOT NULL DEFAULT 'default',
    agent_name      TEXT NOT NULL DEFAULT 'default',
    ttl             INTEGER DEFAULT 0,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX idx_memory_tenant ON memory_store(tenant_id);

-- 追踪数据表
CREATE TABLE traces (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    trace_id        TEXT NOT NULL,
    span_id         TEXT NOT NULL UNIQUE,
    parent_span_id  TEXT,
    name            TEXT NOT NULL,
    start_time      TEXT NOT NULL,
    end_time        TEXT,
    status          TEXT DEFAULT 'PENDING',
    events          TEXT,                                -- JSON array
    attributes      TEXT,                                -- JSON
    tenant_id       TEXT NOT NULL DEFAULT 'default'
);
CREATE INDEX idx_traces_trace ON traces(trace_id);
```

### 6.2 自动迁移策略

```
Database.auto_migrate():
  1. 查询 PRAGMA user_version (当前 schema 版本号)
  2. 按版本顺序执行迁移脚本
  3. 每个迁移脚本事务性执行 (BEGIN/COMMIT)
  4. 迁移失败回滚，输出迁移错误

版本管理:
  v1 (初始): agent_specs, agent_instances
  v2: audit_log, traces
  v3: workflow_runs
  v4: memory_store, policy 字段
  v5: tenant_id 全表添加
  v6: 索引优化

迁移示例:
  -- v2: audit_log
  CREATE TABLE IF NOT EXISTS audit_log (...);
  UPDATE user_version SET version=2;
```

### 6.3 状态一致性保证

| 场景 | 保证策略 |
|------|---------|
| Runtime 崩溃 | WAL 模式确保最后写入不丢失。重启后扫描 agent_instances，已死进程标 FAILED |
| Workflow 执行中断 | 每步完成后写入 workflow_runs.result，重启后可恢复 |
| 并发状态更新 | SQLite 串行写入，单线程写操作无竞态 |
| 进程僵死 | AgentRunner 定时心跳检查，无响应自动 FAILED |
| 多租户数据隔离 | 全部查询 WHERE tenant_id=?，防止跨租户数据泄露 |

---

## 7. 安全架构

### 7.1 安全分层模型

```
Layer 1: 命令注入防护 ── Sandbox (sandbox.py)
  ├── 命令白名单: 仅允许预设命令（hermes, git, ls, cat, python3 等）
  ├── 危险模式检测: Shell 转义字符（; | & ` $() {} []）
  └── 可配置: dangerous_patterns 从 sccsos.yaml 加载

Layer 2: 工具权限控制 ── Tool ACL (policy.py)
  ├── allowed_tools: 白名单列表
  ├── blocked_tools: 黑名单列表
  └── 默认拒绝: 不在白名单中的工具视同禁止

Layer 3: 预算封顶 ── Budget Engine (policy.py)
  ├── max_tokens_per_session: 单次会话 Token 上限
  ├── max_cost_usd: 累计成本上限
  └── 实时查询 audit_log 汇总累计值

Layer 4: Secret 保护 ── 环境变量 + .env
  ├── API Key 不硬编码
  ├── Secret 仅存在于环境变量
  └── .env 文件不纳入版本控制

Layer 5: 多租户隔离 ── Database + API
  ├── DB schema 级: 全部表含 tenant_id 字段
  ├── API 级: X-Tenant-ID 请求头路由
  └── 查询级: WHERE tenant_id=? 强制过滤
```

### 7.2 威胁模型

| 威胁 | 层 | 缓解措施 | 严重程度 |
|------|-----|---------|---------|
| Shell 注入 | L1 | 命令白名单 + 危险模式检测 | 🔴 高危 |
| 工具滥用 | L2 | 工具 ACL + 默认拒绝 | 🟡 中危 |
| 预算失控 | L3 | 预算封顶 + 实时审计 | 🟡 中危 |
| API Key 泄露 | L4 | 环境变量 + .gitignore | 🔴 高危 |
| 跨租户数据访问 | L5 | tenant_id 强制过滤 | 🟡 中危 |
| 无限递归 Agent | L1/L3 | max_turns + max_cost_usd 双重保护 | 🟢 低危 |

### 7.3 安全测试验证

| 测试场景 | 方法 | 预期 |
|---------|------|------|
| 命令注入 | `sccsos agent ask architect "; rm -rf /"` | 拒绝执行 |
| 越权工具 | 请求 blocked_tools 中的工具 | PolicyViolation |
| 超预算 | 设 max_cost_usd=0 后执行 | 拒绝执行 |
| 跨租户 | Tenant A 查询 Tenant B 数据 | 空结果 |

---

## 8. 可观测性架构

### 8.1 可观测性三支柱

```
┌─────────────────────────────────────────────────────────────────────┐
│                     可观测性三支柱                                     │
│                                                                      │
│  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐   │
│  │      Tracing       │  │    Logging        │  │     Metrics       │   │
│  │                    │  │                   │  │                   │   │
│  │  • Span 树        │  │  • JSON Lines     │  │  • Token 统计    │   │
│  │  • 时序数据       │  │  • 日志轮转       │  │  • 成本核算      │   │
│  │  • 父子关系       │  │  • 多级日志级别   │  │  • 错误率        │   │
│  │  • 事件详情       │  │  • 可搜索格式     │  │  • 告警阈值      │   │
│  │                    │  │                   │  │                   │   │
│  │  导出: traces/     │  │  导出: logs/      │  │  导出: 审计SQLite │   │
│  └──────────────────┘  └──────────────────┘  └──────────────────┘   │
│                                                                      │
│  集成:                                                                 │
│  ┌─────────────────────────────────────────────────────────────────┐ │
│  │  sccsos audit report → 终端表格                                  │ │
│  │  sccsos health → 组件状态                                       │ │
│  │  Webhook → 外部系统集成 (Slack, Teams)                          │ │
│  └─────────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────┘
```

### 8.2 告警规则

```
AlertManager.evaluate():

规则 1: 错误率告警
  trigger: error_count / total_count > threshold (默认 0.1 = 10%)
  action: alert_manager.add_alert("error_rate_exceeded", {rate, threshold})

规则 2: 连续失败告警
  trigger: consecutive_failures > threshold (默认 3)
  action: alert_manager.add_alert("consecutive_failures_exceeded", {count, threshold})

规则 3: 成本超支告警
  trigger: daily_cost > threshold (默认 10 USD)
  action: alert_manager.add_alert("daily_budget_exceeded", {cost, threshold})

通知渠道:
  - Webhook: POST JSON 到配置的 URL
  - 日志: Logger.warning("alert_triggered", alert_data)
```

### 8.3 审计报告格式

```
sccsos audit report 输出示例:

┌──────────────┬───────────┬──────────┬──────────┬──────────┐
│ Agent         │ 调用次数   │ 总Token   │ 总成本$    │ 失败率    │
├──────────────┼───────────┼──────────┼──────────┼──────────┤
│ architect     │ 12        │ 45,892    │ 0.365     │ 0.0%     │
│ code-reviewer │ 8         │ 28,134    │ 0.218     │ 12.5%    │
│ doc-writer    │ 5         │ 18,456    │ 0.142     │ 0.0%     │
├──────────────┼───────────┼──────────┼──────────┼──────────┤
│ 总计          │ 25        │ 92,482    │ 0.725     │ 4.0%     │
└──────────────┴───────────┴──────────┴──────────┴──────────┘
```

---

## 9. 部署架构

### 9.1 部署模型

```
开发部署 (本地):
  ┌──────────────┐
  │ sccsos CLI   │━━━→ Hermes Agent (同进程)
  │              │━━━→ SQLite (data/sccsos.db)
  │              │━━━→ DeepSeek API (外部)
  └──────────────┘

API 服务器部署:
  ┌──────────────┐   ┌──────────────┐   ┌──────────────┐
  │ HTTP Client   │──→│ sccsos API   │──→│ Hermes Agent  │
  │ (curl/axios)  │   │ Server       │   │ (子进程)      │
  └──────────────┘   │ port 8765    │   └──────────────┘
                     │              │   ┌──────────────┐
                     │              │──→│ SQLite DB     │
                     └──────────────┘   └──────────────┘

Docker 部署:
  ┌──────────────────────┐
  │  sccsos:0.6.4         │
  │  ┌────────────────┐  │  ┌──────────────┐
  │  │ sccsos API      │──┤→│ Hermes (内置) │
  │  │ Gunicorn/uvicorn│  │  └──────────────┘
  │  └────────────────┘  │  ┌──────────────┐
  │  ┌────────────────┐  │──┤→ SQLite       │
  │  │ 健康检查 /health│  │  │ (持久卷)      │
  │  └────────────────┘  │  └──────────────┘
  └──────────────────────┘
```

### 9.2 Docker 配置

```
Dockerfile 多阶段构建:
  阶段 1 (builder):
    - 安装系统依赖 (Python 3.14, git)
    - 创建虚拟环境 + pip install sccsos
    - Wheel 打包

  阶段 2 (runtime):
    - Python 3.14-slim (最小镜像)
    - 复制虚拟环境 + 应用代码
    - HEALTHCHECK --interval=30s --timeout=3s
    - CMD: python -m sccsos.api.server

docker-compose.yaml:
  services:
    sccsos:
      build: .
      ports: ["8765:8765"]
      volumes:
        - ./data:/app/data
        - ./logs:/app/logs
        - ./traces:/app/traces
      environment:
        - DEEPSEEK_API_KEY=${DEEPSEEK_API_KEY}
      healthcheck:
        test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8765/health')"]
```

### 9.3 配置管理

```
配置文件层级:
  1. sccsos.yaml          ─── 项目配置（版本、数据库、日志、策略）
  2. config/agents.yaml   ─── 默认 Agent 定义
  3. config/pricing.json  ─── LLM 定价表
  4. agents/*.yaml        ─── 用户自定义 Agent
  5. workflows/*.yaml     ─── 用户自定义 Workflow
  6. .env                 ─── 环境变量（API Key 等敏感信息）
  7. 环境变量覆盖          ─── export SCCSOS_DB_PATH=/custom/path

配置加载顺序: 7 > 6 > 1 > 2 (后加载覆盖先加载)
```

---

## 10. 演进路线

### 10.1 已实施版本

| 版本 | 日期 | 核心交付 | 架构成熟度 |
|------|------|---------|-----------|
| v0.1.0 | — | 项目骨架 + CLI 框架 | 概念验证 |
| v0.2.0 | — | Agent Registry + Lifecycle | 核心框架 |
| v0.3.0 | — | Workflow 初版（顺序链） | 基本编排 |
| v0.4.0 | — | DAG 引擎 + 并行 + HermesAdapter | 生产可用 |
| v0.5.0 | — | 安全策略 + 可观测性 + 测试 | 架构完善 |
| v0.6.0 | — | 多租户 + Memory Store + Personality + Docker | 企业特性 |
| v0.6.4 | 2026-07-19 | P0+P1+P2 演进完成, 157 测试, 8.8/10 健康分 | ✅ 当前基线 |

### 10.2 下一阶段规划

```
v0.7.0 — 性能优化与运维增强
  ├── 性能基准测试（对比基线）
  ├── 缓存层（Workflow 步骤结果缓存）
  ├── 审计可视化报告（HTML 输出）
  ├── 配置热加载（不重启更新策略）
  └── Cron 定时 Workflow 触发

v0.8.0 — 扩展生态
  ├── External Vector DB 桥接 (Milvus/Pinecone)
  ├── MCP Tool 注册热加载
  ├── Agent SDK (Python Client Library)
  └── OpenTelemetry 导出集成

v0.9.0 — 企业级特性
  ├── 审计日志导出 (JSON/CSV/SQL)
  ├── 角色基础访问控制 (RBAC)
  ├── 使用量配额管理 (per-tenant per-agent)
  └── 可配置告警通道 (Slack/Teams/钉钉)

v1.0.0 — 稳定版
  ├── API 稳定性承诺 (Semver)
  ├── 迁移指南（从 v0.x 升级）
  ├── 性能 SLA 文档
  └── 安全审计报告
```

### 10.3 架构演进原则

| 原则 | 说明 |
|------|------|
| **向后兼容** | 不破坏现有 YAML 格式 / CLI 接口 |
| **零外部依赖** | 核心路径保持 SQLite + 标准库 |
| **每次变更有测试** | 测试覆盖 ≥ 80% |
| **ADR 记录** | 每个关键决策记录上下文 + 方案 + 权衡 |
| **渐进式增强** | 先监控、后优化、再重构 |

---

## 参考

- [[需求分析-SCCS-OS-需求规格说明书]] — 需求规格说明书
- [[sccsos-architecture-framework]] — 7 大关注域架构框架
- [[ADR-002-sccsos-feasibility-plan]] — 技术可行性分析
- [[ADR-001-multi-agent-architecture]] — 多智能体架构 ADR
- [[hermes-agent-guide]] — Hermes Agent 白皮书
- 代码: sccsos/core/ — AgentRuntime, WorkflowEngine, LifecycleManager, HermesAdapter
- 测试: /Users/smart/dev/hermesws/sccsos/tests/ — 157 用例
