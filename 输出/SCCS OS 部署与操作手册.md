<div class="cover-page">

# SCCS OS 部署与操作手册

> 版本: v0.14.2 | 更新: 2026-07-26 | 架构评分 9.0/10

创新研究院 李锋

v1.0 | 2026 年 7 月

涵盖：环境部署 · 操作指南

</div>

\newpage

# 目录

- **第1章 环境与部署**
- **第2章 操作指南**
- **第3章 实战案例**
- **附录**
  - 附录A：项目目录结构
  - 附录B：Agent 定义 YAML 参考
  - 附录C：技术决策清单

\newpage

# 第1章 部署场景详解

## 1.1 部署方案矩阵

SCCS OS 支持四种部署场景，覆盖从开发到生产的全链路需求：

| 场景 | 环境 | 规模 | 数据库 | 消息总线 | 可观测性 | 适用场景 |
|------|------|:----:|--------|---------|---------|---------|
| **方案一：单实例裸机** | macOS / Linux | 1 节点 | SQLite | LocalEventBus | 内置（无 OTel） | 开发调试、个人使用 |
| **方案二：单实例 Docker** | Docker / macOS / Linux | 1 容器 | SQLite | LocalEventBus | 内置（无 OTel） | 快速体验、CI/CD |
| **方案三：集群简单部署** | Kubernetes ≥ 1.25 | 1~5 副本 | SQLite → PostgreSQL | LocalEventBus → Kafka | 内置 + OTel 可选 | 小团队、Demo 环境 |
| **方案四：集群全量企业级** | Kubernetes → 生产集群 | 3~10 副本 | PostgreSQL (HA) | Kafka (集群) | OTel → Prometheus → Grafana | 生产环境、多租户 |

## 1.2 前置条件与关联系统

### 1.2.1 核心依赖 — Hermes Agent 底座

Hermes Agent 是 SCCS OS 的底层运行时底座，**所有部署场景均需安装**。

```bash
# ── 安装 ──────────────────────────────────────────────
pip install hermes-agent

# ── 验证 ──────────────────────────────────────────────
hermes --version
# 预期: hermes 0.24.x

# ── 初始化配置向导 ─────────────────────────────────────
hermes setup
# 按提示配置：provider、model、API key

# ── 验证 profile 就绪 ─────────────────────────────────
hermes chat "Hello"     # 测试对话正常
hermes doctor           # 检查所有配置项
```

**Hermes Agent 依赖清单**：

| 组件 | 版本要求 | 说明 |
|------|---------|------|
| Python | ≥ 3.11 | 运行时环境 |
| pip | ≥ 23.0 | Python 包管理 |
| Git | ≥ 2.30 | 技能市场拉取（可选） |
| LLM API Key | — | DeepSeek / OpenAI / Anthropic 等 |
| 磁盘空间 | ≥ 500MB | 缓存 + 技能 + 数据库 |

**Hermes Profile 配置**（必须存在至少一个可用 profile）：

```bash
# 查看已有 profiles
hermes config list-profiles
# 预期输出至少包含 "sccsos" 或 "default"

# 如无可用 profile，手动创建
hermes config create-profile sccsos
hermes config set --profile sccsos provider deepseek
hermes config set --profile sccsos model deepseek-chat
hermes config set --profile sccsos api_key <your-api-key>
```

### 1.2.2 LLM API 服务

| 服务商 | 推荐模型 | API 地址 | 获取方式 |
|--------|---------|---------|---------|
| DeepSeek | deepseek-chat | https://api.deepseek.com | 官网注册 |
| OpenAI | gpt-4o | https://api.openai.com | OpenAI Platform |
| Anthropic | claude-sonnet-4 | https://api.anthropic.com | Anthropic Console |

> 所有使用场景需要至少配置一个 LLM API Key。SCCS OS 通过 Hermes Agent 间接调用 LLM，不直接管理 API Key。

### 1.2.3 数据库选项

| 选项 | 场景 | 配置方式 |
|------|------|---------|
| SQLite（默认） | 方案一/二 | 零配置，自动创建 |
| PostgreSQL | 方案三/四 | `pip install sccsos[pg]` + 配置 DSN |

### 1.2.4 消息总线选项

| 选项 | 场景 | 依赖 |
|------|------|------|
| LocalEventBus（默认） | 方案一/二/三 | 零配置，进程内 pub/sub |
| KafkaEventBus | 方案三/四 | `pip install sccsos[kafka]` + Kafka 集群 |

### 1.2.5 可观测性栈（仅方案四）

| 组件 | 用途 | 部署方式 |
|------|------|---------|
| OpenTelemetry Collector | 指标/追踪收集 | DaemonSet |
| Prometheus | 指标存储 + 告警 | Prometheus Operator |
| Grafana | 可视化和仪表盘 | Grafana Operator |
| Loki（可选） | 日志聚合 | Loki Stack |

## 1.3 方案一：单实例裸机部署

### 1.3.1 适用场景

- 开发者本地调试
- 个人学习与实验
- 轻量级任务调度

### 1.3.2 前置条件

```bash
# 1. Python 3.11+
python3 --version

# 2. Hermes Agent 已安装
hermes --version

# 3. Hermes profile 已配置
hermes config list-profiles

# 4. LLM API Key 可访问
hermes chat "ping" --quiet
```

### 1.3.3 安装 SCCS OS

```bash
# 最小安装（CLI + 核心）
pip install sccsos

# 全功能安装（含 API 服务器 + 可选组件）
pip install sccsos[all]

# 验证安装
sccsos version
# 预期: sccsos v0.14.2
```

### 1.3.4 初始化项目

```bash
# 创建一个新项目
sccsos init my-sccsos-project
cd my-sccsos-project

# 查看项目结构
ls -la
# sccsos.yaml          # 项目配置
# agents/              # Agent YAML 定义
# workflows/           # 工作流定义
# personalities/       # 角色设定
```

### 1.3.5 配置 Hermes Profile 关联

编辑 `sccsos.yaml` 确保 Hermes profile 配置正确：

```yaml
hermes:
  profile: sccsos          # 使用的 Hermes profile 名称
  adapter: subprocess      # 子进程通信模式

agents:
  path: ./agents
  wiki_path: ./wiki        # 知识库路径（可选）
  personalities_path: ./personalities

database:
  type: sqlite             # 单实例场景使用 SQLite
  path: ./data/sccsos.db
```

### 1.3.6 启动与验证

```bash
# 1. 健康检查
sccsos health
# 预期:
#   -- SCCS OS Health --
#   Version:   0.14.2
#   Database:  ok
#   Hermes:    OK
#   Agents:    0 registered

# 2. 注册 Agent
sccsos agent create architect

# 3. 启动 Agent（后台进程）
sccsos agent start architect

# 4. 对话验证
sccsos agent ask architect "Hello，请用一句话介绍自己"
# 预期: Agent 返回自我介绍

# 5. 运行示例工作流
sccsos workflow run workflows/示例.yaml

# 6. 启动 API 服务器（可选）
python -m sccsos.api.fastapi_app --port 8765
# 访问 http://localhost:8765/health
```

### 1.3.7 目录结构

```
my-sccsos-project/
├── sccsos.yaml              # 项目配置
├── agents/                  # Agent 定义
│   └── architect.yaml       # 示例 Agent
├── workflows/               # 工作流
│   └── 示例.yaml
├── personalities/           # 角色设定
├── wiki/                    # 知识库（可选）
├── data/                    # 运行时数据（自动创建）
│   ├── sccsos.db            # SQLite 数据库
│   └── traces/              # 追踪导出
└── logs/                    # 日志目录
    └── sccsos.log
```

