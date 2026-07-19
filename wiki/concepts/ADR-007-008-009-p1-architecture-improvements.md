# ADR-007: EventBus 事件总线

## 上下文

WorkflowEngine 直接耦合 6 个观察者：
Tracer、Auditor、WebhookNotifier、AlertManager、Logger、Policy。
新增"执行完毕后发通知"需要改核心代码。

## 方案

```python
# core/event_bus.py — 轻量 pub/sub，零外部依赖
bus = EventBus.get_instance()
bus.on("workflow.completed", webhook_handler)
bus.emit("workflow.completed", run_id="wf_xyz", status="completed")
```

- 单例模式（进程级共享）
- 每个 handler 在 try/except 中运行，单个失败不阻塞其他
- 事件名称常量：`WORKFLOW_STARTED` / `COMPLETED` / `FAILED`
- `STEP_STARTED` / `COMPLETED` / `FAILED` / `SKIPPED`

## 效果

- WorkflowEngine 减 ~50 行（移除 WebhookNotifier + AlertManager 创建调用）
- 新增观察者只需注册 handler，无需改 WorkflowEngine
- 测试可 mock EventBus 或直接验证 emit 参数

---

# ADR-008: Supervisor 监督模式

## 上下文

AgentProcess 是裸 `threading.Thread`：
- 无心跳检测，线程死锁后静默消失
- 无自动重启
- 无健康状态查询

## 方案

```python
# core/supervisor.py
supervisor = Supervisor(max_restarts=3, heartbeat_timeout=30.0, check_interval=5.0)
supervisor.register("architect", process)
supervisor.start()
```

- AgentProcess 每次循环调用 `heartbeat_callback(self.name)`
- Supervisor 后台线程每 5s 检查所有进程
- 故障检测：死进程 → 自动重启（最多 3 次）；无响应 → 警告
- 暂停的进程不触发重启

## 效果

- AgentProcess 加入 `heartbeat_callback` 参数（可选，不破坏现有构造）
- AgentRunner 自动注册/注销 Supervisor
- 生产可靠性提升：进程崩溃后 < 5s 自动恢复

---

# ADR-009: Config 自动映射

## 上下文

`_from_dict()` 使用 ~60 行 if/elif 手写映射。
新增配置字段需改 3 处（dataclass + `_from_dict` + 文档）。

## 方案

```python
def _auto_merge(target, data):
    for fname, fdef in target.__dataclass_fields__.items():
        if fname not in data: continue
        current = getattr(target, fname, None)
        if isinstance(data[fname], dict) and hasattr(current, '__dataclass_fields__'):
            _auto_merge(current, data[fname])  # 递归嵌套
        else:
            setattr(target, fname, data[fname])  # 直接赋值
```

- 使用运行时对象判断（而非类型注解），兼容 `from __future__ import annotations`
- 特殊处理保留：`PoliciesConfig.from_dict()`、`WebhooksConfig.from_dict()`
- 遗留兼容：`tracing.pricing_path` → `pricing.path` 自动回退

## 效果

- `_from_dict` 从 60 行降至 20 行（含注释）
- 新增配置字段只需定义 dataclass 字段 → 零映射代码
- `_auto_merge` 通用函数可复用于其他 dataclass 反序列化场景
