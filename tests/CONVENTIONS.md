# SCCS OS 测试约定

> 保障测试隔离性、可重复性和 CI 兼容性。
>
> **当前基线**: 52 测试文件 · 994 测试函数 · 176 测试类 · 71% 覆盖率 · ~59s 全量运行

## 核心原则

1. **测试之间互不依赖** — 任何测试可以独立运行，运行顺序不影响结果
2. **外部服务可选** — PG/Chroma/Kafka 集成测试必须用 `skipif` 跳过不可用的后端
3. **文件锁避免** — 模块级 fixture 使用独立临时数据库，不共享默认 `./data/sccsos.db`
4. **砂箱引号感知** — `CommandWhitelist.check()` 在检查模式前剥离 Shell 引号内容，避免引号内字面操作符误拦截

---

## SQLite 文件锁隔离规则

当多个测试模块使用 module-scoped fixture 创建 `AgentRuntime` 时，**必须使用独立的临时数据库**，避免 `sqlite3.OperationalError: database is locked`。

### ✅ 正确做法

```python
import tempfile
from pathlib import Path
from sccsos.core.config import AgentOSConfig, DatabaseConfig
from sccsos.core.agent_runtime import AgentRuntime, reset_runtime, set_runtime

@pytest.fixture(scope="module")
def client():
    reset_runtime()

    # 唯一临时数据库
    tmp_dir = Path(tempfile.mkdtemp(prefix="sccsos_test_"))
    cfg = AgentOSConfig(database=DatabaseConfig(path=str(tmp_dir / "test.db")))

    runtime = AgentRuntime(config=cfg)
    runtime.initialize()
    set_runtime(runtime)  # 注入全局，使 create_app() 可见

    yield something

    runtime.close()
```

### ❌ 错误做法（共享默认 DB 文件）

```python
# 不要这样做：与其他模块共享 ./data/sccsos.db
runtime = AgentRuntime()
runtime.initialize()
```

---

## 集成测试跳过规则

所有依赖外部服务的测试必须用模块级 `pytestmark` 实现自动跳过：

| 后端 | 文件 | skipif 条件 |
|------|------|-------------|
| PostgreSQL | `test_postgres_integration.py` | `psycopg2` 不可用 / PG 无响应 |
| ChromaDB | `test_chroma_integration.py` | `chromadb` 不可 import |
| Kafka | `test_event_bus_kafka_integration.py` | `kafka-python` 不可用 / broker 无响应 |

### 模板

```python
def _backend_available() -> bool:
    try:
        # ... 连接测试 ...
        return True
    except Exception:
        return False

pytestmark = pytest.mark.skipif(
    not _backend_available(),
    reason="backend not available",
)
```

---

## 测试文件命名规范

| 类型 | 命名模式 | 说明 |
|------|---------|------|
| 单元测试 | `test_*.py` | 无外部依赖，始终执行 |
| 集成测试 | `test_*_integration.py` | 依赖外部服务，有 skipif |
| Postgres 测试 | `test_postgres_*.py` / `test_postgres_integration.py` | 前者无外部 PG（mock），后者需要 PG |

---

## CLI 运行命令

```bash
# 全量测试（含集成测试，自动跳过不可用后端）
python3 -m pytest tests/ -q

# 仅单元测试（跳过所有集成测试）
python3 -m pytest tests/ \
  --ignore=tests/test_postgres_integration.py \
  --ignore=tests/test_chroma_integration.py \
  --ignore=tests/test_event_bus_kafka_integration.py \
  -q

# 带覆盖率
python3 -m pytest tests/ -q --no-header

# 指定文件
python3 -m pytest tests/test_skill_review_api.py -v
```

> 注意：`pyproject.toml` 中已配置 `addopts="--cov=sccsos --cov-report=term-missing --cov-fail-under=70"`，运行 `pytest` 时默认启用覆盖率。