## 1.4 方案二：单实例 Docker 部署

### 1.4.1 适用场景

- 快速体验（无需 Python 环境）
- CI/CD 流水线集成
- 标准化运行环境

### 1.4.2 前置条件

```bash
# Docker Engine ≥ 24.0
docker --version

# docker-compose（可选，推荐）
docker compose version
```

### 1.4.3 容器镜像

```bash
# 从源码构建
cd /path/to/sccsos
docker build -t sccsos:0.14.2 .

# 从 registry 拉取（如已推送）
docker pull your-registry/sccsos:0.14.2
```

### 1.4.4 Docker CLI 直接运行

```bash
# ── 创建持久化数据目录 ─────────────────────────────────
mkdir -p ~/sccsos-data/{data,logs,traces,agents,workflows,personalities}

# ── 复制默认配置文件 ────────────────────────────────────
cp sccsos.yaml ~/sccsos-data/
cp -r agents/* ~/sccsos-data/agents/
cp -r workflows/* ~/sccsos-data/workflows/
cp -r personalities/* ~/sccsos-data/personalities/

# ── 运行容器 ───────────────────────────────────────────
docker run -d \
  --name sccsos \
  -p 8765:8765 \
  -v ~/sccsos-data/data:/sccsos/data \
  -v ~/sccsos-data/logs:/sccsos/logs \
  -v ~/sccsos-data/traces:/sccsos/traces \
  -v ~/sccsos-data/agents:/sccsos/agents:ro \
  -v ~/sccsos-data/workflows:/sccsos/workflows:ro \
  -v ~/sccsos-data/personalities:/sccsos/personalities:ro \
  -v ~/sccsos-data/sccsos.yaml:/sccsos/sccsos.yaml:ro \
  -e HERMES_PROFILE=sccsos \
  sccsos:0.14.2
```

### 1.4.5 Docker Compose（推荐）

使用项目自带的 `docker-compose.yaml`：

```yaml
version: "3.8"
services:
  sccsos:
    build: .
    image: sccsos:0.14.2
    container_name: sccsos
    ports:
      - "8765:8765"
    volumes:
      - sccsos_data:/sccsos/data        # SQLite 数据库
      - sccsos_logs:/sccsos/logs        # 应用日志
      - sccsos_traces:/sccsos/traces    # 追踪导出
      - ./agents:/sccsos/agents:ro      # Agent 定义（只读）
      - ./workflows:/sccsos/workflows:ro
      - ./personalities:/sccsos/personalities:ro
      - ./wiki:/sccsos/wiki:ro          # 知识库（可选）
    environment:
      - SCCSOS_CONFIG=/sccsos/sccsos.yaml
      - HERMES_PROFILE=sccsos
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "python3", "-m", "sccsos", "health"]
      interval: 30s
      timeout: 10s
      retries: 3

volumes:
  sccsos_data:
  sccsos_logs:
  sccsos_traces:
```

启动：

```bash
docker compose up -d

# 查看日志
docker compose logs -f

# 验证健康
curl http://localhost:8765/health
# 预期: {"status": "ok", "version": "0.14.2", ...}

# 停止
docker compose down

# 停止并删除数据卷
docker compose down -v
```

### 1.4.6 与 Hermes Agent 的集成说明

容器内已预装 Hermes Agent，但 LLM API Key 需要通过环境变量或配置文件传递：

```yaml
# docker-compose.yaml 中补充
environment:
  - HERMES_PROFILE=sccsos
  - DEEPSEEK_API_KEY=${DEEPSEEK_API_KEY}
  # 或通过 mounted config
  - HERMES_CONFIG=/sccsos/hermes.yaml
volumes:
  - ~/.hermes:/root/.hermes:ro   # 挂载宿主 Hermes 配置
```

## 1.5 方案三：集群简单部署

### 1.5.1 适用场景

- 小团队使用（3~10 人）
- Demo / Staging 环境
- 需要基本 HA 的场景

### 1.5.2 前置条件

```bash
# Kubernetes 集群
kubectl cluster-info

# 开发集群推荐
kind create cluster --name sccsos    # 或 minikube start

# 工具链
kubectl version --short     # ≥ 1.25
docker --version            # ≥ 24.0
helm version --short        # ≥ 3.12（可选）
```

### 1.5.3 构建并推送镜像

```bash
cd /path/to/sccsos

# 1. 构建
docker build -t sccsos:0.14.2 .

# 2. 推送到 registry
docker tag sccsos:0.14.2 your-registry/sccsos:0.14.2
docker push your-registry/sccsos:0.14.2

# 3. 本地 kind 集群（无需推送）
kind load docker-image sccsos:0.14.2 --name sccsos
```

### 1.5.4 部署

```bash
# 一键部署全部资源
kubectl apply -f deploy/k8s/

# 或分批部署（便于排查问题）：
kubectl apply -f deploy/k8s/00-namespace.yaml
kubectl apply -f deploy/k8s/10-configmap.yaml
kubectl apply -f deploy/k8s/20-pvc.yaml
kubectl apply -f deploy/k8s/30-deployment.yaml
kubectl apply -f deploy/k8s/40-service.yaml
kubectl apply -f deploy/k8s/50-hpa.yaml
```

### 1.5.5 验证

```bash
# 检查 Pod
kubectl -n sccsos get pods -w

# 端口转发访问
kubectl -n sccsos port-forward svc/sccsos 8765:8765 &
curl http://localhost:8765/health

# 查看日志
kubectl -n sccsos logs -f deployment/sccsos
```

### 1.5.6 资源配置

| 资源 | Request | Limit |
|------|---------|-------|
| CPU | 250m | 1000m |
| 内存 | 512Mi | 2Gi |
| 存储 (PVC) | 10Gi (data) + 5Gi (logs) |

### 1.5.7 HPA 自动扩缩容

```yaml
# deploy/k8s/50-hpa.yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
spec:
  minReplicas: 1
  maxReplicas: 5
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 70
```

## 1.6 方案四：集群全量企业级部署

### 1.6.1 适用场景

- 生产环境多租户
- 大规模并发（500+ 请求）
- 需 99.9% 可用性保证
- 完整可观测性 + 审计合规

### 1.6.2 关联系统全景图

![企业级部署架构全景](images/sccsos-enterprise-deployment-light.png)

*图 1-6: SCCS OS 企业级部署全景架构 — Ingress → SCCS OS 集群 → 中间件层 → 可观测性栈*

### 1.6.3 前置条件

**基础设施**：

| 组件 | 版本 | 用途 | 部署方式 |
|------|------|------|---------|
| Kubernetes | ≥ 1.25 | 容器编排 | 托管集群（EKS/AKS/GKE/TKE） |
| Ingress Controller | 最新 | 流量入口 | nginx-ingress / ALB |
| Cert-Manager | ≥ 1.12 | TLS 证书 | Helm Chart |
| StorageClass | SSD | 持久化存储 | 集群预配置 |

**关联系统**：

| 系统 | 版本 | 用途 | HA 要求 |
|------|------|------|:-------:|
| PostgreSQL | ≥ 14 | 持久化数据库 | ✅ 主从 |
| Kafka | ≥ 3.5 | 跨实例消息总线 | ✅ 3 节点 |
| Redis | ≥ 7 | Session 共享 | ✅ 哨兵 |
| OpenTelemetry Collector | ≥ 0.90 | 指标/追踪收集 | DaemonSet |
| Prometheus | ≥ 2.50 | 指标存储 | ✅ Operator |
| Grafana | ≥ 10 | 可视化 + 告警 | Operator |

