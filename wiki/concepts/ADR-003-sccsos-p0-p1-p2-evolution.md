# ADR-003: Architecture Evolution — P0/P1/P2 Improvements

> 状态: **已实施** | 日期: 2026-07-19 | 版本: v0.5.0

## 上下文

对 SCCS OS v0.5.0 进行系统性架构审计（7-Domain Framework），识别出 12 项问题：
- 🔴 Critical: 2（安全盲区 + 逻辑空洞）
- 🟡 Major: 5（架构侵蚀 + 功能缺口）
- 🟢 Minor: 5（代码异味 + 配置漂移）

## 决策

按照 P0（立即修复）→ P1（架构改进）→ P2（功能扩展）三阶段实施。

## 实施记录

### P0 — 安全修复（2026-07-19）

| 项 | 文件 | 变更 |
|----|------|------|
| CommandWhitelist 接入 | `hermes_adapter.py` | `HermesSubprocessAdapter` 构造函数接受 whitelist，3 个子进程调用前执行 sandbox check |
| retry 异常路径修复 | `orchestrator.py:616` | `except Exception` 块中 `pass` → re-raise `WorkflowExecutionError` |
| check_tool_access 挂接 | `hermes_adapter.py` | delegate_task 的 policy pre-flight 增加 tool access 检查（第二道防线） |

### P1 — 架构改进（2026-07-19）

| 项 | 文件 | 变更 |
|----|------|------|
| Logger 消费配置 | `logger.py` | `get_logger()` 首次调用时读 sccsos.yaml 的 level/directory |
| API Server 复用实例 | `server.py` | 删除独立 Tracer/Auditor 创建，改用 `runtime.tracer`/`runtime.auditor` |
| AgentSpec policy 字段 | `registry.py`, `policy.py`, `agent_runtime.py` | per-agent 策略覆盖：AgentSpec.policy → PolicyEngine.set_agent_policy() → _get_policy_for() |
| db._get_conn() 封装 | `database.py` + 5 模块 | 新增 get_conn()/execute()/executescript() public API，20+ 外部调用迁移 |
| 模板引擎拆分 | `core/templates.py` | Jinja2 代码从 orchestrator.py 独立，文件 697→560 行 |

### P2 — 功能扩展（2026-07-19）

| 项 | 文件 | 变更 |
|----|------|------|
| Agent 级 model 覆盖 | `registry.py`, `orchestrator.py`, `agent_runtime.py` | AgentSpec.model → WorkflowEngine 通过 registry 解析 → HermesAdapter `-m` 参数 |
| Tracer JSON 导出 | `tracer.py`, `agent_runtime.py` | 消费 tracing.export_path，每 span 写入 `{path}/{trace_id}/{span_id}.json` |
| P2-1 | KnowledgeBase 集成 | `config.py`, `agent_runtime.py`, `orchestrator.py` | config 添加 wiki_path，WorkflowEngine 执行步骤前查询 KB → `{{ knowledge }}` 模板注入 |
| P2-2 | 多命名策略支持 | `config.py`, `policy.py` | PoliciesConfig.named 字典，PolicyEngine._get_policy_for() 解析 ref: "policy_name"，AgentSpec 支持 ref 或内联 |
| P2-5 | 编排可视化 | `orchestrator.py`, `cli.py` | WorkflowDef.to_mermaid() 生成 Mermaid flowchart，CLI `sccsos workflow visualize <file>` |

## 已完成（全部）

| 项目 | 描述 | 工作量 | 优先级 |
|-----|------|--------|--------|
| HermesSubprocessAdapter 单元测试 | 添加真子进程 adapter 的测试用例 | ~1h | 中 |
