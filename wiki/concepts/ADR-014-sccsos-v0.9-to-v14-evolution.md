# ADR-014：SCCS OS 架构进化 v0.9.0→v0.14.2 全景

- **日期**: 2026-07-26
- **状态**: 已接受
- **版本关联**: v0.9.0 ~ v0.14.2（8 个版本迭代）
- **当前版本**: v0.16.5（P0 修复 + 版本同步）
- **前置 ADR**: ADR-003（P0/P1/P2 策略）、ADR-011（v0.9.0 基础）

---

## 一、背景

v0.8.1 完成基础可观测性（EventBus/Supervisor/Config）后，SCCS OS 从最小可用产品进入**能力完善和商业化就绪**阶段。本 ADR 覆盖 v0.9.0~v0.14.2 共 8 个版本的架构决策，跨越会话持久化、多模型路由、前端控制台、安全审计、企业级计费、技能市场、K8s 部署等关键进化。——**当前 v0.16.5 已完成 P0 修复 + 版本同步**。

整体演进遵循"三横三纵"主线：
- **三横**：基础架构完善 → 生产稳定性 → 商业化能力
- **三纵**：存储层（SQLite→PostgreSQL/Chroma）、API 层（http.server→FastAPI→WebSocket）、部署层（单进程→多 worker→K8s）

---

## 二、逐版本决策与权衡

### v0.9.0 — 会话持久化 + ModelRouter + FastAPI

| 领域 | 方案 | 选项 | 决策理由 |
|------|------|------|---------|
| 会话存储 | SQLite 表持久化 | vs Redis | 零依赖，与现有 DB 层一致；PAUSED 保存上下文 |
| 模型选择 | YAML 配置池 + 任务感知 | vs 固定模型 | 灵活性，fallback 链保障可用性 |
| HTTP 服务器 | FastAPI + uvicorn | vs http.server | 异步/WebSocket/OpenAPI 原生，http.server 保留为 `--legacy` |
| 追踪 | OTel 可选桥接 | vs 自研全量 | 与标准兼容，opt-in 无侵入 |

**后果**：Conversation history 不再丢失；FastAPI 引入 uvicorn 依赖（可选 extras）；OTel 需额外安装。

### v0.10.0 — ModelRouter 接线 + KB 注入

ModelRouter 在 v0.9.0 已定义但无消费者（`AgentRunner`/`StepExecutor` 未接）。本阶段将 ModelRouter 注入运行时各组件，同时将 KnowledgeBase 上下文引入 `agent ask` 直接对话路径。

**决策**：AgentRunner + WorkflowEngine/StepExecutor 构造函数接受 `model_router` 参数；KB 初始化提前到 `AgentRuntime.initialize()` 开头。

### v0.11.0 — 统一数据访问层 + 架构清理

| 决策 | 说明 |
|------|------|
| 20 条裸 SQL → crud.py | 所有 DB 访问归一化到 `crud.py`，消除 6 个文件的直连 |
| RetryPolicy 提取 | `step_executor.py` 345→180 行，重试逻辑独立可测试 |
| ContextBuilder 提取 | 模板上下文装配逻辑从 step_executor 解耦 |
| per-tenant RuntimeFactory | dict + Lock 模式，支持多租户独立运行时 |
| 删除 3 个废弃 shim | `database.py`、`orchestrator.py`、`cli.py`（纯 re-export） |

### v0.12.0 — Vue 3 SPA 控制台 + WebSocket + Billing

前端从零进入：选择 **Vue 3 + Vite + Pinia**（非 React）——与 Hermes WebUI 技术栈一致，降低团队认知负担。

**决策对照**：

| 维度 | Vue 3 | React |
|------|-------|-------|
| 与 Hermes WebUI 一致性 | 一致 | 不同 |
| 打包体积 | ~40KB gzip | ~45KB gzip |
| 学习曲线 | 较低（模板语法） | 中等（JSX + hooks） |

**新增系统**：Billing 基础框架、QuotaManager 配额管理、Webhook 回调系统、WebSocket 实时事件流。

### v0.13.0 — 技能市场 + RBAC + K8s 部署

| 决策 | 说明 |
|------|------|
| 技能市场 | `skill_market` 表 + 上架/安装/下架 API + CLI |
| RBAC 三角色 | admin/operator/viewer，全部 API 端点鉴权（~20 路由） |
| K8s 优先部署 | Helm Chart（deployment/service/HPA/configmap/PVC）替代裸 Docker |

**RBAC 架构**：`X-Role` header → `require_permission()` FastAPI dependency。三角色层级覆盖，operator 可管理 Agent 但不可访问计费配置。

### v0.14.0 — 安全审计 + PostgreSQL/Chroma 支持

**安全审计 43 项全通**：覆盖 12 类安全缺口——多语言注入、Unicode 混淆、管道链逃逸、路径遍历、环境变量泄漏、敏感数据脱敏等。

**存储扩展决策**：

| 存储 | 方案 | 与 SQLite 关系 |
|------|------|---------------|
| PostgreSQL | 可选后端，`sccsos[postgres]` extras | schema 自动适配 |
| Chroma | 可选向量存储，`sccsos[chroma]` extras | 替代内置 TF-IDF |

**策略**：保持 SQLite 为默认零依赖后端，PostgreSQL/Chroma 通过抽象层可插拔。

### v0.14.1 — Billing 三层计费 + Kafka EventBus + 企业级技能审批

