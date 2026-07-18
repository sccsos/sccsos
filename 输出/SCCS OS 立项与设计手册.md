<div class="cover-page">

# SCCS OS 立项与设计手册

创新研究院 李锋

v1.0 | 2026 年 7 月

涵盖：SCCS-T 产品体系 · 项目概述 · 可行性方案 · 系统架构 · 技术规格

</div>

\newpage

# 目录

- **第1章 项目概述**
- **第2章 可行性方案**
- **第3章 系统架构**
- **第4章 技术规格**
- **附录**
  - 附录A：项目目录结构
  - 附录B：Agent 定义 YAML 参考
  - 附录C：技术决策清单

\newpage


# 第1章 项目概述

## 1.1 项目名称

**SCCS OS** — 自主智能体操作系统

## 1.2 一句话定义

SCCS OS 是一个构建在 Hermes Agent 之上的**智能体运行时平台**，为多 Agent 提供声明式编排、全生命周期管理和可观测性基础设施。

## 1.3 核心原则

1. **不重复造轮子** — 复用 Hermes Agent 的推理、记忆、工具、网关全部能力
2. **分层解耦** — 核心层（自研）与适配层（Hermes API）严格分离
3. **渐进式交付** — Phase 1 先可用，Phase 2 再稳定，Phase 3 后高阶
4. **默认安全** — 最小权限、最少工具、最窄上下文

## 1.4 能力边界

| SCCS OS 做 | SCCS OS 不做 |
|-----------|-------------|
| 多 Agent 编排与调度 | 单 Agent 推理循环（Hermes 做） |
| Agent 生命周期管理 | 工具系统核心（Hermes 做） |
| 权限与安全策略 | 记忆存储引擎（Hermes 做） |
| 可观测性与审计 | 消息网关/平台适配（Hermes 做） |
| 声明式 Workflow 定义 | LLM 模型调用（Hermes 做） |


\newpage


# 第2章 可行性方案

## 1. 方案概述

本文档针对以Hermes Agent为核心运行环境、搭建自研SCCS OS智能体操作系统的技术方案进行全面可行性论证、架构拆解、风险梳理与落地规划。经技术调研验证，**基于Hermes Agent建设SCCS OS技术方案完全可行**，该方案不属于从零自研内核的重开发方案，而是依托成熟开源智能体运行底座，上层封装操作系统级管控能力的二次增强方案，可极大降低SCCS OS底层核心能力的研发成本与试错成本。

其中，Hermes Agent承担单智能体底层运行内核职责，提供推理循环、记忆管理、技能执行、沙箱运行等基础能力；SCCS OS聚焦多智能体集群管控、资源调度、安全治理、运维运营等操作系统级能力，二者架构解耦、能力互补。

## 2. 核心概念定位厘清

### 2.1 Hermes Agent核心定位与能力

Hermes Agent是Nous Research开源的单机/服务端常驻智能体运行时框架，本质是**成熟的单智能体能力底座**，内置完整的智能体运行核心闭环，无需开发者从零实现智能体基础逻辑，核心能力包含：

- **标准推理架构**：原生支持ReAct推理循环，是智能体自主思考、决策、执行的核心基础；

- **分层持久记忆系统**：覆盖短期会话上下文、长期用户画像、项目级记忆等多层存储，可扩展对接向量数据库实现全局知识库能力；

- **模块化技能运行体系**：以Skill为最小可复用执行单元，支持技能注册、调用、迭代更新，匹配SCCS OS“技能即应用”的核心设计理念；

- **多场景隔离沙箱**：支持本地、Docker、SSH等多类型执行沙箱，原生具备基础安全隔离能力；

- **多渠道网关适配**：兼容飞书、微信、CLI、API等多种接入方式，可快速适配上层统一交互入口；

- **自进化闭环能力**：内置Review复盘智能体，可自动沉淀任务经验、优化技能逻辑，支撑智能体持续迭代升级；

- **模型无关适配层**：兼容通义千问、Qwen、OpenAI等主流大模型，可快速对接多模型调度池。

整体而言，Hermes Agent已具备微型SCCS OS的底层执行内核能力，仅缺失集群管控、多租户隔离、全局资源调度等操作系统级能力。

### 2.2 SCCS OS核心定义与能力边界

SCCS OS即智能体操作系统，核心定位是**面向多智能体集群的统一管控底座**，核心目标不止实现单个智能体的运行，而是完成海量智能体实例的全生命周期管理、资源统筹、安全治理与协同调度，核心能力边界包含：

