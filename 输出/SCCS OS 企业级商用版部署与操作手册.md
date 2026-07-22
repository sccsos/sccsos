<div class="cover-page">

# SCCS OS 企业级商用版部署与操作手册

**创新研究院 李锋**

v0.11.4 | 2026 年 7 月

SaaS 多租户大规模部署 | K8s 集群 | PostgreSQL + Kafka

</div>

\newpage

# 第一章 架构概述

## 1.1 企业版技术栈

| 组件 | 轻量化版 | 企业级版 | 安装命令 |
|------|----------|----------|----------|
| 数据库 | SQLite | **PostgreSQL** | `pip install "sccsos[pg]"` |
| 事件总线 | LocalEventBus | **Kafka** | `pip install "sccsos[kafka]"` |
| 部署 | Docker / 裸机 | **K8s Helm** | `helm install sccsos ./deploy/helm/` |
| CI/CD | 手动 | **GitHub Actions** | `.github/workflows/ci.yml` |
| 可观测 | 本地日志 | OTEL + Webhook | `sccsos config webhook add` |

**安装方式**：SCCS OS 支持多种安装模式，企业环境推荐通过 WHL 文件离线部署。

```bash
# WHL 文件安装
pip install dist/sccsos-0.16.5-py3-none-any.whl

# WHL 安装后，补装扩展组件
pip install "sccsos[all]"
```

> **说明**：WHL 安装后无需重新构建核心包，通过 `pip install "sccsos[...]"` 按需补装扩展即可。`sccsos doctor` 可用于验证全部依赖状态。

### Hermes Agent 管理

SCCS OS 提供 `sccsos hermes` 命令组，用于企业环境的 Hermes Agent 生命周期管理：

```bash
# ── 安装 ──
sccsos hermes install                        # 一键脚本安装（推荐）
sccsos hermes install --method git -v v0.18.0  # 指定版本安装
sccsos hermes install --method docker        # Docker 部署

# ── 配置 ──
sccsos hermes setup                          # 配置 LLM Provider / API Key
sccsos hermes use <profile>                  # 切换 Profile

# ── 诊断 ──
sccsos hermes doctor                         # 全面诊断
sccsos hermes doctor --fix                   # 诊断并自动修复

# ── 系统依赖 ──
sccsos hermes postinstall                    # 安装 Browser 引擎等依赖
```

> 企业集群部署时，每个 Worker 节点需确保 Hermes Agent 正确安装配置。`sccsos hermes doctor` 可在 CI/CD 流水线中作为前置检查步骤。

## 1.2 部署架构

```
                        ┌─────────────┐
                        │  K8s Ingress │
                        └──────┬──────┘
                               │
                   ┌───────────┴───────────┐
                   │  sccsos Service (ClusterIP) │
                   └───────────┬───────────┘
                               │
              ┌────────────────┼────────────────┐
              │                │                │
     ┌────────▼───────┐ ┌─────▼──────┐ ┌──────▼───────┐
     │  sccsos API    │ │  sccsos    │ │  sccsos      │
     │  (FastAPI)     │ │  (Worker)  │ │  (Worker)    │
     └────┬───────────┘ └─────┬──────┘ └──────┬───────┘
          │                   │               │
     ┌────▼───────────────────▼───────────────▼───────┐
     │           PostgreSQL (RDS)                      │
     │  agents / sessions / audit_log / skills        │
     └────────────────────────────────────────────────┘
     
     ┌────────────────────────────────────────────────┐
     │          Kafka (Event Bus)                      │
     │  sccsos.workflow.started / completed / failed   │
     └────────────────────────────────────────────────┘
```

## 1.3 资源规划

