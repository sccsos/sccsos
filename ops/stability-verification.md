# SCCS OS 72h 长期运行稳定性验证程序

> **关联**: P0-4 | **工具**: `scripts/stability_monitor.py`
> **版本**: v0.14.2 | **最后更新**: 2026-07-21

## 验证目标

| 指标 | 阈值 | 说明 |
|------|------|------|
| 内存泄漏 (RSS) | ≤500MB 峰值 | 72h 内无明显增长趋势 |
| 文件描述符泄漏 | ≤500 峰值 | close 操作无遗漏 |
| 线程泄漏 | ≤200 峰值 | 后台线程创建/销毁平 |
| 服务可用率 | ≥99.9% | /health 不返回 5xx |
| DB 连接 | 无 locked 错误 | SQLite WAL 正常工作 |
| CPU 使用率 | ≤80% | 空闲时 ≤5% |

## 执行方式

### 方案 A：直接运行（前台 72h）

```bash
# 1. 启动服务器
cd /path/to/sccsos
python3 -m sccsos.api.fastapi_app --port 8765 &

# 2. 启动稳定监控（72h 5min 间隔）
python3 scripts/stability_monitor.py \
  --base-url http://localhost:8765 \
  --duration 72h \
  --interval 5m \
  --output output/stability
```

### 方案 B：Cron 定时检查（推荐生产环境）

使用 Hermes cron 调度，每小时检查一次：

```bash
hermes cron create \
  --name "sccsos-stability-check" \
  --schedule "0 * * * *" \
  --prompt "运行 SCCS OS 稳定性检查脚本 scripts/stability_check.sh，汇报系统资源使用情况、API 健康状态、以及是否存在异常指标。重点关注内存、文件描述符、线程数是否有增长趋势。"
```

### 方案 C：后台进程（不阻塞终端）

```bash
nohup python3 scripts/stability_monitor.py \
  --duration 72h --interval 5m \
  --output output/stability &
```

## 输出文件

| 文件 | 格式 | 说明 |
|------|------|------|
| `output/stability/stability_metrics.csv` | CSV | 时序数据（每 tick 一行） |
| `output/stability/stability_alerts.json` | JSON | 异常告警列表 |

## CSV 字段说明

| 字段 | 单位 | 说明 |
|------|------|------|
| `timestamp` | ISO 8601 | UTC 时间戳 |
| `elapsed_hours` | 小时 | 运行时长 |
| `rss_mb` | MB | 进程常驻内存（核心指标） |
| `vms_mb` | MB | 虚拟内存 |
| `cpu_pct` | % | 进程 CPU 使用率 |
| `open_fds` | 个 | 打开文件描述符（检查泄漏） |
| `threads` | 个 | 线程数（检查泄漏） |
| `system_cpu` | % | 系统 CPU 总使用率 |
| `system_mem_pct` | % | 系统内存使用率 |
| `health_status` | HTTP | /health 返回码 |
| `health_latency_ms` | ms | /health 响应延迟 |
| `agent_count` | 个 | 注册 Agent 数 |
| `site_up` | 0/1 | 站点可用性 |

## 验收标准

```python
import csv
from pathlib import Path

with open("output/stability/stability_metrics.csv") as f:
    reader = csv.DictReader(f)
    rows = list(reader)

# 1. 内存无泄漏趋势
rss_values = [float(r["rss_mb"]) for r in rows]
peak_rss = max(rss_values)
first_rss = rss_values[0]
last_rss = rss_values[-1]
assert peak_rss < 500, f"RSS peak {peak_rss:.0f}MB > 500MB"
assert last_rss < first_rss * 1.5, f"RSS grew {first_rss:.0f}→{last_rss:.0f}MB"

# 2. 文件描述符无泄漏
fd_values = [int(r["open_fds"]) for r in rows]
assert max(fd_values) < 500, f"FD peak {max(fd_values)} > 500"
assert int(rows[-1]["open_fds"]) <= int(rows[0]["open_fds"]) * 1.3

# 3. 服务可用率
uptime = sum(1 for r in rows if r["site_up"] == "1")
total = len(rows)
assert uptime / total >= 0.999, f"Uptime {uptime}/{total} < 99.9%"

print(f"✅ 72h 稳定性验证通过: RSS {first_rss:.0f}→{last_rss:.0f}MB, "
      f"FD {fd_values[0]}→{fd_values[-1]}, uptime {uptime}/{total}")
```