### 1.6.4 Helm Chart 部署（推荐）

```bash
# ── 1. 安装 PostgreSQL ───────────────────────────────────
helm repo add bitnami https://charts.bitnami.com/bitnami
helm install sccsos-pg bitnami/postgresql-ha \
  --namespace sccsos --create-namespace \
  --set postgresql.replicaCount=2 \
  --set persistence.size=50Gi

# ── 2. 安装 Kafka ────────────────────────────────────────
helm install sccsos-kafka bitnami/kafka \
  --namespace sccsos \
  --set replicas=3 \
  --set persistence.size=20Gi

# ── 3. 安装 SCCS OS ──────────────────────────────────────
helm install sccsos ./deploy/helm/sccsos \
  --namespace sccsos \
  -f my-production-values.yaml
```

`my-production-values.yaml` 参考配置：

```yaml
image:
  repository: your-registry/sccsos
  tag: 0.14.2
  pullPolicy: Always
  pullSecrets:
    - name: regcred

replicaCount: 3

config:
  database:
    type: postgresql
    dsn: postgresql://sccsos:password@sccsos-pg-postgresql-ha:5432/sccsos

  event_bus:
    backend: kafka
    bootstrap_servers: sccsos-kafka:9092
    client_id: sccsos-prod

  tracing:
    enabled: true
    otlp_endpoint: http://otel-collector:4318/v1/traces
    export_path: /sccsos/traces

  policies:
    default:
      max_cost_usd: 100.0
      allowed_commands:
        - read_file
        - search_files
        - web_search

ingress:
  enabled: true
  host: sccsos.your-company.com
  tls: true
  annotations:
    cert-manager.io/cluster-issuer: letsencrypt-prod

resources:
  requests:
    cpu: 500m
    memory: 1Gi
  limits:
    cpu: 2
    memory: 4Gi

autoscaling:
  enabled: true
  minReplicas: 3
  maxReplicas: 10
  targetCPUUtilizationPercentage: 70
  targetMemoryUtilizationPercentage: 80
```

### 1.6.5 配置可观测性栈

```bash
# OTel Collector
helm install otel-collector open-telemetry/opentelemetry-collector \
  --namespace sccsos \
  -f otel-collector-config.yaml

# Prometheus + Grafana
helm install prometheus prometheus-community/kube-prometheus-stack \
  --namespace monitoring --create-namespace

# 导入 Grafana Dashboard
kubectl -n monitoring port-forward svc/prometheus-grafana 3000:80
# → 浏览器打开 localhost:3000，导入 deploy/grafana/sccsos-dashboard.json
```

### 1.6.6 安全加固

```yaml
# sccsos.yaml 生产配置
security:
  rbac:
    enabled: true
    default_role: viewer

  rate_limiting:
    enabled: true
    max_requests_per_minute: 60

  audit:
    log_all_operations: true
    retention_days: 90

  tls:
    enabled: true
    cert_path: /etc/tls/tls.crt
    key_path: /etc/tls/tls.key
```

### 1.6.7 备份策略

| 数据 | 备份方式 | 频率 | 保留期 |
|------|---------|:----:|:------:|
| PostgreSQL 数据库 | pg_dump + S3 | 每日 | 30 天 |
| 配置文件 | Git 版本管理 | 每次部署 | 永久 |
| 日志 | Loki 内置 | 实时 | 90 天 |
| 追踪数据 | OTel + 冷存储 | 实时 | 7 天 |

```bash
# PostgreSQL 备份脚本示例
#!/bin/bash
BACKUP_FILE="sccsos-$(date +%Y%m%d).sql.gz"
PGPASSWORD=password pg_dump -h sccsos-pg -U sccsos sccsos | gzip > /backups/$BACKUP_FILE
aws s3 cp /backups/$BACKUP_FILE s3://sccsos-backups/
```

### 1.6.8 验证清单

```bash
# 1. Pod 全部 Running
kubectl -n sccsos get pods
# 预期: sccsos-xxx   3/3 Running
#       sccsos-pg-*  2/2 Running
#       sccsos-kafka-* 3/3 Running

# 2. API 可用
curl -k https://sccsos.your-company.com/health

# 3. 数据库连接正常
kubectl -n sccsos exec deployment/sccsos -- sccsos health

# 4. Kafka 消息可达（启动两个 workflow 验证事件）
sccsos workflow run workflows/示例.yaml

# 5. OTel 链路导出（检查 Grafana -> Explore -> traces）
kubectl -n sccsos port-forward svc/prometheus-grafana 3000:80
# → 查看 sccsos_workflow_runs_total 指标

# 6. 跨 Pod WebSocket 通信
# 在 Grafana 中确认 WebSocket 连接数 > 0

# 7. TLS 证书有效
curl -kv https://sccsos.your-company.com/health 2>&1 | grep "SSL certificate"
```

## 1.7 部署方案选择决策树

![部署方案选择决策树](images/sccsos-deployment-decision-tree-light.png)

*图 1-7: SCCS OS 部署方案选择决策树 — 从使用场景引导到四个部署方案*

## 2.3 目录复制式安装（替代方案）

适用于离线部署、批量克隆、备份恢复等无法通过 `pip install` 在线安装的场景。
通过拷贝已有的 Hermes Agent 安装目录和 Profile 数据目录完成部署。

**适用场景：**

| 场景 | 说明 |
|------|------|
| 离线/内网部署 | 服务器无外网访问权限，无法从 PyPI 安装 |
| 批量节点克隆 | 多台服务器需要完全一致的 Hermes 环境 |
| 备份恢复 | 从备份目录快速恢复运行环境 |
| 环境标准化 | 将预配置好的模板环境分发到多台机器 |

**前置条件：**

准备**两个源目录**和**两个目标目录**：

| 参数 | 含义 | 示例 |
|------|------|------|
| SRC_AGENT | 源 Hermes Agent 程序目录（含 bin/、lib/ 等） | `/backup/hermes-agent/` |
| SRC_PROFILE | 源 Profile 数据目录（含 config.yaml、.env 等） | `/backup/profile-sccsos/` |
| DST_AGENT | 目标机器程序安装目录 | `/opt/hermes-agent/` |
| DST_PROFILE | 目标机器 Profile 数据目录 | `/data/hermes/sccsos/` |

前提要求：

1. 源目录与新服务器的 Python 主版本一致（如均为 Python 3.11+）
2. 源 Hermes Agent 版本 >= 0.18.0
3. 新服务器端口、网络、大模型接口连通性正常
4. 关闭源机器的 Hermes 进程，避免文件锁冲突

**安装步骤：**

第一步：拷贝源目录到目标位置

```bash
## 拷贝程序目录
cp -a SRC_AGENT DST_AGENT

## 拷贝 Profile 数据目录
cp -a SRC_PROFILE DST_PROFILE
```

**第二步：清理旧环境运行残留**

旧机器进程的 PID 文件、锁文件、临时套接字会导致新环境启动失败：

```bash
cd DST_PROFILE

## 删除进程 PID 和运行缓存
rm -f gateway.pid processes.json

## 清理临时套接字和锁文件
rm -rf tmp/ sockets/

## 清空历史日志（可选）
rm -rf logs/*.log
```

**第三步：修正目录权限**

```bash
## 程序目录：可执行
chmod -R 755 DST_AGENT
chmod +x DST_AGENT/bin/*

## Profile 数据目录：严格保密
chmod -R 700 DST_PROFILE
chmod 600 DST_PROFILE/.env
```

