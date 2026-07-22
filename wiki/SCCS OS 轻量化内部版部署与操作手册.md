<div class="cover-page">

# SCCS OS 轻量化内部版部署与操作手册

**创新研究院 李锋**

v0.11.4 | 2026 年 7 月

企业内部小团队部署 | 单服务器 | 零外部依赖

</div>

\newpage

# 第一章 产品概述

## 1.1 SCCS OS 是什么

SCCS OS（Smart Agent Operating System）是一个基于 Hermes Agent 运行时的智能体操作系统平台。它在 Hermes 的单 Agent 推理能力之上，提供多 Agent 编排、安全治理、可观测性、技能管理等操作系统级能力。

## 1.2 SCCS OS 与 Hermes Agent 的分工

| 层 | 职责 | 归属 |
|----|------|------|
| **编排层** | 多 Agent DAG 编排、条件分支、并行执行、重试 | SCCS OS 自研 |
| **安全层** | 命令白名单、工具 ACL、Prompt 注入防护、速率限制 | SCCS OS 自研 |
| **可观测层** | 全链路审计、Token 计费、链路追踪、告警、Webhook | SCCS OS 自研 |
| **技能层** | 技能市场发布/审批/安装/版本管理 | SCCS OS 自研 |
| **运行时层** | ReAct 推理循环、记忆管理、技能沙箱执行 | **Hermes Agent v0.18+** |
| **API 层** | 27 个 RESTful 端点 + WebSocket + 管理控制台 | SCCS OS 自研 |

## 1.3 系统架构

![SCCS OS 轻量化架构流程](images/sccsos-system-architecture-light.png)

*图 1-1: SCCS OS 轻量化架构流程 — CLI → FastAPI → Hermes Adapter → Hermes Agent Runtime*

## 1.4 版本演变

| 版本 | 日期 | 关键变化 |
|------|------|----------|
| v0.7.1 | 2026-07-20 | 初始发布 |
| v0.8.0 | 2026-07-22 | EventBus、Supervisor、配置热重载 |
| v0.9.0 | 2026-07-22 | FastAPI、OTEL、会话持久化、ModelRouter |
| v0.10.0 | 2026-07-22 | 三运行时架构、Prompt 防护、速率限制 |
| v0.11.0 | 2026-07-22 | 数据访问层统一、StepExecutor 拆分、多租户工厂 |
| v0.11.1 | 2026-07-22 | CLI config/webhook/init --samples、技能市场 |
| v0.11.2 | 2026-07-22 | Kafka EventBus、Helm chart、CI/CD、计费大盘 |
| v0.11.3 | 2026-07-22 | 审批工作流、CSV 导出、admin 增强 |
| v0.11.4 | 2026-07-22 | admin.html 打包修复、sccsos doctor |

# 第二章 快速开始

## 2.1 环境要求

| 组件 | 版本 | 验证命令 |
|------|------|----------|
| Python | ≥ 3.11 | `python3 --version` |
| Hermes Agent | ≥ v0.18.0 | `hermes --version` |
| pip | ≥ 21.0 | `pip3 --version` |

## 2.2 安装 SCCS OS

**pip 在线安装：**

```bash
# 基础安装（核心功能）
pip install sccsos

# 含 API 服务（推荐）
pip install "sccsos[api]"

# 全部可选组件
pip install "sccsos[all]"
```

**WHL 文件安装：** 适用于离线环境、内网部署或需要固定版本精确管控的场景。

```bash
# WHL 文件安装
pip install dist/sccsos-0.16.5-py3-none-any.whl

# WHL 安装后，补装扩展组件
pip install "sccsos[all]"
```

**验证安装：**

```bash
sccsos version          # → sccsos v0.16.5
sccsos doctor           # → 检查全部依赖状态
```

## 2.3 安装与管理 Hermes Agent

Hermes Agent 是 SCCS OS 的底层运行时底座。SCCS OS 提供 `sccsos hermes` 命令组，覆盖安装、配置、诊断等全生命周期管理。

**安装 Hermes Agent：**

```bash
# 一键脚本安装（默认，推荐）
sccsos hermes install

# 国内镜像加速（适合大陆网络环境）
sccsos hermes install --china-mirror

# 源码编译安装（开发者）
sccsos hermes install --method git
sccsos hermes install --method git -v v0.18.0   # 指定版本

# Docker 容器部署（生产环境）
sccsos hermes install --method docker
sccsos hermes install --method docker -v 0.18.0

# 仅检测安装状态
sccsos hermes install --check

# 验证安装
hermes --version        # → Hermes Agent v0.18.0
```

