---
title: SCCS OS 需求规格说明书
created: 2026-07-19
updated: 2026-07-19
type: concept
tags: [sccsos, requirements, specification]
confidence: high
---

# SCCS OS 需求规格说明书

> **版本**: v0.7.0
> **状态**: ✅ 已实施 (架构重构完成)
> **基于**: Hermes Agent Runtime + 7大关注域架构框架
> **前置**: [[sccsos-architecture-framework]], [[ADR-002-sccsos-feasibility-plan]], [[ADR-004-sccsos-v0.7.0-architecture-refactor]]

---

## 1. 目标明确性

### 1.1 业务目标

| 目标 | 度量指标 | 当前状态 |
|------|---------|---------|
| **统一 Agent 运行时平台** | 单 CLI 管理所有 Agent 生命周期 | ✅ v0.6.4 已实现 |
| **声明式多 Agent 编排** | YAML 定义 Workflow，支持顺序/并行/条件 | ✅ DAG 引擎已实现 |
| **生产级可观测性** | 链路追踪 + Token 审计 + 告警 | ✅ 已实现 |
| **可嵌入已有系统** | HTTP API + Docker 部署 | ✅ 已实现 |
| **零外部依赖安全沙箱** | 命令白名单 + 策略引擎 | ✅ 已实现 |

### 1.2 系统目标

> 构建在 Hermes Agent 之上的**自主智能体操作系统（Agent Runtime）**，为 AI Agent 提供运行环境、编排调度、生命周期管理和开发者接口。

**不是**：Linux/Windows 类操作系统
**不是**：新的 Agent 框架（复用 Hermes）
**是**：在 Hermes 之上封装的 Agent Runtime 环境
**是**：多 Agent 编排 + 生命周期管理 + 可观测性的统一平台

### 1.3 核心价值主张

| 维度 | 没有 SCCS OS | 有 SCCS OS |
|------|-------------|------------|
| Agent 创建 | 手动配置 config.yaml + SOUL.md | 一键 `sccsos agent create` |
| Agent 编排 | 手动 delegate_task | 声明式 workflow YAML |
| 生命周期 | 手动启停 | 状态机管理 + 自动恢复 |
| 可观测性 | 翻阅日志 | 结构化 Tracing + 审计报告 |
| 知识管理 | 散落 wiki/skills | 统一的 Agent 知识注册 |
| 安全控制 | 无统一策略 | 预算引擎 + 命令白名单 + 工具 ACL |

---

## 2. 范围边界

### 2.1 包含范围

**核心运行时**（`sccsos/core/`）：
- Agent Registry —— Agent 定义注册、发现、查询
- Lifecycle Manager —— 5 状态状态机（CREATED → RUNNING → PAUSED → FAILED → TERMINATED）
- Workflow Orchestrator —— DAG 拓扑排序、并行执行组、条件分支
- Step Executor —— 单步执行、模板渲染、退避重试、审计接入
- Hermes Adapter —— CLI 子进程管理、三层安全防线
- Personality System —— YAML 定义角色、system prompt 注入
- Config / Database —— YAML 配置加载、SQLite 持久层

**可观测性**（`sccsos/observability/`）：
- Tracer —— Span 链路追踪、JSON 导出
- Auditor —— Token 审计、成本核算
- Logger —— JSON 结构化日志、轮转
- Alert Manager —— 错误率/失败次数量化告警
- Webhook Notifier —— HTTP 回调通知
- Pricing Table —— 外部 LLM 定价表

**安全策略**（`sccsos/security/`）：
- Policy Engine —— 预算封顶、工具 ACL、per-agent 策略覆盖
- Sandbox —— 命令白名单守卫、危险模式检测

**记忆系统**（`sccsos/memory/`）：
- Knowledge Base —— 冷记忆桥接（wiki 文件检索）
- Memory Store —— 跨会话 KV 持久记忆
- Vector Store —— TF-IDF 零依赖语义检索

**API 与 CLI**：
- HTTP API Server（零依赖、多租户、X-Tenant-ID）
- Click CLI（agent create/list/start/stop/pause/resume/ask, workflow run/list, audit, health）

**部署**：
- Docker 多阶段构建
- docker-compose 编排
- 健康检查端点

### 2.2 排除范围