**第四步：配置环境变量**

```bash
## 写入 ~/.bashrc（替换为实际路径）
cat >> ~/.bashrc << 'EOF'
export HERMES_HOME="DST_PROFILE"
export PATH="DST_AGENT/bin:$PATH"
EOF

## 生效配置
source ~/.bashrc
```

**第五步：重装 Python 依赖**

不同服务器的 Python 环境存在差异，必须重新适配依赖：

```bash
cd DST_AGENT
pip install . --force-reinstall
```

**第六步：修复配置文件中的绝对路径**

拷贝的 `config.yaml` 中可能包含源机器的绝对路径，需批量替换：

```bash
## 进入 Profile 目录
cd DST_PROFILE

## 检查并修正 config.yaml 中的路径
## 重点关注：
##   - terminal.cwd：终端默认工作目录
##   - 模型文件路径（如有本地模型）
##   - 自定义技能/定时任务的输出目录
##   - 内网模型服务地址（如 Ollama、向量库 API 地址）
```

`.env` 文件仅需修改路径类变量，API 密钥、Token 等认证参数无需修改。

**第七步：验证安装**

```bash
## 验证环境变量
echo $HERMES_HOME

## 验证 CLI 可用
hermes --version

## 运行环境自检
hermes doctor
```

**一键迁移脚本：**

以下脚本整合上述全部步骤（需手动修改开头的目录路径）：

```bash
#!/bin/bash
## Hermes Agent 目录复制迁移一键修复脚本
## 使用前请修改 AGENT_PATH 和 PROFILE_PATH 为实际路径

AGENT_PATH="/opt/hermes-agent"       # 目标程序目录
PROFILE_PATH="/data/hermes/sccsos"  # 目标 Profile 目录

echo "========== 开始 Hermes 目录复制安装 =========="

## 1. 清理残留
echo "1. 清理旧进程缓存与锁文件..."
rm -rf ${PROFILE_PATH}/gateway.pid ${PROFILE_PATH}/processes.json
rm -rf ${PROFILE_PATH}/tmp ${PROFILE_PATH}/sockets
rm -rf ${PROFILE_PATH}/logs/*.log

## 2. 修正权限
echo "2. 配置目录权限..."
chmod -R 755 ${AGENT_PATH}
chmod +x ${AGENT_PATH}/bin/*
chmod -R 700 ${PROFILE_PATH}
chmod 600 ${PROFILE_PATH}/.env

## 3. 写入环境变量（避免重复添加）
echo "3. 配置系统环境变量..."
if ! grep -q "HERMES_HOME" ~/.bashrc; then
cat >> ~/.bashrc << EOF
export HERMES_HOME=${PROFILE_PATH}
export PATH=${AGENT_PATH}/bin:\$PATH
EOF
fi
source ~/.bashrc

## 4. 重装依赖
echo "4. 重装 Python 依赖..."
cd ${AGENT_PATH}
pip install . --force-reinstall

echo "========== 目录复制安装完成 =========="
echo "HERMES_HOME: $HERMES_HOME"
hermes --version
echo "请手动检查 config.yaml 中的绝对路径是否正确"
```

**两种安装方式对比：**

| 对比维度 | pip 在线安装 | 目录复制式安装 |
|----------|-------------|---------------|
| 网络要求 | 需要 PyPI 访问 | 无需网络（离线可用） |
| 安装速度 | 依赖下载速度 | 本地拷贝，速度快 |
| 版本一致性 | 安装时指定版本 | 与源目录完全一致 |
| 配置迁移 | 需手动配置 | 配置随目录完整迁移 |
| 批量部署 | 每台机器单独安装 | 一次准备，批量分发 |
| 适用场景 | 首次安装、开发环境 | 离线部署、批量克隆、灾备 |

## 2.4 Hermes Profile 配置

SCCS OS 依赖 Hermes profile 运行。确保已配置 sccsos profile：

```bash
## 查看现有 profile
hermes profile list

## 如无 sccsos profile，创建或切换到现有 profile
hermes profile use sccsos

## 查看 profile 详情
hermes profile show sccsos
```

profile 配置要求：

| 配置项 | 推荐值 | 说明 |
|--------|--------|------|
| 模型 | deepseek-v4-flash | 默认推理模型 |
| 降级模型 | deepseek-chat | API 不可用时的备用模型 |
| 最大对话轮次 | 90 | 防止无限循环 |
| 系统提示语言 | 中文 | 与 SCCS OS 默认语言一致 |

## 2.5 Python 依赖检查

SCCS OS 核心依赖极少：

| 依赖 | 用途 | 安装检查 |
|------|------|---------|
| pyyaml | YAML 配置解析 | `python3 -c "import yaml; print(yaml.__version__)"` |
| click | CLI 框架 | `python3 -c "import click; print(click.__version__)"` |

## 1.3 安装部署

## 3.1 安装步骤

SCCS OS 通过 pip 以可编辑模式安装：

```bash
## 克隆或进入项目目录
cd /path/to/sccsos

## 安装依赖和 CLI 入口
pip install -e .
```

安装完成后验证 CLI 可用：

```bash
sccsos version
```

预期输出：

```
sccsos v0.4.0
```

## 3.2 初始化项目

在目标工作目录初始化 SCCS OS 项目：

```bash
## 创建项目目录
mkdir my-sccsos-project
cd my-sccsos-project

## 初始化项目
sccsos init
```

初始化会自动创建以下目录结构：

| 目录/文件 | 说明 |
|-----------|------|
| sccsos.yaml | 项目配置文件 |
| agents/ | Agent 定义目录 |
| data/ | SQLite 数据库目录 |
| logs/ | 日志文件目录 |
| traces/ | 追踪数据目录 |
| config/ | 配置示例目录 |
| tests/ | 测试目录 |

## 3.3 验证部署

运行健康检查确认所有组件正常工作：

```bash
sccsos health
```

预期输出示例：

```
sccsos v0.4.0
  Config: sccsos v0.4.0
  Database: ok (0 agents)
  Hermes:   OK
  Agents:   1 registered
  Traces:   0 available
```

各项说明：

| 检查项 | 正常状态 | 异常处理 |
|--------|---------|---------|
| Config | 显示项目名称和版本 | 检查 sccsos.yaml 是否存在 |
| Database | ok + agent 数量 | 检查 data/ 目录权限 |
| Hermes | OK | 确认 Hermes CLI 已安装且在 PATH 中 |
| Agents | 显示已注册 Agent 数 | 检查 agents/ 目录下的 YAML 文件 |

## 1.4 配置说明

## 4.1 项目配置（sccsos.yaml）

SCCS OS 项目配置文件位于项目根目录，采用 YAML 格式：

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| project.name | string | sccsos | 项目名称 |
| project.version | string | 0.4.0 | 项目版本 |
| database.path | string | ./data/sccsos.db | SQLite 数据库路径 |
| defaults.hermes_profile | string | sccsos | 默认 Hermes profile |
| defaults.max_turns | integer | 90 | 最大对话轮次 |
| defaults.timeout | integer | 1800 | 超时秒数（30 分钟） |
| logging.level | string | INFO | 日志级别 |
| logging.format | string | json | 日志格式 |
| logging.directory | string | ./logs | 日志目录 |
| tracing.enabled | boolean | true | 是否启用追踪 |

## 4.2 Agent 定义格式

