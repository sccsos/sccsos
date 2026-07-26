#!/usr/bin/env bash
# SCCS OS — K8s 部署验证清单（无集群时离线检查）
# 在真实 K8s 集群上执行验证时使用本脚本
set -euo pipefail

NAMESPACE="${NAMESPACE:-sccsos}"
DEPLOY_DIR="${DEPLOY_DIR:-deploy/k8s}"
TIMEOUT="${TIMEOUT:-120s}"

echo "═══ SCCS OS K8s 部署验证 ═══"
echo "  Namespace: ${NAMESPACE}"
echo "  Deploy dir: ${DEPLOY_DIR}"
echo

# ── Step 1: 资源文件存在性 ──
echo "1️⃣ 检查资源文件存在性"
REQUIRED=("00-namespace.yaml" "10-configmap.yaml" "20-pvc.yaml"
          "30-deployment.yaml" "40-service.yaml" "50-hpa.yaml")
for f in "${REQUIRED[@]}"; do
    if [ -f "${DEPLOY_DIR}/${f}" ]; then
        echo "  ✅ ${f} 存在"
    else
        echo "  ❌ ${f} 缺失"
        FAIL=1
    fi
done

# ── Step 2: 验证部署文件(需要 kubectl) ──
if command -v kubectl &>/dev/null; then
    echo
    echo "2️⃣ kubectl dry-run 验证"
    for f in "${REQUIRED[@]}"; do
        if kubectl apply --dry-run=client -f "${DEPLOY_DIR}/${f}" -o name &>/dev/null; then
            echo "  ✅ ${f} 语法通过"
        else
            echo "  ❌ ${f} 语法错误"
            kubectl apply --dry-run=client -f "${DEPLOY_DIR}/${f}" 2>&1 || true
            FAIL=1
        fi
    done
else
    echo "2️⃣ 跳过 kubectl 验证（未安装）"
fi

# ── Step 3: 版本一致性 ──
echo
echo "3️⃣ 版本一致性检查"
for f in "${REQUIRED[@]}"; do
    VER=$(grep -oP 'app\.kubernetes\.io/version:\s*"\K[^"]+' "${DEPLOY_DIR}/${f}" 2>/dev/null || echo "N/A")
    echo "  ${f}: app.kubernetes.io/version = ${VER}"
done

# ── Step 4: 镜像引用检查 ──
echo
echo "4️⃣ 镜像引用"
grep -rn "image:" "${DEPLOY_DIR}/30-deployment.yaml" 2>/dev/null || echo "  (未找到)"
grep -rn "image:" "${DEPLOY_DIR}/slim-sidecar/30-deployment.yaml" 2>/dev/null || echo "  (未找到 slim-sidecar)"

# ── Step 5: 启动验证（需要真实集群） ──
echo
echo "5️⃣ 启动验证（需要真实集群）"
cat <<VERIFY

在真实集群上执行：
  # 部署
  kubectl apply -f ${DEPLOY_DIR}/

  # 等待 Pod 就绪
  kubectl -n ${NAMESPACE} wait --for=condition=Ready pod -l app.kubernetes.io/name=sccsos --timeout=${TIMEOUT}

  # 健康检查
  kubectl -n ${NAMESPACE} port-forward svc/sccsos 8765:8765 &
  sleep 2
  curl -s http://localhost:8765/api/v1/health
  pkill -f "port-forward.*8765" || true

  # HPA 验证
  kubectl -n ${NAMESPACE} get hpa

  # PVC 验证
  kubectl -n ${NAMESPACE} get pvc

  # 日志检查
  kubectl -n ${NAMESPACE} logs --tail=50 deployment/sccsos

  # 扩缩容测试
  kubectl -n ${NAMESPACE} scale deployment/sccsos --replicas=3
  kubectl -n ${NAMESPACE} get pods -w &
  sleep 10
  kubectl -n ${NAMESPACE} scale deployment/sccsos --replicas=1
  pkill -f "get pods -w" || true
VERIFY
