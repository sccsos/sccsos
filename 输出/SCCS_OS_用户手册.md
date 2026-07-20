# SCCS OS 用户手册

> **版本**: v0.14.2 | **更新日期**: 2026-07-26  
> **适用**: 企业内部智能体平台 / SaaS 多租户集群

---

## 目录

1. [概述](#1-概述)
2. [安装与初始化](#2-安装与初始化)
3. [快速上手](#3-快速上手)
4. [Agent 管理](#4-agent-管理)
5. [工作流引擎](#5-工作流引擎)
6. [技能市场](#6-技能市场)
7. [安全体系](#7-安全体系)
8. [可观测性](#8-可观测性)
9. [API 参考](#9-api-参考)
10. [部署指南](#10-部署指南)
11. [运维与故障排查](#11-运维与故障排查)
12. [插件开发](#12-插件开发)

---

## 1. 概述

### 1.1 什么是 SCCS OS

SCCS OS 是面向多智能体集群的统一管控平台，底层复用 Hermes Agent 运行时内核，上层自研操作系统级能力。

**核心能力矩阵：**

| 维度 | 能力 |
|------|------|
| **编排引擎** | DAG 拓扑排序 + 条件分支 + 并行 ThreadPool + 退避重试 + Jinja2 模板 |
| **生命周期** | 5 状态状态机 + pause/resume/restart CLI |
| **可观测性** | OTEL Span 链路追踪 + JSON 结构化日志 + Token 审计 + Webhook 通知 + 阈值告警 |
| **安全策略** | 预算引擎 + 命令白名单 + 工具权限 ACL + per-agent 策略覆盖 + Prompt 注入防护 + 速率限制 + RBAC |
| **事件总线** | LocalEventBus（进程内）+ KafkaEventBus（分布式）|
| **模型路由** | 多模型动态调度池 + 指标追踪 + 自动降级 |
| **容器化** | Docker 多阶段构建 + docker-compose + K8s 部署 + HPA 弹性扩缩容 |

### 1.2 架构概览

```
┌─────────────────────────────────────────────────────┐
│                  AgentRuntime                       │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐ │
│  │ RuntimeCore  │  │Observability│  │  Workflow   │ │
│  │  (核心运行)   │  │  (可观测)    │  │  (工作流)    │ │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘ │
│         │               │               │         │
└─────────┼───────────────┼───────────────┼─────────┘
          │               │               │
     ┌────┴───────┐ ┌────┴───────┐ ┌────┴──────────┐
     │ Hermes    │ │ OTEL +    │ │ DAG 引擎     │
     │ Adapter   │ │ Auditor   │ │ + EventBus   │
     └───────────┘ └───────────┘ └───────────────┘
```

---

## 2. 安装与初始化

### 2.1 系统要求

- **Python**: 3.10+
- **磁盘**: 最小 500MB（含依赖）
- **内存**: 最小 512MB（推荐 2GB+）
- **可选**: Docker, K8s, PostgreSQL, Kafka

### 2.2 pip 安装

```bash
# 最小安装（SQLite 后端）
pip install sccsos

# 全功能安装（含 API、OTEL、Kafka、Chroma）
pip install sccsos[all]

# 按需安装
pip install sccsos[api]     # FastAPI + WebSocket
pip install sccsos[otel]    # OpenTelemetry 追踪
pip install sccsos[kafka]   # Kafka 事件总线
pip install sccsos[pg]      # PostgreSQL 支持
pip install sccsos[chroma]  # Chroma 向量数据库
pip install sccsos[dev]     # 开发依赖（测试、lint）
```

### 2.3 初始化项目

```bash
# 创建新项目
cd my-project
sccsos init

# 初始化含样本文件
sccsos init --samples

# 交互式安装向导（数据库/管理员/定价）
sccsos init --interactive
```

交互式向导的步骤：

1. **数据库配置** — 选择 SQLite 或 PostgreSQL
2. **管理员账户** — 创建 RBAC 管理员（租户 ID + 用户名）
3. **定价方案** — free / pro / enterprise / custom

### 2.4 Docker 部署

```bash
# 构建镜像
docker build -t sccsos:0.14.2 .

# 启动服务
docker run -d -p 8765:8765 \
  -v $(pwd)/data:/app/data \
  -e SCCSOS_DB_PATH=/app/data/sccsos.db \
  sccsos:0.14.2
```

---

## 3. 快速上手

### 3.1 创建并启动 Agent

```bash
# 创建 Agent 定义
sccsos agent create architect --file agents/architect.yaml

# 查看帮助
sccsos agent create --help

# 启动 Agent（后台进程）
sccsos agent start architect

# 查看状态
sccsos agent list
sccsos agent status architect
```

### 3.2 对话

```bash
# 直接对话
sccsos agent ask architect "设计一个用户认证模块"

# 异步查询（适合耗时任务）
sccsos agent ask architect "分析上季度数据" --async

# 查看所有 Agent 的输出
sccsos session list
sccsos session show <session-id>
```

### 3.3 运行工作流

```bash
# 同步运行
sccsos workflow run workflows/架构评审.yaml -i "设计用户认证模块"

# 异步运行
sccsos workflow run workflows/每日巡检.yaml --async

# 查看工作流运行历史
sccsos workflow history
sccsos workflow show <run-id>
```

### 3.4 启动 API 服务

```bash
# FastAPI 模式（推荐）
python -m sccsos.api.fastapi_app --port 8765

# 验证
curl -H "X-Tenant-ID: my-tenant" http://localhost:8765/api/v1/health
curl -H "X-Tenant-ID: my-tenant" http://localhost:8765/api/v1/agents
```

### 3.5 访问管理控制台

API 服务启动后，访问 `http://localhost:8765/admin`

管理控制台功能：

| 页面 | 功能 |
|------|------|
| **仪表盘** | 实时 Agent 状态、Token 趋势图、技能市场概览 |
| **Agent 管理** | 创建/启停/删除 Agent |
| **技能市场** | 浏览/管理/审批/安装技能 |
| **追踪** | OTEL Span 链路追踪 |
| **审计** | Token 消耗与操作审计 |
| **配额** | 租户资源配额管理 |
| **计费** | 按使用量计费统计 |

---

## 4. Agent 管理

### 4.1 Agent 生命周期

SCCS OS 使用 5 状态状态机：

```
            ┌──────────┐
            │ created  │
            └────┬─────┘
                 │ start
                 ▼
            ┌──────────┐
    ┌───────│ running  │────────┐
    │       └──────────┘        │
    │ pause      │              │ stop
    ▼           │ resume        ▼
┌────────┐     │          ┌──────────┐
│ paused │──────┘          │ stopped  │
└────────┘                 └──────────┘
                                  │
                                  │ restart
                                  ▼
                             ┌──────────┐
                             │ running  │
                             └──────────┘
```

### 4.2 Agent 定义 YAML

```yaml
# agents/architect.yaml
name: architect
version: "1.0"
description: "系统架构师 Agent"
personality: "architect"
profile: "sccsos"
tenant_id: "default"
model: "deepseek-v4"
toolsets:
  - read_file
  - web_search
policy:
  max_cost_usd: 10.0
  allowed_tools:
    - read_file
    - web_search
  blocked_tools:
    - terminal
tags:
  - architecture
  - design
```

### 4.3 CLI 命令参考

```bash
sccsos agent create <name>        # 创建 Agent
sccsos agent start <name>         # 启动 Agent
sccsos agent stop <name>          # 停止 Agent
sccsos agent pause <name>         # 暂停 Agent
sccsos agent resume <name>        # 恢复 Agent
sccsos agent restart <name>       # 重启 Agent
sccsos agent list                 # 列出所有 Agent
sccsos agent status <name>        # 查看 Agent 状态
sccsos agent ask <name> <prompt>  # 对话
sccsos agent delete <name>        # 删除 Agent
```

---

## 5. 工作流引擎

### 5.1 工作流定义

工作流使用 YAML 定义，支持 DAG 拓扑排序、条件分支、Jinja2 模板和输入传递。

```yaml
# workflows/需求分析.yaml
name: 需求分析流程
description: "从需求文档到技术方案的系统化分析流程"
version: "1.0"

steps:
  - id: parse-requirements
    agent: architect
    prompt: "分析以下需求文档，提取核心功能点：\n{{ input }}"
    output_var: requirements

  - id: review-requirements
    agent: reviewer
    prompt: "评审需求分析结果：\n{{ requirements }}"
    depends_on: [parse-requirements]
    output_var: review_result

  - id: generate-design
    agent: architect
    prompt: >
      根据评审通过的需求，输出技术设计方案：
      {% if review_result.status == "approved" %}
      需求已通过评审，开始设计。
      {{ requirements }}
      {% else %}
      需求需返工，评审意见：{{ review_result.feedback }}
      {% endif %}
    depends_on: [review-requirements]
    condition: "{{ review_result.status != 'rejected' }}"
    output_var: design_doc
```

### 5.2 运行工作流

```bash
# 工作流输入通过 -i 参数传递
sccsos workflow run workflows/需求分析.yaml \
  -i "我们需要一个支持微信登录的用户系统"

# 异步运行（返回立即，后台执行）
sccsos workflow run workflows/每日巡检.yaml --async

# 查看运行中的工作流
sccsos workflow list

# 查看具体运行详情
sccsos workflow show <run-id>

# 取消运行中的工作流
sccsos workflow cancel <run-id>
```

### 5.3 条件分支与并行

- **条件分支**: 使用 `condition` 字段控制步骤是否执行（Jinja2 表达式）
- **并行执行**: 同层无依赖关系的步骤自动并行执行（ThreadPoolExecutor）
- **退避重试**: 失败步骤按指数退避自动重试（默认 3 次）
- **输出传递**: `${{ steps.<id>.output }}` 跨步骤引用

---

## 6. 技能市场

### 6.1 技能生命周期

```
开发 → submit → pending review → approve → published
                      │                    │
                      ↓                    ↓
                   reject → draft      install → 已安装
                      │
                      ↓
                   reset → draft（可重新提交）
```

### 6.2 管理技能

```bash
# 列出所有技能
sccsos skill list

# 搜索技能
sccsos skill search "数据分析"

# 创建技能（API 或直接写 YAML）
sccsos skill publish <name>

# 提交审批
sccsos skill submit <name>

# 审批技能
sccsos skill approve <name>
sccsos skill reject <name> --reason "需要补充文档"

# 安装技能
sccsos skill install <name>

# 查看版本差异
sccsos skill diff <name> 1.0 1.1

# 查看审批历史
sccsos skill history <name>

# 清理失效技能
sccsos skill prune
```

---

## 7. 安全体系

### 7.1 六层安全防线

| 层 | 组件 | 职责 |
|----|------|------|
| 1 | **PromptInjectionGuard** | 检测并阻止注入攻击、越狱提示 |
| 2 | **PolicyEngine** | 预算控制、工具权限 ACL |
| 3 | **CommandWhitelist** | 命令白名单 + 危险模式检测 |
| 4 | **RateLimiter** | Token 桶算法防资源耗尽 |
| 5 | **HermesAdapter** | 三层安全防线（沙箱 + 策略 + 注入） |
| 6 | **RBAC** | 角色权限控制 |

### 7.2 RBAC 角色

| 角色 | 权限 | 典型用户 |
|------|------|---------|
| `admin` | 全部权限（含 `admin:*`） | 系统管理员 |
| `operator` | Agent 启停 + 查看监控/计费/配额 | 运维操作员 |
| `viewer` | 查看 Agent/Skills/Quota/Billing/Traces | 只读用户 |

API 调用时通过 `X-Role` 头传递角色：

```bash
curl -H "X-Tenant-ID: my-tenant" \
     -H "X-Role: admin" \
     http://localhost:8765/api/v1/agents
```

### 7.3 多租户隔离

租户通过 `X-Tenant-ID` HTTP 头隔离：

- Agent 数据按 `tenant_id` 分片
- 会话数据按租户隔离
- 记忆/知识库按租户分片
- 配额/计费按租户独立统计

```bash
# 租户 A 的 Agent
curl -H "X-Tenant-ID: tenant-a" http://localhost:8765/api/v1/agents

# 租户 B 的 Agent（看不到 Tenant A 的）
curl -H "X-Tenant-ID: tenant-b" http://localhost:8765/api/v1/agents
```

---

## 8. 可观测性

### 8.1 审计

```bash
# 查看审计报告
sccsos audit report

# 按时间过滤
sccsos audit report --since "2026-07-01" --until "2026-07-20"

# 按 Agent 过滤
sccsos audit report --agent architect
```

### 8.2 链路追踪

```bash
# 查看追踪列表
sccsos trace list

# 查看具体追踪详情
sccsos trace show <trace-id>

# 查看慢追踪
sccsos trace list --slow --min-duration 5000
```

### 8.3 健康检查

```bash
sccsos health
```

输出包含：Agent 总数/运行数、数据库状态、EventBus 状态、运行时间。

### 8.4 Webhook 通知

```yaml
# config/webhooks.yaml
webhooks:
  - url: "https://hooks.example.com/sccsos"
    events:
      - workflow.completed
      - workflow.failed
      - agent.crashed
    secret: "whsec_xxx"
```

### 8.5 Grafana 监控

`deploy/grafana/sccsos-dashboard.json` 提供预制的 10 面板仪表盘：

1. Agent 总数（Stat）
2. 运行中 Agent（Stat）
3. 失败 Agent（Stat）
4. Token 消耗趋势（TimeSeries）
5. 累计成本（TimeSeries）
6. 工作流运行数（TimeSeries）
7. API 请求数（TimeSeries）
8. 平均延迟（TimeSeries）
9. 错误率（TimeSeries）
10. Agent 状态分布（BarGauge）

---

## 9. API 参考

### 9.1 基础地址

```
http://localhost:8765/api/v1
```

### 9.2 认证头

| 头 | 必填 | 说明 |
|----|------|------|
| `X-Tenant-ID` | 是 | 租户标识 |
| `X-Role` | 是 | 角色（admin/operator/viewer） |

### 9.3 Agent API

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/agents` | 列出 Agent |
| POST | `/agents/register` | 注册 Agent |
| GET | `/agents/{name}` | 获取 Agent 详情 |
| DELETE | `/agents/{name}` | 删除 Agent |
| POST | `/agents/{name}/start` | 启动 Agent |
| POST | `/agents/{name}/stop` | 停止 Agent |
| POST | `/agents/{name}/pause` | 暂停 Agent |
| POST | `/agents/{name}/resume` | 恢复 Agent |
| POST | `/agents/{name}/restart` | 重启 Agent |
| POST | `/agents/{name}/ask` | 对话 |

### 9.4 工作流 API

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/workflows` | 列出工作流 |
| POST | `/workflows/run` | 运行工作流 |
| GET | `/workflows/{run_id}` | 获取运行详情 |
| POST | `/workflows/{run_id}/cancel` | 取消运行 |

### 9.5 技能 API

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/skills` | 列出技能 |
| POST | `/skills` | 创建技能 |
| GET | `/skills/installed` | 已安装技能 |
| POST | `/skills/{name}/submit` | 提交审批 |
| POST | `/skills/{name}/approve` | 批准技能 |
| POST | `/skills/{name}/reject` | 驳回技能 |
| POST | `/skills/{name}/install` | 安装技能 |
| GET | `/skills/{name}/diff?v1=x&v2=y` | 版本对比 |

### 9.6 其他 API

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/health` | 健康检查 |
| GET | `/audit` | 审计日志 |
| GET | `/traces` | 链路追踪 |
| GET | `/billing/summary` | 计费汇总 |
| GET | `/billing/export` | 导出 CSV |
| GET | `/quotas` | 配额管理 |
| GET | `/webhooks` | Webhook 列表 |
| WS | `/ws` | WebSocket 事件流 |

---

## 10. 部署指南

### 10.1 本地开发

```bash
# 安装开发依赖
pip install sccsos[dev]

# 启动服务
python -m sccsos.api.fastapi_app --port 8765 --reload
```

### 10.2 Docker Compose

```yaml
# docker-compose.yaml
version: "3.8"
services:
  sccsos:
    build: .
    ports:
      - "8765:8765"
    volumes:
      - ./data:/app/data
    environment:
      - SCCSOS_DB_PATH=/app/data/sccsos.db
```

### 10.3 K8s 部署

```bash
# 使用 Helm
helm upgrade --install sccsos ./deploy/k8s/helm \
  --set persistence.size=10Gi \
  --set autoscaling.enabled=true \
  --set autoscaling.minReplicas=2

# 验证
kubectl get pods -l app=sccsos
kubectl get hpa sccsos
```

### 10.4 PostgreSQL 配置

```yaml
# sccsos.yaml
database:
  type: postgresql
  dsn: "postgresql://user:pass@localhost:5432/sccsos"
  path: ""  # 清空 SQLite 路径
```

### 10.5 Kafka 配置

```yaml
# sccsos.yaml
event_bus:
  backend: kafka
  bootstrap_servers: "localhost:9092"
```

---

## 11. 运维与故障排查

### 11.1 常用运维命令

```bash
# 系统状态
sccsos health
sccsos doctor             # 诊断配置和依赖

# 配置管理
sccsos config show
sccsos config set key value

# 维护任务
sccsos maintenance run    # 执行维护（清理、校验）
sccsos maintenance schedule  # 查看维护计划

# 基准测试
sccsos benchmark run
sccsos benchmark report
```

### 11.2 常见问题

| 问题 | 原因 | 解决 |
|------|------|------|
| Agent 启动失败 | Supervisor 检测到进程异常 | 检查日志：`sccsos audit report --agent <name>` |
| 数据库锁定 | SQLite 多线程并发 | 切换到 PostgreSQL，或检查连接池配置 |
| 模型调用超时 | 模型服务不可用 | 检查 ModelRouter 配置，切换备用模型 |
| 技能审批卡住 | 缺少数审人员 | 使用 admin 角色审批：`sccsos skill approve <name>` |
| API 返回 403 | RBAC 角色不足 | 检查 `X-Role` 头，确保有足够权限 |
| WebSocket 断开 | 网络问题或服务重启 | 前端自动重连，检查服务状态 |

### 11.3 日志

```bash
# 查看最新日志
tail -f data/logs/sccsos.log

# 按级别过滤
tail -f data/logs/sccsos.log | grep ERROR

# 按 Agent 过滤
tail -f data/logs/sccsos.log | grep "agent.*architect"
```

---

## 12. 插件开发

### 12.1 插件基础

插件是继承 `PluginBase` 并实现钩子方法的 Python 类：

```python
from sccsos.plugin import PluginBase, hook

class MyPlugin(PluginBase):
    @property
    def name(self) -> str:
        return "my-plugin"

    @property
    def version(self) -> str:
        return "1.0.0"

    @hook
    def on_agent_start(self, agent_name: str) -> None:
        print(f"Agent {agent_name} started")

    @hook
    def on_workflow_complete(self, run_id: str) -> None:
        print(f"Workflow {run_id} completed")
```

### 12.2 可用钩子

| 钩子 | 参数 | 触发时机 |
|------|------|---------|
| `on_agent_start` | `agent_name` | Agent 启动时 |
| `on_agent_stop` | `agent_name` | Agent 停止时 |
| `on_workflow_start` | `run_id` | 工作流开始时 |
| `on_workflow_complete` | `run_id` | 工作流完成时 |
| `on_workflow_fail` | `run_id, error` | 工作流失败时 |
| `on_api_request` | `method, path` | API 请求前 |
| `on_api_response` | `method, path, status` | API 响应后 |
| `on_tool_call` | `agent_name, tool` | 工具调用前 |
| `on_shutdown` | (无) | 系统关闭时 |

### 12.3 安装插件

将插件 `.py` 文件放入插件目录（默认 `config/plugins/`）：

```bash
# 创建插件
mkdir -p config/plugins
cat > config/plugins/my_plugin.py << 'EOF'
from sccsos.plugin import PluginBase, hook

class HelloPlugin(PluginBase):
    @property
    def name(self): return "hello"
    @property
    def version(self): return "1.0.0"
    @hook
    def on_agent_start(self, agent_name):
        print(f"Hello, {agent_name}!")
EOF

# 注册
sccsos plugin discover  # 扫描并加载插件
sccsos plugin list      # 查看已注册插件
sccsos plugin info hello # 查看详情
```

---

> **更多资源**: [CHANGELOG.md](CHANGELOG.md) | [输出/可行性技术方案文档.md](输出/9-可行性技术方案文档.md)  
> **授权**: MIT License
