# SCCS OS — Hermes Agent 调用关系技术说明

> 版本: v0.16.5 | 最后更新: 2026-07-26

## 概述

SCCS OS 通过 **Hermes Adapter** 抽象层调用 Hermes Agent 完成 LLM 推理任务。Hermes Agent 是下层运行时底座，SCCS OS 是上层编排管控平台，两者通过子进程 IPC 通信。

```
┌─────────────────────────────────────────────────────────────────┐
│                        SCCS OS 层                                │
│  ┌─────────┐  ┌──────────────┐  ┌────────────┐  ┌───────────┐  │
│  │ CLI     │  │ FastAPI      │  │ Workflow   │  │ Agent     │  │
│  │ (Click) │  │ (HTTP/WS)    │  │ Engine     │  │ Runner    │  │
│  └────┬────┘  └──────┬───────┘  └─────┬──────┘  └─────┬─────┘  │
│       │              │                │              │          │
│       └──────────────┴────────────────┴──────────────┘          │
│                              │                                  │
│                     ┌────────▼────────┐                         │
│                     │  HermesAdapter   │                         │
│                     │   (ABC 接口层)   │                         │
│                     └────────┬────────┘                         │
│                              │ 1. PolicyEngine 预检              │
│                              │ 2. Sandbox 命令扫描               │
│                              │ 3. subprocess 执行                │
├──────────────────────────────┼──────────────────────────────────┤
│                    Hermes Agent 层                                │
│                     ┌────────▼────────┐                         │
│                     │   hermes CLI    │                         │
│                     │  -p <profile>   │                         │
│                     │  -z <prompt>    │                         │
│                     └────────┬────────┘                         │
│                              │                                   │
│                     ┌────────▼────────┐                         │
│                     │  ReAct 推理循环   │                        │
│                     │  记忆 / 技能/工具 │                         │
│                     └────────┬────────┘                         │
│                              │                                   │
│                     ┌────────▼────────┐                         │
│                     │  LLM API 调用   │                         │
│                     │ (DeepSeek/OpenAI)│                         │
│                     └─────────────────┘                         │
└─────────────────────────────────────────────────────────────────┘
```

## 调用链路详解

### 1. CLI 直接对话 (`sccsos agent ask`)

```
用户输入
  │
  ▼
CLI: sccsos agent ask architect "设计认证模块"
  │
  ▼
AgentRuntime.runner → AgentProcess.ask(prompt)
  │  ├─ _build_prompt()        ← MemoryStore + KnowledgeBase + Session 三重注入
  │  ├─ HermesAdapter.delegate_task()
  │  │    ├─ PolicyEngine.check_delegation()       → 预算检查
  │  │    ├─ PolicyEngine.check_tool_access()      → 工具权限
  │  │    ├─ CommandWhitelist.check()              → 命令沙箱
  │  │    └─ subprocess.run(hermes -p sccsos -z "...") → 实际 LLM 调用
  │  └─ session.append_message()                  → 保存对话记录
  │
  ▼
返回 AskResult(response="...")
```

**关键点**：AgentProcess 是常驻后台线程，维护独立的 task queue + session，可连续对话。

### 2. Workflow 执行 (`sccsos workflow run` / API)

```
用户触发
  │
  ▼
WorkflowEngine.execute(workflow)
  │
  ├─ DAGResolver.get_execution_order()     → 解析依赖顺序
  ├─ ThreadPoolExecutor.submit(step...)    → 并行执行
  │
  ▼ (每个 step)
StepExecutor.execute_with_retry(run_id, step)
  │
  ├─ RetryPolicy                           → 指数退避重试（最多 3 次）
  ├─ ContextBuilder.build()                → Jinja2 模板渲染
  │    ├─ {{ steps.xxx.response }}         → 前置步骤输出
  │    ├─ {{ knowledge }}                  → 知识库上下文
  │    ├─ {{ memory }}                     → 持久记忆
  │    └─ {{ input }}                      → 用户输入
  ├─ _check_condition_and_skip()           → 条件分支判断
  ├─ _prepare_prompt()                     → 注入检测 + Personality 包裹
  │
  ▼
HermesAdapter.delegate_task()
  ├─ PolicyEngine.check_delegation()
  ├─ PolicyEngine.check_tool_access()
  ├─ CommandWhitelist.check()
  └─ subprocess.run(hermes -p sccsos -z "...")
  │
  ▼
_record_audit_and_result()
  ├─ Auditor.record_llm_call()             → Token + 成本审计
  ├─ Tracer.end_span()                     → 链路追踪
  └─ step_outputs[step.id] = result        → 供下游步骤使用
```