| 资源 | sccsos API | sccsos Worker | PostgreSQL | Kafka |
|------|:----------:|:-------------:|:----------:|:-----:|
| CPU request | 500m | 2000m | 1000m | 1000m |
| CPU limit | 2000m | 4000m | 4000m | 4000m |
| Memory request | 512Mi | 2Gi | 2Gi | 2Gi |
| Memory limit | 2Gi | 4Gi | 8Gi | 8Gi |
| 副本数 (HPA) | 1-5 | 2-10 | 1 (主) | 3 |
| 存储 | — | 10Gi (PVC) | 50Gi (PVC) | 50Gi (PVC) |

# 第二章 部署实施

## 2.1 基础设施准备

```bash
# PostgreSQL
psql -h pg-host -c "CREATE DATABASE sccsos;"
psql -h pg-host -c "CREATE USER sccsos WITH PASSWORD '***';"
psql -h pg-host -c "GRANT ALL PRIVILEGES ON DATABASE sccsos TO sccsos;"

# Kafka Topics（可选，默认自动创建）
kafka-topics --bootstrap-server kafka:9092 --create \
  --topic sccsos.workflow.started --partitions 3 --replication-factor 2
kafka-topics --bootstrap-server kafka:9092 --create \
  --topic sccsos.workflow.completed --partitions 3 --replication-factor 2
kafka-topics --bootstrap-server kafka:9092 --create \
  --topic sccsos.workflow.failed --partitions 3 --replication-factor 2
```

## 2.2 Helm 部署

```bash
# 配置 values.yaml
cat > values.yaml << 'EOF'
image:
  repository: your-registry/sccsos
  tag: "0.11.4"
config:
  database:
    driver: postgres
    dsn: "postgresql://sccsos:***@pg-host:5432/sccsos"
    schema: public
  logging:
    level: INFO
  tracing:
    enabled: true
persistence:
  enabled: true
  size: 10Gi
autoscaling:
  enabled: true
  minReplicas: 2
  maxReplicas: 10
event_bus:
  backend: kafka
  bootstrap_servers: kafka:9092
EOF

# 部署
helm upgrade --install sccsos ./deploy/helm/sccsos \
  -f values.yaml --namespace sccsos --create-namespace

# 验证
kubectl get pods -n sccsos
kubectl get svc -n sccsos
kubectl get hpa -n sccsos
```

## 2.3 配置 Kafka 事件总线

```yaml
# ConfigMap 中注入
event_bus:
  backend: kafka
  bootstrap_servers: kafka:9092
  client_id: sccsos-prod
  group_id: sccsos-events
```

KafkaEventBus 自动发现 `sccsos.*` 主题，跨 Pod 实时同步工作流状态。

## 2.4 数据库迁移（SQLite → PostgreSQL）

```bash
# 1. 导出 SQLite
sqlite3 data/sccsos.db .dump > dump.sql

# 2. 导入 PostgreSQL
psql -h pg-host -d sccsos -f dump.sql

# 3. 切换配置
sccsos config set database.driver postgres
sccsos config set database.dsn "postgresql://user:***@host:5432/sccsos"

# 4. 验证
sccsos health
```

## 2.5 CI/CD 流水线

```yaml
# .github/workflows/ci.yml（项目自带）
触发: push (main/develop) / PR
步骤:
  1. test → pytest (Python 3.11 + 3.12)
  2. lint → ruff + mypy
  3. build → python -m build（仅打 tag）
  4. deploy → helm upgrade（仅 main）
```

```bash
# 触发部署
git tag v0.11.4
git push origin v0.11.4
# 自动: test → lint → build → helm deploy
```

# 第三章 多租户管理

## 3.1 三层隔离模型

| 层 | 隔离机制 | 实现 |
|----|----------|------|
| **数据层** | `tenant_id` 列过滤 | 全部核心表含 tenant_id |
| **运行时层** | `RuntimeFactory` per-tenant | `get_runtime(tenant_id)` |
| **API 层** | `X-Tenant-ID` 头部 | FastAPI 中间件透传 |

## 3.2 租户操作

```bash
# CLI 按租户过滤
sccsos agent list --tenant tenant-a
sccsos workflow list --tenant tenant-b
sccsos memory list architect --tenant tenant-a

# API 请求
curl -H "X-Tenant-ID: tenant-a" http://sccsos:8765/api/v1/agents
```

