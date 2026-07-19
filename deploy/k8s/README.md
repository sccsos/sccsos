# SCCS OS — Kubernetes Deployment

## Quick Start

```bash
# 1. Build and push the container image
docker build -t sccsos:0.10.0 .
docker tag sccsos:0.10.0 your-registry/sccsos:0.10.0
docker push your-registry/sccsos:0.10.0

# 2. Update image in 30-deployment.yaml, then apply
kubectl apply -f deploy/k8s/

# 3. Verify
kubectl -n sccsos get pods
kubectl -n sccsos port-forward svc/sccsos 8765:8765
curl http://localhost:8765/health
```

## File Structure

```
deploy/k8s/
├── 00-namespace.yaml    # sccsos namespace
├── 10-configmap.yaml    # sccsos.yaml configuration
├── 20-pvc.yaml          # PersistentVolumeClaims (data + logs)
├── 30-deployment.yaml   # Main deployment (liveness + readiness probes)
├── 40-service.yaml      # ClusterIP service
├── 50-hpa.yaml          # HorizontalPodAutoscaler (CPU > 70%)
└── README.md            # This file
```

## Apply Order

```bash
kubectl apply -f deploy/k8s/00-namespace.yaml
kubectl apply -f deploy/k8s/10-configmap.yaml
kubectl apply -f deploy/k8s/20-pvc.yaml
kubectl apply -f deploy/k8s/30-deployment.yaml
kubectl apply -f deploy/k8s/40-service.yaml
kubectl apply -f deploy/k8s/50-hpa.yaml
```

Or apply all at once:
```bash
kubectl apply -f deploy/k8s/
```

## Configuration

Edit `10-configmap.yaml` to adjust SCCS OS settings before deploying.
The ConfigMap is mounted at `/sccsos/config/sccsos.yaml` inside the container.

## Persistent Storage

- `/sccsos/data` — SQLite database (10Gi PVC)
- `/sccsos/logs` — Application logs (5Gi PVC)
- `/sccsos/traces` — Trace exports (emptyDir, non-persistent)

## Resource Limits

| Resource | Request | Limit |
|----------|---------|-------|
| CPU      | 250m    | 1000m |
| Memory   | 512Mi   | 2Gi   |

## Health Checks

- **Liveness**: `GET /health` — restart if unresponsive
- **Readiness**: `GET /health` — route traffic only when ready
- **Period**: 30s (liveness), 10s (readiness)
- **Startup delay**: 10s (liveness), 5s (readiness)
