# SCCS OS — 生产部署 CheckList

> 用于新环境上线前的逐项检查，确保生产就绪。

## □ 1. 基础设施

| 检查项 | 验证方法 | 完成 |
|--------|---------|------|
| K8s 集群版本 ≥ 1.24 | `kubectl version --short` | □ |
| 节点数量 ≥ 3 | `kubectl get nodes` | □ |
| 持久化 StorageClass 已配置 | `kubectl get storageclass` | □ |
| Ingress Controller 已部署 | `kubectl get pods -n ingress-nginx` | □ |
| 镜像仓库可访问 | `docker pull your-registry/sccsos:0.14.0` | □ |

## □ 2. 配置

| 检查项 | 验证方法 | 完成 |
|--------|---------|------|
| ConfigMap 中 `sccsos.yaml` 配置正确 | `kubectl get configmap -n sccsos sccsos-config -o yaml` | □ |
| 数据库路径已配置（默认 SQLite 或 PostgreSQL） | 检查 `database.path` 或 `database.url` | □ |
| 日志格式为 JSON（生产推荐） | `logging.json_format: true` | □ |
| 定价文件已配置或接受默认值 | `config/pricing.json` | □ |
| 密钥已配置（External Secrets / Vault） | `kubectl get secrets -n sccsos` | □ |
| CORS 配置已按需调整 | `api.cors_origins` | □ |

## □ 3. 密钥与安全

| 检查项 | 验证方法 | 完成 |
|--------|---------|------|
| API 密钥不硬编码 | 检查 `.env` 未提交到 git | □ |
| `X-Role` RBAC 已启用 | `curl -H "X-Role: viewer"` 应返回 403 对写操作 | □ |
| `X-Tenant-ID` 隔离已验证 | 不同租户数据不应互通 | □ |
| **TLS 已配置** | `kubectl get certificates -n sccsos`（cert-manager）或 Ingress TLS 配置 | □ |
| **mTLS 已配置（可选）** | Service Mesh (Istio/Linkerd) 双向 TLS | □ |
| **安全审计全链路通过** | `python3 -m pytest tests/test_security_audit.py -q` → 43 passed, 0 failed | □ |
| 网络策略已配置 | `kubectl get networkpolicies -n sccsos` | □ |
| Pod 安全策略已配置 | `securityContext` 在 deployment.yaml 中 | □ |

## □ 4. 可观测性

| 检查项 | 验证方法 | 完成 |
|--------|---------|------|
| 健康端点可用 | `curl http://localhost:8765/api/v1/health` | □ |
| 日志采集对接 EFK/PLG | `kubectl get pods -n logging` | □ |
| 告警规则已配置 | 错误率 > 10% / 失败计数 > 20 | □ |
| Span 追踪已启用（可选） | `sccsos[otel]` + OTLP exporter | □ |
| Webhook 端点已配置 | `sccsos config webhook list` | □ |

## □ 5. 性能与容量

| 检查项 | 验证方法 | 完成 |
|--------|---------|------|
| HPA 已配置并工作 | `kubectl get hpa -n sccsos` | □ |
| 资源 limits 已设置 | `kubectl describe deployment -n sccsos sccsos` | □ |
| **Locust 500 并发压测已执行** | `locust -f tests/locustfile.py --headless -u 500 -r 50 --run-time 60s` | □ |
| **参考报告** | `output/benchmark/性能基线报告.md` | □ |
| P99 延迟 < 500ms | 参考压测报告（单 worker 限流已知，建议 `--workers 4`） | □ |

## □ 6. 灾备恢复

| 检查项 | 验证方法 | 完成 |
|--------|---------|------|
| 数据库备份策略已定义 | `data/` PVC 定期快照，或 `scripts/backup_db.sh` | □ |
| 备份自动化已配置 | CronJob / `kubectl create cronjob` 定期执行 | □ |
| 恢复流程已文档化 | 见下方"灾备恢复流程" | □ |
| 配置备份已纳入 CI/CD | `sccsos.yaml` 版本管理 | □ |
| **72h 稳定性验证已完成** | `python3 scripts/stability_monitor.py --duration 72h` → uptime > 99.9% | □ |

---

# 灾备恢复流程

## 场景 A: Pod 崩溃（自动恢复）

```bash
# 检查状态
kubectl -n sccsos get pods
kubectl -n sccsos describe pod <name>

# Deployment 自动重启（liveness probe 检测到失败后 30s）
kubectl -n sccsos rollout status deployment/sccsos

# 如果自动恢复失败
kubectl -n sccsos rollout restart deployment/sccsos
```

