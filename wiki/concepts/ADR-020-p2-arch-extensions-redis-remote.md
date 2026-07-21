# ADR-020：P2 架构扩展 — Redis PubSub 桥接 + RemoteHermesAdapter

- **日期**: 2026-07-26
- **状态**: 已接受
- **版本关联**: v0.15.0
- **前置 ADR**: ADR-015（多安装模式），ADR-016（Kafka EventBus）

---

## 一、背景

SCCS OS v0.14.2 完成 Phase 3 核心功能后，进入「架构扩展」阶段。两个关键缺口：

1. **多进程 WebSocket**：`uvicorn --workers N` 下，每个 worker 进程有独立的 `connected_clients` 集合和 `LocalEventBus` 实例。Worker-1 的 WS 客户端收不到 Worker-2 发出的事件。
2. **分布式 Hermes 节点**：中心管控节点需向远程 Hermes Agent 节点委派任务，当前仅支持本地 subprocess 和 Docker exec 两种模式。

## 二、决策

### 2.1 Redis PubSub 桥接

```
Worker-1                          Worker-2
┌─────────────────┐              ┌─────────────────┐
│ EventBus        │              │ EventBus        │
│   └→ RedisPub   │───Redis────▶│   ┌→ subscribers │
│   ┌← RedisSub   │◀──channel───│   └← RedisPub    │
└─────────────────┘              └─────────────────┘
```

**核心设计**：

```python
class RedisPubSubBridge:
    def wire_publish(self, local_bus):
        # 在 LocalEventBus 上注册 catch-all handler → Redis PUBLISH
        ...

    def start_subscriber(self, local_bus):
        # 后台线程订阅 Redis channel → local_bus.emit()
        ...
```

**防无限循环**：每条 Redis 消息携带 `_source_worker` 字段，同 worker 事件跳过。

**降级策略**：Redis 不可用 → 仅日志 Warning → WS 广播降级为单进程模式。

**配置**：

```yaml
redis:
  url: redis://localhost:6379/0
  channel: sccsos:events
  enabled: false    # 默认关闭，仅多 worker 部署时开启
```

### 2.2 RemoteHermesAdapter

```python
class RemoteHermesAdapter(HermesAdapter):
    def delegate_task(self, agent_name, prompt, ...):
        # HTTP POST → remote proxy → TaskResult
        resp = httpx.post(f"{url}/api/v1/delegate", json=payload)
```

**API 契约**（远程 proxy 需实现）：

```
POST /api/v1/delegate
Authorization: Bearer <token>
Body: { "agent_name": "...", "prompt": "...", "profile": "...", "model": "..." }
Response: { "response": "...", "duration_ms": 1234, "tokens_input": ..., ... }
```

**安全**：PolicyEngine 预检（与 subprocess 模式相同逻辑）+ Bearer Token 认证。

**配置**：

```yaml
hermes:
  adapter: remote
  remote:
    url: http://hermes-node:8080
    token: my-secret-token
    timeout: 60
```

### 2.3 可选依赖

| 分组 | 依赖 | 用途 |
|------|------|------|
| `sccsos[redis]` | redis>=5.0 | Redis PubSub 桥接 |
| `sccsos[remote]` | httpx>=0.27 | 远程 Hermes HTTP 调用 |

## 三、权衡

| 选项 | 优势 | 劣势 |
|------|------|------|
| **Redis PubSub**（采纳） | 零代码侵入 EventBus，自动发现 | 需部署 Redis |
| 文件轮询（否决） | 零依赖 | 延迟高，IO 浪费 |
| **HTTP 远程代理**（采纳） | 通用，与 Hermes 无关 | 需远程 proxy 服务 |

## 四、后果

- 开启 `redis.enabled: true` 后每 worker 自动桥接
- RemoteHermesAdapter 通过 PolicyEngine 预检（与本地模式一致）
- Health 端点新增 `redis_bridge` 状态字段
- 为后续跨进程 EventBus（如 Redis Streams / NATS）保留扩展点