**配置 Hermes Agent：**

```bash
# 一键交互式配置（设置 LLM Provider / API Key / Profile）
sccsos hermes setup

# 切换 Profile
sccsos hermes use <profile>

# 查看当前配置
sccsos hermes show
```

**安装系统依赖：**

```bash
# 安装 Browser 引擎等系统依赖（Web 浏览能力所需）
sccsos hermes postinstall

# 仅检测依赖状态
sccsos hermes postinstall --check

# 跳过 Browser 引擎（仅需命令行能力时）
sccsos hermes postinstall --no-browser
```

**诊断与修复：**

```bash
# 全面诊断 Hermes 安装和配置
sccsos hermes doctor

# 诊断并自动修复
sccsos hermes doctor --fix
```

> **提示**：以上命令替代了手动 `git clone` 安装方式。如需手动源码安装，仍可参考官方文档：`git clone https://github.com/NousResearch/hermes-agent.git && cd hermes-agent && pip install -e .`

## 2.4 初始化项目

```bash
# 创建项目
mkdir my-project && cd my-project

# 最小初始化
sccsos init

# 完整示例（含 3 个 Agent、5 个工作流、3 个 Personality）
sccsos init --samples

# 查看生成的文件
ls -la
# sccsos.yaml    项目配置
# agents/        Agent 定义
# personalities/ 角色定义
# workflows/     工作流定义
# data/          SQLite 数据库
# logs/          日志
# config/        定价配置
```

`--samples` 会生成开箱即用的示例文件：

| 目录 | 生成内容 |
|------|----------|
| `agents/` | 3 个示例 Agent（architect / code-reviewer / doc-writer） |
| `workflows/` | 5 个工作流 YAML（含冒烟测试、架构评审等） |
| `personalities/` | 3 种角色设定 |

> **提示**：编辑 `sccsos.yaml` 中的 `hermes` 章节配置后，可通过 `sccsos hermes install` 安装 Hermes Agent，并用 `sccsos hermes doctor` 验证安装结果。

## 2.5 快速体验

```bash
# 1. 注册并启动 Agent
sccsos agent create architect
sccsos agent start architect

# 2. 对话
sccsos agent ask architect "用一句话介绍你自己"

# 3. 运行工作流
sccsos workflow run workflows/冒烟测试.yaml

# 4. 查看审计
sccsos audit report

# 5. 启动 API 服务 + 管理控制台
sccsos serve --port 8765
# 访问 http://localhost:8765   管理控制台
# 访问 http://localhost:8765/docs  OpenAPI 文档
```

# 第三章 配置参考

## 3.1 sccsos.yaml 完整规范

```yaml
# ============================================================
# SCCS OS v0.11.4 项目配置
# ============================================================

project:                          # 项目信息
  name: sccsos
  version: 0.11.4

database:                         # 数据库配置
  path: ./data/sccsos.db          # SQLite 路径（driver: sqlite 时生效）
  driver: sqlite                  # sqlite | postgres
  dsn: ""                         # PostgreSQL DSN（driver: postgres 时必填）
  schema: public                  # PostgreSQL schema

defaults:                         # 默认参数
  hermes_profile: sccsos          # Hermes Agent 配置文件
  max_turns: 90                   # Agent 最大对话轮次
  timeout: 1800                   # 超时秒数

logging:                          # 日志配置
  level: INFO                     # DEBUG | INFO | WARNING | ERROR
  format: json                    # json | text
  directory: ./logs
  retention_days: 30

tracing:                          # 链路追踪
  enabled: true
  export_path: ./traces/

pricing:                          # LLM 定价表
  path: ./config/pricing.json     # 定价 JSON 文件路径

agents:                           # Agent 配置
  path: ./agents                  # Agent YAML 定义目录
  wiki_path: ./wiki               # 知识库目录
  personalities_path: ./personalities  # Personality 定义目录

model_pool:                       # 多模型路由池
  enabled: false
  models:
    - name: reasoning
      provider: deepseek
      model: deepseek-v4-flash
      capabilities: [reasoning, code]
    - name: fast
      provider: deepseek
      model: deepseek-v4-flash
      capabilities: [chat, quick]

policies:                         # 安全策略
  default:
    max_tokens_per_session: 100000
    max_cost_usd: 5.0
    allowed_tools:
      - read_file
      - search_files
      - web_search
      - web_extract
      - terminal
      - delegate_task
    blocked_tools: []
    allowed_commands:
      - hermes
      - git
      - ls
      - cat
      - python3
      - pip3
    dangerous_patterns:
      - sudo
      - rm -rf
      - docker
      - eval
  named:                          # 命名策略（被 Agent YAML 引用）
    restricted:
      max_cost_usd: 1.0
      blocked_tools: [web_search]

webhooks:                         # Webhook 通知
  enabled: false
  endpoints:
    - url: https://hooks.example.com/wf
      events: [completed, failed, started]
      secret: whsec_xxx
```

