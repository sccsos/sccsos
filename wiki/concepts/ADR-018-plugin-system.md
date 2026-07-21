# ADR-018：Plugin 插件系统

- **日期**: 2026-07-26
- **状态**: 已接受
- **版本关联**: v0.14.0
- **前置 ADR**: ADR-004（架构框架）

---

## 一、背景

SCCS OS 已有 EventBus 事件通知和 Webhook 回调，但二者都需要在核心代码中硬编码事件类型和回调函数。需要一个标准化扩展机制，允许第三方开发者在不修改核心库的前提下插入自定义行为。

## 二、决策

### 2.1 PluginBase + @hook 装饰器

```python
class PluginBase(ABC):
    @property
    @abstractmethod
    def name(self) -> str: ...

    @property
    @abstractmethod
    def version(self) -> str: ...

    def on_load(self) -> None: ...    # 可选生命周期
    def on_unload(self) -> None: ...

def hook(func):
    func._is_plugin_hook = True
    return func
```

### 2.2 9 个内置钩子

| 钩子 | 触发时机 | 参数 |
|------|---------|------|
| `on_agent_start` | Agent 启动 | `agent_name` |
| `on_agent_stop` | Agent 停止 | `agent_name` |
| `on_workflow_start` | 工作流开始 | `run_id` |
| `on_workflow_complete` | 工作流完成 | `run_id` |
| `on_workflow_fail` | 工作流失败 | `run_id, error` |
| `on_api_request` | API 请求前 | `method, path` |
| `on_api_response` | API 响应后 | `method, path, status` |
| `on_tool_call` | 工具调用前 | `agent_name, tool` |
| `on_shutdown` | 系统关闭 | (无) |

### 2.3 PluginRegistry

```python
registry = get_registry()
registry.register(MyPlugin())
count = registry.discover_from_path("config/plugins/")
```

- `dispatch(hook_name, **kwargs)` — 遍历所有插件，单个失败不影响其他
- 文件发现扫描目录下的 `.py` 文件，自动实例化 PluginBase 子类
- 重复注册同名插件抛出 ValueError

### 2.4 CLI 命令

```bash
sccsos plugin list   # 查看已注册插件
sccsos plugin info   # 查看插件详情
```

## 三、权衡

| 选项 | 优势 | 劣势 |
|------|------|------|
| **PluginBase ABC**（采纳） | 类型安全，IDE 友好 | 需安装额外包 |
| 动态 Monkey-Patch（否决） | 灵活 | 不可追踪，调试困难 |

## 四、后果

- 插件钩子隔离执行（try/except 包裹每个钩子）
- `unittest.mock` 风格的测试
- 插件系统零依赖（纯 Python 标准库）
