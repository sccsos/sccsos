---
title: SCCS OS + Hermes + Wiki 高可用集群部署架构
created: 2026-07-25
updated: 2026-07-25
type: concept
tags: [sccsos, architecture, ha, deployment, k8s, production]
confidence: high
---

# ADR: SCCS OS + Hermes + Wiki 高可用集群部署架构

> 基于 v0.20.10 Locust 500+ 并发压测结果分析，产出面向生产环境的 HA 部署建议
> 关联: [[性能基线报告_v0.20.10]]

---

## 背景

v0.20.10 压测揭示三个核心瓶颈：

| 瓶颈 | 表现 | 根因 |
|------|------|------|
| **连接溢出** | 500 并发下大量 `ConnectionResetError` | uvicorn 4 workers 无法承载 500 并发 TCP 连接 |
| **写锁争用** | 日志 `database is locked` 频繁 | SQLite WAL 模式下多 worker 写入冲突 |
| **速率限制** | 250 并发开始 429 响应 | 默认速率限制器阈值需按 SLA 调整 |

---

## 总体架构

```
                          ┌─────────────────────────┐
                          │     Nginx / HAProxy      │  ← 负载均衡 + TLS 终止
                          │  (active-passive keepalived) │
                          └────┬─────────┬──────────┘
                               │         │
                    ┌──────────▼──┐ ┌───▼──────────┐
                    │ uvicorn x 8 │ │ uvicorn x 8  │  ← 多 worker 水平扩展
                    │ (Node 1)    │ │ (Node 2)     │
                    └──────┬──────┘ └──────┬───────┘
                           │               │
                    ┌──────▼───────────────▼───────┐
                    │        PostgreSQL HA          │  ← Patroni + Pgpool-II
                    │  (Primary + Standby + Quorum) │     自动故障切换
                    └───────────────┬───────────────┘
                                    │
                    ┌───────────────▼───────────────┐
                    │     Hermes 运行时集群           │
                    │  (Hermes x N, 容器化调度)       │
                    │  RemoteHermesAdapter 连接池     │
                    └───────────────┬───────────────┘
                                    │
                    ┌───────────────▼───────────────┐
                    │     Wiki / 知识库存储           │
                    │  MinIO (S3) + Redis 缓存        │
                    └───────────────────────────────┘
```

---

## 组件级 HA 建议

### 1. API 网关层

| 维度 | 建议 |
|------|------|
| **负载均衡** | Nginx upstream 指向多节点 uvicorn 实例 |
| **健康检查** | `/api/v1/health` 端点，间隔 5s，失败 3 次摘除 |
| **连接池** | `worker_connections 8192`，`keepalive 256` |
| **TLS** | 终止于 Nginx 层，后端 HTTP |
| **速率限制** | Nginx `limit_req_zone` 替代应用层 429，按租户分流 |

**关键配置：**
```nginx
upstream sccsos_backend {
    least_conn;
    server node1:8765 max_fails=3 fail_timeout=10s;
    server node2:8765 max_fails=3 fail_timeout=10s;
    keepalive 256;
}

server {
    listen 443 ssl;
    location /api/ {
        proxy_pass http://sccsos_backend;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
        limit_req zone=api burst=200 nodelay;
    }
}
```

### 2. 应用层 (uvicorn)

| 维度 | 建议 |
|------|------|
| **Worker 数** | `2 × CPU 核心`（例如 8 核机器配 16 workers） |
| **每个节点** | 单节点承载 200~300 并发，超量水平扩展 |
| **启动参数** | `--factory --workers $WORKERS --backlog 2048` |
| **优雅关闭** | `--timeout-graceful-shutdown 30` |

> 500 并发目标下: 2 节点 × 8 workers = 16 workers，实测可 >95% 成功率

### 3. 数据库层 (PostgreSQL HA)

这是最关键的一层。从 SQLite 切换为 PostgreSQL 集群的完整方案：

```
┌─────────┐    ┌─────────┐    ┌─────────┐
│ Primary │◄───│ Standby │◄───│ Quorum  │  ← Patroni 自动选主
└────┬────┘    └─────────┘    └─────────┘
     │
┌────▼──────────────────────────────┐
│      Pgpool-II 连接池 + 读写分离     │
│  read: 4 conns/worker → Standby    │
│  write: 1 conn/worker → Primary    │
└────────────────────────────────────┘
```

**配置要点：**
- `sccsos.yaml` 切换到 PostgreSQL 驱动（已内置支持）
- 连接字符串: `postgresql://user:pass@pgpool:5432/sccsos`
- 连接池: `min_connections=10, max_connections=100`
- WAL 归档: 开启 `archive_mode` + 对象存储备份