| 排除项 | 理由 | 替代方案 |
|--------|------|---------|
| LLM 模型训练/微调 | 超出 Agent Runtime 范围 | 外部工具（如 Unsloth） |
| 分布式多机编排 | Hermes `max_spawn_depth: 1` 限制 | 顺序 DAG 避免嵌套 |
| 实时语音/视频交互 | 超出当前产品范围 | 通过消息网关接入 |
| GUI 界面 | CLI + API 优先 | WebUI 由外部项目提供 |
| 向量数据库（外部） | 零依赖原则 | TF-IDF 内置检索 |
| 消息网关 | 由 Hermes 原生提供 | 复用 Hermes 网关 |
| Agent 训练/RLHF | 超出 Agent Runtime 范围 | 外部工具 |

---

## 3. 功能描述粒度

### 3.1 功能全景图

```
SCCS OS 功能地图
│
├── Agent 管理
│   ├── FA-01: Agent 注册/发现/查询
│   ├── FA-02: 生命周期管理（5 状态）
│   ├── FA-03: 后台进程运行（daemon）
│   ├── FA-04: 直接对话（ask）
│   └── FA-05: Personality 角色注入
│
├── Workflow 编排
│   ├── FW-01: 声明式 YAML 定义
│   ├── FW-02: DAG 拓扑排序执行
│   ├── FW-03: 并行执行组（ThreadPool）
│   ├── FW-04: 条件分支
│   ├── FW-05: 模板变量注入（Jinja2）
│   ├── FW-06: 退避重试策略
│   └── FW-07: 异步执行模式
│
├── 安全策略
│   ├── FS-01: 预算封顶（Token/Cost）
│   ├── FS-02: 命令白名单
│   ├── FS-03: 工具权限 ACL
│   ├── FS-04: Per-Agent 策略覆盖
│   └── FS-05: 危险模式检测
│
├── 可观测性
│   ├── FO-01: Span 链路追踪
│   ├── FO-02: Token 审计
│   ├── FO-03: JSON 结构化日志
│   ├── FO-04: 阈值告警
│   ├── FO-05: Webhook 通知
│   └── FO-06: 健康检查
│
├── 记忆系统
│   ├── FM-01: 文件知识库检索
│   ├── FM-02: 跨会话 KV 持久记忆
│   └── FM-03: TF-IDF 语义搜索
│
├── API 层
│   ├── FR-01: Agent CRUD REST API
│   ├── FR-02: Workflow 触发与控制
│   ├── FR-03: 审计报告查询
│   ├── FR-04: 多租户隔离（X-Tenant-ID）
│   └── FR-05: 健康检查端点
│
├── CLI 层
│   ├── FC-01: sccsos init
│   ├── FC-02: sccsos agent (create/list/start/stop/pause/resume/status/ask)
│   ├── FC-03: sccsos workflow (run/list)
│   ├── FC-04: sccsos audit report
│   ├── FC-05: sccsos health
│   └── FC-06: sc 简写别名
│
└── 部署
    ├── FD-01: Docker 多阶段构建
    ├── FD-02: docker-compose 编排
    └── FD-03: 健康检查
```

### 3.2 核心功能详情

#### FA-01: Agent 注册/发现/查询

```
输入:   YAML 定义文件（name, personality, toolsets, lifecycle）
处理:  AgentRegistry.load_specs() → 校验 → 注册到 SQLite
输出:  AgentSpec 对象 / 列表
约束:  名称唯一性、字段完整性校验
验收:  sccsos agent create → sccsos agent list → spec 可见
```

#### FA-02: 生命周期管理

```
输入:   Agent ID + 动作（start/pause/resume/stop）
状态机: CREATED → RUNNING → PAUSED → FAILED → TERMINATED
处理:  状态转换校验 → 数据库持久化 → 进程管理
输出:  状态变更确认 / 错误信息
约束:  非法转换拒绝（如 TERMINATED → RUNNING）
验收:  start → status RUNNING → pause → status PAUSED → resume → status RUNNING → stop → status TERMINATED
```

#### FW-02/03: DAG 编排 + 并行执行