- 多租户、多智能体实例的生命周期调度（创建、启停、销毁、弹性扩缩容）；

- 全局资源隔离、权限分级、执行安全沙箱统一管控；

- 跨智能体通信、全局事件总线、任务分发与多智能体协作；

- 全局统一知识库、标准化技能市场、多模型资源池调度；

- 全链路运维监控、用量统计、计费审计、故障自愈；

- 统一管控控制台、标准化插件生态与开放接口体系。

## 3. 方案可行性核心优势

### 3.1 底层能力高度匹配，规避从零自研风险

Hermes Agent原生补齐了SCCS OS所需的所有单智能体核心能力，无需自主研发推理循环、记忆管理、工具执行、沙箱运行等核心模块，所有底层能力均经过社区验证，稳定性远高于自研底层，可大幅降低底层Bug、逻辑漏洞等技术风险。

### 3..2 架构分层清晰，扩展改造成本低

整体采用上下解耦的分层架构，底层复用Hermes Agent成熟运行时，上层自研SCCS OS管控平面，模块边界清晰、互不侵入，可基于业务需求渐进式迭代，无需一次性完成全量开发。标准分层架构如下：

![](images/sccsos-feasibility-architecture.png)

*图: SCCS OS 分层集成架构 — 三层自研/复用/基础设施，上下解耦*

**上层 SCCS OS 自研管控层**：承载租户管理、集群调度、权限管控、监控审计、技能市场、模型调度、跨智能体通信等操作系统级能力，通过API/进程调用对接底层运行时；

**底层 Hermes Agent 运行底座**：承载智能体推理循环、分层记忆、技能引擎、工具沙箱、多渠道网关、定时任务、子代理委托等核心执行能力；

**基础设施层**：包含容器/K8s、向量数据库、对象存储、消息队列、统一认证服务等基础组件。

### 3.3 部署灵活，商用成本可控

Hermes Agent采用MIT开源协议，无商用授权风险，可免费用于企业内部平台及商业化SaaS产品；同时支持单机、多进程、容器化多种部署方式，可快速打包标准化镜像，用于集群批量分发部署，适配轻量化内部场景与大规模商用场景。

## 4. 核心短板与针对性改造方案

Hermes Agent的原生定位为单用户、单常驻进程的智能体框架，缺失分布式、多租户、集群化的操作系统级能力，是搭建SCCS OS的核心改造点，具体短板及落地改造方案如下：

### 4.1 缺失多租户与多实例集群调度能力

**原生问题**：Hermes默认单用户单进程运行，无租户数据隔离、实例批量管理、负载均衡、任务全局路由能力，无法支撑多用户、多团队、多智能体集群运行。

**改造方案**：将Hermes Agent容器化打包为标准化运行镜像，依托K8s实现实例的批量启停、扩缩容与资源编排；上层SCCS OS新增租户调度服务，为不同租户分配独立容器实例与存储卷，实现记忆、技能、会话数据的租户分片隔离。

### 4.2 安全管控体系粒度粗、能力薄弱

**原生问题**：原生仅支持全局沙箱开关，无细粒度权限管控；智能体自动生成的技能无审核校验机制，易出现越权执行、无效脚本运行；缺少全链路审计、敏感行为拦截、Prompt注入防护能力。

**改造方案**：在Hermes外层搭建统一安全网关，拦截所有工具调用、模型请求，实现操作级权限管控；新增技能审核服务，AI自动生成的技能需经过自动化校验或人工审核后才可入库复用；搭建全链路日志审计系统，统一记录所有执行行为、模型调用、工具操作日志，支持溯源与风险拦截。

### 4.3 无分布式跨智能体协作总线

**原生问题**：仅支持单个Agent内部子代理任务委托，无法实现多Hermes实例之间的消息互通、任务协同、事件联动，不满足SCCS OS多智能体集群协作的核心诉求。

**改造方案**：引入Kafka/RabbitMQ作为SCCS OS全局消息事件总线，开发Hermes网关适配器，打通不同智能体实例的通信链路，实现任务分发、状态同步、事件广播等跨实例协作能力。

### 4.4 运维、计量、运营能力空白

**原生问题**：无Token消耗、工具调用统计计费能力，无CPU、内存、存储等资源配额管控，缺少统一监控大盘、故障告警、自愈能力，无标准化技能分发市场。