## 场景 B: 数据损坏（从 PVC 快照恢复）

```bash
# 1. 缩容到 0
kubectl -n sccsos scale deployment sccsos --replicas=0

# 2. 从快照创建新 PVC
# （具体命令取决于 StorageClass / 云厂商）

# 3. 更新 deployment 引用新 PVC
kubectl -n sccsos set volume deployment/sccsos \
  --add --name=data --mount-path=/sccsos/data \
  --type=persistentVolumeClaim --claim-name=<restored-pvc>

# 4. 恢复运行
kubectl -n sccsos scale deployment sccsos --replicas=1
```

## 场景 C: 版本回滚

```bash
# 查看历史版本
kubectl -n sccsos rollout history deployment/sccsos

# 回滚到上一个版本
kubectl -n sccsos rollout undo deployment/sccsos

# 回滚到指定版本
kubectl -n sccsos rollout undo deployment/sccsos --to-revision=3

# Helm 回滚
helm rollback sccsos 1 --namespace sccsos
```

## 场景 D: 完整集群故障

```bash
# 1. 在新的 K8s 集群部署
kubectl apply -f deploy/k8s/

# 2. 恢复数据库（从外部备份）
# （SQLite: 复制 .db 文件到 PVC; PostgreSQL: pg_restore）

# 3. 验证数据完整性
curl http://<new-cluster-ip>:8765/api/v1/health
```

---

# 监控告警配置指南

## 关键指标

| 指标 | 告警阈值 | 严重级别 | 说明 |
|------|---------|---------|------|
| `error_rate` | WARNING > 10%, CRITICAL > 30% | P2/P1 | 最近 1h 内调用失败率 |
| `failure_count` | WARNING > 5, CRITICAL > 20 | P3/P2 | 最近 1h 内失败调用总数 |
| Pod 状态 | CrashLoopBackOff > 5min | P0 | 应用崩溃 |
| P99 延迟 | > 1s | P1 | API 响应变慢 |

## AlertManager 配置

在 `sccsos.yaml` 中配置告警阈值：

```yaml
policies:
  default:
    max_cost_usd: 100.0  # 每日预算上限
    error_rate_threshold: 0.1   # 10% 错误率触发警告
    failure_count_threshold: 5  # 5 次失败触发警告

webhooks:
  enabled: true
  endpoints:
    - url: "https://hooks.example.com/alerts"
      events: ["alert", "failed"]
      secret: "<webhook-secret>"
```

## Prometheus 集成

```yaml
# prometheus-adapter 配置示例
apiVersion: v1
kind: ConfigMap
metadata:
  name: prometheus-rules
  namespace: sccsos
data:
  sccsos-alerts.yaml: |
    groups:
      - name: sccsos
        rules:
          - alert: HighErrorRate
            expr: rate(sccsos_errors_total[5m]) > 0.1
            for: 5m
            labels: { severity: critical }
            annotations:
              summary: "SCCS OS high error rate"
```

---

# 性能基准参考

| 场景 | 并发用户 | RPS | P50 | P95 | P99 |
|------|---------|-----|-----|-----|-----|
| 健康检查 | 10 | ~500 | <5ms | <10ms | <20ms |
| 混合负载 (R:W=6:4) | 10 | ~200 | <20ms | <50ms | <100ms |
| 混合负载 | 50 | ~800 | <30ms | <80ms | <200ms |
| 混合负载 | 100 | ~1200 | <50ms | <150ms | <400ms |

*以上基准在 4C/8G 节点上测得，实际性能因配置而异。*

---

## □ 7. 架构优化（v0.14.2+）

| 检查项 | 验证方法 | 完成 |
|--------|---------|:----:|
| PolicyEngine 日志已 CRITICAL 级别 | `grep -r 'PolicyEngine init failed' $(find . -name '*.py')` 确认有 logger.critical | □ |
| WorkflowRuntime 线程池已统一 | `grep -r 'ThreadPoolExecutor' sccsos/core/runtime_workflow.py` 确认存在 | □ |
| Config 迁移已检验 | `grep -r 'tracing.pricing_path' sccsos.yaml` — 如无引用则无 deprecation warning | □ |
| AgentRuntime 日志通道正确 | `grep 'get_logger()' sccsos/core/agent_runtime.py` | □ |
| _run_contexts 清理存在 | `grep '_run_contexts.pop' sccsos/core/workflow/engine.py` | □ |

运行 `locust -f tests/locustfile.py --headless -u 10 -r 2 --run-time 60s` 重新测量。