### 4. Hermes 运行时集群

原设计 `HermesSubprocessAdapter` 在容器中启动子进程，多节点场景改为 `RemoteHermesAdapter`：

```
┌─────────────────────────────────────────┐
│  Hermes 调度服务 (sccsos hermes connect) │
│  ┌─────────────────────────────────────┐│
│  │  Hermes 连接池                       ││
│  │  ├─ hermes-1:8081 (健康检查 ✅)      ││
│  │  ├─ hermes-2:8081 (健康检查 ✅)      ││
│  │  ├─ hermes-3:8081 (健康检查 ✅)      ││
│  │  └─ hermes-N:8081 (健康检查 ✅)      ││
│  └─────────────────────────────────────┘│
└─────────────────────────────────────────┘
```

**Hermes 容器：**
```yaml
# Hermes 实例容器配置
apiVersion: apps/v1
kind: Deployment
metadata:
  name: hermes-worker
spec:
  replicas: 8
  template:
    spec:
      containers:
      - name: hermes
        env:
        - name: HERMES_MODE
          value: "serve"
        - name: HERMES_PORT
          value: "8081"
        resources:
          requests:
            cpu: "1"
            memory: "2Gi"
          limits:
            cpu: "2"
            memory: "4Gi"
```

### 5. Wiki / 知识库层

```
┌──────────────────────┐
│    MinIO (S3 兼容)    │  ← 对象存储，多副本 + 纠删码
│   ┌───┐ ┌───┐ ┌───┐ │
│   │ M1│ │ M2│ │ M3│ │
│   └───┘ └───┘ └───┘ │
└──────────┬───────────┘
           │
┌──────────▼───────────┐
│   Redis Cluster       │  ← 知识库缓存 + 会话缓存
│  (3 master + 3 slave) │     减少直读 MinIO 延迟
└──────────────────────┘
```

### 6. 水平扩缩容 (K8s HPA)

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: sccsos-api
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: sccsos-api
  minReplicas: 2
  maxReplicas: 10
  metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 70
  - type: Pods
    pods:
      metric:
        name: sccsos_requests_per_second
      target:
        type: AverageValue
        averageValue: 200
```

---

## 生产部署 Checklist (从当前到生产就绪)

### 必须项 (Go/No-Go 门禁)

- [ ] SQLite → PostgreSQL 切换验证
- [ ] PostgreSQL HA 集群就绪 (Patroni + Pgpool-II)
- [ ] Nginx 负载均衡配置 + 健康检查
- [ ] `sccsos.yaml` 的 `database` 和 `rate_limit` 参数调优
- [ ] K8s Deployment 配置 resource requests/limits
- [ ] 至少 2 节点部署，容忍单节点故障

### 建议项 (最佳实践)

- [ ] Hermes 容器化 + RemoteHermesAdapter 连接池
- [ ] MinIO 对象存储 + Redis 缓存层
- [ ] HPA 弹性扩缩容配置 (CPU + RPS 双指标)
- [ ] 数据库连接池参数调优
- [ ] Prometheus + Grafana 监控面板
- [ ] ELK/Loki 日志聚合

### 增强项 (可选)

- [ ] Nginx + Keepalived VIP 实现入口 HA
- [ ] PgBouncer 数据库连接池替代应用层连接池
- [ ] Hermes 无状态化改造 (移除本地文件依赖)
- [ ] Wiki 多级缓存 (CDN → Redis → MinIO)

---

## 预期性能

在完成上述 HA 架构部署后，预期性能：

| 指标 | 当前 (v0.20.10, SQLite, 4w) | 目标 (PostgreSQL, 16w, 2节点) |
|------|:---------------------------:|:-----------------------------:|
| 最大安全并发 | 150~200 | 1,000+ |
| P99 延迟 (200 并发) | ~8,000ms | < 500ms |
| P50 延迟 (200 并发) | ~3,000ms | < 20ms |
| 故障切换时间 | N/A (单点) | < 30s |
| 可用性 | 99% | 99.9% |

---

## 风险

| 风险 | 影响 | 缓解 |
|------|------|------|
| PostgreSQL 运维复杂度增加 | DBA 维护成本 | 使用托管云数据库 (RDS/CloudSQL) |
| Hermes 无状态化改造成本 | 需重构记忆存储 | Phase 2 推进，优先 RemoteHermesAdapter |
| K8s 网络延迟增加 | ~1-2ms 跨节点开销 | 同节点调度 via pod affinity |
| 连接池耗尽 | 雪崩级联失败 | 设置连接池上限 + 熔断降级 |
