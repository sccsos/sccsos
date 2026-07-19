# ADR-006: SCCS OS v0.7.1 架构优化

**日期**: 2026-07-22
**状态**: 已实施
**版块**: architecture

## 背景

v0.7.0 架构审计（深度架构分析）发现以下问题：

| # | 问题 | 严重性 | 域 |
|---|------|:------:|---|
| M2 | API Server 不联动 Runner，通过 API 启动的 Agent 无法 `ask` | 🔴 P0 | Agent 生命周期 |
| M5 | `agent list` 按 id 匹配 Lifecycle，始终显示 "registered" | 🟡 P0 | Agent 生命周期 |
| M6 | `step_outputs` 多线程写无保护 | 🟡 P0 | 多智能体编排 |
| M1 | `cancel_run`/`list_runs` 无 tenant 过滤 | 🟡 P1 | 多租户隔离 |
| M3 | Pricing 配置嵌套在 TracingConfig 下，语义不当 | 🟢 P1 | 配置管理 |
| m5 | `_execute_step` 过长（~180行），上下文构建与执行逻辑粘连 | 🟢 P1 | 可维护性 |

## 变更摘要

### P0 — 功能正确性修复

#### 1. API Server 联动 Runner（M2）
**文件**: `api/server.py`

所有生命周期 API handler 补充 runner 调用：

| Handler | 新增调用 |
|---------|---------|
| `_handle_start_agent` | `runner.start_agent(name, ...)` |
| `_handle_stop_agent` | `runner.stop_agent(name)` |
| `_handle_pause_agent` | `runner.pause_agent(name)` |
| `_handle_resume_agent` | `runner.resume_agent(name)` |
| `_handle_restart_agent` | `runner.stop_agent()` + `runner.start_agent()` |

此前 CLI `agent start` 和 API `POST /agents/{name}/start` 行为不一致：CLI 启动后台 runner 线程，API 只更新 DB 状态。修正后两者行为完全一致。

#### 2. agent list 状态列修复（M5）
**文件**: `cli.py`

重构匹配逻辑：遍历 `lifecycle.list_instances()` 构建 `name → status` 映射，而非直接调 `get_instance(name)`（按 agent_id UUID 查找）。

#### 3. step_outputs 线程安全（M6）
**文件**: `step_executor.py`

跳过路径的 `step_outputs[step.id]` 写入移至 `with self._db_lock:` 块内，与成功路径保持一致的锁保护。

#### 4. 测试环境修复
**文件**: `test_api_server.py`

API 测试 fixture 改为：初始化真实 Runtime → 替换 adapter 为 MockHermesAdapter → 同步 runner 的 adapter 引用。避免在无 hermes CLI 的测试环境中 hang。

### P1 — 架构改进

#### 5. cancel_run / list_runs 多租户过滤（M1）
**文件**: `orchestrator.py`

- `cancel_run(run_id, tenant_id=None)`: 提供 tenant_id 时先验证 run 属于该 tenant
- `list_runs(limit, tenant_id=None)`: 提供 tenant_id 时 WHERE 过滤

#### 6. Pricing 配置独立（M3）
**文件**: `config.py`, `agent_runtime.py`, `cli.py`

| 变更 | 说明 |
|------|------|
| 新增 `PricingConfig` dataclass | 独立 `pricing` 配置节，`path` 字段 |
| 加入 `AgentOSConfig` | `pricing: PricingConfig` |
| 解析支持 | `_from_dict()` 读取 `data["pricing"]` |
| 消费优先 | `agent_runtime.py` 使用 `cfg.pricing.path or cfg.tracing.pricing_path` |
| 默认模板 | `cli.py` _DEFAULT_YAML 中 `pricing.path` 替代 `tracing.pricing_path` |

`tracing.pricing_path` 标记为弃用（deprecated），保持向后兼容。

#### 7. StepExecutor 上下文字段提取（m5）
**文件**: `step_executor.py`

新增 `_build_context(run_id, step, step_outputs) → (context_dict, render_fn)` 方法，从 `_execute_step()` 中提取约 20 行的模板上下文构建逻辑。降低 `_execute_step` 复杂度，提高可测试性。

## 健康评分变化

| 域 | v0.7.0 | v0.7.1 | 变化 |
|----|:------:|:------:|:----:|
| 多智能体编排 | 9.5 | 9.5 | — |
| 工具增强型 LLM | 8.0 | 8.0 | — |
| Agent 生命周期 | 9.0 | **9.5** | +0.5（API-Runner 联动） |
| 可观测性 | 8.5 | 8.5 | — |
| 安全沙箱 | 7.5 | 7.5 | — |
| 记忆系统 | 8.5 | 8.5 | — |
| 提示工程 | 8.0 | 8.0 | — |
| 多租户隔离 | 6.5 | **7.5** | +1.0（cancel/list tenant 过滤） |
| 测试质量 | 9.5 | 9.5 | — |
| **综合** | **8.5** | **8.7** | **+0.2** |

## 技术债务剩余

- 会话持久化（ADR-005 核心建议，目标 v0.8.0）
- OpenTelemetry 集成（可选依赖，P2）
- Prompt 版本管理与 A/B 测试（P2）
- DAO 抽象层 / PostgreSQL 支持（P2）
- 文件系统隔离沙箱（推迟至 v0.9+）
- 全局消息事件总线（推迟）

## 相关文件

- `wiki/concepts/sccsos-architecture-framework.md` — 7 域架构框架
- `wiki/concepts/ADR-005-sccsos-v0.8.0-feasibility-analysis.md` — v0.8.0 规划
