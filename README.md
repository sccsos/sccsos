# SCCS OS v0.16.6

**Smart Agent Runtime Platform for SCCS-T Product Ecosystem**

[![Tests](https://img.shields.io/badge/tests-1158%20passed-brightgreen)](https://github.com/your-org/sccsos)
[![Coverage](https://img.shields.io/badge/coverage-67%25-yellow)](https://github.com/your-org/sccsos)
[![Health](https://img.shields.io/badge/health-8.8/10-blue)](wiki/concepts/sccsos-architecture-framework.md)

SCCS OS 是一个面向多智能体集群的统一管控平台，底层复用 Hermes Agent 运行时内核，上层自研操作系统级能力。
采用**三层子运行时架构**解耦核心、可观测性与工作流编排。

```bash
pip install sccsos[all]
sccsos init
sccsos agent create architect
sccsos agent start architect
sccsos agent ask architect "设计一个认证模块"
```

---

## 架构概览

![系统架构图](输出/images/sccsos-system-architecture-light.png)

```
AgentRuntime (统一入口 Facade)
  ├── RuntimeCore                    # 核心：DB/Regsitry/Adapter/Runner/Session/Supervisor
  ├── ObservabilityRuntime           # 可观测：追踪/审计/日志/告警/Webhook/Pricing
  └── WorkflowRuntime                # 工作流：编排引擎/策略/角色/事件总线
```

### 七域架构框架

| # | 域 | 评分 | 核心能力 |
|---|-----|:----:|---------|
| 1 | 多智能体编排 | **9.3** | DAG + 条件分支 + 并行 ThreadPool + Jinja2 + 退避重试 |
| 2 | 工具增强型 LLM | **9.0** | ABC 适配层 + 三层安全防线 + ModelRouter + Personality |
| 3 | Agent 生命周期 | **9.5** | 5 状态 FSM + Supervisor 心跳 + AgentRunner 后台线程 |
| 4 | 可观测性 | **8.8** | Span 追踪 + JSON 日志 + Token 审计 + Webhook + 告警 + OTel |
| 5 | 安全沙箱 | **9.2** | 预算引擎 + 命令白名单 + 工具 ACL + RBAC + 注入防护 |
| 6 | 记忆系统 | **9.0** | 知识库 + TF-IDF 向量检索 + 跨会话 KV 记忆 + Chroma |
| 7 | 提示工程 | **8.5** | Agent YAML + Personality 版本管理 + Jinja2 沙箱 |
| | **综合** | **~9.0** | 架构深度审计完成，P0+P1 优化已实施 |

> 评分基准：详见 [架构框架](wiki/concepts/sccsos-architecture-framework.md) | [ADR 系列](wiki/concepts/)

---

## 快速开始

```bash
# 安装
pip install sccsos[all]

# 初始化项目
sccsos init my-project
cd my-project

# 注册并启动 Agent（后台进程）
sccsos agent create architect
sccsos agent start architect
sccsos agent list              # Runner 列显示运行状态
sccsos agent status architect

# 直接对话
sccsos agent ask architect "设计一个用户认证模块"

# 运行 Workflow（支持条件分支和输入传递）
sccsos workflow run workflows/架构评审.yaml -i "设计用户认证模块"

# 异步运行
sccsos workflow run workflows/每日巡检.yaml --async

# 查看审计
sccsos audit report
sccsos health

# 启动 API 服务器（FastAPI 模式）
python -m sccsos.api.fastapi_app --port 8765
# 浏览器打开 http://localhost:8765/admin 访问 Vue 控制台
```

---

## 核心特性

### 编排引擎
- **DAG 拓扑排序** — 自动解析步骤依赖关系
- **条件分支** — Jinja2 条件表达式控制步骤跳过
- **并行执行** — ThreadPoolExecutor 并发组
- **退避重试** — 指数退避 + 瞬态错误自动恢复
- **Jinja2 模板** — 沙箱渲染，13 个内置过滤器

### 生命周期管理
- **5 状态状态机** — CREATED → RUNNING → PAUSED → STOPPED / FAILED
- **Supervisor 心跳** — 自动检测无响应 Agent 并重启（上限保护）
- **Session 持久化** — 跨会话记忆恢复
- **Agent 后台进程** — 独立的 task queue + stop event

### 可观测性
- **Span 追踪** — 每条 workflow 和 step 的完整执行链路
- **JSON 结构化日志** — 可被任何日志平台消费
- **Token 审计** — 每步调用的 Token 消耗和成本追踪
- **OTel 桥接** — OpenTelemetry 导出到任意后端（可选）
- **Webhook 通知** — 工作流完成/失败时回调
- **阈值告警** — 错误率/成本超限自动告警
- **Grafana 仪表盘** — 10 面板预配置模板

### 安全体系
- **三层防线**：注入检测 → 预算/工具 ACL → 命令沙箱
- **RBAC**：admin/operator/viewer 三角色，20+ 权限点
- **速率限制**：每 Agent 调用频率控制
- **敏感数据脱敏**：身份/信用卡/密钥/密码自动 redact
- **多语言防注入**：Unicode NFKC 归一化 + 西里尔同形字转写

### 记忆系统
- **知识库**：Markdown wiki → TF-IDF 向量检索
- **跨会话 KV 记忆**：持久化键值存储（支持 TTL 过期）
- **模板注入**：`{{ knowledge }}` 和 `{{ memory }}` 上下文变量
- **Chroma 可选**：替代 TF-IDF 的向量数据库（可选依赖）

### 事件总线
- **EventBusABC 抽象** — 可通过适配器扩展
- **LocalEventBus** — 进程内 pub/sub（默认）
- **KafkaEventBus** — 分布式集群消息（可选 kafka-python）
- **事件持久化** — SQLite 事件队列 + 重放

### API 层
- **FastAPI**（推荐）— 异步 + WebSocket + OpenAPI /docs
- **Vue 3 SPA** 管理控制台 — 7 页面实时仪表盘
- **WebSocket 实时事件** — Agent 生命周期 + 工作流 + 技能市场
- **RBAC 权限守卫** — 每个端点独立鉴权

---

## CLI 命令（15 个子命令）

| 命令 | 说明 |
|------|------|
| `sccsos init` | 初始化项目 / `--interactive` 交互式向导 |
| `sccsos agent create/list/start/stop` | Agent CRUD 与生命周期 |
| `sccsos agent pause/resume/restart` | Agent 暂停/恢复/重启 |
| `sccsos agent ask <name> <prompt>` | 向运行中 Agent 发 prompt |
| `sccsos workflow validate/run/status` | 工作流管理 |
| `sccsos workflow cancel/list/visualize` | 取消/列表/DAG 可视化 |
| `sccsos audit report/log` | 审计和成本报告 |
| `sccsos trace list/show` | 链路追踪 |
| `sccsos memory save/get/list/delete` | 跨会话持久记忆 |
| `sccsos session list/show/close` | 会话历史 |
| `sccsos personality list/show/set/unset` | 角色管理 |
| `sccsos config reload` | 热重载配置 |
| `sccsos health` | 系统健康检查 |
| `sccsos serve` | 启动 FastAPI 服务器 |
| `sccsos version` | 版本信息 |

---
## 部署

### Docker 部署（双模式）

```bash
# 全合一镜像（Hermes 内嵌）
docker build -t sccsos:0.16.6 -f Dockerfile .
docker run -d -p 8765:8765 sccsos:0.16.6

# 或使用 Docker Compose：
#   全合一模式（默认）：docker compose up -d
#   双容器模式（slim）：docker compose --profile slim up -d
```

### Kubernetes

```bash
helm install sccsos deploy/k8s/ --values my-values.yaml

# HPA 弹性扩缩容
kubectl apply -f deploy/k8s/hpa.yaml
```

### 生产环境清单

详见 [ops/production-checklist.md](ops/production-checklist.md)：

- [ ] 数据库：SQLite (WAL) → PostgreSQL for HA
- [ ] 消息总线：LocalEventBus → Kafka
- [ ] 可观测性：启用 OTel 导出到 Prometheus + Grafana
- [ ] 安全：TLS/mTLS + JWT 鉴权
- [ ] 备份：DB 自动备份 + 配置版本化

---

## 测试

```bash
# 全量测试（快速：默认跳过慢测试）
python -m pytest tests/ -q

# 包含慢测试（故障自愈、并发）
python -m pytest tests/ -m slow -v

# 覆盖率
python -m pytest --cov=sccsos

# 安全审计
python -m pytest tests/test_security_audit.py -v

# 故障自愈测试
python -m pytest tests/test_fault_tolerance.py -v
```

| 指标 | 数值 |
|------|:----:|
| 测试用例 | **994** (52 文件, 176 测试类) |
| 覆盖率 | **71%** |
| 安全审计 | **43/43** 通过 (0 xfail) |
| 故障自愈 | **26** 个场景 |
| CI 门禁 | ≥70% 覆盖率 |

---

## 项目结构

```
sccsos/
├── core/                  # 核心运行时 (~3,500 行)
│   ├── agent_runtime.py   # 统一入口 Facade
│   ├── runtime_core.py    # 核心子运行时
│   ├── runtime_observability.py # 可观测子运行时
│   ├── runtime_workflow.py      # 工作流子运行时
│   └── workflow/          # DAG + 条件分支 + 并行引擎
├── api/                   # FastAPI (推荐) + Vue SPA
│   ├── fastapi_app.py     # 应用工厂
│   └── routes/            # 11 个路由模块
├── cli/                   # Click (15 子命令)
├── memory/                # 知识库 + 向量检索 + KV 记忆
├── observability/         # 追踪/审计/日志/告警/Webhook
├── security/              # 注入防护/RBAC/沙箱/速限
├── tests/                 # 50 文件, 994 用例
├── deploy/k8s/            # Kubernetes 部署清单
├── Dockerfile             # 多阶段构建
├── docker-compose.yaml    # 容器编排
└── wiki/                  # 架构框架 + ADR 决策记录
```

---

## 架构健康评分

| 维度 | 评分 | 趋势 |
|------|:----:|:----:|
| 多智能体编排 | 9.3 | ✅ |
| 工具增强型 LLM | 9.0 | ✅ |
| Agent 生命周期 | 9.5 | ✅ |
| 可观测性 | 8.8 | ⬆ ThreadPoolExecutor |
| 安全沙箱 | 9.2 | ✅ |
| 记忆系统 | 9.0 | ✅ |
| 多租户隔离 | 8.5 | ✅ |
| 事件与解耦 | 8.5 | ⬆ Circuit Breaker |
| **综合** | **~9.0** | 🏆 架构审计完成 |

---

## 版本历史

| 版本 | 日期 | 关键特性 |
|------|------|---------|
| v0.16.6 | 2026-07-27 | home/code_path 安装 env 注入 + code_path fallback 修复 |
| v0.16.5 | 2026-07-26 | hermes-installer 默认智能体 + init Agent 策略调整 |
| v0.16.4 | 2026-07-26 | Profile 克隆增加 .env 同步 |
| v0.16.3 | 2026-07-26 | .env 密钥同步 + Profile 完整克隆修复（22 键） |
| v0.16.2 | 2026-07-26 | API Key 自动同步（env var → Hermes profile）+ 安装流程完善 |
| v0.16.1 | 2026-07-26 | 架构深度审计：24,649行分析 + 健康评分修正 8.7 + 死代码确认 |
| v0.16.0 | 2026-07-26 | 默认配置优先 + doctor 一致性检查 + profile 克隆策略 |
| v0.15.9 | 2026-07-26 | 国内镜像全覆盖 script/git/docker + 安装后自动配置 Hermes profile |
| v0.15.8 | 2026-07-26 | 安装路径读取 + setup 配置结构修复 + base_url 默认值 |
| v0.15.5 | 2026-07-26 | Hermes 7模式安装 + 角色包 + 架构审计 P0+P1 优化 |
| v0.14.1 | 2026-07-22 | 技能市场 + RBAC + K8s + 审批评论 |
| v0.14.0 | 2026-07-22 | 安全加固 + E2E API + Locust 压测 |
| v0.13 | 2026-07-22 | Vue 3 SPA + WebSocket + Billing/Quota |
| v0.8~v0.12 | 2026-07 | 渐进架构演进，从 4.9 升至 8.8 |

详见 [CHANGELOG.md](CHANGELOG.md) | [ADR 系列](wiki/concepts/)

---

## 贡献

详见 [CONTRIBUTING.md](CONTRIBUTING.md) — 含环境搭建、编码规范、测试要求、PR 流程等 12 章指南。

---

## License

MIT