## 3.2 Agent YAML 定义规范

```yaml
# agents/architect.yaml
name: architect                     # Agent 名称（唯一标识）
version: 1.0                        # 版本号
description: 创新研究院 李锋         # 描述
personality: agent-architect        # 关联 Personality 文件（personalities/ 目录下）
profile: sccsos                     # Hermes Agent 配置文件名
policy: standard                    # 引用 sccsos.yaml 中的 named 策略（可选）
model: deepseek-v4-flash            # 固定模型（可选，默认由 ModelRouter 分配）
toolsets:                           # 允许的工具集
  - llm-wiki
  - filesystem
  - web-search
tags:                               # 标签
  - core
  - architecture
lifecycle:                          # 生命周期参数
  max_turns: 90
  timeout: 1800
  auto_recover: true                # 故障自动恢复
tenant_id: default                  # 租户 ID（可选，默认 default）
```

## 3.3 Personality YAML 定义规范

```yaml
# personalities/agent-architect.yaml
name: agent-architect               # 角色名称（Agent 定义中引用）
description: 创新研究院 李锋         # 描述
system_prompt: |                    # 系统提示词（核心内容）
  你是一名资深软件架构师...
model: deepseek-v4-flash            # 默认模型
temperature: 0.5                    # 温度参数（0.0 - 1.0）
```

## 3.4 工作流 YAML 定义规范

```yaml
# workflows/架构评审.yaml
name: 架构评审                       # 工作流名称
description: 多角度架构设计方案评审    # 描述
schema_version: '1.1'               # 模式版本
parallel_groups:                    # 并行组定义
  - id: review
    max_concurrent: 3
    steps:
      - doc-review
      - code-review

steps:
  - id: analysis                    # 步骤 ID（唯一）
    name: 需求分析                   # 步骤名称
    agent: architect                # 执行 Agent
    prompt: |                       # 提示词（支持 Jinja2 模板）
      分析以下需求：{{ steps.input.context }}
    condition: |                    # 条件分支（可选）
      {{ steps.analysis.response | length > 0 }}
    input: analysis.response        # 输入依赖（可选）
    retry: 2                        # 失败重试次数（可选）
    timeout: 300                    # 超时秒数（可选）
```

## 3.5 配置热重载

```bash
sccsos config reload                # 重载 sccsos.yaml
sccsos config show                  # 查看完整配置
sccsos config show --webhooks       # 仅 Webhook
sccsos config show --policies       # 仅安全策略
```

# 第四章 命令参考

## 4.1 全部 14 个命令组

| 命令组 | 子命令数 | 功能 |
|--------|:-------:|------|
| `sccsos agent` | 10 | Agent 全生命周期管理 |
| `sccsos workflow` | 6 | 工作流编排与执行 |
| `sccsos skill` | 9 | 技能市场管理 |
| `sccsos config` | 3 | 配置查看与管理 |
| `sccsos audit` | 3 | 审计与计费 |
| `sccsos memory` | 5 | 持久记忆管理 |
| `sccsos session` | 3 | 会话管理 |
| `sccsos personality` | 6 | Personality 版本管理 |
| `sccsos trace` | 2 | 链路追踪 |
| `sccsos init` | 2 参数 | 项目初始化 |
| `sccsos serve` | 3 参数 | API 服务启动 |
| `sccsos health` | 0 | 系统健康检查 |
| `sccsos doctor` | 0 | 依赖检查 |
| `sccsos version` | 0 | 版本信息 |

## 4.2 agent 命令详解

```bash
# 创建 Agent
sccsos agent create architect               # 从默认模板
sccsos agent create my-agent --file my.yaml  # 从自定义文件

# 列出 Agent
sccsos agent list                           # 全部
sccsos agent list --tenant project-a        # 按租户

# 启动/停止/暂停/恢复/重启
sccsos agent start architect                # CREATED/RUNNING
sccsos agent stop architect                 # RUNNING/TERMINATED
sccsos agent pause architect                # RUNNING/PAUSED
sccsos agent resume architect               # PAUSED/RUNNING
sccsos agent restart architect              # FAILED/RUNNING

# 对话与状态
sccsos agent ask architect "设计认证模块"    # 发送提示词
sccsos agent status architect               # 查看状态
sccsos agent logs architect                 # 查看日志
```

