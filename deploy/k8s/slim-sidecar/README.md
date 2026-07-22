# SCCS OS — Slim + Sidecar K8s 部署模式

此目录包含 slim+sidecar 模式的 K8s 部署清单，与 `deploy/k8s/` 中的全合一模式对应。

## 架构

```
Pod
├── sccsos (sccsos:0.16.5-slim)    ← 主容器，无 Hermes 嵌入
│   ├── FastAPI Server :8765
│   ├── Workflow Engine
│   └── HermesAdapter (docker-exec)
│
└── hermes-agent (sccsos-hermes:0.16.5)  ← Sidecar，仅 Hermes CLI
    └── sleep infinity (等待 docker exec 调用)
```

## 与全合一模式的区别

| 维度 | 全合一 (deploy/k8s/) | Slim+Sidecar (deploy/k8s/slim-sidecar/) |
|------|---------------------|----------------------------------------|
| 镜像 | sccsos:0.16.5 (~600MB) | sccsos:0.16.5-slim (~350MB) + sccsos-hermes:0.16.5 (~120MB) |
| 总大小 | ~600MB | ~470MB |
| 扩缩容 | 绑定 | 可独立 HPA |
| 版本管理 | 同步升级 | 独立升级 |
| 通信方式 | subprocess | docker exec (需 Docker socket) |

## 前置条件

1. 构建 slim 和 hermes 镜像：
   ```bash
   docker build -t sccsos:0.16.5-slim -f Dockerfile.slim .
   docker build -t sccsos-hermes:0.16.5 -f Dockerfile.hermes .
   ```

2. 创建 API Key Secret：
   ```bash
   kubectl create secret generic sccsos-secrets \
     --namespace sccsos \
     --from-literal=deepseek-api-key='sk-xxx'
   ```

3. 确保 K8s 节点有 Docker socket（hostPath）。部分托管 K8s 服务可能限制此操作。

## 部署

```bash
# 先部署基础设施（namespace, PVC, 共享资源）
kubectl apply -f ../00-namespace.yaml
kubectl apply -f ../20-pvc.yaml

# 部署 slim+sidecar
kubectl apply -f 10-configmap.yaml
kubectl apply -f 30-deployment.yaml

# 确认
kubectl get pods -n sccsos
kubectl logs -n sccsos -l app.kubernetes.io/name=sccsos -c sccsos
```
