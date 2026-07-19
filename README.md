# SCCS OS — Smart Agent Runtime Platform

> v0.7.1 | [测试验证与操作手册](输出/SCCS OS 测试验证与操作手册.md)

SCCS OS 是一个轻量级智能体运行时环境，提供多 Agent 编排、生命周期管理、可观测性、安全策略和开发者接口。基于 Hermes Agent 构建，支持多租户隔离和容器化部署。

## 快速开始

```bash
# 安装
pip install sccsos

# 初始化项目
sccsos init my-project
cd my-project

# 注册并启动 Agent
sccsos agent create architect
sccsos agent start architect

# 对话
sccsos agent ask architect "设计一个用户认证模块"

# 运行工作流
sccsos workflow run workflows/架构评审.yaml -i "构建微服务架构"

# 查看系统状态
sccsos health
sccsos audit report

# Docker 部署
docker build -t sccsos:0.6.4 .
docker run -d -p 8765:8765 sccsos:0.6.4
```

## 特性

| 特性 | 说明 |
|------|------|
| **多 Agent 编排** | DAG 工作流引擎，支持并行执行、条件分支、重试和取消 |
| **Agent 生命周期** | 5 状态状态机 (CREATED/RUNNING/PAUSED/FAILED/TERMINATED) |
| **后台进程管理** | `agent start` 启动后台进程，`agent ask` 发送 prompt 并等待响应 |
| **安全沙箱** | 命令白名单 + 危险模式拦截 + Budget 预算 + 工具 ACL |
| **可观测性** | Span 链路追踪 + JSON 结构化日志 + Token 审计 + Webhook 通知 + 阈值告警 |
| **记忆系统** | TF-IDF 语义检索 + Wiki 知识库 + 模板注入 + 跨会话持久 KV 存储 |
| **Personality 系统** | 为每个 Agent 定义角色和系统提示词 |
| **多租户隔离** | DB schema 级 tenant_id + X-Tenant-ID API 头 |
| **容器化部署** | Docker 多阶段构建 + docker-compose |
| **HTTP API** | 零依赖 REST API 服务器，全部端点覆盖 |

## CLI 命令

```bash
sccsos init             # 初始化项目
sccsos version          # 显示版本
sccsos health           # 系统健康检查

sccsos agent list       # 列出所有 Agent
sccsos agent create     # 创建新的 Agent
sccsos agent start      # 启动 Agent（后台进程）
sccsos agent stop       # 停止 Agent
sccsos agent pause      # 暂停 Agent
sccsos agent resume     # 恢复 Agent
sccsos agent restart    # 重启失败的 Agent
sccsos agent status     # 查看 Agent 状态
sccsos agent ask        # 向 Agent 发送 prompt
sccsos agent logs       # 查看 Agent 日志

sccsos workflow run       # 运行工作流
sccsos workflow validate  # 验证工作流 YAML
sccsos workflow visualize # 生成 Mermaid 流程图
sccsos workflow status    # 查看工作流运行状态
sccsos workflow list      # 列出最近工作流
sccsos workflow cancel    # 取消运行中的工作流

sccsos trace list       # 列出追踪记录
sccsos trace show       # 查看追踪详情

sccsos audit report     # 审计报告
sccsos audit log        # 审计日志
```

## 配置

项目根目录的 `sccsos.yaml` 是配置文件：

```yaml
project:
  name: my-project
  version: 1.0.0

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

tracing:
  enabled: true
  export_path: ./traces/

pricing:
  path: ./config/pricing.json

agents:
  path: ./agents
  wiki_path: ./wiki
  personalities_path: ./personalities

policies:
  default:
    max_tokens_per_session: 100000
    max_cost_usd: 5.0
    allowed_tools:
      - read_file
      - search_files
      - web_search
    blocked_tools: []
    allowed_commands:
      - hermes
      - git
      - ls
      - python3
```

完整参考配置见 `config/sample-config.yaml`，详细操作指南见[测试验证与操作手册](输出/SCCS OS 测试验证与操作手册.md)。

## 工作流示例

```yaml
name: architecture-review
version: "1.0"
description: 多 Agent 协同架构评审

steps:
  - id: requirements_analysis
    name: 需求分析
    agent: architect
    prompt: |
      分析以下项目需求：
      {{ steps.input.context }}

  - id: architecture_design
    name: 架构设计
    agent: architect
    prompt: |
      基于需求分析设计架构：
      {{ steps.requirements_analysis.response }}
    depends_on:
      - requirements_analysis
```

## 系统架构

```
CLI / API
  └→ AgentRuntime
       ├→ AgentRegistry — YAML Agent 定义
       ├→ LifecycleManager — 5 状态状态机
       ├→ WorkflowEngine — DAG 解析 + 并行执行
       │    ├→ StepExecutor — 单步执行 (模板/条件/重试/审计)
       │    └→ HermesAdapter — CLI 桥接 + 三层安全防线
       │         ├→ PolicyEngine — 预算 + 工具 ACL
       │         └→ CommandWhitelist — 危险模式 + 白名单
       ├→ PersonalityRegistry — Agent 角色 + system prompt 注入
       ├→ AlertManager — 阈值监控 + Webhook 告警
       ├→ KnowledgeBase — TF-IDF 语义检索
       ├→ MemoryStore — 跨会话 KV 持久记忆
       └→ Tracer / Auditor — 追踪 + 审计
```

## 技术栈

- **语言**: Python 3.11+
- **运行时**: Hermes Agent (Nous Research)
- **数据库**: SQLite (WAL 模式) + 自动 schema 迁移
- **模板**: Jinja2 (Sandboxed)
- **CLI**: Click
- **部署**: Docker + docker-compose

## 测试

```bash
# 全量测试
python3 -m pytest tests/ -v

# 按模块
python3 -m pytest tests/test_integration.py -v --tb=short
python3 -m pytest tests/test_api_server.py -v --tb=short

# 完整测试验证指南
cat '输出/SCCS OS 测试验证与操作手册.md'
```

## 许可证

MIT