## 4.3 workflow 命令详解

```bash
sccsos workflow run workflows/架构评审.yaml          # 运行工作流
sccsos workflow run workflows/每日巡检.yaml --async  # 异步运行
sccsos workflow list                                 # 列出运行
sccsos workflow status wf_abc123                     # 运行状态
sccsos workflow cancel wf_abc123                     # 取消运行
sccsos workflow validate workflows/架构评审.yaml      # 验证定义
sccsos workflow visualize workflows/架构评审.yaml     # 可视化 DAG
```

## 4.4 skill 命令详解

```bash
sccsos skill publish personalities/my.yaml --author "Alice"  # 发布
sccsos skill submit my-agent                                  # 提交审批
sccsos skill approve my-agent                                 # 审批通过
sccsos skill reject my-agent --reason "缺测试用例"             # 驳回
sccsos skill list                                             # 列表
sccsos skill list --status published                          # 按状态
sccsos skill show my-agent --version 1.0                      # 查看
sccsos skill install my-agent                                 # 安装
sccsos skill archive my-agent                                 # 归档
sccsos skill remove my-agent                                  # 移除
```

## 4.5 config 命令详解

```bash
sccsos config show                   # 全量配置
sccsos config show --webhooks        # 仅 Webhook
sccsos config show --policies        # 仅安全策略
sccsos config reload                 # 热重载

# Webhook 管理
sccsos config webhook list           # 列出 Webhook
sccsos config webhook add https://hook.example.com/wf \  # 添加
  --events completed,failed \
  --secret whsec_xxx \
  --enable
sccsos config webhook remove 0       # 按索引删除
sccsos config webhook test 0         # 测试发送
```

## 4.6 audit 命令详解

```bash
sccsos audit report                          # 审计汇总
sccsos audit report --since 2026-07-01       # 按日期
sccsos audit report --agent architect        # 按 Agent
sccsos audit log                             # 审计日志
sccsos audit log --limit 50                  # 指定条数
sccsos audit log --agent architect           # 按 Agent 过滤
sccsos audit billing                         # 计费报表
sccsos audit billing --csv                   # 导出 CSV
sccsos audit billing --csv > billing.csv     # 保存到文件
```

## 4.7 其他命令

```bash
# 记忆管理
sccsos memory save architect language "Python"     # 保存
sccsos memory save architect key value --ttl 3600  # 带过期
sccsos memory get architect language               # 读取
sccsos memory list architect                       # 列表
sccsos memory delete architect temp_key            # 删除
sccsos memory clear architect                      # 清空

# 会话管理
sccsos session list                                # 会话列表
sccsos session show ses_abc123                     # 会话详情
sccsos session close ses_abc123                    # 关闭会话

# Personality 版本
sccsos personality list                            # 版本列表
sccsos personality save architect "更新提示词"      # 保存快照
sccsos personality show architect --version 1.0    # 查看
sccsos personality rollback architect 1.0          # 回滚
sccsos personality validate                        # 校验全部
sccsos personality clean --keep 3                  # 清理旧版

# 追踪
sccsos trace list                                  # 追踪列表
sccsos trace show trace_abc123                     # 追踪详情

# 系统
sccsos version                                     # 版本
sccsos health                                      # 健康检查
sccsos doctor                                      # 依赖检查
sccsos init --samples                              # 初始化示例
sccsos serve --port 8765                           # 启动 API
```

# 第五章 API 参考

## 5.1 全部 27 个端点

