# SCCS OS v0.11.0 — 测试验证指南

> 版本: v0.11.0 | 更新: 2026-07-22
> 涵盖：功能验证 · 集成测试 · 部署验证 · 操作案例
> 别名：`sc` 等价于 `sccsos`（全部命令可用）

---

## 目录

- [第1章 部署验证](#第1章-部署验证)
- [第2章 CLI 功能验证](#第2章-cli-功能验证)
- [第3章 工作流验证](#第3章-工作流验证)
- [第4章 多租户隔离验证](#第4章-多租户隔离验证)
- [第5章 安全策略验证](#第5章-安全策略验证)
- [第6章 可观测性验证](#第6章-可观测性验证)
- [第7章 告警系统验证](#第7章-告警系统验证)
- [第8章 记忆系统验证](#第8章-记忆系统验证)
- [第9章 API 服务验证](#第9章-api-服务验证)
- [第10章 容器部署验证](#第10章-容器部署验证)
- [第11章 自动化测试套件](#第11章-自动化测试套件)
- [第12章 实战案例](#第12章-实战案例)

---

## 第1章 部署验证

### 1.1 环境准备

| 组件 | 版本要求 | 验证命令 |
|------|---------|---------|
| Python | >= 3.11 | `python3 --version` |
| Hermes Agent | >= 0.18.0 | `hermes --version` |
| pip | >= 21.0 | `pip3 --version` |

### 1.2 安装验证

```bash
# 安装 SCCS OS
cd /path/to/sccsos
pip install -e .

# 验证 CLI 可用
sccsos version
# 预期: sccsos v0.11.0
#
# 查看帮助
sccsos --help
# 预期: 显示 agent/workflow/trace/audit/health/memory/init/version/serve 10 个命令

# 简写别名
sc version
# 预期: sccsos v0.11.0
sc --help
# 预期: 与 sccsos --help 输出一致
```

### 1.3 初始化验证

```bash
# 初始化项目
mkdir -p /tmp/sccsos-test && cd /tmp/sccsos-test
sccsos init

# 验证目录结构
ls -la
# 预期:
#   sccsos.yaml    项目配置
#   agents/        Agent 定义目录
#   data/          SQLite 数据库目录
#   logs/          日志目录
#   traces/        追踪数据目录
#   workflows/     工作流定义目录
#   personalities/ 角色定义目录

# 验证配置文件
cat sccsos.yaml | head -5
# 预期: 包含 project/database/defaults/logging/tracing/agents/policies 配置节
```

### 1.4 健康检查

```bash
sccsos health
# 预期输出示例:
#   sccsos v0.11.0
#   Database: ok (0 agents)
#   Hermes:   OK
#   Agents:   0 registered
```

---

## 第2章 CLI 功能验证

### 2.1 Agent 管理验证

```bash
# 2.1.1 创建 Agent
sccsos agent create test-agent
# 预期: Created: agents/test-agent.yaml

# 2.1.2 列出 Agent
sccsos agent list
# 预期: 显示 test-agent 及其状态

# 按租户过滤
sccsos agent list --tenant default
# 预期: 仅显示 default 租户的 Agent

# 2.1.3 启动 Agent（后台进程）
sccsos agent start test-agent
# 预期: Started: test-agent (agent_xxx) [background]

# 2.1.4 查看状态
sccsos agent status test-agent
# 预期: 显示状态 running、会话 ID、最近事件

# 2.1.5 对话
sccsos agent ask test-agent "你好，请用一句话自我介绍"
# 预期: Agent 返回响应（非空字符串）

# 2.1.6 暂停 Agent
sccsos agent pause test-agent
# 预期: Paused: test-agent (agent_xxx)

# 2.1.7 恢复 Agent
sccsos agent resume test-agent
# 预期: Resumed: test-agent (agent_xxx)

# 2.1.8 查看日志
sccsos agent logs test-agent
# 预期: 显示最近事件

# 2.1.9 停止 Agent
sccsos agent stop test-agent
# 预期: Stopped background process: test-agent / Stopped: test-agent

# 2.1.10 重启失败的 Agent（模拟失败）
sccsos agent restart test-agent
# 预期: No failed instance found (如果 Agent 未处于 FAILED 状态)
```

### 2.2 工作流管理验证

```bash
# 2.2.1 验证工作流
sccsos workflow validate workflows/冒烟测试.yaml
# 预期: Validation: PASSED（或 WARNINGS）

# 2.2.2 可视化工作流
sccsos workflow visualize workflows/冒烟测试.yaml
# 预期: 输出 Mermaid flowchart

# 2.2.3 列出工作流运行
sccsos workflow list
# 预期: 显示工作流运行列表（可能为空）

# 按租户过滤
sccsos workflow list --tenant default
# 预期: 仅显示 default 租户的运行记录

# 2.2.4 取消工作流
sccsos workflow cancel wf_nonexistent
# 预期: Run 'wf_nonexistent' not found.
```

### 2.3 审计与追踪验证

```bash
# 审计报告
sccsos audit report
# 预期: 显示审计汇总（调用次数/Token/成本/成功率）

# 审计日志
sccsos audit log
# 预期: 显示审计条目列表

# 追踪列表
sccsos trace list
# 预期: 显示追踪列表

# 版本查询
sccsos version
# 预期: sccsos v0.11.0

# 简写别名
# sccsos 的全部命令均可通过 sc 简写执行
sc version
sc health
sc agent list
```

### 2.4 持久记忆管理验证

```bash
# 2.4.1 保存记忆
sccsos memory save architect language Python
# 预期: Saved: architect/language = Python

# 2.4.2 获取记忆
sccsos memory get architect language
# 预期: Python

# 2.4.3 列出所有记忆 key
sccsos memory list architect
# 预期: Memory keys for 'architect': - language

# 2.4.4 保存带 TTL 的记忆（3600 秒后过期）
sccsos memory save architect temp_key temp_value --ttl 3600
# 预期: Saved: architect/temp_key = temp_value

# 2.4.5 删除单条记忆
sccsos memory delete architect temp_key
# 预期: Deleted: architect/temp_key

# 2.4.6 清空 Agent 全部记忆
sccsos memory clear architect
# 预期: Cleared N entries for agent 'architect'

# 2.4.7 跨租户隔离验证
sccsos memory save architect greeting hello --tenant tenant-a
sccsos memory save architect greeting bonjour --tenant tenant-b
sccsos memory get architect greeting --tenant tenant-a
# 预期: hello
sccsos memory get architect greeting --tenant tenant-b
# 预期: bonjour
```

---

## 第3章 工作流验证

### 3.1 冒烟测试

验证最基本的工作流执行路径：

```bash
cd /path/to/sccsos/project
sccsos workflow run workflows/冒烟测试.yaml
```

预期结果：
- CLI 输出 "Workflow completed!"
- 显示 Run ID
- 状态为 "completed"

### 3.2 条件分支工作流

验证条件分支的跳过逻辑：

```bash
sccsos workflow run workflows/条件分支示例.yaml \
  -i "实现用户登录功能，需要支持 OAuth 2.0"
# 预期: 需求明确 → 深度设计步骤执行

sccsos workflow run workflows/条件分支示例.yaml \
  -i "需求待确定"
# 预期: 需求不够明确 → 澄清建议步骤执行
```

### 3.3 带输入的工作流

```bash
sccsos workflow run workflows/架构评审.yaml \
  -i "构建一个微服务架构的电商平台，支持 10 万并发"
# 预期: 4 个步骤依次执行（需求分析→架构设计→风险评估→评审总结）
```

### 3.4 异步执行

```bash
sccsos workflow run workflows/每日巡检.yaml --async
# 预期: 立即返回，提示使用 workflow list/status 查看进度
sccsos workflow list
sccsos workflow status <run_id>
```

### 3.5 Webhook 通知验证

```bash
# 确认 sccsos.yaml 中配置了 webhooks
cat sccsos.yaml | grep -A 5 "webhooks"
# 预期: 显示 webhooks 配置（如果已启用）

# 运行工作流触发通知
sccsos workflow run workflows/冒烟测试.yaml
# 如果 webhooks.enabled=true: 目标端点收到 POST 通知
```

---

## 第4章 多租户隔离验证

### 4.1 API 租户隔离

```bash
# 启动 API 服务器（FastAPI 模式）
sccsos serve --port 8765

# 注册 Agent（租户 A）
curl -X POST http://localhost:8765/agents/register \
  -H "Content-Type: application/json" \
  -H "X-Tenant-ID: tenant-a" \
  -d '{"name":"agent-a1","description":"Tenant A agent"}'
# 预期: 201 {"registered": "agent-a1"}

# 注册 Agent（租户 B）
curl -X POST http://localhost:8765/agents/register \
  -H "Content-Type: application/json" \
  -H "X-Tenant-ID: tenant-b" \
  -d '{"name":"agent-b1","description":"Tenant B agent"}'
# 预期: 201 {"registered": "agent-b1"}

# 列出租户 A 的 Agent
curl -s http://localhost:8765/agents \
  -H "X-Tenant-ID: tenant-a" | python3 -m json.tool
# 预期: 仅包含 agent-a1
# 验证: "count": 1, "agents" 列表中只有 agent-a1

# 列出租户 B 的 Agent
curl -s http://localhost:8765/agents \
  -H "X-Tenant-ID: tenant-b" | python3 -m json.tool
# 预期: 仅包含 agent-b1

# 验证无 X-Tenant-ID 头（默认租户）
curl -s http://localhost:8765/agents | python3 -m json.tool
# 预期: "tenant_id": "default"，可能为空列表
```

### 4.2 JSON body 指定租户

```bash
curl -X POST http://localhost:8765/agents/register \
  -H "Content-Type: application/json" \
  -d '{"name":"custom-tenant-agent","tenant_id":"custom-1"}'
# 预期: 201 {"registered": "custom-tenant-agent"}

curl -s http://localhost:8765/agents \
  -H "X-Tenant-ID: custom-1" | python3 -m json.tool | grep agent
# 预期: 显示 custom-tenant-agent
```

### 4.3 CLI 租户隔离

```bash
# CLI 现在支持 --tenant flag
sccsos agent list --tenant tenant-a
# 预期: 仅显示 tenant-a 的 Agent

sccsos workflow list --tenant tenant-b
# 预期: 仅显示 tenant-b 的工作流运行记录
```

---

## 第5章 安全策略验证

### 5.1 命令白名单验证

```bash
# 通过 HermesSubprocessAdapter 验证命令拦截
# 危险命令被拦截（模拟场景）
python3 -c "
from sccsos.security.sandbox import CommandWhitelist
wl = CommandWhitelist(allowed_commands=['ls', 'echo'],
                       dangerous_patterns=['docker'])
# 验证危险模式拦截
assert not wl.check('sudo rm -rf /').allowed
# 验证额外危险模式拦截
assert not wl.check('docker ps').allowed
# 验证白名单通过
assert wl.check('echo hello').allowed
print('✅ 命令白名单三层防线验证通过')
"
```

### 5.2 策略引擎验证

```bash
python3 -c "
from sccsos.core.database import Database
from sccsos.core.config import AgentOSConfig, PoliciesConfig, PolicyDefaults
from sccsos.security.policy import PolicyEngine

# 初始化
db = Database('/tmp/sccsos-test-policy.db')
db.initialize()

# 配置严格策略
config = AgentOSConfig(
    policies=PoliciesConfig(
        default=PolicyDefaults(
            max_cost_usd=5.0,
            allowed_tools=['read_file', 'search_files'],
            blocked_tools=['terminal'],
        )
    )
)

policy = PolicyEngine(db, config)

# 预算检查
result = policy.check_delegation(agent_name='test', estimated_cost=0.5)
assert result.allowed, f'预算检查失败: {result.reason}'

# 工具 ACL 检查
result = policy.check_tool_access('test', 'read_file')
assert result.allowed, f'工具 ACL 误拦截: {result.reason}'

result = policy.check_tool_access('test', 'terminal')
assert not result.allowed, '工具 ACL 未拦截 blocked 工具'

print('✅ 策略引擎验证通过')
"
```

### 5.3 Per-Agent 策略覆盖验证

```bash
python3 -c "
from sccsos.core.config import AgentOSConfig, PoliciesConfig, PolicyDefaults
from sccsos.core.database import Database
from sccsos.security.policy import PolicyEngine

db = Database('/tmp/sccsos-per-agent.db')
db.initialize()
config = AgentOSConfig()
policy = PolicyEngine(db, config)

# 注册 per-agent 策略
policy.set_agent_policy('restricted-agent', {
    'max_cost_usd': 1.0,
    'blocked_tools': ['web_search'],
})

# 受限 Agent 应拒绝 web_search
result = policy.check_tool_access('restricted-agent', 'web_search')
assert not result.allowed, 'Per-agent 策略覆盖未生效'

print('✅ Per-agent 策略覆盖验证通过')
"
```

---

## 第6章 可观测性验证

### 6.1 结构化日志验证

```bash
# 确认日志在 JSON 格式输出
cat logs/sccsos.log | head -3 | python3 -m json.tool
# 预期: 每行是一个 JSON 对象，包含 timestamp/level/name/message

# 验证 JSON 格式
python3 -c "
import json
with open('logs/sccsos.log') as f:
    for i, line in enumerate(f):
        if i >= 3: break
        obj = json.loads(line.strip())
        assert 'timestamp' in obj
        assert 'level' in obj
        assert 'message' in obj
        print(f'✅ 日志条目 {i+1}: [{obj[\"level\"]}] {obj[\"message\"][:60]}')
"
```

### 6.2 Trace 验证

```bash
# 运行工作流产生 trace
sccsos workflow run workflows/冒烟测试.yaml

# 查看 traces
sccsos trace list
# 预期: 显示至少一条 trace

# 查看具体 trace（使用上面返回的 trace_id）
sccsos trace show <trace_id>
# 预期: 显示 Span 树结构
```

### 6.3 审计报告验证

```bash
sccsos audit report
# 预期: 显示
#   Total calls:    N
#   Total tokens:   NNN
#   Total cost:     $X.XXXX
#   Avg duration:   NNNms
#   Success rate:   N/N
#   By event type:  ...
#   By model:       ...
#   Cost over time: ...
```

### 6.4 Trace JSON 导出验证

```bash
# 检查 traces 导出目录
ls -la traces/
# 预期: 存在以 trace_id 命名的子目录，内含 span JSON 文件

# 验证 span JSON 格式
python3 -c "
import json
from pathlib import Path
trace_dirs = list(Path('traces').iterdir())
if trace_dirs:
    span_files = list(trace_dirs[0].iterdir())
    if span_files:
        span = json.loads(span_files[0].read_text())
        assert 'trace_id' in span
        assert 'span_id' in span
        assert 'duration_ms' in span
        print(f'✅ Span JSON 验证通过: {span[\"name\"]} ({span[\"duration_ms\"]}ms)')
"
```

---

## 第7章 告警系统验证

### 7.1 AlertManager 基本验证

```bash
python3 -c "
from sccsos.core.database import Database
from sccsos.observability.alert_manager import AlertManager

db = Database('/tmp/sccsos-alert-test.db')
db.initialize()

# 插入失败记录（模拟高频失败）
conn = db._get_conn()
for i in range(10):
    conn.execute(
        'INSERT INTO audit_log (tenant_id, agent_id, event_type, success) '
        'VALUES (?, ?, ?, ?)',
        ('test', 'agent-a', 'llm_call', 0 if i < 3 else 1),
    )
conn.commit()

alert = AlertManager(db)
results = alert.evaluate_after_run(run_id='test-run', tenant_id='test')
if results:
    for r in results:
        print(f'  ⚠ [{r.level}] {r.message}')
else:
    print('  ✅ 未触发告警')

print('✅ AlertManager 验证通过')
"
```

### 7.2 告警 Webhook 推送

```bash
# 配置 webhook 端点（需在 sccsos.yaml 中配置）
# 运行工作流时，AlertManager 自动评估阈值
# 超限时通过 WebhookNotifier 发送 POST 到配置的 endpoints

# 验证方案：启动本地 HTTP 监听
python3 -c "
from http.server import HTTPServer, BaseHTTPRequestHandler
class WebhookCapture(BaseHTTPRequestHandler):
    received = []
    def do_POST(self):
        length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(length)
        self.received.append(json.loads(body))
        self.send_response(200)
        self.end_headers()
    def log_message(self, *a): pass

import json, threading
server = HTTPServer(('', 19999), WebhookCapture)
t = threading.Thread(target=server.serve_forever, daemon=True)
t.start()
print(f'✅ Webhook 监听器已启动 (port 19999)')
" &
```

---

## 第8章 记忆系统验证

### 8.1 知识库验证

```bash
python3 -c "
from pathlib import Path
from sccsos.memory.knowledge_base import KnowledgeBase

# 使用现有 wiki
kb = KnowledgeBase(wiki_path=Path('wiki'), use_vector=True)
results = kb.query('architecture', top_k=3)
print(f'✅ 知识库查询返回 {len(results)} 条结果')
for r in results:
    print(f'  - [{r.source}] {r.title} (score: {r.relevance:.3f})')

# 验证上下文注入
context = kb.get_context_for('agent lifecycle')
if context:
    print(f'✅ 上下文注入返回 {len(context)} 字符')
else:
    print('⚠ 上下文注入为空（可能无匹配文档）')
"
```

### 8.2 跨会话持久记忆验证

```bash
python3 -c "
from sccsos.core.database import Database
from sccsos.memory.memory_store import MemoryStore

db = Database('/tmp/sccsos-memory-test.db')
db.initialize()

store = MemoryStore(db)

# 写入记忆
store.save('architect', 'preferred_language', 'Python', 'tenant-a')
store.save('architect', 'preferred_framework', 'FastAPI', 'tenant-a')
store.save('reviewer', 'preferred_language', 'Go', 'tenant-a')

# 读取单条
val = store.get('architect', 'preferred_language', 'tenant-a')
assert val == 'Python', f'期望 Python, 实际 {val}'
print(f'✅ 单条读取: preferred_language = {val}')

# 列出所有 key
keys = store.list_keys('architect', 'tenant-a')
assert len(keys) == 2, f'期望 2 个 key, 实际 {len(keys)}'
print(f'✅ Key 列表: {keys}')

# 读取全部
all_data = store.get_all('architect', 'tenant-a')
assert 'preferred_language' in all_data
assert 'preferred_framework' in all_data
print(f'✅ 全部读取: {all_data}')

# 租户隔离验证
tenant_b_data = store.get_all('architect', 'tenant-b')
assert len(tenant_b_data) == 0, '租户 B 不应看到租户 A 的数据'
print(f'✅ 租户隔离验证通过（tenant-b 数据为空）')

# 删除记忆
deleted = store.delete('architect', 'preferred_language', 'tenant-a')
assert deleted, '删除失败'
print(f'✅ 删除成功')

# 清理测试数据
store.clear_agent('architect', 'tenant-a')
store.clear_agent('reviewer', 'tenant-a')

print('✅ MemoryStore 全部验证通过')
"
```

### 8.4 TTL 过期验证

```bash
python3 -c "
from sccsos.core.database import Database
from sccsos.memory.memory_store import MemoryStore
import time

db = Database('/tmp/sccsos-ttl-test.db')
db.initialize()

store = MemoryStore(db)

# 写入带短 TTL 的记忆
store.save('architect', 'temp_key', 'temp_value', 'tenant-a', ttl_seconds=1)

# 立即读取 — 应存在
val = store.get('architect', 'temp_key', 'tenant-a')
assert val == 'temp_value', f'TTL 未到时不应过期: {val}'
print(f'✅ TTL 未到时读取成功: {val}')

# 等待 1.5 秒让 TTL 过期
time.sleep(1.5)

# 过期后读取 — 应返回 None
val = store.get('architect', 'temp_key', 'tenant-a')
assert val is None, f'TTL 过期后应返回 None, 实际: {val}'
print(f'✅ TTL 过期后返回 None')

# 清理
store.clear_agent('architect', 'tenant-a')
print('✅ TTL 过期验证通过')
"
```

### 8.3 Personality 注入验证

```bash
python3 -c "
from sccsos.core.personality import PersonalityRegistry, Personality

registry = PersonalityRegistry()
registry.register(Personality(
    name='architect',
    system_prompt='You are a senior software architect.',
))

# 验证 prompt 包装
result = registry.wrap_prompt('architect', 'Design a module.')
assert 'senior software architect' in result.prompt
assert 'Design a module.' in result.prompt
assert result.applied_personality == 'architect'
print(f'✅ Personality 注入验证通过')
print(f'   原始 prompt: 12 chars')
print(f'   包装后 prompt: {len(result.prompt)} chars')
"
```

---

## 第9章 API 服务验证

### 9.1 启动 API 服务器

```bash
# 启动（后台）
python -m sccsos.api.server --port 8765 &
sleep 2

# 验证进程
ps aux | grep sccsos.api.server | grep -v grep
# 预期: 显示服务器进程
```

### 9.2 端点验证

```bash
# 健康检查
curl -s http://localhost:8765/health | python3 -m json.tool
# 预期:
# {
#   "version": "0.6.4",
#   "initialized": true,
#   "database": {"status": "ok", ...},
#   "hermes": true/false,
#   "agents": N
# }

# Agent 列表
curl -s http://localhost:8765/agents | python3 -m json.tool
# 预期: {"agents": [...], "count": N}

# 注册 Agent
curl -s -X POST http://localhost:8765/agents/register \
  -H "Content-Type: application/json" \
  -d '{"name":"api-agent","toolsets":["filesystem"]}' | python3 -m json.tool
# 预期: {"registered": "api-agent"}

# Agent 状态
curl -s http://localhost:8765/agents/api-agent | python3 -m json.tool
# 预期: 显示 agent 信息

# 启动 Agent
curl -s -X POST http://localhost:8765/agents/api-agent/start | python3 -m json.tool
# 预期: {"started": "api-agent", "id": "agent_xxx"}

# 对话
curl -s -X POST http://localhost:8765/agents/api-agent/ask \
  -H "Content-Type: application/json" \
  -d '{"prompt":"Hello"}' | python3 -m json.tool
# 预期: {"response": "...", "success": true}

# 暂停/恢复
curl -s -X POST http://localhost:8765/agents/api-agent/pause | python3 -m json.tool
curl -s -X POST http://localhost:8765/agents/api-agent/resume | python3 -m json.tool

# 停止
curl -s -X POST http://localhost:8765/agents/api-agent/stop | python3 -m json.tool
# 预期: {"stopped": "api-agent"}

# 工作流运行
curl -s -X POST http://localhost:8765/workflows/run \
  -H "Content-Type: application/json" \
  -d '{"file": "workflows/冒烟测试.yaml"}' | python3 -m json.tool
# 预期: {"run_id": "wf_xxx", "status": "completed"}

# 工作流验证
curl -s -X POST http://localhost:8765/workflows/validate \
  -H "Content-Type: application/json" \
  -d '{"file": "workflows/冒烟测试.yaml"}' | python3 -m json.tool
# 预期: {"valid": true, "workflow": "...", ...}

# 审计
curl -s http://localhost:8765/audit/report | python3 -m json.tool
curl -s http://localhost:8765/audit/log | python3 -m json.tool

# Trace
curl -s http://localhost:8765/traces | python3 -m json.tool

# 404
curl -s http://localhost:8765/nonexistent | python3 -m json.tool
# 预期: 404 {"error": "Not found"}
```

### 9.3 API 安全头

```bash
curl -s -I http://localhost:8765/health 2>&1 | grep -i "Access-Control"
# 预期: Access-Control-Allow-Origin: *
```

---

## 第10章 容器部署验证

### 10.1 Docker 构建

```bash
cd /path/to/sccsos

# 构建镜像
docker build -t sccsos:0.6.4 .

# 验证镜像
docker images | grep sccsos
# 预期: sccsos  0.6.4  ...  多阶段构建镜像

# 运行容器
docker run -d --name sccsos-test \
  -p 8765:8765 \
  -v sccsos_data:/sccsos/data \
  sccsos:0.6.4

# 验证容器运行
docker ps | grep sccsos
# 预期: 容器状态为 Up

# 验证健康检查
sleep 5
docker inspect sccsos-test --format='{{json .State.Health.Status}}'
# 预期: "healthy"

# 验证 API 访问
curl -s http://localhost:8765/health | python3 -m json.tool
# 预期: 返回健康状态 JSON

# 停止并清理
docker stop sccsos-test
docker rm sccsos-test
```

### 10.2 Docker Compose 部署

```bash
cd /path/to/sccsos

# 启动服务
docker compose up -d

# 验证
docker compose ps
# 预期: sccsos 服务状态为 Up (healthy)

# 访问 API
curl http://localhost:8765/health

# 查看日志
docker compose logs -f

# 停止
docker compose down
# 注意: volumes 不会被自动删除
# 如需清理: docker compose down -v
```

---

## 第11章 自动化测试套件

### 11.1 运行全量测试

```bash
cd /path/to/sccsos

# 全量测试
python3 -m pytest tests/ -v

# 预期: 157 passed（或更多，取决于新增用例）
# 测试用例分类:
#   tests/test_integration.py       → 核心流程 + 策略引擎 + AgentRunner + Schema 验证 + 条件分支 + Personality
#   tests/test_comprehensive.py     → 配置加载 + 沙箱 + 定价 + 模板 + 向量库 + 知识库
#   tests/test_api_server.py        → API 端点端到端测试
#   tests/test_workflow_validate.py → 工作流 YAML 定义验证
#   tests/test_agent_definition.py  → Agent 定义 YAML 验证
```

### 11.2 按模块运行测试

```bash
# 仅核心集成测试
python3 -m pytest tests/test_integration.py -v --tb=short

# 仅 API 测试
python3 -m pytest tests/test_api_server.py -v --tb=short

# 仅组件测试
python3 -m pytest tests/test_comprehensive.py -v --tb=short

# 仅工作流验证
python3 -m pytest tests/test_workflow_validate.py -v

# 仅 Agent 定义验证
python3 -m pytest tests/test_agent_definition.py -v
```

### 11.3 测试覆盖率（手动确认）

```bash
# 安装 coverage
pip install coverage

# 运行覆盖率测试
coverage run -m pytest tests/ -q
coverage report -m --skip-covered

# 重点关注:
# - sccsos/core/agent_runner.py     → AgentProcess/Runner 生命周期
# - sccsos/core/step_executor.py    → 条件分支 + 重试 + personality 注入
# - sccsos/core/personality.py      → 角色注册 + 加载 + prompt 包装
# - sccsos/observability/alert_manager.py → 阈值评估 + 告警推送
# - sccsos/memory/memory_store.py   → KV 持久化 + 租户隔离
```

---

## 第12章 实战案例

### 12.1 架构评审工作流

```bash
cd /path/to/sccsos/project

# 运行架构评审
sccsos workflow run workflows/架构评审.yaml \
  -i "构建一个基于微服务的电商平台，支持 10 万日活用户，需要高可用和高扩展性"

# 预期: 4 个步骤依次执行
#   1. requirements_analysis (需求分析)
#   2. architecture_design (架构方案设计)
#   3. risk_assessment (风险评估)
#   4. review_summary (评审总结)
```

### 12.2 每日巡检工作流

```bash
cd /path/to/sccsos/project

# 运行每日巡检
sccsos workflow run workflows/每日巡检.yaml

# 预期: 3 个步骤
#   1. health-check (系统健康检查)
#   2. audit-summary (审计汇总)
#   3. inspection-report (巡检报告生成)
```

### 12.3 条件分支工作流

```bash
cd /path/to/sccsos/project

# 场景 1: 需求明确 → 深度设计
sccsos workflow run workflows/条件分支示例.yaml \
  -i "我们需要一个用户认证系统，支持 OAuth 2.0 和 JWT Token，预计 5000 用户"

# 场景 2: 需求模糊 → 澄清建议
sccsos workflow run workflows/条件分支示例.yaml \
  -i "做个系统"
```

### 12.4 多 Agent 协同

```bash
cd /path/to/sccsos/project

# 查看可用 Agent
sccsos agent list

# 启动架构师
sccsos agent start architect

# 对话
sccsos agent ask architect "请设计一个 RESTful API 认证方案"
```

### 12.5 异常恢复与故障处理

```bash
# 场景 1: Agent 进程异常退出
sccsos agent status architect
# 如果显示 failed:
sccsos agent restart architect

# 场景 2: 工作流执行超时
sccsos workflow run workflows/架构评审.yaml --async
sccsos workflow list
sccsos workflow cancel <run_id>

# 场景 3: 数据库损坏恢复
# 停止所有 Agent
sccsos agent stop architect

# 备份旧数据库（如有）
cp data/sccsos.db data/sccsos.db.bak

# 删除并重建（sccsos 会自动创建新数据库）
rm data/sccsos.db
sccsos init --force
sccsos health

# 场景 4: 配置错误修复
# 修复 sccsos.yaml 后重启服务
sccsos health
# 如果配置加载失败，检查 YAML 格式
python3 -c "import yaml; yaml.safe_load(open('sccsos.yaml'))"
```

### 12.6 数据清理

```bash
# 清理测试数据库
rm -f /tmp/sccsos-test*.db

# 清理日志
rm -rf logs/*.log

# 清理 traces
rm -rf traces/*/

# 重置项目数据（保留配置和 Agent 定义）
rm -f data/sccsos.db
sccsos init --force
```

---

## 附录

### A. 测试状态矩阵

| 模块 | 测试文件 | 测试数 | 覆盖场景 |
|------|---------|--------|---------|
| AgentRegistry | test_integration.py | 6 | 注册/查找/去重/标签/计数/YAML 加载 |
| LifecycleManager | test_integration.py | 4 | 全状态机/无效转换/列表查询 |
| WorkflowEngine | test_integration.py | 12 | 单步/DAG/模板/空工作流/环检测/取消/重试/超时/条件 |
| PolicyEngine | test_integration.py | 8 | 预算/工具ACL/Per-agent/工具集校验 |
| AgentRunner | test_integration.py | 6 | 启停/双重启动/对话/stop_all/策略+模型 |
| Schema 验证 | test_integration.py | 8 | 空步骤/缺id/重复id/缺agent/缺prompt/无效timeout/parallel |
| Condition | test_integration.py | 2 | 条件真/条件假 |
| Personality | test_integration.py | 6 | 空注册/注册查找/prompt包装/YAML加载/跳过无效文件 |
| CommandWhitelist | test_integration.py + test_comprehensive.py | 9 | 危险模式/白名单/额外模式/to_config |
| Config | test_comprehensive.py | 3 | 完整加载/默认值/缺失回退 |
| PricingTable | test_comprehensive.py | 7 | 默认/未知模型/估算/新增模型/JSON加载/缺失回退 |
| TemplateEngine | test_comprehensive.py | 15 | 变量/点号/条件/循环/过滤器/默认值/未定义/空/算术 |
| VectorStore | test_comprehensive.py | 8 | 空搜索/文档/排名/snippet/大量文档/删除/清空 |
| KnowledgeBase | test_comprehensive.py | 6 | 空/加载/来源/上下文/向量/YAML frontmatter |
| MemoryStore | test_integration.py + memory_store.py | — | **CLI 命令 save/get/list/delete/clear + TTL 过期** |
| API Server | test_api_server.py | 22 | 健康/Agent/工作流/Trace/审计/404/CORS + **pause/resume/restart/ask/visualize** |
| Workflow Validate | test_workflow_validate.py | 4 | YAML 验证/Mermaid/Visualize CLI |
| Agent Definition | test_agent_definition.py | 1 | YAML 定义完整性 |
| **合计** | **5 文件** | **157** | — |

### B. 验收检查清单

- [ ] 所有 157 测试通过
- [ ] CLI 9 个命令可用（agent/workflow/trace/audit/health/memory/init/version + **`sc` 别名**）
- [ ] Agent 创建/启动/停止/对话全链路可用
- [ ] 工作流 DAG 执行 + 条件分支正常
- [ ] 多租户隔离（X-Tenant-ID header + CLI `--tenant` flag）
- [ ] 安全策略生效（预算/工具 ACL/命令白名单）
- [ ] 审计追踪可用
- [ ] Webhook 通知可推送
- [ ] AlertManager 告警评估
- [ ] MemoryStore 持久记忆读写（save/get/list/delete/clear + **TTL 过期**）
- [ ] 自动化测试套件 322+ 通过，新模块测试覆盖 RetryPolicy/ContextBuilder/MultiTenant
- [ ] Personality 注入正常（3 个角色：architect/doc-writer/code-reviewer）
- [ ] API Server 全部端点正常（含 pause/resume/restart/ask）
- [ ] `{{ memory }}` 模板变量在工作流步骤中可用
- [ ] Docker 构建 + 运行正常

---

## 第13章 RetryPolicy 测试场景

### 13.1 成功路径

```bash
python3 -c "
from sccsos.core.retry_policy import RetryPolicy
import threading

policy = RetryPolicy(None, threading.Lock())
# 零失败：fn 第一次就成功
result = policy.execute(lambda: 'ok', max_attempts=3)
assert result == 'ok'
print('✅ RetryPolicy 成功路径验证通过')
"
```

### 13.2 重试后成功

```bash
python3 -c "
from sccsos.core.retry_policy import RetryPolicy
import threading

policy = RetryPolicy(None, threading.Lock())
attempts = [0]
def flaky():
    attempts[0] += 1
    if attempts[0] < 3:
        raise ValueError('transient')
    return 'finally_ok'

result = policy.execute(flaky, step_id='test', max_attempts=5)
assert result == 'finally_ok'
assert attempts[0] == 3
print('✅ RetryPolicy 重试后成功验证通过')
"
```

### 13.3 重试耗尽

```bash
python3 -c "
from sccsos.core.retry_policy import RetryPolicy
import threading

policy = RetryPolicy(None, threading.Lock())
try:
    policy.execute(lambda: (_ for _ in ()).throw(ValueError('boom')),
                   step_id='exhaust', max_attempts=2)
    assert False, 'Should have raised'
except Exception as e:
    assert 'failed after 2 attempts' in str(e)
    print('✅ RetryPolicy 重试耗尽验证通过')
"
```

### 13.4 非重试异常不予重试

```bash
python3 -c "
from sccsos.core.retry_policy import RetryPolicy
import threading

policy = RetryPolicy(None, threading.Lock())
try:
    policy.execute(lambda: (_ for _ in ()).throw(ValueError('Policy rejected')),
                   step_id='noretry', max_attempts=5)
    assert False, 'Should have raised'
except ValueError:
    print('✅ RetryPolicy 非重试异常验证通过')
"
```

### 13.5 取消信号中断

```bash
python3 -c "
from sccsos.core.retry_policy import RetryPolicy
import threading

policy = RetryPolicy(None, threading.Lock())
evt = threading.Event()
evt.set()  # 立即取消

try:
    policy.execute(lambda: None, step_id='cancel', max_attempts=5, cancel_event=evt)
    assert False, 'Should have raised'
except Exception as e:
    assert 'cancelled' in str(e)
    print('✅ RetryPolicy 取消信号验证通过')
"
```

---

## 第14章 ContextBuilder 测试场景

### 14.1 基础上下文构建

```bash
python3 -c "
from sccsos.core.context_builder import ContextBuilder
from types import SimpleNamespace

cb = ContextBuilder()
step = SimpleNamespace(agent='test', name='step1', prompt='hello')
ctx, render_fn = cb.build(step, {'prev': {'response': 'ok'}}, 'run-1')

assert ctx['steps'] == {'prev': {'response': 'ok'}}
assert ctx['run_id'] == 'run-1'
assert 'knowledge' not in ctx
assert 'memory' not in ctx
print('✅ ContextBuilder 基础上下文验证通过')
"
```

### 14.2 记忆注入

```bash
python3 -c "
from sccsos.core.context_builder import ContextBuilder
from types import SimpleNamespace

# 模拟 memory_store
class FakeMemory:
    def get_all(self, agent):
        return {'language': 'Python'}

cb = ContextBuilder(memory_store=FakeMemory())
step = SimpleNamespace(agent='coder', name='step1', prompt='write code')
ctx, _ = cb.build(step, {}, 'run-1')
assert ctx['memory'] == {'language': 'Python'}
print('✅ ContextBuilder 记忆注入验证通过')
"
```
