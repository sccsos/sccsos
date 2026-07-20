<div class="cover-page">

# SCCS OS 操作手册

**智能体架构设计师**

版本 v0.4.0 | 2026 年 7 月

</div>

\newpage

# 第一章 概述

## 1.1 文档说明

本文档是 SCCS OS 智能体操作系统的完整操作指南，涵盖 CLI 命令详解、Agent 管理、工作流编排、可观测性工具和常见问题处理。适用于使用 SCCS OS 的开发者和运维人员。

## 1.2 CLI 命令总览

![SCCS OS 核心组件关系图](images/sccsos-component-relationship-light.png))

*图 3: SCCS OS 核心组件关系图 — CLI 命令背后的核心组件交互*


SCCS OS 提供 15 条命令，分为 6 组：

| 命令组 | 命令 | 功能 |
|--------|------|------|
| 系统 | version | 显示版本信息 |
| 系统 | init | 初始化项目 |
| 系统 | health | 系统健康检查 |
| Agent 管理 | agent list | 列出所有 Agent |
| Agent 管理 | agent create | 创建 Agent 定义 |
| Agent 管理 | agent start | 启动 Agent |
| Agent 管理 | agent stop | 停止 Agent |
| Agent 管理 | agent status | 查询运行状态 |
| Agent 管理 | agent logs | 查看事件日志 |
| 工作流 | workflow validate | 验证工作流定义 |
| 工作流 | workflow run | 执行工作流 |
| 工作流 | workflow status | 查询运行状态 |
| 工作流 | workflow cancel | 取消运行中的工作流 |
| 工作流 | workflow list | 列出最近运行记录 |
| 追踪 | trace list | 列出追踪记录 |
| 追踪 | trace show | 查看追踪详情 |
| 审计 | audit report | 生成审计报告 |
| 审计 | audit log | 查看审计日志 |

\newpage

# 第二章 Agent 管理

## 2.1 查看 Agent 列表

列出所有已注册的 Agent：

```bash
sccsos agent list
```

输出示例：

```
Name                 Version    Status       Description
----------------------------------------------------------------------
architect            1.0        registered   智能体架构设计师
test-coder           1.0        registered
```

各列说明：

| 列 | 说明 |
|----|------|
| Name | Agent 名称，定义在 YAML 的 name 字段 |
| Version | 定义版本号 |
| Status | 当前运行状态：registered/running/paused/terminated |
| Description | 功能描述 |

## 2.2 创建 Agent

### 通过 YAML 文件创建

```bash
sccsos agent create my-agent -f path/to/my-agent.yaml
```

### 通过命令行快速创建

```bash
sccsos agent create my-agent
```

这会在 agents/ 目录下创建一个空的 YAML 模板文件，编辑后即可使用。

## 2.3 启动 Agent

启动一个已注册的 Agent：

```bash
sccsos agent start architect
```

启动过程：

1. SCCS OS 从 Registry 读取 Agent 定义
2. 创建 Agent 实例（状态：CREATED）
3. 启动 Agent，分配 Hermes 会话（状态：RUNNING）
4. 事件 recorded 到数据库

成功后输出：

```
Started: architect (agent_a1b2c3d4e5f6)
```

## 2.4 停止 Agent

停止运行中的 Agent：

```bash
sccsos agent stop architect
```

停止后状态转换为 TERMINATED，会话资源释放。

## 2.5 查询状态

查看 Agent 的详细运行状态和历史事件：

```bash
sccsos agent status architect
```

输出示例：

```
Agent: architect
  ID:     agent_a1b2c3d4e5f6
  Status: running
  Spec:   v1.0
  Profile: sccsos
  Session: ses_f6e5d4c3b2a1
  Recent events (3):
    [created] Agent 'architect' created
    [running] created → running via start
```

## 2.6 查看日志

查看 Agent 的生命周期事件记录：

```bash
sccsos agent logs architect
sccsos agent logs architect --limit 50
```

输出按时间倒序排列，每条记录包含时间戳、事件类型和详情。


![Agent 生命周期状态机](images/sccsos-lifecycle-state-machine-light.png)

*图 1: Agent 生命周期状态机 — 5 种状态与 8 种转换关系*
## 2.7 生命周期状态机

SCCS OS 定义了 5 种运行状态：

