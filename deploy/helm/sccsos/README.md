# SCCS OS Helm Chart

Deploy SCCS OS (Smart Agent Runtime Platform) on Kubernetes.

## Prerequisites

- Kubernetes 1.22+
- Helm 3.8+
- PV provisioner for persistent storage (default: 10Gi)

## Install

```bash
# From local chart
helm install sccsos ./deploy/helm/sccsos --namespace sccsos --create-namespace

# With custom values
helm install sccsos ./deploy/helm/sccsos \
  --namespace sccsos --create-namespace \
  -f my-values.yaml
```

## Configuration

| Parameter | Default | Description |
|-----------|---------|-------------|
| `mode` | `all-in-one` | Deployment mode: `all-in-one` or `slim+sidecar` |
| `image.repository` | `sccsos` | SCCS OS image repository |
| `image.tag` | `0.20.10` | SCCS OS image tag |
| `image.slimTag` | `0.20.10-slim` | Slim image tag (slim+sidecar mode) |
| `hermes.image.repository` | `sccsos-hermes` | Hermes sidecar image |
| `hermes.image.tag` | `0.20.10` | Hermes sidecar tag |
| `service.port` | `8765` | API service port |
| `service.type` | `ClusterIP` | Service type |
| `ingress.enabled` | `false` | Enable ingress |
| `ingress.host` | `sccsos.example.com` | Ingress hostname |
| `resources.requests.cpu` | `500m` | CPU request |
| `resources.requests.memory` | `512Mi` | Memory request |
| `autoscaling.enabled` | `true` | Enable HPA |
| `autoscaling.minReplicas` | `1` | Minimum pods |
| `autoscaling.maxReplicas` | `5` | Maximum pods |
| `persistence.enabled` | `true` | Enable PVC |
| `persistence.size` | `10Gi` | Storage size |
| `config.database.driver` | `sqlite` | Database driver (sqlite/postgresql) |
| `config.database.path` | `/sccsos/data/sccsos.db` | SQLite path |

## Deployment Modes

### all-in-one (default)
Single container with SCCS OS + Hermes Agent bundled.

### slim+sidecar
Two containers: sccsos-slim (API) + hermes-agent (sidecar).
Use for production deployments with clear separation of concerns.

## Post-Install

```bash
# Initialize
kubectl exec deploy/sccsos -- sccsos init

# Register an agent
kubectl exec deploy/sccsos -- sccsos agent create architect

# Check health
kubectl exec deploy/sccsos -- sccsos health
```

## Uninstall

```bash
helm uninstall sccsos --namespace sccsos
kubectl delete namespace sccsos
```