Agent 定义文件存放于 agents/ 目录，采用 YAML 格式：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| name | string | 是 | Agent 唯一标识名 |
| version | string | 否 | 语义化版本号 |
| description | string | 否 | 功能描述 |
| personality | string | 否 | 映射到 Hermes personality |
| profile | string | 否 | Hermes profile 名称 |
| toolsets | list | 否 | 启用的工具集 |
| tags | list | 否 | 分类标签 |
| lifecycle.max_turns | integer | 否 | 最大对话轮次 |
| lifecycle.timeout | integer | 否 | 超时秒数 |

示例 Agent 定义：

```yaml
name: architect
version: 1.0
description: 创新研究院 李锋
personality: agent-architect
profile: sccsos
toolsets:
  - llm-wiki
  - filesystem
  - web-search
tags:
  - core
  - architecture
lifecycle:
  max_turns: 90
  timeout: 1800
  auto_recover: true
```

## 1.5 部署验证

## 5.1 基本功能验证

完成安装和初始化后，按以下步骤验证核心功能：

### 步骤一：查看已注册 Agent

```bash
sccsos agent list
```

应显示至少一个已注册的 Agent。

### 步骤二：启动 Agent

```bash
sccsos agent start architect
```

### 步骤三：查看运行状态

```bash
sccsos agent status architect
```

应显示状态为 running，并包含会话 ID。

### 步骤四：停止 Agent

```bash
sccsos agent stop architect
```

### 步骤五：查看事件日志

```bash
sccsos agent logs architect
```

应显示完整的生命周期事件链。

## 5.2 工作流验证

创建测试工作流文件 test-wf.yaml：

```yaml
name: smoke-test
version: 1.0
description: 冒烟测试工作流
steps:
  - id: greet
    name: 问候
    agent: architect
    prompt: "Say 'SCCS OS deployment verification successful'"
```

运行工作流：
```bash
sccsos workflow run test-wf.yaml
sccsos workflow list
```

## 5.3 可观测性验证

验证追踪功能：
```bash
## 查看追踪列表
sccsos trace list

## 查看追踪详情
sccsos trace show <trace_id>
```

验证审计功能：
```bash
## 查看审计报告
sccsos audit report

## 查看审计日志
sccsos audit log
```

## 1.6 部署场景案例

## 6.1 案例：软件开发团队部署 SCCS OS

**场景**：某软件开发团队（5 人）需要搭建内部智能体平台，支撑日常的架构设计评审、代码审查、文档生成等任务。

**需求分析**：

| 需求 | 说明 |
|------|------|
| 团队角色 | 架构师 1 人、后端开发 3 人、前端开发 1 人 |
| 主要任务 | 架构设计评审、代码审查、技术文档生成、API 接口设计 |
| 模型需求 | DeepSeek 为主，Claude 辅助复杂推理 |
| 数据隔离 | 各项目数据互相独立 |

**部署步骤**：

```bash
## 1. 安装 Hermes Agent
pip install hermes-agent
hermes setup

## 2. 创建团队专用 Profile
hermes profile create team-sccsos --clone default
hermes profile use team-sccsos

## 3. 安装 SCCS OS
cd ~/projects/team-sccsos
pip install -e /path/to/sccsos

## 4. 初始化项目
sccsos init
```

**Agent 定义**（`agents/`）：

```yaml
## architect.yaml — 架构设计师
name: architect
version: 1.0
description: 架构设计与评审 Agent
profile: team-sccsos
toolsets:
  - llm-wiki
  - web-search
  - filesystem
lifecycle:
  max_turns: 60
  timeout: 1800
---
## code-reviewer.yaml — 代码审查 Agent
name: code-reviewer
version: 1.0
description: 代码质量审查 Agent
profile: team-sccsos
toolsets:
  - filesystem
  - delegate_task
lifecycle:
  max_turns: 40
  timeout: 1200
---
## doc-writer.yaml — 文档生成 Agent
name: doc-writer
version: 1.0
description: 技术文档自动生成 Agent
profile: team-sccsos
toolsets:
  - filesystem
  - web-search
lifecycle:
  max_turns: 30
  timeout: 900
```

**日常操作流程**：

```bash
## 查看所有 Agent
sccsos agent list

## 启动团队 Agent
sccsos agent start architect
sccsos agent start code-reviewer
sccsos agent start doc-writer

## 运行架构评审工作流
sccsos workflow run workflows/架构评审.yaml

## 查看本周审计报告
sccsos audit report --since 2026-07-14
```

## 6.2 案例：企业多团队隔离部署

**场景**：某企业中 A、B 两个部门共享同一台服务器，需要数据完全隔离。

**方案**：利用 Hermes Profile 实现部门级数据隔离，每个部门使用独立的 Profile 和数据库。

```bash
## 为 A 部门创建 Profile
hermes profile create dept-a --clone default
hermes profile use dept-a
sccsos init --project-name sccsos-dept-a

## 为 B 部门创建 Profile
hermes profile create dept-b --clone default
hermes profile use dept-b
sccsos init --project-name sccsos-dept-b
```

每个部门的 Profile 拥有独立的 `HERMES_HOME`、独立的 SQLite 数据库和独立的 config.yaml。

```yaml
## dept-a 的 Agent 定义
name: analyst-a
profile: dept-a
## ...（部门 A 的业务 Agent 配置）

## dept-b 的 Agent 定义
name: analyst-b
profile: dept-b
## ...（部门 B 的业务 Agent 配置）
```

运行隔离验证：

```bash
## 切换到 A 部门
hermes profile use dept-a
sccsos agent list           # 只看到 A 部门的 Agent

## 切换到 B 部门
hermes profile use dept-b
sccsos agent list           # 只看到 B 部门的 Agent
```

# 第2章 操作指南

## 2.1 概述

## 1.1 文档说明

本文档是 SCCS OS 智能体操作系统的完整操作指南，涵盖 CLI 命令详解、Agent 管理、工作流编排、可观测性工具和常见问题处理。适用于使用 SCCS OS 的开发者和运维人员。

## 1.2 CLI 命令总览

![](images/sccsos-component-relationship-light.png)

*图 3: SCCS OS 核心组件关系图 — CLI 命令背后的核心组件交互*

SCCS OS 提供 15 条命令，分为 6 组：

| 命令组 | 命令 | 功能 |
|--------|------|------|
| 系统 | version | 显示版本信息 |
| 系统 | init | 初始化项目 |
| 系统 | health | 系统健康检查 |
| Agent 管理 | agent list | 列出所有 Agent |
| Agent 管理 | agent create | 创建 Agent 定义 |
| Agent 管理 | agent start | 启动 Agent |
| Agent 管理 | agent stop | 停止 Agent |
| Agent 管理 | agent status | 查询运行状态 |
| Agent 管理 | agent logs | 查看事件日志 |
| 工作流 | workflow validate | 验证工作流定义 |
| 工作流 | workflow run | 执行工作流 |
| 工作流 | workflow status | 查询运行状态 |
| 工作流 | workflow cancel | 取消运行中的工作流 |
| 工作流 | workflow list | 列出最近运行记录 |
| 追踪 | trace list | 列出追踪记录 |
| 追踪 | trace show | 查看追踪详情 |
| 审计 | audit report | 生成审计报告 |
| 审计 | audit log | 查看审计日志 |

## 2.2 Agent 管理

## 2.1 查看 Agent 列表

列出所有已注册的 Agent：

```bash
sccsos agent list
```

输出示例：

```
Name                 Version    Status       Description
----------------------------------------------------------------------
architect            1.0        registered   创新研究院 李锋
test-coder           1.0        registered
```

各列说明：

