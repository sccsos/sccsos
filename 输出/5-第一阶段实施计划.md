# SCCS OS Phase 1 实施计划

> 核心框架搭建 | 预估工期: 7-10 天 | 状态: 待启动

---

## 1. Phase 1 目标

**交付**: 可通过 CLI 注册 Agent → 启动 → 查看状态 → 停止 的 Agent Runtime 最小闭环。

### 验收标准

```
[ ] sccsos init             → 生成 sccsos.yaml + 目录结构
[ ] sccsos agent create     → 创建 agents/*.yaml 示例
[ ] sccsos agent list       → 列出已注册 Agent
[ ] sccsos agent start      → 启动 Agent（通过 Hermes profile）
[ ] sccsos agent stop       → 停止 Agent
[ ] sccsos agent status     → 查询 Agent 状态
[ ] sccsos agent logs       → 查看 Agent 日志
[ ] 生命周期状态转换正确      → CREATED→RUNNING→PAUSED→TERMINATED
[ ] 数据持久化正常            → SQLite 读写正确
[ ] Hermes 适配器通          → 成功调用 delegate_task
```

---

## 2. 任务分解

### Step 1: 项目初始化和骨架（1 天）

| # | 任务 | 文件 | 依赖 |
|---|------|------|------|
| 1.1 | 创建 `pyproject.toml`，声明依赖 | `pyproject.toml` | — |
| 1.2 | 创建 `sccsos.yaml` 默认配置 | `sccsos.yaml` | — |
| 1.3 | 实现 CLI 入口 `cli.py`：`click` 命令组 | `sccsos/cli.py` | — |
| 1.4 | 实现 `sccsos init` 命令 | `sccsos/cli.py` | 1.2 |
| 1.5 | 实现基础配置加载器 | `sccsos/core/config.py` | 1.2 |

**交付**: `sccsos init` 可初始化一个空项目

### Step 2: Agent Registry（1.5 天）

| # | 任务 | 文件 | 依赖 |
|---|------|------|------|
| 2.1 | 定义 `AgentSpec` 数据类 | `sccsos/core/registry.py` | — |
| 2.2 | 实现 YAML 加载和验证 | `sccsos/core/registry.py` | 2.1 |
| 2.3 | 实现 Registry：register/list/get/find | `sccsos/core/registry.py` | 2.2 |
| 2.4 | 创建示例 Agent 定义 YAML | `agents/architect.yaml` | 2.1 |
| 2.5 | 实现 `sccsos agent create/list` CLI | `sccsos/cli.py` | 2.3 |

**交付**: 可通过 CLI 注册和查询 Agent 定义

### Step 3: 数据库层（1 天）

| # | 任务 | 文件 | 依赖 |
|---|------|------|------|
| 3.1 | 创建数据库初始化 + Schema DDL | `sccsos/core/database.py` | — |
| 3.2 | 实现 `Database` 上下文管理器 | `sccsos/core/database.py` | 3.1 |
| 3.3 | 实现 CRUD：agents/agent_events 表 | `sccsos/core/database.py` | 3.2 |
| 3.4 | 集成到 `sccsos init` | `sccsos/cli.py` | 3.3 |

**交付**: Agent 实例数据可持久化到 SQLite

### Step 4: Lifecycle Manager（2 天）

| # | 任务 | 文件 | 依赖 |
|---|------|------|------|
| 4.1 | 定义 `AgentStatus` 枚举 + 状态转换矩阵 | `sccsos/core/lifecycle.py` | 3.3 |
| 4.2 | 实现 `LifecycleManager` 核心逻辑 | `sccsos/core/lifecycle.py` | 4.1 |
| 4.3 | 状态转换的持久化和恢复 | `sccsos/core/lifecycle.py` | 4.2 + 3.3 |
| 4.4 | 实现 `sccsos start/stop/status` CLI | `sccsos/cli.py` | 4.2 |

**交付**: Agent 可以启动（状态写入 DB）和停止

### Step 5: Hermes 适配器（2 天）⚠️ 关键路径

| # | 任务 | 文件 | 依赖 |
|---|------|------|------|
| 5.1 | 定义 `HermesAdapter` 抽象基类（ABC） | `sccsos/core/hermes_adapter.py` | — |
| 5.2 | 实现生产适配器：profile 切换、session 管理 | `sccsos/core/hermes_adapter.py` | 5.1 |
| 5.3 | 实现 `delegate_task` 调用 | `sccsos/core/hermes_adapter.py` | 5.2 |
| 5.4 | 实现 Mock 适配器用于测试 | `tests/test_hermes_adapter.py` | 5.1 |
| 5.5 | 集成 LifecycleManager → HermesAdapter | `sccsos/core/lifecycle.py` | 5.2 + 4.3 |