```
输入:   Workflow YAML（steps, parallel_groups, depends_on）
处理:  拓扑排序 → ThreadPoolExecutor 并发 → 条件求值 → 模板注入
输出:  WorkflowResult（steps 结果 + trace + audit）
约束:  循环依赖检测、无环保证
验收:  架构评审.yaml 全流程执行（4步顺序 + 2步并行）
```

#### FS-01/03: 预算引擎 + 工具 ACL

```
输入:   AgentPolicy（max_cost_usd, allowed_tools, blocked_tools）
处理:  PolicyEngine.pre_check() → 审计日志累计值 → 阈值比较
输出:  PolicyViolation / 通过
约束:  每次 delegate_task 前执行
验收:  超预算拒绝 + 工具白名单过滤
```

#### FO-01: Span 链路追踪

```
输入:   Workflow 执行事件
处理:  Tracer.start_span() → 记录耗时/状态/事件 → 递归完成 → JSON 导出
输出:  traces/{trace_id}.json
约束:  线程安全、导出路径可配置
验收:  workflow run → traces/ 下生成 JSON 文件
```

---

## 4. 非功能需求

### 4.1 性能

| 指标 | 目标 | 当前基线 | 测量方法 |
|------|------|---------|---------|
| Workflow 编排延迟 | < 100ms（不含 LLM 调用） | — | `sccsos workflow run` 计时 |
| 并发 Agent 数 | ≥ 3（Hermes 限制） | 3 | `max_concurrent_children: 3` |
| CLI 响应时间 | < 500ms | — | 交互计时 |
| API 吞吐量 | ≥ 100 req/s | — | wrk / k6 |
| 数据库查询 | < 50ms (99p) | — | SQLite WAL 模式 |

### 4.2 可用性

| 指标 | 目标 | 实现方式 |
|------|------|---------|
| 正常运行时间 | ≥ 99.9%（API Server） | Docker 健康检查 + 自动重启 |
| 崩溃恢复 | ≤ 30s | AgentRunner 后台进程管理 |
| 数据库可靠性 | WAL 模式 + 自动迁移 | Database.auto_migrate() |
| 部署回滚 | docker-compose 版本管理 | 镜像标签化 |

### 4.3 安全性

| 域 | 需求 | 实现 |
|----|------|------|
| 命令注入 | Shell 命令白名单 | Sandbox：仅允许预定义命令列表 |
| 工具权限 | 最小权限原则 | PolicyEngine：allowed_tools + blocked_tools |
| 预算控制 | 成本封顶 | Auditor 累计 + PolicyEngine 阈值校验 |
| 多租户隔离 | Tenant 粒度数据隔离 | SQLite tenant_id 字段 + API X-Tenant-ID |
| Secret 管理 | 不硬编码凭据 | 环境变量 + .env 文件 |
| 传感器绕过 | 检测危险模式 | Sandbox.dangerous_patterns 模式匹配 |

### 4.4 可维护性

| 指标 | 目标 | 当前 |
|------|------|------|
| 测试覆盖率 | ≥ 80% | 157 用例覆盖核心路径 |
| 代码行数 | < 10K 可维护 | ~6,708 行 |
| 文档覆盖率 | 所有模块必须有 docstring | Google 风格 docstrings |
| ADR 覆盖率 | 每个关键决策有记录 | 3 个 ADR |
| 类型注解 | 全量 Python type hints | 已实施 |

### 4.5 兼容性

| 维度 | 要求 |
|------|------|
| Python | ≥ 3.11 |
| Hermes Agent | 当前最新版本 |
| SQLite | ≥ 3.38（FTS5 支持） |
| 操作系统 | Linux / macOS |
| 容器 | Docker 24+ / docker-compose 2+ |
| LLM Provider | DeepSeek / OpenRouter / OpenAI-compatible |

---

## 5. 成功标准

### 5.1 架构合规性

| 验收条件 | 验证方式 | 状态 |
|---------|---------|------|
| 7 大关注域全覆盖 | 架构审计 | ✅ 已覆盖 |
| 5 原则可追溯 | ADR 记录 | ✅ 3 个 ADR |
| 零外部依赖（核心路径） | pip install --no-deps | ✅ TF-IDF + SQLite 内置 |
| 可观测性即功能 | 每个流程产生 trace + audit | ✅ 已验证 |

### 5.2 功能验收