| 列 | 说明 |
|----|------|
| Name | Agent 名称，定义在 YAML 的 name 字段 |
| Version | 定义版本号 |
| Status | 当前运行状态：registered/running/paused/terminated |
| Description | 功能描述 |

## 2.2 创建 Agent

### 通过 YAML 文件创建

```bash
sccsos agent create my-agent -f path/to/my-agent.yaml
```

### 通过命令行快速创建

```bash
sccsos agent create my-agent
```

这会在 agents/ 目录下创建一个空的 YAML 模板文件，编辑后即可使用。

## 2.3 启动 Agent

启动一个已注册的 Agent：

```bash
sccsos agent start architect
```

启动过程：

1. SCCS OS 从 Registry 读取 Agent 定义
2. 创建 Agent 实例（状态：CREATED）
3. 启动 Agent，分配 Hermes 会话（状态：RUNNING）
4. 事件 recorded 到数据库

成功后输出：

```
Started: architect (agent_a1b2c3d4e5f6)
```

## 2.4 停止 Agent

停止运行中的 Agent：

```bash
sccsos agent stop architect
```

停止后状态转换为 TERMINATED，会话资源释放。

## 2.5 查询状态

查看 Agent 的详细运行状态和历史事件：

```bash
sccsos agent status architect
```

输出示例：

```
Agent: architect
  ID:     agent_a1b2c3d4e5f6
  Status: running
  Spec:   v1.0
  Profile: sccsos
  Session: ses_f6e5d4c3b2a1
  Recent events (3):
    [created] Agent 'architect' created
    [running] created → running via start
```

## 2.6 查看日志

查看 Agent 的生命周期事件记录：

```bash
sccsos agent logs architect
sccsos agent logs architect --limit 50
```

输出按时间倒序排列，每条记录包含时间戳、事件类型和详情。

![](images/sccsos-lifecycle-state-machine-light.png)

*图 1: Agent 生命周期状态机 — 5 种状态与 8 种转换关系*
## 2.7 生命周期状态机

SCCS OS 定义了 5 种运行状态：

| 状态 | 说明 | 可转换到 |
|------|------|---------|
| CREATED | Agent 定义已注册，未启动 | RUNNING |
| RUNNING | Agent 正在运行 | PAUSED, FAILED, TERMINATED |
| PAUSED | Agent 已暂停 | RUNNING, TERMINATED |
| FAILED | 运行异常 | RUNNING (restart), TERMINATED |
| TERMINATED | 已终止，资源释放 | （终态） |

![](images/sccsos-workflow-sequence-light.png)

*图 2: Workflow 执行时序图 — 从 DAG 构建到步骤执行、结果聚合的完整流程*

## 2.3 工作流编排

## 3.1 工作流定义

工作流使用 YAML 格式定义，支持多步骤编排、依赖管理和模板注入。

### 基本结构

```yaml
name: workflow-name
version: 1.0
description: 工作流描述

steps:
  - id: step-id
    name: 步骤名称
    agent: architect
    prompt: "执行提示词"
    depends_on:
      - other-step-id

parallel_groups:
  - id: group-id
    steps:
      - step-a
      - step-b
    max_concurrent: 2
```

### 字段说明

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| name | string | 是 | 工作流名称 |
| version | string | 否 | 版本号 |
| description | string | 否 | 描述 |
| steps[].id | string | 是 | 步骤唯一标识 |
| steps[].name | string | 否 | 步骤名称 |
| steps[].agent | string | 否 | 执行 Agent（默认 architect） |
| steps[].prompt | string | 否 | 执行提示词 |
| steps[].depends_on | list | 否 | 前置依赖步骤 ID |
| steps[].timeout | integer | 否 | 步骤超时秒数 |
| steps[].retry | integer | 否 | 失败重试次数 |

## 3.2 模板注入

工作流步骤的 prompt 支持模板语法，可引用前序步骤的输出：

| 模板语法 | 说明 |
|----------|------|
| {{ steps.step-id.response }} | 引用步骤的完整响应 |
| {{ run_id }} | 当前运行 ID |

示例：

```yaml
steps:
  - id: architecture-review
    agent: architect
    prompt: "Review requirements and produce ADR"

  - id: code-generation
    agent: architect
    prompt: |
      Implement based on the architecture:
      {{ steps.architecture-review.response }}
    depends_on:
      - architecture-review
```

## 3.3 验证工作流

执行工作流前建议先验证 YAML 定义的正确性：

```bash
sccsos workflow validate my-workflow.yaml
```

验证检查项：

1. YAML 格式合法性
2. 步骤 ID 唯一性
3. 依赖关系完整性（无缺失依赖）
4. 循环依赖检测
5. 提示词非空检查

## 3.4 执行工作流

```bash
sccsos workflow run my-workflow.yaml
```

执行过程：

1. 加载并验证工作流定义
2. 创建追踪 Span（根 Span = 工作流名称）
3. DAG 解析生成执行层级
4. 按层顺序执行步骤
5. 每个步骤通过 Hermes 适配器委派给 Agent
6. 模板按需渲染
7. 输出缓存供后续步骤引用
8. 记录审计日志

## 3.5 查询运行状态

```bash
## 按运行 ID 查询
sccsos workflow status wf_a1b2c3d4e5f6

## 列出最近运行记录
sccsos workflow list
```

## 3.6 取消工作流

```bash
sccsos workflow cancel wf_a1b2c3d4e5f6
```

取消后状态标记为 cancelled，正在执行的步骤不会强制中断。

## 2.4 可观测性

## 4.1 链路追踪

SCCS OS 提供 Span 树结构的链路追踪，每次工作流执行自动生成追踪记录。

### 查看追踪列表

```bash
sccsos trace list
```

输出示例：

```
Trace ID                 Spans    Total (ms)   First Span
----------------------------------------------------------------------
wf_a1b2c3d4e5f6          3        16753        2026-07-14T04:20:39
```

### 查看追踪详情

```bash
sccsos trace show wf_a1b2c3d4e5f6
```

输出示例（树形结构）：

```
Trace: wf_a1b2c3d4e5f6
Spans: 3

✅ workflow:obs-test (8.4s)
  └─ ✅ step:step-one (4.3s)
  └─ ✅ step:step-two (4.1s)
```

每个 Span 包含：

| 属性 | 说明 |
|------|------|
| span_id | Span 唯一 ID |
| parent_span_id | 父 Span ID（构建树结构） |
| name | Span 名称 |
| agent_name | 执行 Agent |
| start_time | 开始时间 |
| end_time | 结束时间 |
| duration_ms | 耗时（毫秒） |
| status | 状态：ok/error |
| events | 关联事件列表 |

## 4.2 审计与成本核算

SCCS OS 自动记录所有 LLM 调用和工具调用，支持成本估算。

### 生成审计报告

```bash
sccsos audit report
```

输出示例：

```
Audit Report
  Generated: 2026-07-14T04:20:48

  Total calls:    3
  Total tokens:   40
  Total cost:     $0.0000
  Avg duration:   2791ms
  Success rate:   3/3

  By event type:
    llm_call            3 calls,     40 tokens, $0.0000

  By model:
    deepseek-v4-flash           2 calls, $0.0000

  Cost over time:
    2026-07-14: $0.0000
```

### 按时间段审计

```bash
## 指定起始日期
sccsos audit report --since 2026-07-01

## 按 Agent 筛选
sccsos audit report --agent architect
```

### 查看审计日志

```bash
## 最近 20 条
sccsos audit log

## 指定数量
sccsos audit log --limit 50

## 按 Agent 筛选
sccsos audit log --agent architect
```

