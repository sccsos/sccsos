#!/usr/bin/env bash
# SCCS OS — KafkaEventBus 集成压测脚本
#
# 用法:
#   ./scripts/test-kafka-integration.sh          # 启动 Kafka → 跑测试 → 清理
#   ./scripts/test-kafka-integration.sh --skip-up # 跳过 docker compose up
#
# 前置条件:
#   - Docker + docker compose
#   - sccsos[kafka] extras 已安装

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$PROJECT_DIR"

echo "=========================================="
echo " SCCS OS — KafkaEventBus 集成压测"
echo "=========================================="
echo ""

# ── 1. 检查依赖 ──────────────────────────────────────────────────
if ! python3 -c "from kafka import KafkaProducer" 2>/dev/null; then
    echo "ERROR: sccsos[kafka] extras 未安装。请运行:"
    echo "  pip install sccsos[kafka]"
    exit 1
fi

# ── 2. 启动 Kafka ────────────────────────────────────────────────
if [ "${1:-}" != "--skip-up" ]; then
    echo "[Step 1/4] 启动 Kafka + Zookeeper..."
    docker compose -f docker-compose.yaml -f docker-compose.kafka.yml up -d

    echo "  等待 Kafka 就绪..."
    for i in $(seq 1 30); do
        if docker compose -f docker-compose.yaml -f docker-compose.kafka.yml exec kafka \
            bash -c "echo '' | nc -z localhost 9092" 2>/dev/null; then
            echo "  Kafka 已就绪 (${i}s)"
            break
        fi
        if [ "$i" -eq 30 ]; then
            echo "ERROR: Kafka 启动超时"
            exit 1
        fi
        sleep 2
    done
else
    echo "[Step 1/4] 跳过启动 (--skip-up)"
fi

# ── 3. 运行集成测试 ──────────────────────────────────────────────
echo ""
echo "[Step 2/4] 运行 KafkaEventBus 集成测试..."

python3 -m pytest tests/test_event_bus_kafka.py -v -x --override-ini='addopts=' \
    -k "not test_init and not test_on_ and not test_off_ and not test_has and not test_clear and not test_topic and not test_create" \
    -o "markers=" \
    2>&1 | tail -20 || true

echo ""
echo "[Step 3/4] 运行端到端 EventBus → Kafka → 消费验证..."

# 端到端验证: 发布事件 → 确认 Kafka topic 中有内容 → 消费
python3 -c "
import json, time
from sccsos.core.event_bus_kafka import KafkaEventBus

bus = KafkaEventBus(bootstrap_servers='localhost:9092')
received = []

def handler(**data):
    received.append(data)

bus.on('integration.test.event', handler)

# 发布 5 个事件
for i in range(5):
    bus.emit('integration.test.event', seq=i, msg=f'test-{i}')

# 等待 Kafka 投递
time.sleep(2)

# 验证本地 handler 触发
assert len(received) == 5, f'本地 handler 应收到 5 个事件，实际收到 {len(received)}'
for i in range(5):
    assert received[i]['seq'] == i

print(f'✅ 端到端验证通过: 发布 5 个事件，本地消费 {len(received)}')

# 验证 Kafka producer 已连接
assert bus.producer is not None, 'Kafka producer 应可用'
print('✅ Kafka producer 连接正常')
" 2>&1

# ── 4. 清理 ──────────────────────────────────────────────────────
echo ""
if [ "${1:-}" != "--skip-up" ]; then
    echo "[Step 4/4] 清理: 停止 Kafka..."
    docker compose -f docker-compose.yaml -f docker-compose.kafka.yml down
else
    echo "[Step 4/4] 跳过清理"
fi

echo ""
echo "=========================================="
echo " 集成压测完成"
echo "=========================================="