| 方法 | 路径 | 说明 | CLI 等价 |
|------|------|------|----------|
| GET | `/api/v1/health` | 系统健康检查 | `sccsos health` |
| GET | `/api/v1/agents` | 列出 Agent | `sccsos agent list` |
| POST | `/api/v1/agents/register` | 注册 Agent | `sccsos agent create` |
| GET | `/api/v1/agents/{name}` | Agent 状态 | `sccsos agent status` |
| POST | `/api/v1/agents/{name}/start` | 启动 Agent | `sccsos agent start` |
| POST | `/api/v1/agents/{name}/stop` | 停止 Agent | `sccsos agent stop` |
| POST | `/api/v1/agents/{name}/pause` | 暂停 Agent | `sccsos agent pause` |
| POST | `/api/v1/agents/{name}/resume` | 恢复 Agent | `sccsos agent resume` |
| POST | `/api/v1/agents/{name}/restart` | 重启 Agent | `sccsos agent restart` |
| POST | `/api/v1/agents/{name}/ask` | 对话 Agent | `sccsos agent ask` |
| GET | `/api/v1/workflows` | 工作流列表 | `sccsos workflow list` |
| POST | `/api/v1/workflows/run` | 运行工作流 | `sccsos workflow run` |
| POST | `/api/v1/workflows/validate` | 验证工作流 | `sccsos workflow validate` |
| GET | `/api/v1/workflows/visualize` | 可视化 DAG | `sccsos workflow visualize` |
| GET | `/api/v1/workflows/{run_id}` | 运行状态 | `sccsos workflow status` |
| POST | `/api/v1/workflows/{run_id}/cancel` | 取消运行 | `sccsos workflow cancel` |
| GET | `/api/v1/sessions` | 会话列表 | `sccsos session list` |
| GET | `/api/v1/sessions/{id}` | 会话详情 | `sccsos session show` |
| GET | `/api/v1/sessions/{id}/messages` | 会话消息 | — |
| POST | `/api/v1/sessions/{id}/close` | 关闭会话 | `sccsos session close` |
| GET | `/api/v1/traces` | 追踪列表 | `sccsos trace list` |
| GET | `/api/v1/traces/{id}` | 追踪详情 | `sccsos trace show` |
| GET | `/api/v1/audit/report` | 审计报告 | `sccsos audit report` |
| GET | `/api/v1/audit/log` | 审计日志 | `sccsos audit log` |
| GET | `/api/v1/skills` | 技能市场 | `sccsos skill list` |
| GET | `/` | 管理控制台 | — |
| GET | `/admin` | 管理控制台 | — |
| WS | `/api/v1/ws` | 实时事件流 | — |
| GET | `/docs` | OpenAPI 文档 | — |

# 第六章 管理控制台

## 6.1 访问方式

```bash
sccsos serve --port 8765
# http://localhost:8765      管理控制台首页
# http://localhost:8765/docs  OpenAPI Swagger 文档
```

## 6.2 七个标签页

| 标签 | 功能 |
|------|------|
| 🤖 **Agents** | 查看 Agent 列表、状态、启动/暂停/停止/重启操作 |
| 📋 **Workflows** | 查看工作流运行记录、状态、取消运行 |
| 🧩 **Skills** | 技能市场可视化列表（名称/版本/类型/状态/作者） |
| 📊 **Audit** | 审计报告摘要（总调用/总消耗/成功率） |
| 💰 **Billing** | 计费统计（总成本/按模型分布） |
| ⚡ **Events** | WebSocket 实时事件流（工作流状态变更推送） |
| ❤️ **Health** | 系统健康状态 JSON |

# 第七章 完整功能矩阵

## 7.1 功能清单

| 功能模块 | CLI | API | Web UI | 说明 |
|----------|:---:|:---:|:------:|------|
| Agent 创建/注册 | ✅ | ✅ | — | YAML 定义 |
| Agent 启动/停止 | ✅ | ✅ | ✅ | 5 状态状态机 |
| Agent 暂停/恢复 | ✅ | ✅ | ✅ | 会话上下文保存 |
| Agent 对话 | ✅ | ✅ | — | 持久记忆注入 |
| Agent 日志查看 | ✅ | — | — | 事件列表 |
| Agent 自动恢复 | ✅ | — | — | Supervisor 心跳 |
| 工作流 DAG 编排 | ✅ | ✅ | — | 拓扑排序 |
| 条件分支 | ✅ | — | — | Jinja2 条件 |
| 并行执行组 | ✅ | — | — | ThreadPool |
| 失败重试 | ✅ | — | — | 指数退避 |
| 异步运行 | ✅ | — | — | 后台执行 |
| 工作流可视化 | ✅ | ✅ | — | Mermaid 图表 |
| 技能市场发布 | ✅ | — | — | draft → in_review |
| 技能审批 | ✅ | — | — | approve/reject |
| 技能安装 | ✅ | — | — | 本地复制 |
| 技能归档 | ✅ | — | — | 保留记录 |
| 工具权限 ACL | ✅ | — | — | 白名单/黑名单 |
| 命令白名单 | ✅ | — | — | 危险模式匹配 |
| Prompt 注入防护 | ✅ | — | — | 自动检测拦截 |
| 速率限制 | ✅ | — | — | 100 req/s |
| 审计全链路 | ✅ | ✅ | ✅ | LLM/工具/工作流 |
| 计费报表 | ✅ | ✅ | ✅ | 按模型/按日 |
| CSV 导出 | ✅ | — | — | 导入 Excel |
| 链路追踪 | ✅ | ✅ | — | Span 树 |
| JSON 日志 | — | — | — | 结构化 |
| 阈值告警 | ✅ | — | — | AlertManager |
| Webhook 通知 | ✅ | ✅ | — | 工作流事件 |
| 持久记忆 | ✅ | — | — | KV + TTL |
| 会话管理 | ✅ | ✅ | — | 历史消息 |
| Personality 版本控制 | ✅ | — | — | 快照/回滚 |
| 配置热重载 | ✅ | — | — | 零停机 |
| Web 控制台 | — | ✅ | ✅ | 7 标签页 |
| 健康检查 | ✅ | ✅ | ✅ | Database/Hermes |
| 依赖检查 | ✅ | — | — | doctor 命令 |
| 示例项目生成 | ✅ | — | — | init --samples |
| Docker 部署 | — | — | — | Dockerfile 提供 |
| PostgreSQL 支持 | — | — | — | driver: postgres |
| EventBus Kafka | — | — | — | [kafka] extras |
| Helm Chart | — | — | — | deploy/helm/ |
| CI/CD | — | — | — | GitHub Actions |