定价表（用于成本估算）：

| 模型 | 输入价格（每百万 Token） | 输出价格（每百万 Token） |
|------|------------------------|-------------------------|
| deepseek-v4-flash | $0.14 | $0.28 |
| deepseek-v4-pro | $0.44 | $0.87 |
| deepseek-chat | $0.14 | $0.28 |
| deepseek-reasoner | $0.55 | $2.19 |
| claude-sonnet-4 | $3.00 | $15.00 |
| gemini-2.5-flash | $0.30 | $2.50 |

## 2.5 系统管理

## 5.1 系统健康检查

```bash
sccsos health
```

检查项包括：

1. 配置加载状态
2. 数据库连接与 Schema
3. Hermes CLI 可达性
4. Agent 注册数量
5. 追踪数据可用性

## 5.2 数据库管理

SCCS OS 使用 SQLite 数据库，默认路径为 data/sccsos.db。

数据库包含 6 张表：

| 表名 | 用途 |
|------|------|
| agents | Agent 实例持久化 |
| agent_events | Agent 生命周期事件日志 |
| workflow_runs | 工作流运行记录 |
| workflow_steps | 工作流步骤执行记录 |
| traces | 追踪 Span 数据 |
| audit_log | 审计日志 |

```bash
## 查看数据库大小
ls -lh data/sccsos.db

## 使用 sqlite3 直接查询
sqlite3 data/sccsos.db "SELECT status, count(*) FROM agents GROUP BY status;"
```

## 5.3 日志管理

SCCS OS 日志默认输出到控制台和 logs/ 目录。

```bash
## 查看日志目录
ls -lh logs/

## 日志格式（JSON 行）
cat logs/sccsos.log | python3 -m json.tool
```

## 2.6 常见问题

## 6.1 安装问题

| 问题 | 原因 | 解决方法 |
|------|------|---------|
| sccsos 命令找不到 | pip 安装路径不在 PATH 中 | 运行 `pip show agentos` 找到安装路径，加入 PATH |
| Hermes 不可用 | Hermes CLI 未安装或不在 PATH | 确认 `hermes --version` 可正常运行 |
| 数据库初始化失败 | data/ 目录无写入权限 | `mkdir -p data && chmod 755 data` |
| YAML 解析错误 | 配置文件格式不正确 | 使用 `sccsos workflow validate` 检测 |

## 6.2 运行时问题

| 问题 | 原因 | 解决方法 |
|------|------|---------|
| Agent 启动失败 | Agent 定义中 profile 不存在 | 检查 Hermes profile 是否存在 |
| Agent 停止失败 | 实例不在内存中 | 使用 `sccsos agent status` 确认当前状态 |
| 工作流执行超时 | 某步骤超过 300 秒限制 | 缩短提示词或增加 timeout 配置 |
| 追踪数据为空 | 数据库首次使用 | 执行一次工作流后即有数据 |
| Token 成本为 0 | Token 为估算值 | 实际成本以模型提供商账单为准 |

## 6.3 性能建议

1. 工作流步骤数建议控制在 10 步以内
2. 提示词长度建议不超过 2000 Token
3. 数据库定时备份（cp data/sccsos.db backup/）
4. 日志定期清理（默认保留 30 天）

## 2.7 实战案例

## 7.1 案例：架构评审工作流

**目标**：对新项目的架构设计方案进行多 Agent 协同评审。

**工作流定义**（`workflows/架构评审.yaml`）：

```yaml
name: architecture-review
version: 1.0
description: 多 Agent 架构评审流水线
steps:
  - id: requirement-analysis
    name: 需求分析
    agent: architect
    prompt: |
      分析以下需求文档，提取关键架构约束：
      {{ requirements }}
      输出格式：详细的需求摘要 + 关键约束列表

  - id: design-proposal
    name: 设计方案
    agent: architect
    prompt: |
      基于需求分析结果，生成技术架构方案：
      输入：{{ steps.requirement-analysis.response }}
      输出包含：分层架构图描述、核心组件列表、技术选型建议
    depends_on:
      - requirement-analysis

  - id: code-review
    name: 代码审查
    agent: code-reviewer
    prompt: |
      审查以下代码是否符合架构设计规范：
      架构要求：{{ steps.design-proposal.response }}
      代码位置：./src/
      输出：合规项列表 + 不合规项及修改建议
    depends_on:
      - design-proposal

  - id: summary-report
    name: 汇总报告
    agent: doc-writer
    prompt: |
      汇总架构评审全过程，生成最终报告：
      - 需求分析：{{ steps.requirement-analysis.response }}
      - 设计方案：{{ steps.design-proposal.response }}
      - 代码审查：{{ steps.code-review.response }}
      输出格式：Markdown 文档，包含评审结论、建议、待办事项
    depends_on:
      - code-review
```

**执行命令**：

```bash
## 注入需求文档
export requirements=$(cat docs/项目需求.md)

## 运行评审工作流
sccsos workflow run workflows/架构评审.yaml
sccsos workflow status <run-id>
sccsos trace show <trace-id>
```

## 7.2 案例：日常巡检工作流

**目标**：每天早上自动检查系统状态，生成运维日报。

```yaml
name: daily-health-check
version: 1.0
description: 每日系统巡检
steps:
  - id: agent-status
    name: Agent 状态检查
    agent: architect
    prompt: |
      检查所有注册 Agent 的运行状态。
      输出格式：表格（Agent 名称 / 状态 / 运行时长 / 错误数）

  - id: audit-summary
    name: 审计汇总
    agent: architect
    prompt: |
      生成昨日审计摘要：
      - 总调用次数、Token 消耗、预估成本
      - 按 Agent 分类的调用量统计
      - 异常事件列表（如有）

  - id: report
    name: 生成日报
    agent: doc-writer
    prompt: |
      综合以上数据，生成运维日报：
      Agent 状态：{{ steps.agent-status.response }}
      审计数据：{{ steps.audit-summary.response }}
      输出格式：Markdown 表格 + 关键指标总结
    depends_on:
      - agent-status
      - audit-summary
```

```bash
## 执行日常巡检
sccsos workflow run workflows/每日巡检.yaml

## 查看审计报告
sccsos audit report --since $(date -d 'yesterday' +%Y-%m-%d)
```

## 7.3 案例：多 Agent 并行检索对比

**目标**：同时对同一问题使用不同模型/策略进行检索，对比结果。

```yaml
name: parallel-research
version: 1.0
description: 并行检索对比
parallel_groups:
  - id: research-group
    steps:
      - deep-research
      - web-quick
    max_concurrent: 2
steps:
  - id: deep-research
    name: 深度检索
    agent: architect
    prompt: |
      对以下问题进行深度技术研究：
      {{ research_question }}
      要求：引用可靠来源，给出技术方案对比

  - id: web-quick
    name: 快速检索
    agent: code-reviewer
    prompt: |
      快速搜索以下问题的业界实践：
      {{ research_question }}
      要求：列出 3-5 个实际案例

  - id: synthesis
    name: 综合报告
    agent: doc-writer
    prompt: |
      综合两种检索结果，生成对比报告：
      深度检索：{{ steps.deep-research.response }}
      快速检索：{{ steps.web-quick.response }}
      输出：差异点对比表 + 最终推荐方案
    depends_on:
      - deep-research
      - web-quick
```

```bash
## 设置研究问题
export research_question="微服务架构 vs 模块化单体架构的选型分析"

## 运行并行检索
sccsos workflow run workflows/并行检索.yaml
```