| 状态 | 说明 | 可转换到 |
|------|------|---------|
| CREATED | Agent 定义已注册，未启动 | RUNNING |
| RUNNING | Agent 正在运行 | PAUSED, FAILED, TERMINATED |
| PAUSED | Agent 已暂停 | RUNNING, TERMINATED |
| FAILED | 运行异常 | RUNNING (restart), TERMINATED |
| TERMINATED | 已终止，资源释放 | （终态） |

\newpage


![Workflow 执行时序图](images/sccsos-workflow-sequence-light.png)

*图 2: Workflow 执行时序图 — 从 DAG 构建到步骤执行、结果聚合的完整流程*

# 第三章 工作流编排

## 3.1 工作流定义

工作流使用 YAML 格式定义，支持多步骤编排、依赖管理和模板注入。

### 基本结构

```yaml
name: workflow-name
version: 1.0
description: 工作流描述

steps:
  - id: step-id
    name: 步骤名称
    agent: architect
    prompt: "执行提示词"
    depends_on:
      - other-step-id

parallel_groups:
  - id: group-id
    steps:
      - step-a
      - step-b
    max_concurrent: 2
```

### 字段说明

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| name | string | 是 | 工作流名称 |
| version | string | 否 | 版本号 |
| description | string | 否 | 描述 |
| steps[].id | string | 是 | 步骤唯一标识 |
| steps[].name | string | 否 | 步骤名称 |
| steps[].agent | string | 否 | 执行 Agent（默认 architect） |
| steps[].prompt | string | 否 | 执行提示词 |
| steps[].depends_on | list | 否 | 前置依赖步骤 ID |
| steps[].timeout | integer | 否 | 步骤超时秒数 |
| steps[].retry | integer | 否 | 失败重试次数 |

## 3.2 模板注入

工作流步骤的 prompt 支持模板语法，可引用前序步骤的输出：

| 模板语法 | 说明 |
|----------|------|
| {{ steps.step-id.response }} | 引用步骤的完整响应 |
| {{ run_id }} | 当前运行 ID |

示例：

```yaml
steps:
  - id: architecture-review
    agent: architect
    prompt: "Review requirements and produce ADR"

  - id: code-generation
    agent: architect
    prompt: |
      Implement based on the architecture:
      {{ steps.architecture-review.response }}
    depends_on:
      - architecture-review
```

## 3.3 验证工作流

执行工作流前建议先验证 YAML 定义的正确性：

```bash
sccsos workflow validate my-workflow.yaml
```

验证检查项：

1. YAML 格式合法性
2. 步骤 ID 唯一性
3. 依赖关系完整性（无缺失依赖）
4. 循环依赖检测
5. 提示词非空检查

## 3.4 执行工作流

```bash
sccsos workflow run my-workflow.yaml
```

执行过程：

1. 加载并验证工作流定义
2. 创建追踪 Span（根 Span = 工作流名称）
3. DAG 解析生成执行层级
4. 按层顺序执行步骤
5. 每个步骤通过 Hermes 适配器委派给 Agent
6. 模板按需渲染
7. 输出缓存供后续步骤引用
8. 记录审计日志

## 3.5 查询运行状态

```bash
# 按运行 ID 查询
sccsos workflow status wf_a1b2c3d4e5f6

# 列出最近运行记录
sccsos workflow list
```

## 3.6 取消工作流

```bash
sccsos workflow cancel wf_a1b2c3d4e5f6
```

取消后状态标记为 cancelled，正在执行的步骤不会强制中断。

\newpage

# 第四章 可观测性

## 4.1 链路追踪

SCCS OS 提供 Span 树结构的链路追踪，每次工作流执行自动生成追踪记录。

### 查看追踪列表

```bash
sccsos trace list
```

输出示例：

```
Trace ID                 Spans    Total (ms)   First Span
----------------------------------------------------------------------
wf_a1b2c3d4e5f6          3        16753        2026-07-14T04:20:39
```

### 查看追踪详情

```bash
sccsos trace show wf_a1b2c3d4e5f6
```

输出示例（树形结构）：

```
Trace: wf_a1b2c3d4e5f6
Spans: 3

✅ workflow:obs-test (8.4s)
  └─ ✅ step:step-one (4.3s)
  └─ ✅ step:step-two (4.1s)
```

每个 Span 包含：

| 属性 | 说明 |
|------|------|
| span_id | Span 唯一 ID |
| parent_span_id | 父 Span ID（构建树结构） |
| name | Span 名称 |
| agent_name | 执行 Agent |
| start_time | 开始时间 |
| end_time | 结束时间 |
| duration_ms | 耗时（毫秒） |
| status | 状态：ok/error |
| events | 关联事件列表 |