## 3.3 租户级策略

```yaml
policies:
  named:
    gold-tenant:                  # 金租户
      max_cost_usd: 100.0
      max_tokens_per_session: 500000
      allowed_tools: [read_file, search_files, web_search,
                      web_extract, terminal, delegate_task]
    silver-tenant:                # 银租户
      max_cost_usd: 20.0
      max_tokens_per_session: 100000
      allowed_tools: [read_file, search_files, web_search]

model_pool:                       # 租户模型路由
  models:
    - name: gold-v4
      model: deepseek-v4-pro
      capabilities: [reasoning, code]
    - name: silver-v4
      model: deepseek-v4-flash
      capabilities: [chat, quick]
```

# 第四章 完整功能参考

## 4.1 全部命令速查

```bash
# === Agent 管理（10 子命令）===
sccsos agent create <name>            # 创建
sccsos agent list [--tenant]          # 列表
sccsos agent start <name>             # 启动
sccsos agent stop <name>              # 停止
sccsos agent pause <name>             # 暂停
sccsos agent resume <name>            # 恢复
sccsos agent restart <name>           # 重启
sccsos agent ask <name> <prompt>      # 对话
sccsos agent status <name>            # 状态
sccsos agent logs <name>              # 日志

# === 工作流（6 子命令）===
sccsos workflow run <file> [-i input] # 运行
sccsos workflow list [--tenant]       # 列表
sccsos workflow status <id>           # 状态
sccsos workflow cancel <id>           # 取消
sccsos workflow validate <file>       # 验证
sccsos workflow visualize <file>      # 可视化

# === 技能市场（9 子命令）===
sccsos skill publish <file> [--author]  # 发布
sccsos skill submit <name>              # 提交审批
sccsos skill approve <name>             # 通过
sccsos skill reject <name> [--reason]   # 驳回
sccsos skill list [--status] [--type]   # 列表
sccsos skill show <name> [-v version]   # 查看
sccsos skill install <name> [-d dir]    # 安装
sccsos skill archive <name>             # 归档
sccsos skill remove <name>              # 移除

# === 配置管理（3 + 4 子命令）===
sccsos config show [--webhooks] [--policies]  # 查看
sccsos config reload                           # 重载
sccsos config webhook list                     # Webhook 列表
sccsos config webhook add <url> [--events]     # Webhook 添加
sccsos config webhook remove <url|idx>         # Webhook 删除
sccsos config webhook test [target]            # Webhook 测试

# === 审计计费（3 子命令）===
sccsos audit report [--since] [--agent]  # 审计报告
sccsos audit log [--limit] [--agent]     # 审计日志
sccsos audit billing [--since] [--csv]   # 计费报表

# === 记忆（5 子命令）===
sccsos memory save <agent> <key> <val> [--ttl]
sccsos memory get <agent> <key>
sccsos memory list <agent>
sccsos memory delete <agent> <key>
sccsos memory clear <agent>

# === 会话（3 子命令）===
sccsos session list [--agent] [--tenant]
sccsos session show <id>
sccsos session close <id>

# === Personality 版本（6 子命令）===
sccsos personality list
sccsos personality save <name> [change_log]
sccsos personality show <name> [-v version]
sccsos personality rollback <name> <version>
sccsos personality validate
sccsos personality clean [--keep N]

# === 追踪（2 子命令）===
sccsos trace list
sccsos trace show <id>

# === 系统（6 命令）===
sccsos version
sccsos health
sccsos doctor
sccsos init [--dir] [--samples]
sccsos serve [--port] [--host] [--legacy]
```

