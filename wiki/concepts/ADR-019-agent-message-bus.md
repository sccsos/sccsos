# ADR-019：AgentMessageBus — 跨实例 Agent 通信

- **日期**: 2026-07-26
- **状态**: 已接受
- **版本关联**: v0.14.1
- **前置 ADR**: ADR-016（Kafka EventBus）

---

## 一、背景

EventBus 处理「系统级事件」（工作流完成、Agent 生命周期变更）。多 Agent 协作需要「Agent-to-Agent 消息通信」——指定目标 Agent、请求-响应语义、消息持久化。

## 二、决策

### 2.1 AgentMessage 数据模型

```python
@dataclass
class AgentMessage:
    msg_id: str
    from_agent: str
    to_agent: str              # 目标 Agent 或 __broadcast__
    msg_type: MessageType      # request / response / broadcast
    payload: dict
    timestamp: str
    correlation_id: str        # 请求-响应配对
```

### 2.2 消息总线 API

```python
bus = AgentMessageBus("agent-architect", db)
bus.connect()                            # 注册 EventBus 回调
bus.on_message(lambda msg: ...)          # 所有消息
bus.on_type(MessageType.REQUEST, cb)     # 仅特定类型

bus.send("agent-reviewer", {"doc_id": "42"})
bus.broadcast({"event": "maintenance"})
bus.respond("agent-alpha", {"status": "ok"}, correlation_id=corr_id)
```

### 2.3 持久化

所有消息自动写入 `agent_messages` 表（当传入 db 参数时）：

```sql
CREATE TABLE IF NOT EXISTS agent_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    msg_id TEXT NOT NULL UNIQUE,
    from_agent TEXT NOT NULL,
    to_agent TEXT NOT NULL,
    msg_type TEXT NOT NULL DEFAULT 'broadcast',
    payload_json TEXT NOT NULL DEFAULT '{}',
    correlation_id TEXT DEFAULT '',
    direction TEXT NOT NULL DEFAULT 'incoming',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
```

### 2.4 测试关键陷阱

```python
# ❌ 必须先 connect()
bus_b.on_message(lambda msg: ...)    # 仅本地存储，未注册 EventBus
bus_a.send("agent-beta", {"test": 1})  # 丢失！

# ✅ 正确顺序
bus_b.connect()                       # 注册 EventBus 回调
bus_b.on_message(lambda msg: ...)
bus_a.send("agent-beta", {"test": 1})  # 收到！
```

**同步语义**：LocalEventBus 的 emit() 同步调用所有 handler，因此 connect() 后 send() 的消息同步交付。

## 三、权衡

| 选项 | 优势 | 劣势 |
|------|------|------|
| **EventBus 之上构建**（采纳） | 复用已有 pub/sub 机制 | EventBus 阻塞影响消息吞吐 |
| 独立 ZeroMQ 通道（否决） | 高性能 | 额外依赖 + 运维复杂度 |

## 四、后果

- AgentMessageBus 依赖 EventBus 基础设施
- 进程内同步通信（跨进程需配合 KafkaEventBus）
- 消息自动持久化到 SQLite（进程重启可恢复）