## 4.2 审计与成本核算

SCCS OS 自动记录所有 LLM 调用和工具调用，支持成本估算。

### 生成审计报告

```bash
sccsos audit report
```

输出示例：

```
Audit Report
  Generated: 2026-07-14T04:20:48

  Total calls:    3
  Total tokens:   40
  Total cost:     $0.0000
  Avg duration:   2791ms
  Success rate:   3/3

  By event type:
    llm_call            3 calls,     40 tokens, $0.0000

  By model:
    deepseek-v4-flash           2 calls, $0.0000

  Cost over time:
    2026-07-14: $0.0000
```

### 按时间段审计

```bash
# 指定起始日期
sccsos audit report --since 2026-07-01

# 按 Agent 筛选
sccsos audit report --agent architect
```

### 查看审计日志

```bash
# 最近 20 条
sccsos audit log

# 指定数量
sccsos audit log --limit 50

# 按 Agent 筛选
sccsos audit log --agent architect
```

定价表（用于成本估算）：

| 模型 | 输入价格（每百万 Token） | 输出价格（每百万 Token） |
|------|------------------------|-------------------------|
| deepseek-v4-flash | $0.14 | $0.28 |
| deepseek-v4-pro | $0.44 | $0.87 |
| deepseek-chat | $0.14 | $0.28 |
| deepseek-reasoner | $0.55 | $2.19 |
| claude-sonnet-4 | $3.00 | $15.00 |
| gemini-2.5-flash | $0.30 | $2.50 |

\newpage

# 第五章 系统管理

## 5.1 系统健康检查

```bash
sccsos health
```

检查项包括：

1. 配置加载状态
2. 数据库连接与 Schema
3. Hermes CLI 可达性
4. Agent 注册数量
5. 追踪数据可用性

## 5.2 数据库管理

SCCS OS 使用 SQLite 数据库，默认路径为 data/sccsos.db。

数据库包含 6 张表：

| 表名 | 用途 |
|------|------|
| agents | Agent 实例持久化 |
| agent_events | Agent 生命周期事件日志 |
| workflow_runs | 工作流运行记录 |
| workflow_steps | 工作流步骤执行记录 |
| traces | 追踪 Span 数据 |
| audit_log | 审计日志 |

```bash
# 查看数据库大小
ls -lh data/sccsos.db

# 使用 sqlite3 直接查询
sqlite3 data/sccsos.db "SELECT status, count(*) FROM agents GROUP BY status;"
```

## 5.3 日志管理

SCCS OS 日志默认输出到控制台和 logs/ 目录。

```bash
# 查看日志目录
ls -lh logs/

# 日志格式（JSON 行）
cat logs/sccsos.log | python3 -m json.tool
```

\newpage

# 第六章 常见问题

## 6.1 安装问题

| 问题 | 原因 | 解决方法 |
|------|------|---------|
| sccsos 命令找不到 | pip 安装路径不在 PATH 中 | 运行 `pip show agentos` 找到安装路径，加入 PATH |
| Hermes 不可用 | Hermes CLI 未安装或不在 PATH | 确认 `hermes --version` 可正常运行 |
| 数据库初始化失败 | data/ 目录无写入权限 | `mkdir -p data && chmod 755 data` |
| YAML 解析错误 | 配置文件格式不正确 | 使用 `sccsos workflow validate` 检测 |

## 6.2 运行时问题

| 问题 | 原因 | 解决方法 |
|------|------|---------|
| Agent 启动失败 | Agent 定义中 profile 不存在 | 检查 Hermes profile 是否存在 |
| Agent 停止失败 | 实例不在内存中 | 使用 `sccsos agent status` 确认当前状态 |
| 工作流执行超时 | 某步骤超过 300 秒限制 | 缩短提示词或增加 timeout 配置 |
| 追踪数据为空 | 数据库首次使用 | 执行一次工作流后即有数据 |
| Token 成本为 0 | Token 为估算值 | 实际成本以模型提供商账单为准 |

## 6.3 性能建议

1. 工作流步骤数建议控制在 10 步以内
2. 提示词长度建议不超过 2000 Token
3. 数据库定时备份（cp data/sccsos.db backup/）
4. 日志定期清理（默认保留 30 天）

\newpage