**改造方案**：上层SCCS OS配套开发监控运维、用量计量、资源配额三大服务，对所有模型调用、工具执行、资源占用进行埋点统计；搭建可视化运维大盘与告警体系，实现故障自动感知与恢复；构建统一技能市场，支持技能上架、分发、版本管理与权限管控。

### 4.5 工程运维复杂度较高

**原生问题**：原生配置体系庞大，多实例集群部署后运维成本高；部分环境存在兼容性Bug；自动迭代的技能易出现冗余、失效问题。

**改造方案**：统一标准化容器配置模板，实现批量配置管理；针对性打磨容器环境兼容性，修复边界问题；新增技能版本管理与清理机制，自动校验技能可用性，清理冗余失效技能。

## 5. 两大落地实施路线

基于业务规模、落地周期、成本诉求，可选择轻量化落地或企业级分布式落地两种方案，适配不同场景需求。

### 5.1 轻量化私有SCCS OS方案（小团队/内部场景）

**适用场景**：企业内部数字员工平台、个人/团队智能体工作台、小规模内部赋能场景，无需分布式集群能力。

**落地方案**：以Hermes Agent为单智能体运行内核，仅极简封装上层管控能力，包含Web管理后台、多进程Agent实例管理、统一账号认证、共享知识库；不搭建分布式集群，采用单服务器多进程隔离模式，完全复用Hermes原生记忆、技能、网关核心能力。

**落地周期**：1\~2个月可完成可用版本落地。

### 5.2 企业级分布式SCCS OS方案（商用/大规模集群场景）

**适用场景**：对外SaaS智能体平台、集团化多部门智能体底座、大规模多租户商用场景。

**落地方案**：完成Hermes Agent标准化容器镜像封装；搭建完整自研控制平面，实现K8s集群编排、多租户隔离、全局消息总线、安全网关、计量审计、技能市场、多模型调度；改造底层存储架构，替换本地SQLite为分布式数据库\+向量数据库，实现数据分片隔离；搭建安全沙箱集群与模型资源池，支撑大规模智能体并发运行。

**落地周期**：3\~6个月可完成完整商业化版本落地。

## 6. 方案对比：Hermes底座 vs 从零自研内核

|对比维度|基于Hermes Agent搭建SCCS OS|从零自研Agent运行内核|
|---|---|---|
|底层开发量|极低，复用全套成熟底层能力|极高，推理、记忆、沙箱、工具全部自研|
|落地周期|短，快速落地业务能力|长，3\~6个月仅能完成基础底层能力|
|稳定性|社区验证成熟，生产环境可用|自研边界Bug多，稳定性风险高|
|定制自由度|中等，需适配框架原生接口规范|极高，内核架构完全自主可控|
|集群改造成本|中等，仅需开发上层管控平面|低，但底层全量自研，整体成本极高|

## 7. 最终结论与落地建议

### 7.1 核心结论

1\. **技术完全可行**：Hermes Agent具备完整的单智能体运行内核，可作为SCCS OS的核心执行底座，完全替代从零自研底层的方案，技术成熟、风险可控。

2\. **能力边界清晰**：Hermes Agent负责“单智能体执行”，自研上层平台负责“多智能体集群管控”，二者分工明确、架构解耦，是最高性价比的SCCS OS搭建模式。

3\. **核心工作量聚焦**：整体开发工作量集中在多租户隔离、集群调度、全局安全治理、跨智能体协作四大上层模块，无需投入底层内核研发。

### 7.2 落地建议

1\. 中小规模内部场景：优先采用轻量化方案，依托Hermes快速落地，降低研发成本与落地周期；

2\. 商用SaaS、大型集群场景：以Hermes为执行单元，配套完整自研控制平面，补齐分布式、多租户、安全运营能力，构建企业级SCCS OS；

3\. 仅在需要极致内核定制、完全脱离第三方框架的特殊场景下，考虑从零自研智能体运行内核。



\newpage


# 第3章 系统架构

## 3.1 分层架构

### 3.1.1 分层架构

![](images/sccsos-system-architecture-light.png)

*图 1: SCCS OS 系统分层架构图 — SVG/HTML 源文件见 `images/sccsos-system-architecture.svg`（可交互HTML版本见 `images/sccsos-system-architecture.html`）*

**四层职责说明**:

