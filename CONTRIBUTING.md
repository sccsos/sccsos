# SCCS OS — 开发者贡献指南

> 版本: v0.16.6 | 更新: 2026-07-27

欢迎参与 SCCS OS 智能体操作系统的开发！本文档涵盖代码规范、开发流程、测试要求、API 接入、自定义技能开发和插件编写等指南。

---

## 📋 目录

- [开发环境搭建](#-开发环境搭建)
- [项目结构速览](#-项目结构速览)
- [代码规范](#-代码规范)
- [测试要求](#-测试要求)
- [提交 PR 流程](#-提交-pr-流程)
- [API 接入指南](#-api-接入指南)
- [自定义技能开发](#-自定义技能开发)
- [自定义插件开发](#-自定义插件开发)
- [架构决策记录 (ADR)](#-架构决策记录-adr)
- [常见问题](#-常见问题)

---

## 🛠 开发环境搭建

### 前置要求

| 工具 | 版本 | 用途 |
|-----|------|------|
| Python | ≥ 3.10 | 运行环境 |
| pip | ≥ 21.0 | 包管理 |
| Node.js | ≥ 18 | 前端 (可选) |
| Docker | ≥ 20.10 | 容器化 (可选) |
| kubectl | ≥ 1.24 | K8s 部署 (可选) |

### 快速启动

```bash
# 克隆仓库
git clone https://github.com/your-org/sccsos.git
cd sccsos

# 安装依赖（推荐使用 venv）
python3 -m venv .venv && source .venv/bin/activate

# 基础安装
pip install -e .

# 开发模式（含所有额外依赖）
pip install -e ".[dev,api,otel,all]"

# 验证安装
sccsos --version
sccsos init --help

# 运行测试（快速模式，仅检查引入模块）
python3 -m pytest tests/ --tb=short -q

# 启动 API 服务器
python3 -m sccsos.api.fastapi_app --port 8765
```

### 前端开发

```bash
cd frontend/
npm install
npm run dev  # 开发服务器（热重载）
npm run build  # 生产构建
```

---

## 🏗 项目结构速览

```
sccsos/
├── __init__.py           # 包入口
├── __main__.py           # python -m sccsos
├── _version.py           # 版本单源（所有版本号源自此）
│
├── core/                 # 核心运行时（~3,500 行）
│   ├── agent_runtime.py  # 统一入口 Runtime（Facade 模式）
│   ├── agent_runner.py   # Agent 后台进程管理
│   ├── config.py         # YAML 配置加载 + 数据类
│   ├── db/               # 持久层（Database + Schema + CRUD）
│   ├── event_bus.py      # EventBusABC + LocalEventBus
│   ├── events.py         # 事件常量
│   ├── hermes_adapter.py # Hermes CLI 适配器 + 3 层安全防线
│   ├── lifecycle.py      # 5 状态状态机
│   ├── model_router.py   # 多模型调度
│   ├── session.py        # 会话管理
│   ├── supervisor.py     # 心跳检测 + 自动重启
│   ├── skill_review.py   # 技能审批管理
│   ├── retry_policy.py   # 指数退避重试
│   ├── context_builder.py# Jinja2 上下文装配
│   ├── templates.py      # Jinja2 沙箱模板
│   └── workflow/         # 工作流引擎（DAG + Engine + Context）
│
├── api/                  # HTTP API
│   ├── fastapi_app.py    # FastAPI 应用入口（推荐）
│   ├── models.py         # Pydantic 模型
│   └── routes/           # 路由模块（7 个文件）
│       ├── agents.py     # Agent CRUD
│       ├── audit.py      # 审计
│       ├── billing.py    # 计费
│       ├── health.py     # 健康检查
│       ├── sessions.py   # 会话
│       ├── skills.py     # 技能市场 + 审批 + 评分
│       ├── traces.py     # 追踪
│       ├── workflows.py  # 工作流
│       └── ws.py         # WebSocket
│
├── cli/                  # Click CLI（9 个子命令）
│
├── security/             # 安全体系（6 层）
│   ├── base.py           # 抽象基类
│   ├── injection.py      # Prompt 注入防护
│   ├── policy.py         # 预算/工具权限策略
│   ├── ratelimit.py      # 速率限制器
│   ├── rbac.py           # 角色权限控制
│   └── sandbox.py        # 命令白名单
│
├── observability/        # 可观测性（6 模块）
│   ├── alert_manager.py  # 阈值告警
│   ├── auditor.py        # Token/操作审计
│   ├── billing.py        # 计费导出
│   ├── logger.py         # JSON 结构化日志
│   ├── otel_tracer.py    # OpenTelemetry 追踪
│   ├── pricing.py        # LLM 定价表
│   ├── tracer.py         # Span 追踪
│   └── webhook.py        # HTTP 回调
│
├── memory/               # 记忆系统（3 模块）
├── skill_market/         # 技能市场
├── skill_rating.py       # 技能评分系统
├── agents/               # Agent YAML 定义
├── workflows/            # Workflow YAML 定义
├── personalities/        # Personality YAML
├── tests/                # 测试（50+ 文件, 940+ 用例）
├── deploy/               # 部署（Docker / K8s / Helm）
└── frontend/             # Vue 3 SPA（7 页面）
```

---

## 📐 代码规范

### 通用规则

- **Python 版本**: 3.10+ (使用 `from __future__ import annotations`)
- **代码风格**: PEP 8
- **命名规范**:
  - 类名: `PascalCase`
  - 函数/方法: `snake_case`
  - 模块级常量: `UPPER_CASE`
  - 私有成员: `_prefix` (Python 惯例)
- **类型注解**: 所有公共 API 必须标注完整类型
- **文档字符串**: Google-style docstrings

### 模块规范

```python
"""Module docstring — single line purpose + optional usage example."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger("sccsos.module_name")


class MyService:
    """Description of what this class does.

    Usage:
        svc = MyService(db)
        result = svc.do_thing(param1="value")
    """

    def __init__(self, db: "Database") -> None:
        self._db = db
```

### 版本管理

版本号单源定义于 `sccsos/_version.py`，所有引用该文件的模块自动同步。

```bash
# 升级版本（需同步 17+ 文件）
# 手动修改 _version.py 后运行：
python3 scripts/sync_version.py  # 自动同步所有引用文件
```

### 架构约束

1. **DB 访问统一通过 `Database` 类**（经 `crud.py` 或直接 `db.execute()`）
2. **事件通信统一通过 `EventBusABC`**
3. **新功能必须实现对应抽象接口**（如新的安全模块继承 `SecurityBase`）
4. **配置项统一在 `config.py` 声明，不支持硬编码**

---

## 🧪 测试要求

### 测试框架

- **框架**: pytest ≥ 7.0
- **覆盖率**: CI 门禁 ≥ 70%（整体）
- **运行命令**:

```bash
# 全部测试（含覆盖率）
python3 -m pytest tests/ --cov=sccsos --tb=short

# 指定模块测试
python3 -m pytest tests/test_skill_rating.py -v

# 快速无覆盖测试
python3 -m pytest tests/ --tb=no -q
```

### 测试规范

参考 `tests/CONVENTIONS.md`：

- 每个模块对应一个 `test_<module>.py` 文件
- 使用 `pytest.fixture` 管理共享资源（如 DB、Runtime）
- 所有使用 SQLite 的测试使用 `:memory:` 数据库
- 不依赖测试执行顺序
- 测试用例覆盖：
  - 正常路径（Happy path）
  - 边界条件（空值、极值）
  - 错误路径（异常、权限不足、资源不存在）
  - 安全审计校验

### 覆盖率目标

| 模块类型 | 目标覆盖率 |
|---------|-----------|
| 核心运行时 (core/) | ≥ 85% |
| 安全模块 (security/) | ≥ 90% |
| API 路由 (api/routes/) | ≥ 80% |
| CLI 命令 (cli/) | ≥ 60% |
| 可观测性 (observability/) | ≥ 80% |
| **整体** | **≥ 70%** |

---

## 🔀 提交 PR 流程

### 分支策略

```
main          ← 生产就绪版本
  └─ develop  ← 开发主线
       ├─ feat/<name>    ← 新功能
       ├─ fix/<name>     ← Bug 修复
       ├─ docs/<name>    ← 文档更新
       └─ refactor/<name> ← 重构
```

### PR 提交流程

1. **创建分支**：从 `develop` 签出 `feat/my-feature`
2. **实现功能**：遵循代码规范 + 编写测试
3. **本地验证**：
   ```bash
   python3 -m pytest tests/ --cov=sccsos --tb=short
   ```
4. **提交 PR**：填写 PR 模板（见 `.github/PULL_REQUEST_TEMPLATE.md`）
5. **CI 检查**：
   - ✅ 全部测试通过
   - ✅ 覆盖率 ≥ 70%
   - ✅ Lint 无错误
   - ✅ 版本号同步一致
6. **代码审查**：至少 1 位维护者 Approval
7. **合并**：Squash merge 到 `develop`

### 提交信息规范

```
<type>(<scope>): <简短说明>

<详细说明（如需）>
```

类型: `feat` / `fix` / `docs` / `refactor` / `test` / `chore`

示例:
```
feat(skill-rating): 添加技能星级评分系统

- POST /skills/{name}/rate — 1-5 星评分
- GET /skills/{name}/rating — 聚合统计
- GET /skills/ratings/top — 热门技能排行
- 28 测试用例全覆盖
```

---

## 🔌 API 接入指南

### 基础地址

```
生产环境: https://<your-host>/api/v1/
开发环境: http://localhost:8765/api/v1/
```

### 认证

SCCS OS 使用 HTTP 头进行租户隔离和权限管控：

| 请求头 | 必填 | 说明 |
|--------|------|------|
| `X-Tenant-ID` | 是 | 租户标识（多租户场景） |
| `X-Role` | 否 | 角色：`admin` / `operator` / `viewer` |

### 核心端点

| 端点 | 方法 | 说明 |
|------|------|------|
| `/health` | GET | 健康检查 |
| `/agents` | GET | 列出 Agent 实例 |
| `/agents/{name}/{action}` | POST | Agent 操作（start/stop/pause/resume） |
| `/skills` | GET | 列出技能市场 |
| `/skills` | POST | 发布新技能 |
| `/skills/{name}/rate` | POST | 技能评分 |
| `/skills/ratings/top` | GET | 评分最高技能 |
| `/skills/popular` | GET | 热门技能 |
| `/skills/{name}/install` | POST | 安装技能 |
| `/workflows/run` | POST | 运行工作流 |
| `/billing/summary` | GET | 用量统计 |
| `/traces` | GET | 追踪查询 |

### 示例：技能评分

```bash
# 评分
curl -X POST "http://localhost:8765/api/v1/skills/agent-architect/rate?score=5&user_id=alice&comment=Great!"

# 查看评分统计
curl "http://localhost:8765/api/v1/skills/agent-architect/rating"

# 热门技能排行
curl "http://localhost:8765/api/v1/skills/ratings/top?limit=10"
```

---

## 🧩 自定义技能开发

技能是 SCCS OS 的核心可复用单元，支持三种类型：`personality` / `agent` / `workflow`。

### Personality 技能格式

```yaml
# personalities/my-assistant.yaml
name: my-assistant
system_prompt: |
  你是一个专业的 AI 助手，擅长技术问答。
  请在回答时使用中文，保持简洁准确。
temperature: 0.7
max_tokens: 2048
tools:
  - web_search
  - code_executor
knowledge_base:
  - docs/*
memory:
  ttl: 3600
```

### Agent 定义格式

```yaml
# agents/data-analyzer.yaml
name: data-analyzer
personality: my-assistant
model: gpt-4
budget:
  max_calls: 100
  max_tokens: 50000
schedule: "0 9 * * 1-5"  # 工作日 9 点
```

### 工作流格式

```yaml
# workflows/每日报表.yaml
name: daily-report
version: "1.0"
steps:
  - id: collect
    agent: data-collector
    prompt: "收集今日运营数据"
  - id: analyze
    agent: data-analyzer
    prompt: "分析 {{ steps.collect.output }}"
    depends_on: [collect]
  - id: report
    agent: report-writer
    prompt: "生成 {{ steps.analyze.output }} 的日报"
    depends_on: [analyze]
```

### 技能市场流程

```bash
# 1. 发布技能
sccsos skill publish personalities/my-assistant.yaml

# 2. 提交审核
sccsos skill submit my-assistant

# 3. 审批（admin 角色）
sccsos skill approve my-assistant

# 4. 安装
sccsos skill install my-assistant

# 5. 使用
sccsos agent create my-agent --personality my-assistant
sccsos agent ask my-agent "你好"
```

---

## 🔧 自定义插件开发

SCCS OS 支持通过插件扩展能力。插件是遵循特定接口的 Python 包。

### 插件结构

```
my-plugin/
├── __init__.py       # 注册入口
├── plugin.yaml       # 插件元信息
└── handlers.py       # 事件处理
```

### 插件示例

```python
# my-plugin/__init__.py
"""My custom SCCS OS plugin — adds Slack notification support."""

from sccsos.plugin import BasePlugin, hook


class SlackNotifier(BasePlugin):
    """Sends workflow completion notifications to Slack."""

    name = "slack-notifier"
    version = "1.0.0"
    description = "Slack 通知插件"

    @hook
    def on_workflow_completed(self, run_id: str, **data):
        """Send notification when a workflow completes."""
        webhook_url = self.config.get("slack_webhook_url")
        if webhook_url:
            self._post_to_slack(webhook_url, f"✅ 工作流 {run_id} 完成")

    def _post_to_slack(self, url: str, message: str):
        import requests
        requests.post(url, json={"text": message})
```

### 安装插件

```bash
# 从本地目录
sccsos plugin install ./my-plugin

# 从远程仓库
sccsos plugin install git+https://github.com/user/my-plugin.git

# 列出已安装插件
sccsos plugin list
```

---

## 📝 架构决策记录 (ADR)

项目使用 ADR (Architecture Decision Record) 记录关键架构决策。ADR 文件存放于 `wiki/concepts/` 目录。

### ADR 编号规范

ADR 编号连续递增，命名格式：`ADR-<编号>-<简短主题>.md`

### ADR 模板

```markdown
# ADR-<编号>：<决策标题>

- **日期**: YYYY-MM-DD
- **状态**: 已接受 / 提议 / 已废弃
- **决策者**: 姓名

## 背景

描述了需要做决策的业务/技术上下文。

## 方案对比

| 方案 | 优点 | 缺点 |
|------|------|------|
| 方案 A | ... | ... |
| 方案 B | ... | ... |

## 决策

选择了方案 A，因为：

## 后果

采用本决策后的正面/负面影响。
```

### 已录 ADR 索引

| 编号 | 主题 | 版本关联 |
|------|------|---------|
| ADR-003 | P0/P1/P2 三阶段演化路径 | v0.7.0 |
| ADR-004 | 深度架构设计：三层子运行时 | v0.7.0 |
| ADR-005 | 可行性分析验证 | v0.8.0 |
| ADR-006 | 架构优化：EventBus + Supervisor | v0.8.1 |
| ADR-007/008/009 | P1 架构改进：Auto-Merge/热点加载/Schema 版本 | v0.8.1 |
| ADR-010 | v0.8.1 发布决策 | v0.8.1 |
| ADR-011 | Session 持久化 + ModelRouter + FastAPI 渐进迁移 | v0.9.0 |
| ADR-012 | 技能市场 + 审批系统 + RBAC | v0.13.0 |
| ADR-013 | 技能评分 + 故障自愈测试 + 文档社区基建 | v0.15.5 |

---

## ❓ 常见问题

### Q: 如何添加新的数据库表？

1. 在 `sccsos/core/db/schema.py` 的 `SCHEMA_SQL` 和 `POSTGRES_SCHEMA_SQL` 中定义表结构
2. 在 `apply_migrations()` 函数中添加迁移逻辑
3. 在 `sccsos/core/db/crud.py` 中添加对应的 CRUD 操作

### Q: 如何添加新的 CLI 命令？

1. 在 `sccsos/cli/` 下创建新模块（参考现有命令格式）
2. 在 `sccsos/cli/__init__.py` 的 `cli` 组中注册新命令
3. 在 `tests/` 中添加对应的 CLI 测试

### Q: 如何添加新的 API 路由？

1. 在 `sccsos/api/routes/` 下创建路由文件或添加现有文件
2. 使用 `@router.get/post/...` 装饰器定义端点
3. 在 `sccsos/api/fastapi_app.py` 的 `_register_routes()` 中注册

### Q: 覆盖率不达标怎么办？

参考 `tests/CONVENTIONS.md` 中的模式添加缺失测试，重点关注未覆盖的函数和分支。
使用 `python3 -m pytest tests/ --cov=sccsos --cov-report=term-missing` 查看具体缺失行。

### Q: 如何贡献文档？

文档以 `.md` 格式存放于项目根和 `wiki/` 目录。请确保：
- 中英文术语统一（参考已有文档）
- 代码示例可运行
- 文档与代码版本同步

---

## 📚 延伸阅读

- [项目 AGENTS.md](./AGENTS.md) — 项目概述与架构概览
- [CHANGELOG.md](./CHANGELOG.md) — 版本变更记录
- [测试规范](./tests/CONVENTIONS.md) — 详细测试约定
- [Wiki - 架构框架](./wiki/concepts/sccsos-architecture-framework.md) — 7 大关注域
- [Wiki - ADR 索引](./wiki/concepts/) — 架构决策记录
- [可行性技术方案](./输出/9-可行性技术方案文档.md) — 项目立项文档
- [生产部署 Checklist](./ops/production-checklist.md) — 上线检查清单
