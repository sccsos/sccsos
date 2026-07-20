# SCCS OS — Kubernetes 部署与验证手册

> **版本**: 0.14.0  
> **API 端口**: 8765  
> **运行时**: Python 3.11 + FastAPI  
> **数据库**: SQLite（默认）/ PostgreSQL（可选）

---

## 目录

1. [前置条件](#1-前置条件)
2. [快速部署](#2-快速部署)
3. [部署验证](#3-部署验证)
4. [扩缩容测试](#4-扩缩容测试)
5. [清理卸载](#5-清理卸载)
6. [Helm 部署方式](#6-helm-部署方式)
7. [生产环境建议](#7-生产环境建议)

---

## 1. 前置条件

### 1.1 必需工具

| 工具 | 版本 | 用途 |
|------|------|------|
| `kubectl` | ≥ 1.25 | 管理 K8s 资源 |
| `docker` | ≥ 24.0 | 构建容器镜像 |
| `kind` / `minikube` | latest | 本地开发集群（二选一） |
| `helm`（可选） | ≥ 3.12 | Helm Chart 部署 |
| `curl` | — | API 健康检查 |

### 1.2 集群要求

- **开发环境**: 推荐使用 [kind](https://kind.sigs.k8s.io/) 或 [minikube](https://minikube.sigs.k8s.io/)
  - 最少 2 vCPU / 4GB 内存
  - 默认 StorageClass 自动创建 PV
- **生产环境**: Kubernetes ≥ 1.25 集群
  - 推荐使用托管服务：EKS / AKS / GKE / TKE
  - 需要默认 StorageClass 支持动态卷供应

### 1.3 快速创建本地集群

```bash
# ── kind ────────────────────────────────────────────────
cat <<EOF | kind create cluster --name sccsos --config=-
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
nodes:
  - role: control-plane
  - role: worker
EOF

# ── minikube ────────────────────────────────────────────
minikube start --cpus=2 --memory=4096 --kubernetes-version=v1.28.0
```

验证集群就绪：

```bash
kubectl cluster-info
kubectl get nodes
```

---

## 2. 快速部署

### 2.1 构建容器镜像

在项目根目录构建 Docker 镜像：

```bash
cd /path/to/sccsos

# 构建镜像
docker build -t sccsos:0.14.0 .

# 推送到镜像仓库（生产环境必做）
docker tag sccsos:0.14.0 your-registry/sccsos:0.14.0
docker push your-registry/sccsos:0.14.0
```

> 本地 kind/minikube 集群可直接使用本地镜像，无需推送：
> ```bash
> kind load docker-image sccsos:0.14.0 --name sccsos
> ```

### 2.2 更新镜像引用（可选）

如果使用私有仓库，编辑 `30-deployment.yaml` 中的 `image` 字段：

```yaml
# deploy/k8s/30-deployment.yaml
spec:
  template:
    spec:
      containers:
        - name: sccsos
          image: your-registry/sccsos:0.14.0   # ← 修改此处
          imagePullPolicy: IfNotPresent
```

### 2.3 按顺序部署资源

```bash
# 部署 Namespace
kubectl apply -f deploy/k8s/00-namespace.yaml

# 部署 ConfigMap（应用配置）
kubectl apply -f deploy/k8s/10-configmap.yaml

# 部署 PersistentVolumeClaim（持久化存储）
kubectl apply -f deploy/k8s/20-pvc.yaml

# 部署 Deployment（主应用）
kubectl apply -f deploy/k8s/30-deployment.yaml

# 部署 Service（服务发现与负载均衡）
kubectl apply -f deploy/k8s/40-service.yaml

# 部署 HorizontalPodAutoscaler（自动扩缩容）
kubectl apply -f deploy/k8s/50-hpa.yaml
```

**一键部署全部资源**：

```bash
kubectl apply -f deploy/k8s/
```

### 2.4 部署可选 ConfigMap 资源

部署中包含以下可选 ConfigMap，用于挂载额外静态内容。如不需要可忽略（设置 `optional: true`，Pod 正常启动）：

```bash
# Agent 定义文件
kubectl create configmap sccsos-agents -n sccsos --from-file=agents/

# 工作流定义文件
kubectl create configmap sccsos-workflows -n sccsos --from-file=workflows/

# 角色设定文件
kubectl create configmap sccsos-personalities -n sccsos --from-file=personalities/

# Wiki 知识库文件
kubectl create configmap sccsos-wiki -n sccsos --from-file=wiki/
```

### 2.5 资源配置清单

| 资源 | Request | Limit |
|------|---------|-------|
| CPU | 250m | 1000m |
| 内存 | 512Mi | 2Gi |

### 2.6 持久化存储

| 挂载点 | 类型 | 大小 | 用途 |
|--------|------|------|------|
| `/sccsos/data` | PVC (sccsos-data) | 10Gi | SQLite 数据库 |
| `/sccsos/logs` | PVC (sccsos-logs) | 5Gi | 应用日志 |
| `/sccsos/traces` | emptyDir | — | 追踪导出（非持久） |

---

## 3. 部署验证

### 3.1 检查 Pod 状态

```bash
# 查看命名空间中所有资源
kubectl -n sccsos get all

# 查看 Pod 详细状态
kubectl -n sccsos get pods -o wide

# 查看 Pod 详细信息（含事件）
kubectl -n sccsos describe pods

# 持续监测 Pod 启动
kubectl -n sccsos get pods -w
```

预期输出示例：

```
NAME                      READY   STATUS    RESTARTS   AGE
sccsos-7d4f8b9c6f-xk9z2   1/1     Running   0          45s
```

### 3.2 检查部署与 HPA

```bash
# 检查 Deployment 状态
kubectl -n sccsos rollout status deployment/sccsos

# 查看 HPA 详情
kubectl -n sccsos describe hpa/sccsos

# 检查 Service 端点
kubectl -n sccsos get endpoints sccsos
```

### 3.3 查看应用日志

```bash
# 实时日志
kubectl -n sccsos logs -f deployment/sccsos

# 查看最近 100 行
kubectl -n sccsos logs --tail=100 deployment/sccsos

# 查看指定 Pod 日志（多副本时）
kubectl -n sccsos logs sccsos-7d4f8b9c6f-xk9z2
```

启动成功的日志应包含类似以下内容：

```
INFO     Starting SCCS OS API server...
INFO     Database initialized at /sccsos/data/sccsos.db
INFO     Listening on http://0.0.0.0:8765
```

### 3.4 健康检查（Health Endpoint）

使用端口转发临时访问：

```bash
# 方式一：端口转发（推荐调试用）
kubectl -n sccsos port-forward svc/sccsos 8765:8765

# 在另一个终端检查健康状态
curl -s http://localhost:8765/health | jq .
```

预期响应：

```json
{
  "status": "ok",
  "version": "0.14.0",
  "uptime_seconds": 123
}
```

### 3.5 使用临时 Pod 进行网络连通性测试

```bash
# 启动临时 busybox Pod 测试集群内部访问
kubectl run -it --rm debug --image=busybox:1.36 -n sccsos -- sh

# 在 debug Pod 内部执行：
wget -qO- http://sccsos:8765/health
# 或
wget -qO- http://sccsos.sccsos.svc.cluster.local:8765/health
```

### 3.6 检查持久化存储

```bash
# 确认 PVC 状态为 Bound
kubectl -n sccsos get pvc

# 预期输出：
# NAME           STATUS   VOLUME                                     CAPACITY   ACCESS MODES   STORAGECLASS   AGE
# sccsos-data    Bound    pvc-xxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx      10Gi       RWO            standard       1m
# sccsos-logs    Bound    pvc-yyyyy-yyyy-yyyy-yyyy-yyyyyyyyyyyy      5Gi        RWO            standard       1m
```

### 3.7 检查探针（Probe）状态

```bash
# 查看 Pod 的探针详情
kubectl -n sccsos get pod <pod-name> -o jsonpath='{.status.containerStatuses[0].ready}' && echo ""

# 查看 RESTARTS 列确认没有因探针失败而重启
kubectl -n sccsos get pods

# 如 RESTARTS > 0，查看原因
kubectl -n sccsos logs --previous deployment/sccsos
```

### 3.8 Prometheus 监控注解验证

SCCS OS 的 Deployment 已自动配置 Prometheus scrape 注解：

```bash
# 验证注解已生效
kubectl -n sccsos get pod <pod-name> -o json | jq '.metadata.annotations'

# 应包含：
# {
#   "prometheus.io/scrape": "true",
#   "prometheus.io/port": "8765"
# }
```

---

## 4. 扩缩容测试

SCCS OS 默认配置了 HPA，根据 CPU 和内存利用率自动扩缩。

### 4.1 查看 HPA 状态

```bash
# 查看 HPA 指标状态
kubectl -n sccsos get hpa -w

# 预期输出（稳定状态）：
# NAME     REFERENCE           TARGETS                MINPODS   MAXPODS   REPLICAS   AGE
# sccsos   Deployment/sccsos   15%/70% (CPU)         1          5         1          5m
#                           25%/80% (Memory)
```

### 4.2 手动扩缩测试

```bash
# 临时扩容到 3 副本（验证 HPA 释放后恢复）
kubectl -n sccsos scale deployment/sccsos --replicas=3

# 监控自动回缩
kubectl -n sccsos get pods -w

# 恢复为 HPA 管理
kubectl -n sccsos scale deployment/sccsos --replicas=1
```

### 4.3 负载测试（模拟高 CPU 触发扩缩容）

> 注意：仅用于开发/测试环境！

```bash
# 创建负载测试 Pod
kubectl run -it --rm load-test --image=busybox:1.36 -n sccsos -- sh

# 在 load-test Pod 内执行压力测试
# 每 0.5 秒发送一次请求
while true; do
  wget -qO- http://sccsos:8765/health > /dev/null 2>&1
  sleep 0.5
done
```

在另一个终端监控 HPA 行为：

```bash
kubectl -n sccsos get hpa -w

# 观察 TARGETS 列 CPU 利用率上升，REPLICAS 自动增加
# 一旦 CPU 持续超过 70%，HPA 会逐步扩容至最多 5 副本
# 压力降低后自动缩回 1 副本（默认冷却期 ~3-5 分钟）
```

### 4.4 负载测试清理

```bash
# Ctrl+C 退出负载测试 Pod
# HPA 会自动恢复副本数
```

---

## 5. 清理卸载

### 5.1 保留 PVC 清理（数据保留）

```bash
# 删除所有 SCCS OS 资源（保留 PVC、Namespace）
kubectl delete -n sccsos deployment/sccsos
kubectl delete -n sccsos service/sccsos
kubectl delete -n sccsos hpa/sccsos
```

### 5.2 完全清理（含数据）

```bash
# 删除命名空间内的全部资源
kubectl delete namespace sccsos

# 验证删除
kubectl get ns
```

> ⚠️ 删除 Namespace 会连带删除所有 PVC，**SQLite 数据库数据将永久丢失**。如需保留，请先备份。

### 5.3 一键清理（从当前目录）

```bash
# 逆序删除所有资源
kubectl delete -f deploy/k8s/
```

### 5.4 本地集群清理

```bash
# kind
kind delete cluster --name sccsos

# minikube
minikube stop && minikube delete
```

---

## 6. Helm 部署方式

SCCS OS 提供了 Helm Chart 作为替代部署方式，位于 `deploy/helm/sccsos/`。

### 6.1 安装 Chart

```bash
# 直接安装
helm install sccsos ./deploy/helm/sccsos --namespace sccsos --create-namespace

# 使用自定义 values.yaml
helm install sccsos ./deploy/helm/sccsos \
  --namespace sccsos \
  --create-namespace \
  -f my-values.yaml
```

### 6.2 自定义部署

```bash
# 使用 --set 覆盖单值
helm install sccsos ./deploy/helm/sccsos \
  --namespace sccsos \
  --create-namespace \
  --set image.repository=myregistry/sccsos \
  --set image.tag=0.14.0 \
  --set resources.requests.cpu=500m \
  --set ingress.enabled=true \
  --set ingress.host=sccsos.mydomain.com
```

### 6.3 升级与回滚

```bash
# 升级
helm upgrade sccsos ./deploy/helm/sccsos -f my-values.yaml

# 查看历史版本
helm history sccsos -n sccsos

# 回滚到上一版本
helm rollback sccsos 1 -n sccsos
```

### 6.4 卸载

```bash
helm uninstall sccsos -n sccsos
```

> ⚠️ Helm 卸载不会自动删除 Namespace 和 PVC。如需完全清理：
> ```bash
> kubectl delete namespace sccsos
> ```

### 6.5 kubectl 方式 vs Helm 方式对比

| 特性 | kubectl (deploy/k8s/) | Helm (deploy/helm/) |
|------|----------------------|---------------------|
| 复杂度 | 直接、透明 | 模板化、参数化 |
| 自定义 | 手动修改 YAML | values.yaml + --set |
| 版本管理 | Git 管理 YAML | Helm release 历史 |
| 生产推荐 | 小规模部署 | CI/CD + 多环境 |
| 学习成本 | 低 | 中 |

---

## 7. 生产环境建议

### 7.1 容器镜像管理

- 使用**私有镜像仓库**（Harbor / ECR / ACR / GCR），不要依赖 `latest` 标签
- 设置明确的版本标签：`sccsos:0.14.0`、`sccsos:0.12.2`
- 配置 `imagePullSecrets` 用于私有仓库拉取：

```yaml
# 在 30-deployment.yaml 中添加
spec:
  template:
    spec:
      imagePullSecrets:
        - name: regcred
```

### 7.2 持久化存储

- **生产环境必须使用 PVC**（已配置 10Gi + 5Gi）
- 指定 `storageClassName` 以匹配集群的持久化存储类型（SSD / NVMe）
- 启用**定期备份**方案（Velero / Kopia / 云服务厂商快照）
- SQLite 数据库文件路径：`/sccsos/data/sccsos.db`

```yaml
# 在 20-pvc.yaml 中指定 StorageClass
spec:
  storageClassName: gp3              # AWS EKS
  # storageClassName: managed-premium # Azure AKS
  # storageClassName: premium-rwo     # Google GKE
```

### 7.3 数据库与 PostgreSQL 切换

默认使用 SQLite（单文件数据库）。生产环境建议切换为 PostgreSQL：

```yaml
# 10-configmap.yaml 中修改
database:
  driver: postgresql
  host: postgres-service.db-namespace.svc.cluster.local
  port: 5432
  name: sccsos
  user: sccsos
  password: ${SCCSOS_DB_PASSWORD}   # 通过环境变量注入
```

> PostgreSQL 密码建议通过 Secret 挂载，而非明文写在 ConfigMap 中。

### 7.4 Secret 管理

**绝对不要在 ConfigMap 中存储敏感信息！**

```bash
# 创建数据库密码 Secret
kubectl create secret generic sccsos-db \
  -n sccsos \
  --from-literal=password='your-strong-password'

# 使用 External Secrets Operator（推荐）
# 从 AWS Secrets Manager / Azure Key Vault / GCP Secret Manager 同步
```

在 Deployment 中引用 Secret：

```yaml
# 在 30-deployment.yaml 中添加
env:
  - name: SCCSOS_DB_PASSWORD
    valueFrom:
      secretKeyRef:
        name: sccsos-db
        key: password
```

### 7.5 资源限制（生产调优）

根据实际负载调整资源请求和限制：

| 场景 | CPU Request | CPU Limit | Memory Request | Memory Limit |
|------|-------------|-----------|----------------|--------------|
| 轻量（单 Agent） | 250m | 500m | 512Mi | 1Gi |
| 标准（默认） | 500m | 1000m | 1Gi | 2Gi |
| 高负载（多 Agent 并发） | 1000m | 2000m | 2Gi | 4Gi |

### 7.6 网络与 Ingress

默认 Service 类型为 `ClusterIP`，外部流量需通过 Ingress 暴露：

```yaml
# 创建 Ingress（以 Nginx Ingress Controller 为例）
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: sccsos
  namespace: sccsos
  annotations:
    nginx.ingress.kubernetes.io/ssl-redirect: "true"
spec:
  ingressClassName: nginx
  tls:
    - hosts:
        - sccsos.yourdomain.com
      secretName: sccsos-tls
  rules:
    - host: sccsos.yourdomain.com
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: sccsos
                port:
                  number: 8765
```

### 7.7 健康检查探针调优

生产环境建议根据应用启动时间调整探针参数（在 `30-deployment.yaml` 中修改）：

```yaml
livenessProbe:
  httpGet:
    path: /health
    port: http-api
  initialDelaySeconds: 30    # 应用首次启动时间较长
  periodSeconds: 30           # 每 30s 检查一次
  timeoutSeconds: 5           # 请求超时时间
  failureThreshold: 3         # 连续 3 次失败后重启
readinessProbe:
  httpGet:
    path: /health
    port: http-api
  initialDelaySeconds: 5
  periodSeconds: 10
  timeoutSeconds: 3
  failureThreshold: 2
```

### 7.8 Pod 分布与反亲和

多副本部署时建议配置 Pod 反亲和，避免同一节点部署多个副本：

```yaml
# 在 30-deployment.yaml 中添加
affinity:
  podAntiAffinity:
    preferredDuringSchedulingIgnoredDuringExecution:
      - weight: 100
        podAffinityTerm:
          labelSelector:
            matchExpressions:
              - key: app.kubernetes.io/name
                operator: In
                values:
                  - sccsos
          topologyKey: kubernetes.io/hostname
```

### 7.9 PodDisruptionBudget（可选）

```yaml
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: sccsos-pdb
  namespace: sccsos
spec:
  minAvailable: 1
  selector:
    matchLabels:
      app.kubernetes.io/name: sccsos
```

### 7.10 监控与告警

- **Prometheus**: Deployment 已自动添加 `prometheus.io/scrape: "true"` 和 `prometheus.io/port: "8765"` 注解
- **Grafana**: 建议配置 Grafana 仪表盘监控 API 延迟 / 请求量 / Agent 执行时间
- **告警规则建议**:
  - Pod `CrashLoopBackOff` 状态
  - Pod 重启次数 > 3 次/小时
  - HPA 达到最大副本数持续 > 10 分钟
  - PVC 使用率 > 80%

### 7.11 安全检查清单

| 检查项 | 状态 |
|--------|------|
| ✅ 非 root 运行（runAsUser: 1000, runAsNonRoot: true） | ✓ 已配置 |
| ✅ ConfigMap 只读挂载（readOnly: true） | ✓ 已配置 |
| ✅ Liveness/Readiness 探针 | ✓ 已配置 |
| ✅ 资源请求与限制 | ✓ 已配置 |
| ✅ Prometheus 监控注解 | ✓ 已配置 |
| ✅ 明确的版本标签（非 latest） | ✓ 已配置 |
| ❌ Secret 管理 | 需手动创建 |
| ❌ NetworkPolicy | 需额外配置 |
| ❌ PodAntiAffinity | 需手动开启 |
| ❌ PodDisruptionBudget | 需手动创建 |

---

## 文件结构

```
deploy/k8s/
├── 00-namespace.yaml    # sccsos 命名空间（version: 0.14.0）
├── 10-configmap.yaml    # 应用配置（sccsos.yaml）
├── 20-pvc.yaml          # 持久卷声明（data: 10Gi, logs: 5Gi）
├── 30-deployment.yaml   # 主部署（含探针、资源限制、Prometheus 注解）
├── 40-service.yaml      # ClusterIP Service（端口 8765）
├── 50-hpa.yaml          # HPA（CPU: 70%, Memory: 80%, 1-5 副本）
└── README.md            # 本文档
```

## 快速参考命令

```bash
# ── 部署 ──
kubectl apply -f deploy/k8s/

# ── 状态检查 ──
kubectl -n sccsos get pods -o wide
kubectl -n sccsos get pvc
kubectl -n sccsos get hpa

# ── 应用日志 ──
kubectl -n sccsos logs -f deployment/sccsos

# ── 健康检查 ──
kubectl -n sccsos port-forward svc/sccsos 8765:8765 &
curl http://localhost:8765/health

# ── 扩缩容 ──
kubectl -n sccsos scale deployment/sccsos --replicas=3

# ── 清理 ──
kubectl delete -f deploy/k8s/
```