| 层级 | 职责 | 关键组件 |
|------|------|---------|
| **API 层** | CLI 命令入口，用户交互界面 | `agentos` 15 条命令行（click 框架） |
| **核心层** | Agent 注册、生命周期、Workflow 编排 | Registry / Lifecycle / Orchestrator / HermesAdapter |
| **安全 & 可观测层** | 横切面：权限管控、链路追踪、审计核算 | PolicyEngine / Tracer / Auditor / Logger |
| **Hermes 底座** | 单 Agent 推理循环与基础设施 | ReAct 循环 · 47+工具 · 记忆 · 网关 · 沙箱 · MCP |

### 3.1.2 核心组件关系

![](images/sccsos-component-relationship-light.png)

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


## 3.2 核心组件

### 3.2.1 Agent Registry (`core/registry.py`)

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

### 3.2.2 Lifecycle Manager (`core/lifecycle.py`)

5 状态状态机，管理 Agent 运行生命周期。

![](images/sccsos-lifecycle-state-machine-light.png)

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

### 3.2.3 Orchestrator / Workflow Engine (`core/orchestrator.py`)

声明式 Workflow 解析与执行引擎。

![](images/sccsos-workflow-sequence-light.png)

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

### 3.2.4 Hermes 适配层

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

### 3.2.5 Policy Engine (`security/policy.py`)

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

### 3.2.6 Tracer (`observability/tracer.py`)

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


\newpage


# 第4章 技术规格

## 4.1 数据模型

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


![](images/sccsos-component-relationship-light.png)

*图 1: SCCS OS 核心组件关系图 — Registry、Lifecycle、Orchestrator 三大核心通过 HermesAdapter 桥接 Hermes 底座*

## 4.2 接口定义

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


![](images/sccsos-lifecycle-state-machine-light.png)

*图 2: Agent 生命周期状态机 — 5 状态 8 种转换，所有状态转换持久化到 SQLite agent_events 表*

## 4.3 数据库 Schema

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


## 4.4 错误处理

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


## 4.5 配置规范

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



\newpage



# 附录


# 附录A：项目目录结构

```
sccsos/
├── AGENTS.md                       # 项目语境
├── sccsos/                        # 核心包
│   ├── __init__.py
│   ├── cli.py                      # CLI 入口（click 框架）
│   ├── core/
│   │   ├── registry.py             # Agent 注册表
│   │   ├── lifecycle.py            # 生命周期状态机
│   │   ├── orchestrator.py         # Workflow 引擎
│   │   ├── database.py             # SQLite 持久化
│   │   ├── hermes_adapter.py       # Hermes 桥接
│   │   └── config.py               # 配置加载器
│   ├── agents/                     # Agent 定义 YAML
│   ├── workflows/                  # Workflow 定义 YAML
│   ├── observability/
│   │   ├── tracer.py               # 链路追踪
│   │   ├── auditor.py              # Token 审计
│   │   └── logger.py               # 结构化日志
│   └── security/                   # 安全层（预留）
├── 文档/                           # 源文档（Markdown + 插图）
├── 输出/                           # 生成的 DOCX/PDF
├── 脚本/                           # 构建工具
├── 数据/                           # SQLite 数据库
├── 测试/                           # 测试用例
├── 配置/                           # 示例配置
├── 外部参考/                       # 外部参考文件
└── pyproject.toml                  # 项目配置
```


\newpage


# 附录B：Agent 定义 YAML 参考

```yaml
# agents/architect.yaml
name: architect
version: 1.0
description: 智能体架构设计师
personality: agent-architect
profile: agentos
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


\newpage


# 附录C：技术决策清单

| 决策 | 选择 | 理由 |
|------|------|------|
| Agent 定义格式 | YAML + JSON Schema | 与 Hermes config.yaml 一致 |
| 编排模式 | 声明式 DAG + 本地顺序 | 避免分布式复杂度 |
| 状态持久化 | SQLite + JSON | Hermes 已用 SQLite 复用 |
| CLI 框架 | click | 轻量、成熟、Python 原生 |
| 配置管理 | YAML + 环境变量 | 与 Hermes 惯例对齐 |
| 追踪格式 | 自定义 JSON → 可导出 OpenTelemetry | 零外部依赖起步 |
| 安全策略 | 默认拒绝（白名单模式） | 最小权限原则 |
| 适配层 | 抽象基类（ABC）模式 | 生产/测试可切换 |
| Hermes 集成 | 子进程 delegate_task | 轻量隔离 |