这些案例可直接修改参数后用于实际业务场景。

\newpage

# 附录

# 附录A：项目目录结构

```
sccsos/
├── AGENTS.md                       # 项目语境
├── sccsos/                        # 核心包
│   ├── __init__.py
│   ├── cli.py                      # CLI 入口（click 框架）
│   ├── core/
│   │   ├── registry.py             # Agent 注册表
│   │   ├── lifecycle.py            # 生命周期状态机
│   │   ├── orchestrator.py         # Workflow 引擎
│   │   ├── database.py             # SQLite 持久化
│   │   ├── hermes_adapter.py       # Hermes 桥接
│   │   └── config.py               # 配置加载器
│   ├── agents/                     # Agent 定义 YAML
│   ├── workflows/                  # Workflow 定义 YAML
│   ├── observability/
│   │   ├── tracer.py               # 链路追踪
│   │   ├── auditor.py              # Token 审计
│   │   └── logger.py               # 结构化日志
│   └── security/                   # 安全层（预留）
├── 文档/                           # 源文档（Markdown + 插图）
├── 输出/                           # 生成的 DOCX/PDF
├── 脚本/                           # 构建工具
├── 数据/                           # SQLite 数据库
├── 测试/                           # 测试用例
├── 配置/                           # 示例配置
├── 外部参考/                       # 外部参考文件
└── pyproject.toml                  # 项目配置
```

\newpage

# 附录B：Agent 定义 YAML 参考

```yaml
# agents/architect.yaml
name: architect
version: 1.0
description: 创新研究院 李锋
personality: agent-architect
profile: agentos
toolsets:
  - llm-wiki
  - filesystem
  - web-search
tags:
  - core
  - architecture
lifecycle:
  max_turns: 90
  timeout: 1800
  auto_recover: true
```

\newpage

# 附录C：技术决策清单

| 决策 | 选择 | 理由 |
|------|------|------|
| Agent 定义格式 | YAML + JSON Schema | 与 Hermes config.yaml 一致 |
| 编排模式 | 声明式 DAG + 本地顺序 | 避免分布式复杂度 |
| 状态持久化 | SQLite + JSON | Hermes 已用 SQLite 复用 |
| CLI 框架 | click | 轻量、成熟、Python 原生 |
| 配置管理 | YAML + 环境变量 | 与 Hermes 惯例对齐 |
| 追踪格式 | 自定义 JSON → 可导出 OpenTelemetry | 零外部依赖起步 |
| 安全策略 | 默认拒绝（白名单模式） | 最小权限原则 |
| 适配层 | 抽象基类（ABC）模式 | 生产/测试可切换 |
| Hermes 集成 | 子进程 delegate_task | 轻量隔离 |

## 附录D：SCCS OS 与 Hermes Agent 调用关系

### D.1 总体架构

![SCCS OS ↔ Hermes Agent 调用关系全景](images/sccsos-hermes-call-flow-light.png)

*图 D-1: SCCS OS ↔ Hermes Agent 调用关系全景 — SCCS OS 层编排管控，Hermes Agent 层推理执行*

SCCS OS 通过 **Hermes Adapter** 抽象层调用 Hermes Agent 完成 LLM 推理任务。Hermes Agent 是下层运行时底座，SCCS OS 是上层编排管控平台，两者通过子进程 IPC 通信。

### D.2 两条调用路径

**路径一：CLI 直接对话（`sccsos agent ask`）**

```
CLI → AgentRuntime → AgentRunner → AgentProcess (常驻后台线程)
  ├─ _build_prompt()        ← MemoryStore + KnowledgeBase + Session 三重注入
  ├─ HermesAdapter.delegate_task()
  │    ├─ PolicyEngine.check_delegation()       → 预算检查
  │    ├─ PolicyEngine.check_tool_access()      → 工具权限
  │    ├─ CommandWhitelist.check()              → 命令沙箱
  │    └─ subprocess.run(hermes -p sccsos -z "...") → 实际 LLM 调用
  └─ session.append_message()                  → 保存对话记录
```

**路径二：工作流执行（`sccsos workflow run` / API）**

```
用户触发 → WorkflowEngine.execute()
  ├─ DAGResolver → ThreadPoolExecutor(并行组)
  └─ StepExecutor.execute_with_retry()
       ├─ RetryPolicy (指数退避, max 3 次)
       ├─ ContextBuilder (Jinja2 模板 + Knowledge + Memory)
       ├─ _check_condition_and_skip() (条件分支)
       ├─ _prepare_prompt() (注入检测 + Personality)
       ├─ HermesAdapter.delegate_task() (同上三层安全)
       └─ _record_audit_and_result() (追踪 + 审计)
```

### D.3 三层安全防线（每次调用必经）

| 层 | 模块 | 位置 | 检查内容 |
|:--:|------|------|---------|
| ① | PromptInjectionGuard | StepExecutor._prepare_prompt() | Unicode 同形字、多语言注入、系统提示提取、敏感数据脱敏 |
| ② | PolicyEngine | Adapter._policy_preflight() | 预算上限、工具权限白名单、per-agent 策略覆盖 |
| ③ | CommandWhitelist | Adapter._sandbox_check() | 危险命令、路径穿越、管道链、环境变量泄漏、命令长度上限 |

### D.4 Hermes CLI 子进程调用格式

```bash
# 基本调用（SCCS OS 内部自动构建）
hermes -p sccsos -z "你的提示词"

# 带模型指定
hermes -p sccsos -m deepseek-v4-flash -z "提示词"

# 验证 Hermes 可用
hermes --version               # ≥ 0.24.x
hermes doctor                  # 全面诊断
hermes config list-profiles    # 查看可用 profile
```

### D.5 所需的 Hermes Profile 配置

执行 `hermes -p sccsos -z "..."` 前，Hermes Agent 必须配置：

```yaml
# ~/.hermes/profiles/sccsos/config.yaml
provider: deepseek          # 或 openai / anthropic
model: deepseek-v4-flash    # 或 gpt-4o / claude-sonnet-4
api_key: <your-api-key>     # 从环境变量或配置文件读取
```

### D.6 SCCS OS 侧适配器配置

```yaml
# sccsos.yaml
hermes:
  profile: sccsos            # 使用的 Hermes profile 名称
  adapter: subprocess        # 通信模式：subprocess / mock
  binary: hermes             # Hermes CLI 二进制路径
```

### D.7 性能特征

| 指标 | 典型值 | 说明 |
|------|:------:|------|
| 子进程启动开销 | ~50ms | Python 进程 fork + import |
| 首次 LLM 调用 | ~2-5s | 模型加载 + 推理 |
| 后续连续调用 | ~1-3s | 模型已热加载 |
| 超时默认值 | 300s | 可在 step 定义中覆盖 |
| 重试次数 | 2 次 | 瞬态错误自动重试（指数退避） |

### D.8 测试模式

测试时使用 MockHermesAdapter 替代真实子进程调用：

```yaml
# sccsos.yaml (测试环境)
hermes:
  adapter: mock               # 不调用 Hermes CLI，返回固定响应
```

Mock 保留完整安全防线，确保测试可验证安全策略而不依赖真实 LLM。

## 附录E：相关文档

- [SCCS OS — Hermes Agent 调用关系技术说明](../wiki/concepts/sccsos-hermes-call-relationship.md)
- [架构框架 — 7-Domain Design](../wiki/concepts/sccsos-architecture-framework.md)
- [ADR-011 — Session/ModelRouter/FastAPI](../wiki/concepts/ADR-011-session-modelrouter-fastapi.md)