### 3. API 服务器 (`python -m sccsos.api.fastapi_app`)

```
HTTP POST /api/v1/workflows/run
  │
  ├─ RBAC: require_permission(P.WORKFLOWS_WRITE)
  ├─ X-Tenant-ID → 多租户隔离
  ├─ RuntimeFactory.get_runtime(tenant_id)
  │
  ▼
  ├─ WorkflowEngine.validate(workflow)     → Schema 校验
  ├─ WorkflowEngine.execute(workflow)      → 同上调用链
  │
  ▼
WebSocket 广播: workflow.completed → Vue SPA 实时更新
```

## 三层安全防线（每次调用必经）

每一层在调用链的不同阶段执行：

| 层 | 模块 | 位置 | 检查内容 |
|:--:|------|------|---------|
| ① | `PromptInjectionGuard` | `StepExecutor._prepare_prompt()` | Unicode 同形字、多语言注入、系统提示提取、批量数据提取、敏感数据脱敏 |
| ② | `PolicyEngine` | `HermesAdapter._policy_preflight()` | 预算上限、工具权限白名单、per-agent 策略覆盖 |
| ③ | `CommandWhitelist` | `HermesSubprocessAdapter._sandbox_check()` | 危险命令、路径穿越、管道链、环境变量泄漏、命令长度上限 |

## Hermes CLI 调用命令格式

### 真实子进程命令

```bash
# 基本调用
hermes -p sccsos -z "你的提示词"

# 带模型指定
hermes -p sccsos -m deepseek-v4-flash -z "提示词"

# 验证 Hermes 可用
hermes --version               # ≥ 0.24.x
hermes doctor                  # 全面诊断
hermes config list-profiles    # 查看可用 profile
```

### 所需的 Hermes Profile 配置

执行 `hermes -p sccsos -z "..."` 前，Hermes Agent 需要：

```yaml
# ~/.hermes/profiles/sccsos/config.yaml
provider: deepseek          # 或 openai / anthropic
model: deepseek-v4-flash    # 或 gpt-4o / claude-sonnet-4
api_key: <your-api-key>     # 从环境变量或配置文件读取
```

## SCCS OS 侧的 Adapter 配置

```yaml
# sccsos.yaml
hermes:
  profile: sccsos            # 使用的 Hermes profile 名称
  adapter: subprocess        # 通信模式：subprocess / mock
  binary: hermes             # Hermes CLI 二进制路径
```

## 调用性能特征

| 指标 | 典型值 | 说明 |
|------|:------:|------|
| 子进程启动开销 | ~50ms | Python 进程 fork + import |
| 首次 LLM 调用 | ~2-5s | 模型加载 + 推理 |
| 后续连续调用 | ~1-3s | 模型已热加载 |
| 超时默认值 | 300s | 可在 step 定义中覆盖 |
| 重试次数 | 2 次 | 瞬态错误自动重试（指数退避） |

## 测试模式（MockHermesAdapter）

测试时使用 `MockHermesAdapter` 替代真实子进程调用：

```yaml
# sccsos.yaml (测试环境)
hermes:
  adapter: mock               # 不调用 Hermes CLI，返回固定响应
```

Mock 适配器保留完整的安全防线（PolicyEngine 预算/ACL 检查），确保测试可验证安全策略而不依赖真实 LLM。