**交付**: `sccsos start` 真正启动 Hermes Agent 会话

### Step 6: 日志与健康检查（1 天）

| # | 任务 | 文件 | 依赖 |
|---|------|------|------|
| 6.1 | 实现结构化日志 | `sccsos/observability/logger.py` | — |
| 6.2 | 集成事件记录到 agent_events | `sccsos/core/lifecycle.py` | 6.1 |
| 6.3 | 实现 `sccsos agent logs` CLI | `sccsos/cli.py` | 6.2 |
| 6.4 | 实现 `sccsos health` 检查命令 | `sccsos/cli.py` | 5.3 + 3.3 |

**交付**: Agent 操作有日志可查，系统健康可检查

### Step 7: 集成测试和文档（0.5 天）

| # | 任务 | 文件 | 依赖 |
|---|------|------|------|
| 7.1 | Phase 1 端到端测试 | `tests/test_phase1_e2e.py` | Step 1-6 |
| 7.2 | 更新 AGENTS.md 为 Phase 1 完成状态 | `AGENTS.md` | 7.1 |
| 7.3 | 编写快速上手指南 | `docs/quickstart.md` | 7.1 |

**交付**: 完整的 Phase 1 交付物

---


![Workflow 执行时序图](images/sccsos-workflow-sequence-light.png)

*图 1: Workflow 执行时序图 — DAG 构建、顺序执行、并行并发、结果聚合全流程*

## 3. 依赖关系图

```
Step 1 (项目骨架)
    │
    ▼
Step 2 (Registry) ──→ Step 3 (数据库)
    │                       │
    └───────────┬───────────┘
                ▼
          Step 4 (Lifecycle)
                │
                ▼
          Step 5 (Hermes适配器) ⚠️ 关键路径
                │
                ▼
          Step 6 (日志+健康检查)
                │
                ▼
          Step 7 (集成测试+文档)
```

---

## 4. 文件创建顺序

| 顺序 | 文件 | 代码行数(估) |
|------|------|-------------|
| 1 | `pyproject.toml` | 15 |
| 2 | `sccsos/core/__init__.py` | 2 |
| 3 | `sccsos/core/config.py` | 30 |
| 4 | `sccsos/core/registry.py` | 120 |
| 5 | `sccsos/core/database.py` | 100 |
| 6 | `sccsos/core/lifecycle.py` | 150 |
| 7 | `sccsos/core/hermes_adapter.py` | 100 |
| 8 | `sccsos/observability/logger.py` | 50 |
| 9 | `sccsos/cli.py` | 180 |
| 10 | `sccsos.yaml` | 25 |
| 11 | `agents/architect.yaml` | 15 |
| 12 | `tests/test_phase1_e2e.py` | 80 |
| 13 | `docs/quickstart.md` | 50 |

**代码总量预估**: ~900 行 Python

---

## 5. 关键交付物清单

### 新文件（Phase 1 需创建）

```
sccsos/
├── pyproject.toml
├── sccsos.yaml
├── sccsos/
│   ├── __init__.py
│   ├── cli.py                       ← CLI 入口
│   ├── core/
│   │   ├── __init__.py
│   │   ├── config.py                ← 配置加载
│   │   ├── registry.py              ← Agent 注册表
│   │   ├── database.py              ← SQLite 封装
│   │   ├── lifecycle.py             ← 生命周期状态机
│   │   └── hermes_adapter.py        ← Hermes API 桥接
│   ├── observability/
│   │   ├── __init__.py
│   │   └── logger.py                ← 结构化日志
│   └── agents/
│       └── architect.yaml           ← 示例 Agent 定义
├── tests/
│   └── test_phase1_e2e.py           ← 端到端测试
└── docs/
    └── quickstart.md                ← 快速上手指南
```

---

## 6. 风险与缓冲

| 风险 | 影响 | 缓冲策略 |
|------|------|---------|
| Hermes API 接口变化 | Step 5 延期 | 预留 1 天缓冲 |
| SQLite 并发行问题 | Step 3 修整 | WAL 模式默认开启 |
| CLI 设计反复 | Step 1 延期 | 先实现最小命令集 |
| 文档编写 | 不影响代码路径 | 最后一天集中完成 |

**总工期**: 7-10 天（含 2 天缓冲）

---

## 7. 下一步行动

### 立即开始（Step 1）

```
1. pyproject.toml          → 依赖声明
2. sccsos/core/config.py  → 配置加载器
3. sccsos/cli.py          → click 命令组 + `sccsos init`
```

准备好了告诉我，我们从 Step 1 开始编码。
