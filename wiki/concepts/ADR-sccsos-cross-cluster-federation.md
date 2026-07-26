---
title: SCCS OS 跨集群联邦架构设计
created: 2026-07-25
updated: 2026-07-25
type: concept
tags: [sccsos, architecture, federation, multi-cluster, p2]
confidence: medium
---

# ADR: SCCS OS 跨集群联邦架构设计

> **状态**: 🟡 规划阶段 — 待评审
> **关联**: [[ADR-sccsos-ha-cluster-deployment]], [[ADR-019-agent-message-bus]]

---

## 背景

当前 SCCS OS 部署限定在单一 K8s 集群内。随着业务扩展至多个数据中心、云+边缘混合部署，需要跨集群联邦能力：

| 场景 | 需求 | 优先级 |
|------|------|--------|
| 多数据中心 | 用户请求路由到最近数据中心 | P0 |
| 云+边缘 | 边缘节点离线仍可本地决策 | P0 |
| 租户数据主权 | 敏感数据不跨区域传输 | P1 |
| 全局统一管理 | 一个控制台管理所有集群 | P1 |

---

## 总体架构

```
                   ┌───────────────────────────────────┐
                   │       Global Control Plane         │
                   │  (Global API Gateway + Fleet Manager) │
                   └──────┬──────────┬──────────┬───────┘
                          │          │          │
              ┌───────────▼──┐ ┌─────▼─────┐ ┌──▼───────────┐
              │  Cluster A   │ │ Cluster B  │ │  Cluster C   │
              │  (us-east-1) │ │ (eu-west-1)│ │ (ap-southeast)│
              │              │ │            │ │              │
              │  ┌────────┐  │ │ ┌────────┐ │ │  ┌────────┐  │
              │  │ SCCSOS │  │ │ │ SCCSOS │ │ │  │ SCCSOS │  │
              │  │ +Hermes│  │ │ │ +Hermes│ │ │  │ +Hermes│  │
              │  └────────┘  │ │ └────────┘ │ │  └────────┘  │
              │  (N replicas)│ │ (N replicas)│ │ (N replicas) │
              └──────────────┘ └────────────┘ └──────────────┘
                         \           |           /
                          \          |          /
                           └─────────▼─────────┘
                          ┌──────────────────────┐
                          │  Global Event Bus     │
                          │  (Kafka Cross-Region) │
                          │  + Global KV Store     │
                          │  (Redis/Etcd Global)   │
                          └──────────────────────┘
```

---

## 组件设计

### 1. Global Control Plane

| 组件 | 职责 | 实现方案 |
|------|------|---------|
| **Fleet Manager** | 注册/发现集群，健康检查，全局 Agent 路由表 | Operator 模式 (CRD) |
| **Global API Gateway** | 根据 tenant_id/region 路由请求到最近集群 | 地域 DNS + Envoy |
| **Federation CRD** | `ClusterFederation` 资源定义集群拓扑 | K8s CRD |

```yaml
# ClusterFederation CRD 示例
apiVersion: federation.sccsos.io/v1
kind: ClusterFederation
metadata:
  name: us-east-1
spec:
  region: us-east-1
  tier: production
  capacity:
    maxAgents: 1000
    maxWorkflows: 500
  gateway:
    hostname: us-east.sccsos.example.com
    tls: true
  sync:
    namespace: sccsos-federation
    interval: 30s
```

### 2. 跨集群 EventBus

| 方案 | 延迟 | 复杂度 | 推荐场景 |
|------|------|--------|---------|
| **Kafka MirrorMaker** | ~500ms | 中 | 全局事件同步 |
| **Redis 跨区域拓扑** | ~1ms | 高 | 低延迟需求 |
| **Pulsar geo-replication** | ~200ms | 中 | 多租户严格隔离 |

**推荐**: Kafka MirrorMaker 2.0 — 成熟方案，Confluent 提供跨区域复制能力。

```yaml
# Kafka MirrorMaker 配置示意
clusters:
  - alias: cluster-a
    bootstrap.servers: "kafka-a:9092"
  - alias: cluster-b
    bootstrap.servers: "kafka-b:9092"

mirrors:
  - source.cluster: cluster-a
    target.cluster: cluster-b
    topics: [sccsos.events, sccsos.agent.lifecycle]
  - source.cluster: cluster-b
    target.cluster: cluster-a
    topics: [sccsos.events.global]
```