# 第八章 安全体系

## 8.1 三层安全防线

```
第一层: API → X-Tenant-ID 租户隔离 + RateLimiter(100/s)
第二层: Prompt → InjectionGuard(关键词检测)
第三层: 执行 → PolicyEngine(工具ACL) + Sandbox(命令白名单)
```

## 8.2 策略配置

```yaml
policies:
  default:
    allowed_tools: [read_file, search_files, web_search, terminal]
    blocked_tools: [execute_code]
    allowed_commands: [hermes, git, ls, cat, python3, pip3]
    dangerous_patterns: [sudo, rm -rf, docker, eval]
```

## 8.3 Per-Agent 策略

```yaml
# sccsos.yaml
policies:
  named:
    read-only:
      max_cost_usd: 1.0
      allowed_tools: [read_file, search_files]

# agents/reader.yaml
name: reader
policy: read-only
```

# 第九章 可观测性

## 9.1 五大可观测系统

| 系统 | 数据源 | 查询方式 |
|------|--------|----------|
| **审计 (Auditor)** | audit_log 表 | `sccsos audit report/log` |
| **计费 (Pricing)** | audit_log + pricing.json | `sccsos audit billing` |
| **追踪 (Tracer)** | traces 表 | `sccsos trace list/show` |
| **告警 (AlertManager)** | audit_log 阈值 | Webhook 推送 |
| **日志 (Logger)** | 文件系统 | `logs/sccsos.log` |

## 9.2 审计日志字段

| 字段 | 说明 | 示例 |
|------|------|------|
| tenant_id | 租户 | `default` |
| agent_id | Agent | `architect` |
| event_type | 事件类型 | `llm_call` / `tool_call` |
| model_name | 模型 | `deepseek-v4-flash` |
| tokens_used | Token 用量 | 1234 |
| cost_usd | 费用 | 0.0012 |
| duration_ms | 耗时 | 3500 |
| success | 是否成功 | 1 |

# 第十章 故障处理

## 10.1 常见问题

```bash
# Agent 启动失败
sccsos agent logs architect            # 查看错误日志
sccsos health                          # 检查 Hermes 连接

# API 服务不可用
pip install "sccsos[api]"              # 安装 FastAPI
sccsos doctor                          # 检查依赖

# 数据库异常
ls -la data/sccsos.db                  # 检查文件权限
sccsos health                          # 检查数据库状态

# 记忆未生效
sccsos memory save architect lang py   # 确认记忆已保存
sccsos agent ask architect "你的记忆?"  # 检查注入

# Webhook 未触发
sccsos config webhook list             # 检查配置
sccsos config webhook test 0           # 发送测试
```

## 10.2 日志查看

```bash
tail -f logs/sccsos.log                # 运行日志
tail -f logs/errors.log                # 错误日志
sccsos agent logs architect            # Agent 日志
```

## 10.3 数据备份

```bash
cp data/sccsos.db data/sccsos.db.bak   # SQLite 备份
cp data/sccsos.db.bak data/sccsos.db   # 恢复
```