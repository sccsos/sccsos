# ADR-016：Kafka EventBus + Circuit Breaker 熔断器

- **日期**: 2026-07-26
- **状态**: 已接受
- **版本关联**: v0.14.1
- **前置 ADR**: ADR-007（EventBus ABC + LocalEventBus），ADR-014

---

## 一、背景

v0.8.0 引入 `EventBusABC` 抽象和 `LocalEventBus` 进程内实现。当 SCCS OS 需要从单进程扩展到多 worker / 多节点部署时，需要分布式事件总线。Kafka 是企业级消息队列的标准选择。

## 二、决策

### 2.1 KafkaEventBus 架构

```python
class KafkaEventBus(EventBusABC):
    def __init__(self, bootstrap_servers, client_id, group_id):
        self._producer = None  # 惰性初始化
        self._handlers = {}
        self._consumer_thread = None
        self._circuit_breaker = CircuitBreaker(...)
```

**惰性连接**：producer 在首次 emit() 时创建，consumer 在 subscribe() 时启动。

### 2.2 Circuit Breaker 三态熔断器

| 状态 | 行为 | 阈值 |
|------|------|------|
| CLOSED | 正常发送 | — |
| OPEN | 快速失败（抛 CircuitBreakerOpenError） | 连续 5 次失败 |
| HALF_OPEN | 探针恢复（成功 3 次 → CLOSED，失败 → OPEN） | 恢复超时 30s |

```python
cb = CircuitBreaker(failure_threshold=5, recovery_timeout=30.0, half_open_max_requests=3)
```

**线程安全**：所有状态变更使用 `threading.Lock()`，`time.monotonic()` 计时。

### 2.3 优雅降级策略

```python
try:
    prod = self.producer
    future = prod.send(topic, value=data)
    future.get(timeout=5)
except CircuitBreakerOpenError:
    logger.debug("Skipping Kafka — circuit open")
    # 降级为 local-only 模式
except Exception as e:
    logger.warning("Kafka publish failed: %s", e)
```

### 2.4 健康检查

```python
def health_check(self) -> dict:
    return {
        "status": "ok|degraded",
        "circuit_state": "closed|open|half_open",
        "partitions": [...],
    }
```

## 三、权衡

| 选项 | 优势 | 劣势 |
|------|------|------|
| **Kafka**（采纳） | 生产标准，吞吐量高 | 需额外部署 Kafka 集群 |
| RabbitMQ（考虑） | 轻量 | 与 EventBus 语义匹配度低 |
| Redis PubSub（v0.15） | 零依赖 | 不支持持久化 |

**为什么不直接用 LocalEventBus 跨进程**：LocalEventBus 的 handler 列表是进程内的，emit() 只在同一进程内触发。

## 四、后果

- Kafka 为可选依赖：`sccsos[kafka]`
- 无 Kafka 时自动回退到 LocalEventBus
- Circuit Breaker 不保护已有 producer 连接（只保护新连接创建）
- 新增 `configure_event_bus(backend="kafka")` 入口