### 3. 全局 Agent 调度

```
租户请求入口
    │
    ▼
Global API Gateway
    │
    ├── 地域亲和? → 路由到最近集群
    ├── 数据主权? → 路由到指定区域
    └── 负载均衡? → 选择负载最低的集群
            │
            ▼
    Fleet Manager (调度决策)
            │
            ▼
    ┌─────────────────────────┐
    │  Cluster Selector        │
    │  ├─ 地域 (geo/region)    │
    │  ├─ 负载 (当前 RPS/CPU)  │
    │  ├─ 容量 (max_agents)   │
    │  ├─ 租户亲和 (已有资源) │
    │  └─ 租户隔离 (强制区域) │
    └─────────────────────────┘
```

### 4. 数据同步策略

| 数据类型 | 同步策略 | 一致性 | 
|---------|---------|--------|
| Agent 定义 | 全局 → 集群 (push) | 最终一致 |
| 会话数据 | 本地存储，不跨集群 | 本地一致 |
| 记忆/知识库 | 全局 KV (Redis) 缓存 | 最终一致 |
| 审计日志 | 本地写入 + 全局 Kafka 聚合 | 最终一致 |
| 计费数据 | 本地聚合 → 全局汇总 | 最终一致 |
| 技能市场 | 全局 → 集群 (pull) | 强一致 |

### 5. 离线与故障恢复

```
Edge Cluster 离线场景:

   正常时:    Global CP ←──→ Edge Cluster (同步数据)
   
   断网时:    Edge Cluster 本地自治运行
              ├── 本地 Agent 继续执行
              ├── 本地会话/记忆保持
              ├── 本地审计缓存
              └── 本地计费暂存
   
   恢复时:    Global CP ←──→ Edge Cluster (增量同步)
              ├── 上传离线期间审计日志
              ├── 同步计费数据
              ├── 合并会话变更
              └── 拉取最新技能市场
```

---

## 实施路线

### Phase 1 (P0) — 基础联邦骨架

- [ ] 定义 `ClusterFederation` CRD
- [ ] Fleet Manager 注册/心跳/健康检查
- [ ] Global API Gateway 地域路由
- [ ] Kafka MirrorMaker 跨集群事件复制
- [ ] `sccsos federation join --cluster-id <id>` CLI

**工期**: 3 周

### Phase 2 (P1) — 数据同步与调度

- [ ] 全局 Agent 调度 (地域/负载/租户亲和)
- [ ] 全局技能市场同步
- [ ] 全局审计日志聚合
- [ ] 全局计费汇总
- [ ] 离线自治运行模式

**工期**: 3 周

### Phase 3 (P2) — 联邦管理控制台

- [ ] Vue 前端联邦管理页面
- [ ] 跨集群 Agent 拓扑可视化
- [ ] 跨集群事件实时日志
- [ ] 计费/审计按集群筛选

**工期**: 2 周

---

## 风险

| 风险 | 影响 | 缓解 |
|------|------|------|
| 网络分区 | 数据不一致 | 离线模式 + 增量同步 |
| 全局 Kafka SPOF | 跨集群事件丢失 | Kafka 多区域复制 + 本地缓存 |
| 数据合规 | 数据跨区域违规 | 区域亲和路由 + 数据主权标签 |
| 调度震荡 | Agent 频繁迁移 | 最小亲和窗口 + 重调度冷却期 |

---

## 与现有架构的关系

```
现有单集群架构:
  K8s Cluster
    ├── SCCS OS + Hermes
    ├── SQLite / PostgreSQL
    └── Local EventBus

联邦后:
  K8s Cluster A                 K8s Cluster B
    ├── SCCS OS + Hermes          ├── SCCS OS + Hermes
    ├── PostgreSQL (shard A)      ├── PostgreSQL (shard B)
    ├── Local EventBus            ├── Local EventBus
    └── Kafka Producer ─────┬────┘ └── Kafka Producer
                            │
                    Global Kafka (MirrorMaker)
                            │
                    ┌───────▼───────┐
                    │ Global CP      │
                    │ (Fleet Mgr +   │
                    │  API Gateway)  │
                    └───────────────┘
```