| 场景 | 操作 | 预期结果 | 状态 |
|------|------|---------|------|
| Agent 全生命周期 | create → start → pause → resume → stop | 5 状态正常流转 | ✅ |
| DAG Workflow | 运行 架构评审.yaml | 4 步顺序执行 | ✅ |
| 并行 Workflow | 运行 并行检索.yaml | 2 步并行 + 1 步聚合 | ✅ |
| 条件分支 | 运行 条件分支示例.yaml | CLEAR/VAGUE 分支 | ✅ |
| 异步 Workflow | --async 参数 | 后台执行 | ✅ |
| 预算限制 | 设 max_cost_usd=0 | 拒绝执行 | ✅ |
| 多租户 | 不同 X-Tenant-ID | 数据隔离 | ✅ |
| API 服务器 | GET /agents | Agent 列表 | ✅ |

### 5.3 非功能验收

| 条件 | 验收标准 | 状态 |
|------|---------|------|
| 全部测试通过 | `pytest -v` 157/157 绿色 | ✅ |
| Docker 构建 | `docker build` 无错误 | ✅ |
| Trace 导出 | workflow 执行后 traces/ 有 JSON | ✅ |
| 日志 JSON 格式 | logs/ 下 JSON 可解析 | ✅ |
| 健康检查 | `sccsos health` 返回组件状态 | ✅ |
| 审计报告 | `sccsos audit report` 输出表格 | ✅ |

### 5.4 演进就绪度

| 维度 | 就绪状态 | 下一阶段 |
|------|---------|---------|
| 核心框架 | ✅ 完成 (Phase 1) | 性能优化 |
| 编排引擎 | ✅ 完成 (Phase 2) | 分布式扩展 |
| 可观测性 | ✅ 完成 (Phase 3) | 可视化面板 |
| 安全策略 | ✅ 完成 | 审计告警升级 |
| 记忆系统 | ✅ 完成 | 外部向量 DB 桥接 |
| API 层 | ✅ 完成 | 客户端 SDK |
| 容器化 | ✅ 完成 | K8s Operator |

---

## 6. 领域模型

### 6.1 核心实体

```
AgentSpec        — Agent 定义（名称、Personality、Toolset、Lifecycle 策略）
AgentInstance    — Agent 运行时实例（状态、进程 ID、会话 ID）
WorkflowDef     — Workflow 定义（步骤、依赖、并行组）
WorkflowResult  — Workflow 执行结果（各步骤响应、Trace、审计）
Span            — 追踪跨度（ID、父 Span、耗时、事件列表）
AuditRecord     — 审计记录（时间、Agent、Token、成本、操作）
Policy          — 策略配置（预算、工具白名单、命令白名单）
MemoryEntry     — 记忆条目（Key-Value、Tenant、TTL）
```

### 6.2 实体关系

```
AgentSpec 1──N AgentInstance
WorkflowDef 1──N WorkflowResult
WorkflowResult 1──N StepResult
AgentInstance 1──N AuditRecord
AgentInstance 1──N Span
AgentSpec 1──1 Policy
AgentInstance N──N MemoryEntry
```

---

## 7. 依赖关系

| 依赖 | 用途 | 版本要求 | 类型 |
|------|------|---------|------|
| Hermes Agent | Agent 运行时核心 | ≥ 当前 | 核心依赖 |
| Python 3.11+ | 运行时 | ≥ 3.11 | 运行时 |
| SQLite 3.38+ | 持久化 | FTS5 支持 | 内置 |
| Click 8+ | CLI 框架 | ≥ 8.0 | 可选依赖 |
| Jinja2 3+ | 模板引擎 | ≥ 3.0 | 可选依赖 |
| PyYAML 6+ | YAML 解析 | ≥ 6.0 | 可选依赖 |
| DeepSeek API | LLM 服务 | 无 | 外部服务 |
| Docker 24+ | 容器化 | ≥ 24 | 部署可选 |

---

## 参考

- [[sccsos-architecture-framework]] — 7 大关注域架构框架
- [[ADR-002-sccsos-feasibility-plan]] — 技术可行性分析
- [[ADR-001-multi-agent-architecture]] — 多智能体架构 ADR
- [[hermes-agent-guide]] — Hermes Agent 白皮书