## 4.2 全部 API 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/` | 管理控制台首页 |
| GET | `/admin` | 管理控制台 |
| GET | `/docs` | OpenAPI 文档 |
| WS | `/api/v1/ws` | 实时事件流 |
| GET | `/api/v1/health` | 系统健康 |
| GET | `/api/v1/agents` | Agent 列表 |
| POST | `/api/v1/agents/register` | 注册 Agent |
| GET/POST | `/api/v1/agents/{name}/*` | Agent CRUD |
| GET/POST | `/api/v1/workflows/*` | 工作流 CRUD |
| GET/POST | `/api/v1/sessions/*` | 会话 CRUD |
| GET | `/api/v1/traces/*` | 追踪查询 |
| GET | `/api/v1/audit/*` | 审计查询 |
| GET | `/api/v1/skills` | 技能列表 |

# 第五章 安全体系

## 5.1 三层安全防线

```
┌─────────────────────────────────────────────────────────────┐
│ 第一层: API 安全                                             │
│  ├─ X-Tenant-ID → 租户数据隔离                               │
│  ├─ RateLimiter → 100 请求/秒/租户                           │
│  └─ FastAPI CORS → 跨域控制                                  │
├─────────────────────────────────────────────────────────────┤
│ 第二层: Prompt 安全                                          │
│  ├─ PromptInjectionGuard → 注入指令检测                      │
│  └─ 关键词匹配: "忽略之前指令" / "system" / "你是一个"        │
├─────────────────────────────────────────────────────────────┤
│ 第三层: 执行安全                                             │
│  ├─ PolicyEngine → 工具 ACL + budget 控制                   │
│  ├─ CommandWhitelist → 危险命令拦截                          │
│  └─ AuditLog → 全链路操作审计                                │
└─────────────────────────────────────────────────────────────┘
```

## 5.2 K8s NetworkPolicy 限制

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: sccsos-isolate
spec:
  podSelector:
    matchLabels:
      app.kubernetes.io/name: sccsos
  policyTypes:
    - Ingress
    - Egress
  ingress:
    - from:
        - podSelector:
            matchLabels:
              app.kubernetes.io/name: sccsos
  egress:
    - to:
        - ipBlock:
            cidr: 0.0.0.0/0
```

# 第六章 技能市场运营

## 6.1 运营流程

```
开发者                    审核者                    使用者
  │                        │                        │
  ├─ publish ──→ draft ──┐ │                        │
  │                      │ │                        │
  ├─ submit ──→ in_review─┼─┤                        │
  │                      │ │                        │
  │                      │ ├─ approve ──→ published ──┼─→ install
  │                      │ │                        │
  │                      │ └─ reject ──→ rejected    │
  │                                                │
  │                              └─ archive ──→ archived
```

## 6.2 完整操作示例

```bash
# 1. 开发者发布
sccsos skill publish personalities/nlp-agent.yaml \
  --author "Alice" \
  --tag nlp --tag translation

# 2. 提交审批
sccsos skill submit nlp-agent

# 3. 审核者查看待审
sccsos skill list --status in_review

# 4. 审核者审批（或驳回）
sccsos skill approve nlp-agent
# sccsos skill reject nlp-agent --reason "缺少 system_prompt"

# 5. 使用者安装
sccsos skill install nlp-agent
```

# 第七章 计费与计量

## 7.1 定价模型

```json
{
  "version": 1,
  "models": {
    "deepseek-v4-flash":  [0.14, 0.28],
    "deepseek-v4-pro":    [0.44, 0.87],
    "gpt-4o":            [2.50, 10.00]
  }
}
```

格式：`[$input_price, $output_price]` 每百万 Token 成本。

## 7.2 计费报表

```bash
# 终端报表
sccsos audit billing
# Billing Summary
# ================
#   Total calls:     156
#   Total tokens:    1,234,567
#   Total cost:      $0.4321
# Cost by Model:
#   deepseek-v4-flash   $0.2800
# Cost by Day (last 7):
#   2026-07-20  $0.1200

# CSV 导出
sccsos audit billing --csv > billing-$(date +%Y%m).csv
```

# 第八章 运维管理

## 8.1 滚动升级

```bash
# 更新版本
helm upgrade sccsos ./deploy/helm/sccsos --set image.tag=0.12.0

