# ADR-010: SCCS OS v0.8.1 Release Notes

## 版本信息

- **版本**: v0.8.1
- **日期**: 2026-07-22
- **基线**: v0.8.0 (3 commits → 9 commits)

## 变更摘要

### v0.8.0 (P0+P1+P2)

自 v0.7.1 以来的累积变更：

**P0 — 关键修复**
- DB 连接泄漏修复 (3 文件, 9 处 `conn.execute()` → `self._db.execute()`)
- CLI 拆分 (1 文件 1139 行 → 4 模块)
- Tracer.end_span 防御性返回 (防止级联 KeyError)

**P1 — 架构加固**
- EventBus 事件总线 (`core/event_bus.py`, 88 行)
- Config 自动映射 (`_from_dict` 60 行 → 20 行)
- Supervisor 监督模式 (`core/supervisor.py`, 心跳 + 自动重启)
- 核心测试覆盖 (+30 测试)

**P2 — 功能演进**
- 自定义 Jinja2 过滤器 (6 个: json_parse/dumps, pick, strptime/strftime, truncate_cn)
- Workflow Schema 版本化 (迁移系统 `@_register_migration`)
- Config 热加载 (`sccsos config reload`)

### v0.8.1

- `sccsos init` 新增 `config/` 目录和 `config/pricing.json` 样本文件
- 降级 pricing 未找到日志为 INFO 级别

## 测试状态

- **260 测试**, 0 失败
- 11 测试文件覆盖全部模块
- 测试 195 → 260 (+65)

## 项目结构

```
sccsos/
├── core/          (15 文件, ~4,500 行)  引擎层
├── cli/           (4 文件, ~2,000 行)   CLI
├── api/           (1 文件, ~530 行)     HTTP API
├── observability/ (6 文件, ~1,000 行)   可观测性
├── memory/        (4 文件, ~650 行)     持久化
├── security/      (3 文件, ~410 行)     安全
└── tests/         (11 文件, ~3,300 行)  测试
```

## 架构图

```
CLI (click, 10 commands)    API (http.server)
          │
     AgentRuntime (singleton)
          │
    ┌─────┼─────┬──────┬──────┐
    │     │     │      │      │
 Registry Runner Engine Session Supervisor
    │     │     │      │      │
    └─────┼─────┼──────┼──────┘
          │     │
      EventBus  Database (SQLite WAL)
          │     │
    ┌─────┴─────┴──────┐
    │ PolicyEngine     │
    │ CommandWhitelist │
    └────────┬─────────┘
             │
    ┌────────┴──────────┐
    │ Tracer / Auditor  │
    │ Webhook / Alert   │
    └───────────────────┘
```
