# ADR-004: SCCS OS v0.7.0 架构重构

**日期**: 2026-07-20  
**状态**: 已实施  
**版块**: architecture

## 背景

v0.6.4 架构审计（资源栈互审）发现以下关键问题：
- C1: PAUSED 状态空心（只改 DB 不停 runner 线程）
- C2: agent ask 直通路径跳过 MemoryStore
- M4/M5: WorkflowEngine.execute() 非线程安全
- N1: DB 操作模式不一致
- M1: API 注册不创建 Lifecycle 实例

## 变更摘要

### P0 — 紧急修复

1. **AgentRunner pause/resume** (`agent_runner.py`, `cli.py`)
   - AgentProcess 添加 `_paused` Event
   - pause 时 ask() 立即返回错误，_run_loop 丢弃队列任务
   - CLI pause/resume 同步停启 runner 线程
   - C1 完全修复

2. **agent ask 接入 MemoryStore** (`agent_runner.py`, `agent_runtime.py`)
   - AgentProcess 接受 `memory_store` 参数
   - _run_loop 中 delegate_task 前注入 `{{ memory }}` 上下文
   - AgentRuntime 初始化顺序调整（MemoryStore 创建移至 Runner 之前）
   - C2 完全修复

### P1 — 架构改进

3. **WorkflowEngine 线程安全化** (`orchestrator.py`)
   - `WorkflowRunContext` dataclass — 封装 per-run 状态
   - `self._run_contexts[run_id]` 字典管理，execute() 创建独立上下文
   - `cancel_run()` 通过 run_id 查找对应 cancel_event
   - M4/M5 完全修复

4. **统一 DB 操作模式** (`database.py`, `orchestrator.py`, `step_executor.py`)
   - 新增 `fetchone()` / `fetchall()` 便捷方法
   - 13 处 `get_conn().execute()` → `db.execute()` 迁移
   - N1 完全修复

5. **API 状态守卫 + 注册改进** (`api/server.py`)
   - pause/resume/restart/stop 按 `AgentStatus` 匹配实例
   - register 自动创建 Lifecycle 实例
   - M1 完全修复

### P2 — 功能扩展

6. **MemoryStore 主动过期清理** → `purge_expired()` 方法
7. **配置一致性检查** → AgentRuntime._check_config() 校验 pricing_path
8. **get_run_status 多租户隔离** → 可选 tenant_id 参数
9. **StepExecutor 模板渲染器注入** → 可选的 template_engine 参数
10. **AgentProcess 响应 cancel_event** → _run_loop 检查并排空队列

## 健康评分变化

| 域 | v0.6.4 | v0.7.0 | 变化 |
|----|:------:|:------:|:----:|
| 多智能体编排 | 9.0 | 9.5 | +0.5（线程安全 WorkflowRunContext） |
| 工具增强型 LLM | 8.0 | 8.0 | — |
| Agent 状态管理 | 6.5 | 8.5 | +2.0（MemoryStore 接线 agent ask + PAUSED 真实化） |
| Agent 生命周期 | 8.0 | 9.0 | +1.0（PAUSED 语义完备 + API 状态守卫） |
| 可观测性 | 8.5 | 8.5 | — |
| 安全沙箱 | 7.5 | 7.5 | — |
| 提示工程 | 7.5 | 8.0 | +0.5（模板引擎可注入） |
| **综合** | **8.0/10** | **8.5/10** | **+0.5** |

## 技术债务剩余

- 文件系统隔离沙箱
- 网络出口限制
- OpenTelemetry 集成
- 真实 token 计数（非估算）
- 多 SQLite 副本/PostgreSQL
- Prompt 版本管理与 A/B 测试

## 相关文件

- `sccsos/core/agent_runner.py` — pause/resume + memory + cancel
- `sccsos/core/orchestrator.py` — WorkflowRunContext
- `sccsos/core/agent_runtime.py` — 重排 init 顺序 + _check_config
- `sccsos/core/step_executor.py` — template_engine 注入
- `sccsos/core/database.py` — fetchone/fetchall
- `sccsos/api/server.py` — AgentStatus 守卫 + lifecycle.create
- `sccsos/memory/memory_store.py` — purge_expired