# 监控
kubectl rollout status deployment/sccsos -n sccsos
```

## 8.2 扩缩容

```bash
# 手动
kubectl scale deployment/sccsos --replicas=5 -n sccsos

# 自动（HPA）
# min=2, max=10, targetCPU=70%
kubectl get hpa -n sccsos
```

## 8.3 数据备份

```bash
# PostgreSQL
pg_dump -h pg-host -U sccsos sccsos > backup-$(date +%Y%m%d).sql

# 定时备份（K8s CronJob）
kubectl create cronjob sccsos-backup --schedule="0 2 * * *" \
  --image=postgres:16 -- pg_dump postgresql://sccsos:***@pg-host:5432/sccsos
```

## 8.4 监控告警

```bash
# 健康检查
curl http://sccsos:8765/api/v1/health

# Webhook 告警
sccsos config webhook add https://alert.company.com/sccsos \
  --events failed --secret whsec_alert

# 查看日志
kubectl logs -l app.kubernetes.io/name=sccsos -n sccsos | jq '.'
```

## 8.5 故障排查

| 症状 | 排查步骤 |
|------|----------|
| Pod 启动失败 | `kubectl describe pod -n sccsos` → Events |
| 数据库连接失败 | `sccsos health` → Database 状态 |
| Kafka 事件未送达 | 检查 Kafka consumer group: `kafka-consumer-groups --group sccsos-events` |
| Agent 不响应 | `sccsos agent logs <name>` → 检查 Hermes 连接 |
| 技能安装失败 | `sccsos skill show <name>` → 确认状态为 published |

# 第九章 功能对比

## 9.1 两版功能矩阵

| 功能模块 | 轻量化版 | 企业级版 |
|----------|:-------:|:--------:|
| CLI 14 命令组（45+ 子命令） | ✅ | ✅ |
| FastAPI 27 路由 | ✅ | ✅ |
| admin.html 7 标签页 | ✅ | ✅ |
| Agent 5 状态状态机 | ✅ | ✅ |
| DAG 工作流 + 条件 + 并行 | ✅ | ✅ |
| Jinja2 模板 + 自定义过滤器 | ✅ | ✅ |
| 失败重试（指数退避） | ✅ | ✅ |
| 技能市场（9 子命令） | ✅ | ✅ |
| 技能审批流程 | ✅ | ✅ |
| 工具权限 ACL + 命令白名单 | ✅ | ✅ |
| Prompt 注入防护 | ✅ | ✅ |
| 全链路审计 + 计费 | ✅ | ✅ |
| 持久记忆（KV + TTL） | ✅ | ✅ |
| 会话管理 | ✅ | ✅ |
| Personality 版本控制 + 回滚 | ✅ | ✅ |
| 链路追踪 | ✅ | ✅ |
| 配置热重载 | ✅ | ✅ |
| sccsos doctor 依赖检查 | ✅ | ✅ |
| **SQLite 数据库** | **✅ 默认** | ❌ |
| **PostgreSQL 数据库** | ❌ | **✅** |
| **LocalEventBus** | **✅ 默认** | ❌ |
| **Kafka 事件总线** | ❌ | **✅** |
| **Docker 部署** | **✅** | ❌ |
| **Helm Chart 部署** | ❌ | **✅** |
| **HPA 自动扩缩容** | ❌ | **✅** |
| **GitHub Actions CI/CD** | ❌ | **✅** |
| **K8s NetworkPolicy** | ❌ | **✅** |

## 9.2 版本升级路径

```
轻量化版 (SQLite + Local) 
    │
    ├── 改 database.driver = postgres → PostgreSQL
    ├── 改 event_bus.backend = kafka → Kafka
    ├── helm install → K8s 部署
    └── git push tag → CI/CD 自动
    │
企业级版 (PG + Kafka + K8s + CI/CD)
```