# 第七章 实战案例

## 7.1 案例：架构评审工作流

**目标**：对新项目的架构设计方案进行多 Agent 协同评审。

**工作流定义**（`workflows/架构评审.yaml`）：

```yaml
name: architecture-review
version: 1.0
description: 多 Agent 架构评审流水线
steps:
  - id: requirement-analysis
    name: 需求分析
    agent: architect
    prompt: |
      分析以下需求文档，提取关键架构约束：
      {{ requirements }}
      输出格式：详细的需求摘要 + 关键约束列表

  - id: design-proposal
    name: 设计方案
    agent: architect
    prompt: |
      基于需求分析结果，生成技术架构方案：
      输入：{{ steps.requirement-analysis.response }}
      输出包含：分层架构图描述、核心组件列表、技术选型建议
    depends_on:
      - requirement-analysis

  - id: code-review
    name: 代码审查
    agent: code-reviewer
    prompt: |
      审查以下代码是否符合架构设计规范：
      架构要求：{{ steps.design-proposal.response }}
      代码位置：./src/
      输出：合规项列表 + 不合规项及修改建议
    depends_on:
      - design-proposal

  - id: summary-report
    name: 汇总报告
    agent: doc-writer
    prompt: |
      汇总架构评审全过程，生成最终报告：
      - 需求分析：{{ steps.requirement-analysis.response }}
      - 设计方案：{{ steps.design-proposal.response }}
      - 代码审查：{{ steps.code-review.response }}
      输出格式：Markdown 文档，包含评审结论、建议、待办事项
    depends_on:
      - code-review
```

**执行命令**：

```bash
# 注入需求文档
export requirements=$(cat docs/项目需求.md)

# 运行评审工作流
sccsos workflow run workflows/架构评审.yaml
sccsos workflow status <run-id>
sccsos trace show <trace-id>
```

## 7.2 案例：日常巡检工作流

**目标**：每天早上自动检查系统状态，生成运维日报。

```yaml
name: daily-health-check
version: 1.0
description: 每日系统巡检
steps:
  - id: agent-status
    name: Agent 状态检查
    agent: architect
    prompt: |
      检查所有注册 Agent 的运行状态。
      输出格式：表格（Agent 名称 / 状态 / 运行时长 / 错误数）

  - id: audit-summary
    name: 审计汇总
    agent: architect
    prompt: |
      生成昨日审计摘要：
      - 总调用次数、Token 消耗、预估成本
      - 按 Agent 分类的调用量统计
      - 异常事件列表（如有）

  - id: report
    name: 生成日报
    agent: doc-writer
    prompt: |
      综合以上数据，生成运维日报：
      Agent 状态：{{ steps.agent-status.response }}
      审计数据：{{ steps.audit-summary.response }}
      输出格式：Markdown 表格 + 关键指标总结
    depends_on:
      - agent-status
      - audit-summary
```

```bash
# 执行日常巡检
sccsos workflow run workflows/每日巡检.yaml

# 查看审计报告
sccsos audit report --since $(date -d 'yesterday' +%Y-%m-%d)
```

## 7.3 案例：多 Agent 并行检索对比

**目标**：同时对同一问题使用不同模型/策略进行检索，对比结果。

```yaml
name: parallel-research
version: 1.0
description: 并行检索对比
parallel_groups:
  - id: research-group
    steps:
      - deep-research
      - web-quick
    max_concurrent: 2
steps:
  - id: deep-research
    name: 深度检索
    agent: architect
    prompt: |
      对以下问题进行深度技术研究：
      {{ research_question }}
      要求：引用可靠来源，给出技术方案对比

  - id: web-quick
    name: 快速检索
    agent: code-reviewer
    prompt: |
      快速搜索以下问题的业界实践：
      {{ research_question }}
      要求：列出 3-5 个实际案例

  - id: synthesis
    name: 综合报告
    agent: doc-writer
    prompt: |
      综合两种检索结果，生成对比报告：
      深度检索：{{ steps.deep-research.response }}
      快速检索：{{ steps.web-quick.response }}
      输出：差异点对比表 + 最终推荐方案
    depends_on:
      - deep-research
      - web-quick
```

```bash
# 设置研究问题
export research_question="微服务架构 vs 模块化单体架构的选型分析"

# 运行并行检索
sccsos workflow run workflows/并行检索.yaml
```

这些案例可直接修改参数后用于实际业务场景。
