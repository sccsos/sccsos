# ADR-011：Session 持久化 + ModelRouter + FastAPI 渐进迁移

- **日期**: 2026-07-26
- **状态**: 已接受
- **版本关联**: v0.9.0

## 背景

v0.8.1 发布后，项目面临三个架构缺口：会话状态丢失、模型选择无统一路由、HTTP 服务器性能瓶颈。

## 方案对比

### 1. Session 持久化

| 方案 | 优点 | 缺点 |
|------|------|------|
| SQLite 表持久化 | 零依赖、与现有 DB 层一致 | 无分布式支持 |
| Redis 外部存储 | 分布式就绪 | 引入外部依赖、运维成本 |

**决策**: SQLite 表持久化（agent_sessions + session_messages），PAUSED 保存上下文。

### 2. ModelRouter

| 方案 | 优点 | 缺点 |
|------|------|------|
| YAML 配置池 + 任务感知选择 | 灵活、无外部依赖 | 需要手动维护模型列表 |
| 固定模型配置 | 极简 | 无法按任务优化 |

**决策**: YAML 配置池 + 任务感知选择 + fallback 链。

### 3. HTTP Server

| 方案 | 优点 | 缺点 |
|------|------|------|
| FastAPI （推荐）| 异步、WebSocket 原生、OpenAPI 自动生成 | 需要安装 uvicorn |
| http.server 继续维护 | 零依赖 | 性能瓶颈、无 WS |

**决策**: FastAPI 为主入口，http.server 保留为 `--legacy` 选项。

## 后果

- 正面：Conversation history 不再丢失、模型可自动按任务选择、API 性能提升、WebSocket 实时事件就绪
- 负面：Session DB 写入增加存储开销（~2KB 每次 ask）、FastAPI 引入 uvicorn 依赖（可选 extras）
