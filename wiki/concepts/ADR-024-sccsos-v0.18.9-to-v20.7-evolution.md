# ADR-024：SCCS OS v0.18.9→v0.20.7 — config-sync 分离与安全修复

- **日期**: 2026-07-25
- **状态**: 已接受
- **版本关联**: v0.18.9 ~ v0.20.7
- **当前版本**: v0.20.7
- **前置 ADR**: ADR-023（v0.16.5→v0.17.9 全封闭安装）
- **后置延续**: 待定

---

## 一、背景

v0.18.9 完成 Hermes CLI 安装流程和 Shell 环境配置后，config 同步逻辑内嵌在 `hermes_cmd.py`（~700 行）中，与 CLI 命令注册、Helm 管理、profile 管理等职责耦合。主要痛点：

1. 用户修改 `sccsos.yaml` 后无法单独重新同步配置（必须重新 `install` 或 `doctor --fix`）
2. `_auto_apply_config` 函数中 config 同步 + .env 管理 + profile 克隆 + 一致性验证 4 件事混在一起
3. 无单元测试覆盖 config 同步逻辑

本 ADR 覆盖 v0.18.9→v0.20.7 共 2 个版本的架构决策。

## 二、变更汇总

### v0.19.3 — config-sync 模块分离（2026-07-25）

| 变更 | 说明 |
|------|------|
| **`hermes_config_sync.py` 新建** | 从 `hermes_cmd.py` 分离 5 个函数到独立模块 |
| **`sccsos hermes config-sync`** | 新增独立 CLI 命令 |
| 迁移的函数 | `_auto_apply_config`, `_ensure_env_file`, `_set_default_config`, `_write_model_config`, `_build_hermes_env` |

### v0.20.7 — 修复（2026-07-25）

| 变更 | 说明 |
|------|------|
| **`_resolve_hermes_root()`** 新增 | 修复 `HERMES_HOME` 指向 profile 目录时路径解析错误 |
| **lambda `**kw` 兼容** | 修复 `_write_model_config` 调用 lambda 时 `extra_env` 关键字参数异常 |
| **`.env` 门控解除** | `_ensure_env_file` 不再依赖 `api_key` 非空，`base_url` 始终写入 |
| **注入检测 `\b` 词边界** | 修复 `python3 --version` 等反引号命令误报为命令注入 |

## 三、架构变化

### 3.1 模块关系（v0.20.7）

```
hermes_cmd.py (CLI 入口)
  ├── hermes_install.py     (安装核心逻辑)
  ├── hermes_config_sync.py (config/.env 同步)
  ├── hermes_setup.py       (交互式引导配置)
  └── hermes_doctor.py      (诊断 + 修复)
```

### 3.2 HERMES_HOME 路径解析

当 `HERMES_HOME` 环境变量指向 profile 子目录（如 Hermes WebUI 会话中常见），`_resolve_hermes_root()` 应用 walkup 逻辑：

```
HERMES_HOME = /Users/smart/dev/hermes/profiles/sccsos
  → parent.name == "profiles" → parent.parent
  → /Users/smart/dev/hermes                                    ✅ resolved root
```

所有 `hermes config set` 子进程调用均使用解析后的根路径。

### 3.3 .env 同步策略

| 场景 | api_key | base_url | 行为 |
|------|---------|----------|------|
| sccsos.yaml 有 api_key | ✅ 写入 | ✅ 写入 | 完整同步 |
| 仅环境变量有 api_key | ✅ 写入 | ✅ 写入 | 完整同步 |
| 两者均无 api_key | — | ✅ 写入 | 仅写入 base_url |
| 有 api_key 后重跑 | ✅ 追加 | ✅ 追加 | 增量写入 |

## 四、ADR 关联

| ADR | 关联 |
|-----|------|
| ADR-023 | 前序 — Hermes 安装体系（全封闭目录 + shell rc + 子进程 env） |
| ADR-014 | v0.9→v0.14 架构进化（事件总线、可观测性、安全体系基线） |