| 系统 | 决策 | 说明 |
|------|------|------|
| Billing | pay_per_token / per_call / subscription 三层 | SubscriptionManager CRUD + API |
| EventBus | KafkaEventBus（kafka-python）| retry + 本地 fallback + consumer 模式 |
| 技能审批 | review_comments + review_history + version_diff | 线程评论、版本对比、draft 状态 |
| 可观测性 | Grafana 大盘模板（10 panels）| 导入即用 |
| CI/CD | GitHub Release 自动构建 | wheel + sdist + CHANGELOG 提取 |
| 故障测试 | 26 场景×4 层 | DB 并发/Supervisor/EventBus/线程泄漏 |

**Kafka 权衡**：选择 Kafka 而非 RabbitMQ — SCCS OS 的事件量级（~100/s）两者均可胜任，但 Kafka 的日志持久化和消费者组模型更匹配多实例事件回放场景。

### v0.14.2 — 技能评分 + 架构审计 + 社区基建 + Hermes 集成 + 角色包

| 决策 | 说明 |
|------|------|
| 技能评分 1-5 星 | `skill_ratings` 表（INSERT OR REPLACE）+ 聚合统计 + InstallCount |
| 故障自愈 26 场景 | DBR/W1-R1 测试分类，`@pytest.mark.slow` 标记 |
| CONTRIBUTING.md | 12 章开发者指南 |
| Issue 模板 ×3 | Bug/Feature/Question |
| 架构审计 P0+P1 | PolicyEngine CRITICAL 日志、ThreadPoolExecutor、Config deprecation |
| Hermes 7 安装模式 | pip/git-installer/Docker 等自动探测，`HermesManager.discover()` |
| HERMES_HOME/CODE_PATH | 三源优先级（env > config > default），多租户 HERMES_HOME 隔离 |
| 角色包机制 | 4 角色 (architect/doc-writer/code-reviewer/strategist) 一键安装 |
| CLI role 命令 | `sccsos role list/info/install` + `sccsos init --role` 集成 |
| DockerHermesAdapter | `docker exec` 适配器，支持 cancel/retry/timeout |
| 性能基线报告 | Locust 50u(98%)/100u(96.1%)/250u(92.9%)/500u(24.7%)，SQLite 写锁瓶颈确认 |
| 稳定性看门狗 | `tests/scripts/stability_watchdog.py` 72h 长期运行监控 |

**架构审计发现**（7 域验证）：

| 严重度 | 数量 | 示例 |
|--------|:----:|------|
| Critical | 2 | PolicyEngine 异常被 bare except 静默吞掉、AgentRuntime 初始化日志未走 JSON logger |
| Major | 5 | 线程管理未统一（混用 bare Thread 和 ThreadPool）、Config 弃用路径无告警 |
| Minor | 6 | 测试统计过时、Mermaid 图中已删除文件路径 |

---

## 三、整体架构演进时间线

```
v0.8.1                     基础就绪
  │
v0.9.0  ─── Session 持久化 + ModelRouter + FastAPI（P1+P2）
  │
v0.10.0 ─── ModelRouter 接线 + KB ask 注入（P0 修复）
  │
v0.11.0 ─── CRUD 统一 + RetryPolicy/ContextBuilder 提取（P0+P1）
  │
v0.12.0 ─── Vue 3 SPA + WebSocket + Billing/Quota（新能力）
  │
v0.13.0 ─── 技能市场 + RBAC + K8s 部署（企业级）
  │
v0.14.0 ─── 安全审计全通 + PostgreSQL/Chroma（生产准备）
  │
v0.14.1 ─── Billing 三层 + Kafka + 企业审批 + CI/CD（商业化）
  │
v0.14.2 ─── 技能评分 + 架构审计 + 社区基建（质量闭环）
```

---

## 四、关键架构指标演化

| 指标 | v0.9.0 | v0.14.2 |
|------|:------:|:--------:|
| 代码量 (LoC) | ~7,200 | ~15,800 |
| 测试用例 | 312 | 994 |
| 测试文件 | ~18 | 52 |
| API 端点 | ~12 | 29+ |
| 前端页面 | 0 | 7 |
| 部署方式 | Docker | Docker + Helm/K8s |
| 存储后端 | SQLite 仅 | SQLite + PostgreSQL + Chroma |
| 消息总线 | 无 | LocalEventBus + Kafka |
| 健康评分 | ~7.5 | 9.0/10 |
| 安全审计覆盖 | 无 | 43 项审计全通过 |
| Hermes 安装模式 | 仅 Docker | 7 种自动探测 |
| 角色包 | 无 | 4 角色一键安装 |
| 性能基线 | 无 | Locust 50u~500u 报告 |

---

## 五、关键权衡总结

| 权衡 | 选择 | 代价 |
|------|------|------|
| SQLite 优先 vs 分布式 DB | SQLite 优先 + PostgreSQL 可插拔 | 多 worker 场景有锁竞争 |
| Vue 3 vs React | Vue 3（与 Hermes WebUI 一致） | React 生态更广 |
| Kafka vs RabbitMQ | Kafka | 运维复杂度更高 |
| 内置 TFD-IF vs Chroma | TF-IDF 默认 + Chroma 可选 | Chroma 需安装 |
| 单 Worker vs 多 Worker | 多 Worker（4） | 内存增加 ~4× |
| 安全内建 vs 后加 | 内建（43 项审计） | 开发速度略降 |
