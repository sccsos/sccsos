# ADR-022：SCCS OS 架构进化 v0.15.0→v0.16.5 全景

- **日期**: 2026-07-27
- **状态**: 已接受
- **版本关联**: v0.15.0 ~ v0.16.5（9 个版本迭代）
- **当前版本**: v0.16.5
- **前置 ADR**: ADR-014（v0.9.0→v0.14.2 进化）、ADR-021（双模式 Docker）
- **后置延续**: ADR-023（计划：v0.17+ 性能基线 + 稳定化）

---

## 一、背景

v0.14.2 完成 P2 架构扩展（技能评分、故障自愈、RBAC、Vue SPA）后，SCCS OS 整体能力已超可行性方案定义的 P0+P1+P2 范围。v0.15.0→v0.16.5 聚焦**生产就绪度**，三个核心主题：

1. **Hermes 安装体验全面升级**（v0.15.6→v0.15.9）— 中国镜像、自动配置、实时进度
2. **配置同步体系**（v0.16.0→v0.16.4）— Profile 克隆、`.env` 密钥同步、`doctor` 一致性校验
3. **架构审计与基线修复**（v0.16.1）— 深度审计报告、健康评分修正、版本号全文件同步

整体演进遵循"**安装体验 → 配置一致 → 审计闭环**"的收尾主线。

## 二、逐版本决策与权衡

### v0.15.0→v0.15.5 — 架构审计与基线修复

| 决策 | 说明 |
|------|------|
| 深度架构审计 | 7 域 × 6 维度健康评分：12x 12=144 子项，24,649 行 / 108 源文件深度分析 |
| 健康评分 9.2→8.7 修正 | 发现 5 个 Major + 6 个 Minor 问题，评分从 9.2 回调至 8.7 |
| AgentMessageBus 标记 Deprecated | 228 行实现、零生产引用，代码确认死代码 |
| 版本号全文件同步 | 从 ~20 文件扩展到 46 文件同步（含 Dockerfile/K8s/Helm/文档/测试断言）|

**决策理由**：在进入生产验收前需要真实基线，避免自我评分膨胀。

**后果**：健康评分下降但实际质量提升（诚实基线），修复路线图清晰化。

### v0.15.6 — Hermes 安装实时流输出

| 领域 | 方案 | 决策理由 |
|------|------|---------|
| 安装进度 | 实时终端输出（`--progress-bar`） | 静默 300s+ 安装无反馈 = 用户以为卡死 |
| 脚本安装超时 | 300s → 600s | 国内网络带宽有限，需更宽窗口 |
| Git 安装超时 | clone 120s → 180s，fetch 60s → 120s | 大仓库 clone 在限速网络下慢 |
| Docker Pull 超时 | 300s → 600s | 大镜像 `nousresearch/hermes-agent` 约 2GB |

**后果**：用户现在可见逐行安装进度，不再怀疑进程挂起。

### v0.15.7→v0.15.8 — 内部修补

版本号同步 + 边界修复，无架构级决策。

### v0.15.9 — 中国镜像 + 自动安装后配置

| 决策 | 说明 |
|------|------|
| `--china-mirror` 三模式 | Git 镜像 `cnb.cool` / Docker 镜像 `docker.xuanyuan.run` / 脚本镜像 `res1.hermesagent.org.cn` |
| 安装后自动 `_auto_apply_config()` | 安装完成后自动将 `sccsos.yaml` 的 model/provider/base_url 同步到 Hermes profile，消除额外 `setup` 步骤 |

**决策理由**：中国大陆用户无法直接访问 GitHub/Nous Research CDN，需要官方墙内镜像。

**后果**：`sccsos hermes install --china-mirror` 一键完成安装+配置。

### v0.16.0 — `_auto_apply_config()` 策略重构 + `doctor` 一致性检查

| 决策 | 说明 |
|------|------|
| 先写默认配置，再克隆到目标 profile | 之前直接写目标 profile 导致 `~/.hermes/config.yaml` 缺失 |
| `doctor` 新增配置一致性检查 | 对比 `sccsos.yaml` ↔ Hermes profile 的 model/provider/base_url |
| `doctor --fix` 自动同步 | 检测到不一致时一键修复 |
| `_get_profile_config_path()` 健壮性提升 | 处理 `HERMES_HOME` 指向 `profiles/<name>` 子目录的异常 |

**决策理由**：用户运行 `sccsos hermes setup` 后，发现 `sccsos hermes doctor` 显示配置不一致，需要自动化修复。

**后果**：`doctor` 从诊断工具升级为诊断+修复工具。

### v0.16.1 — 架构审计深度报告

| 决策 | 说明 |
|------|------|
| 架构审计报告产出 | 24,649 行 / 108 源文件，12 域×6 维度 |
| AgentMessageBus 死代码确认 | 228 行实现、零生产引用，标记为 Deprecated |
| 健康评分 9.2 → 8.7 最终修正 | 审计出分从 9.2 回调至 8.7，后续恢复至 8.8 |

