# SCCS OS — Grafana 监控仪表盘

## 前置条件

1. **Prometheus** + **Grafana** 已部署（可用 `docker-compose.observability.yaml`）
2. sccsos 配置了 OpenTelemetry 导出：`sccsos.yaml` 中设置 `tracing.otlp_endpoint`
3. OTel Collector 配置了 Prometheus exporter

## 导入仪表盘

### 方法 A：Grafana UI

1. Grafana → 左侧菜单 → "+" → "Import"
2. Upload `deploy/grafana/sccsos-dashboard.json`
3. 选择 Prometheus 数据源
4. 点击 "Import"

### 方法 B：API 导入

```bash
curl -X POST "http://admin:password@localhost:3000/api/dashboards/db" \
  -H "Content-Type: application/json" \
  -d @deploy/grafana/sccsos-dashboard.json
```

## 面板说明

| 面板 | 说明 | 数据来源 |
|------|------|---------|
| Agent 总数 | 注册的 Agent 总数（含 running/created/paused） | `sccsos_agent_info` |
| 运行中 Agent | 当前活跃运行的 Agent 数量 | `sccsos_agent_info{status="running"}` |
| 失败 Agent | 报错 Agent 告警 | `sccsos_agent_info{status="failed"}` |
| Token 消耗趋势 | 按模型分组的 Token 消耗速率 | `sccsos_token_total` |
| 成本趋势 ($) | 按模型分组的 LLM 调用成本 | `sccsos_cost_usd_total` |
| Agent 状态分布 | 各状态的 Agent 数量柱状图 | `sccsos_agent_info` |
| 工作流执行状态 | 成功/失败的工作流数量趋势 | `sccsos_workflow_runs_total` |
| API 调用量 | 每分钟 API 请求量 | `sccsos_api_requests_total` |
| 平均延迟 | 按模型的平均响应延迟 | `sccsos_duration_ms_*` |
| 错误率 | 按 Agent 的调用错误率(%) | `sccsos_agent_errors_total / sccsos_agent_calls_total` |

## Prometheus 指标

sccsos 通过 OpenTelemetry SDK 暴露以下指标：

| 指标 | 类型 | 标签 |
|------|------|------|
| `sccsos_agent_info` | Gauge | `agent_id`, `name`, `status`, `tenant_id` |
| `sccsos_token_total` | Counter | `model`, `agent_id`, `tenant_id` |
| `sccsos_cost_usd_total` | Counter | `model`, `agent_id` |
| `sccsos_duration_ms_*` | Histogram | `model`, `agent_id` |
| `sccsos_workflow_runs_total` | Counter | `status`, `workflow_name` |
| `sccsos_api_requests_total` | Counter | `method`, `endpoint`, `status_code` |
| `sccsos_agent_calls_total` | Counter | `agent_id` |
| `sccsos_agent_errors_total` | Counter | `agent_id` |

## 告警建议

| 告警规则 | 条件 | 严重性 |
|---------|------|--------|
| Agent 宕机 | `sccsos_agent_info{status="failed"} > 0` 持续 5m | critical |
| 成本异常 | `rate(sccsos_cost_usd_total[1h]) > $threshold` | warning |
| 错误率超限 | 错误率 > 10% 持续 5m | warning |
| 工作流持续失败 | `rate(sccsos_workflow_runs_total{status="failed"}[15m]) > 5` | critical |