**后果**：后续 v0.16.2+ 的修复路径基于此审计报告。

### v0.16.2 — API Key 自动同步

| 决策 | 说明 |
|------|------|
| `_auto_apply_config()` 新增 `api_key` 处理 | 从环境变量 `DEEPSEEK_API_KEY` 自动同步到 Hermes profile 的 `model.api_key` |
| `_write_model_config()` 扩展 | 新增 `api_key` 参数，同步到默认配置和 profile 配置 |
| 交叉校验容错 | `api_key` 仅 profile 有不算不一致（Hermes 默认用 `.env` 存储） |

**决策理由**：用户期望 `sccsos hermes install` 后系统自动配置好 API Key，无需手动编辑。

### v0.16.3 — `.env` 密钥文件同步

| 决策 | 说明 |
|------|------|
| `_ensure_env_file()` 新增 | 写入 `~/.hermes/.env` 和 `~/.hermes/profiles/<name>/.env` |
| 权限 0o600 | 密钥文件仅 owner 可读写 |
| Profile 克隆修复 | 新 profile 创建时完整复制默认配置（~22 个顶层键），而非仅有 `model.*` |

**决策理由**：部分 Heremes CLI 行为读取 `.env` 而非 `config.yaml` 中的 `api_key`。同时需要两个文件都同步。

### v0.16.4 — Profile 克隆增加 `.env` 同步

| 决策 | 说明 |
|------|------|
| 创建新 profile 时自动复制 `.env` | 从 `~/.hermes/.env` → `~/.hermes/profiles/<name>/.env` |

**后果**：Profile 克隆现在完整同步 config + .env。

### v0.16.5 — hermes-installer 默认智能体

| 决策 | 说明 |
|------|------|
| `sccsos init` 默认生成 `agents/hermes-installer.yaml` | 而非之前的 `architect.yaml` |
| `architect.yaml` 仅在 `--samples` 时生成 | 简化首次体验 |
| `SAMPLE_PERSONALITY_HERMES_INSTALL` + `SAMPLE_AGENT_HERMES_INSTALL` 新模板 | 封装 Hermes 安装配置完整流程 |

**决策理由**：新用户最需要的是先配好 Hermes 底座，而非直接进入架构师角色。

## 三、架构影响

```
v0.14.2 → v0.16.5  (Production Hardening)
│
├─ Hermes Installation (v0.15.6→v0.15.9)
│  ├─ China mirror (三模式: git/docker/script)
│  ├─ Streaming progress (script/git/docker)
│  └─ Auto-config on install (model/provider/api_key sync)
│
├─ Config Synchronization (v0.16.0→v0.16.4)
│  ├─ Profile clone + .env sync
│  ├─ Doctor consistency check + --fix
│  └─ _auto_apply_config() strategy refactor
│
├─ Architecture Audit (v0.16.1)
│  ├─ Deep audit (24,649 LOC / 108 files)
│  ├─ Health score correction (9.2→8.7→8.8)
│  └─ AgentMessageBus deprecated
│
└─ Default Agent Strategy (v0.16.5)
   └─ hermes-installer as default → simplified onboarding
```

## 四、设计决策总结

| # | 决策 | 版本 | 类型 |
|---|------|:----:|:----:|
| 1 | Hermes 安装实时流输出取代静默等待 | v0.15.6 | 体验优化 |
| 2 | 三模式中国镜像（git/docker/script） | v0.15.9 | 地域适配 |
| 3 | 安装后自动配置同步 | v0.15.9 | 流程优化 |
| 4 | Doctor --fix 自动修复配置不一致 | v0.16.0 | 工具增强 |
| 5 | API Key 自动同步到 Hermes profile | v0.16.2 | 配置统一 |
| 6 | `.env` 密钥文件双写（HERMES_HOME + profile） | v0.16.3 | 安全 + 兼容 |
| 7 | 默认 Agent 策略从 architect→hermes-installer | v0.16.5 | 引导优化 |

## 五、后果

### 积极后果

- ✅ `sccsos hermes install --china-mirror` 全流程 < 2 分钟（国内）
- ✅ `sccsos hermes doctor --fix` 一键修复配置不一致
- ✅ 新用户 `sccsos init` 后直接 `agent ask` 即可使用
- ✅ `.env` 权限 0o600，密钥泄露风险降低
- ✅ 版本号 46 文件全同步，消除版本混乱

### 技术债务

- ⚠️ `with_injection_guard` / `with_rate_limiter` 的 Builder 链接线未完成（P0 安全修复残留）
- ⚠️ AgentMessageBus 零引用但未删除（Deprecated 标记，等待 v0.17 清理）
- ⚠️ `Dockerfile` 与 `Dockerfile.slim` 版本号需独立同步

### 后续待办

- [ ] Locust 500+ 并发压测 + 性能基线报告
- [ ] 72h 长期运行稳定性验证
- [ ] ADR-023 覆盖 v0.17+ 规划
- [ ] AgentMessageBus 正式清理（删除死代码）
