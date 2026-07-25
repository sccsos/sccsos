# ADR-023：SCCS OS 架构进化 v0.16.5→v0.17.9 — 全封闭安装与生产环境适配

- **日期**: 2026-07-24
- **状态**: 已接受
- **版本关联**: v0.16.5 ~ v0.17.9（14 个版本迭代）
- **当前版本**: v0.17.9
- **前置 ADR**: ADR-022（v0.15.0→v0.16.5 进化）、ADR-021（双模式 Docker）
- **后置延续**: ADR-024（v0.18.9→v0.19.4 config-sync 分离与安全修复）

---

## 一、背景

v0.16.5 完成 Hermes 安装配置系统的基础搭建后，SCCS OS 进入**全封闭安装与生产环境适配**阶段。核心矛盾：Hermes Agent 的安装过程高度依赖网络环境（GitHub/官方 CDN），多模式安装（script/git/docker）的环境变量注入路径断裂，以及安装后 Shell 环境配置需要人工介入。

本 ADR 覆盖 v0.16.5→v0.17.9 共 14 个版本的架构决策，核心主题：

1. **全封闭安装目录布局** — 定义标准化的 `$HOME/hermes/` 目录树（`data/`/`agent/`/`uv-cache/`/`bin/`）
2. **子进程环境变量注入体系** — 从 `sccsos.yaml` → `install.sh` 的全链路 env 传递
3. **Shell RC 自动配置** — 跨 shell（bash/zsh）的环境变量自动写入
4. **架构审计与评分修正** — 深度审计 24,649 行代码，补充 5 Major + 6 Minor 发现问题

---

## 二、全封闭安装目录布局

### 2.1 问题

Hermes Agent 原生安装的默认目录 (`~/.hermes/`) 与自定义前缀期望的目录树 (`~/hermes/runtime/` + `~/hermes/install/`) 不一致，导致：
- 安装后 binary 不可达（PATH 未包含 `$HERMES_INSTALL_DIR/venv/bin`）
- UV 缓存目录意外增长（未纳入管控）
- 多实例部署时目录标准不统一

### 2.2 决策

标准化 `$HOME/hermes/` 目录树：

```
$HOME/hermes/
├── data/                     # HERMES_HOME（运行时数据）
│   ├── profiles/
│   ├── skills/
│   ├── sessions/
│   ├── memories/
│   └── cron/
├── agent/                    # HERMES_INSTALL_DIR（安装目标）
│   └── venv/bin/hermes       # 实际 binary 位置
├── bin/                      # UV 等工具目录
├── uv-cache/                 # UV_CACHE_DIR
└── config.yaml               # 顶层 Hermes 配置

环境变量：
  HERMES_HOME=$HOME/hermes/data
  HERMES_INSTALL_DIR=$HOME/hermes/agent
  UV_INSTALL_DIR=$HOME/hermes/bin
  UV_CACHE_DIR=$HOME/hermes/uv-cache
  PATH=$HERMES_HOME/bin:$HERMES_INSTALL_DIR/venv/bin:$PATH
```

**关键设计原则**：
- `HERMES_HOME` 和 `HERMES_INSTALL_DIR` 是完全独立的两条配置轴，去除中间变量 `HOME_HERMES`
- `install.sh` 子进程通过 `--prefix` 参数接收安装目录，同时通过 env var 传递 UV 配置
- shell RC 中仅写入四大核心变量，不写入派生变量

### 2.3 `sccsos.yaml` 配置段

```yaml
hermes:
  install_dir: ""              # HERMES_INSTALL_DIR（空=自动回退）
  home: ""                     # HERMES_HOME（空=自动回退）
  shell_rc:
    auto_setup: true           # 安装后自动写入 RC 文件
    rc_file: ""                # 指定 RC 文件（空=自动检测）
  uv:
    install_dir: ""            # UV_INSTALL_DIR
    cache_dir: ""              # UV_CACHE_DIR
```

优先级：`环境变量 > sccsos.yaml > 系统默认值`

---

## 三、子进程环境变量注入体系

### 3.1 问题

`sccsos hermes install` 通过子进程调用 `install.sh`（script 模式）、`pip install`（git 模式）或 `docker pull`（docker 模式）。这些子进程不继承 Hermes 配置中的 `HERMES_HOME`/`HERMES_INSTALL_DIR`/`UV_INSTALL_DIR`/`UV_CACHE_DIR`，导致自定义前缀安装时配置全部写入默认路径 `~/.hermes/`。

### 3.2 决策

三模式 env 注入架构：

```
sccsos.yaml → _build_hermes_env() → 子进程 env
```

| 模式 | 注入方式 | 关键 env var |
|------|---------|-------------|
| script | `subprocess.run(env=merged_env)` | `HERMES_HOME`, `HERMES_INSTALL_DIR`, `UV_INSTALL_DIR`, `UV_CACHE_DIR`, `DEEPSEEK_API_KEY` |
| git | `subprocess.run(env=merged_env)` + `pip install -e` 上下文 | 同上 + `HERMES_CODE_PATH`（已废弃） |
| docker | `docker run -e VAR=VALUE` | 同上（container 内透传） |

**合并策略**：`merged_env = {**os.environ, **extra_env}` — 子进程继承父进程全部环境变量，extra_env 覆盖/新增配置字段。

### 3.3 安装后自动配置链

```
install() 完成
  └─ _auto_apply_config()
       ├─ _ensure_home_structure()   → 创建 $HERMES_HOME 目录树
       ├─ _ensure_env_file()         → 写入 .env（API Key 权限 0o600）
       ├─ _clone_default_profile()   → 从默认配置克隆到目标 profile
       ├─ _write_model_config()      → 写入 model/provider/base_url
       ├─ _setup_shell_rc()          → 写入 .bashrc/.zshrc
       └─ 连通性验证                  → hermes -z ping
```

---

## 四、Shell RC 自动配置

### 4.1 决策

`_setup_shell_rc()` 在安装完成后自动将四大核心环境变量写入用户 shell RC 文件：

```bash
# SCCS OS Hermes Agent 环境变量
export HERMES_HOME=$HOME/hermes/data
export HERMES_INSTALL_DIR=$HOME/hermes/agent
export UV_INSTALL_DIR=$HOME/hermes/bin
export UV_CACHE_DIR=$HOME/hermes/uv-cache
export PATH=$HERMES_HOME/bin:$HERMES_INSTALL_DIR/venv/bin:$PATH
```

**检测逻辑**：
1. 检测 `$SHELL` → bash（`.bashrc`）/ zsh（`.zshrc`）
2. 已存在相同 export 则跳过（幂等）
3. 尾部追加空行 + 注释分隔 + 变量声明

**CLI 接口**：
- `sccsos hermes install --shell-rc`（安装时启用）
- `sccsos hermes env-setup`（单独执行）

---

## 五、架构审计与评分修正

### 5.1 v0.16.1 深度审计

对 24,649 行 / 108 源文件进行 7-Domain 深度审计，发现：

| 严重度 | 数量 | 典型问题 |
|:------:|:----:|---------|
| 🔴 Major | 5 | AgentMessageBus 死代码 228 行零引用、PolicyEngine 构造失败静默吞异常、CommandWhitelist 引号内误判 |
| 🟢 Minor | 6 | 配置路径转换、日志记录统一、运行时线程管理规范化 |

**评分修正**：9.2 → 8.7（后修复至 8.8）

### 5.2 核心修复

| 域 | 修复内容 |
|----|---------|
| 安全沙箱 | CommandWhitelist 引号感知匹配（`'...'`/`"..."` 内容剥离后再检查符号模式） |
| Agent 生命周期 | PolicyEngine 失败由 `bare except` 改为 `logger.critical` + 异常详情 |
| 可观测性 | `AgentRuntime.initialize()` 异常日志切换为结构化 `get_logger()` |
| 事件解耦 | WorkflowRuntime 后台线程从 `threading.Thread(daemon=True)` 合并为共享 `ThreadPoolExecutor` |
| AgentMessageBus | 标记为 Deprecated（228 行实现零生产引用，保留仅用于测试） |

### 5.3 架构影响

| 域 | 权重 | v0.16.0 评分 | v0.16.5 评分 | v0.17.9 评分 |
|---|:----:|:------------:|:------------:|:------------:|
| 多智能体编排 | 20% | 9.5 | 9.3 | 9.3 |
| 工具增强型 LLM | 15% | 9.0 | 9.0 | 9.0 |
| Agent 生命周期 | 15% | 9.5 | 9.5 | 9.5 |
| 可观测性 | 15% | 8.5 | 8.7 | 8.8 |
| 安全沙箱 | 10% | 9.0 | 9.2 | 9.2 |
| 记忆系统 | 10% | 9.0 | 9.0 | 9.0 |
| 提示工程 | 5% | 8.5 | 8.5 | 8.5 |
| 多租户隔离 | 5% | 8.5 | 8.5 | 8.5 |
| 事件与解耦 | 5% | 9.0 | 9.0 | 9.0 |
| 基础设施 | 5% | 8.0 | 8.5 | 8.5 |
| 计费系统 | 5% | 9.0 | 9.0 | 9.0 |
| 测试质量 | 5% | 8.5 | 9.2 | 9.2 |
| **综合** | **100%** | **8.7** | **8.8** | **8.8** |

---

## 六、核心架构原则

1. **全封闭安装** — SCCS OS 应当完全管理 Hermes Agent 的安装目录、环境变量和 Shell 配置，用户无需手动干预
2. **env 传递** — `sccsos.yaml` 中的非默认配置必须通过环境变量传递到子进程
3. **幂等性** — 安装后配置、Shell RC 写入、Profile 克隆都必须是幂等的
4. **优先级** — 环境变量 > `sccsos.yaml` > 系统默认值
5. **可观测性** — 安装失败要有清晰的诊断信息（`doctor` 命令），而非 silent failure

---

## 七、关键决策

| # | 决策 | 备选方案 | 理由 |
|---|------|---------|------|
| 1 | 安装后自动执行 `_auto_apply_config()` | 让用户手动运行 `setup` | 减少用户操作步骤，P0 体验 |
| 2 | 四大独立 env var 而非单一 `HOME_HERMES` 派生 | `HOME_HERMES` 中间变量方案 | 减少间接层，shell 启动时更快 |
| 3 | `install.sh` 子进程使用 merged_env 而非 partial | 仅传递必需变量 | 避免遗漏（如 Docker socket 路径、https_proxy）|
| 4 | `.env` 文件权限 0o600 | 默认 0o644 | API Key 安全合规 |
| 5 | Shell RC 写入采用幂等检查 | 无条件追加 | 多次安装不污染 RC 文件 |
| 6 | `install_dir` 替代 `code_path` | 保留 `code_path` | code_path 语义模糊（源码 vs 安装），install_dir 语义清晰 |
| 7 | `pip install sccsos[...]` 通过文件协议引用 WHL | 通过 `--find-links` | 版本锁定明确，构建可复现 |

---

## 八、遗留项

| # | 项 | 优先级 | 说明 |
|---|----|:------:|------|
| 1 | Hermes CLI 版本校验 | P2 | `hermes --version` 返回版本号，需要确认与 SCCS OS 的兼容性 |
| 2 | 多模式安装 CI 测试矩阵 | P2 | pip / docker / git-installer 三种模式的 CI 自动化验证 |
| 3 | 离线安装包制作 | P3 | 预下载 Hermes WHL + install.sh 到本地，离线环境安装 |
| 4 | 安装后重启持久化 | P3 | Shell RC 写入后需用户手动 `source ~/.zshrc`，可考虑自动 `exec $SHELL` |

---

## 九、结论

v0.16.5→v0.17.9 完成了 SCCS OS 的**全封闭安装能力**，使系统能完全托管 Hermes Agent 的安装、配置、环境集成全流程。这是继 Phase 3 商业能力后的**生产就绪度关键补全**——从"开发者手动配置"模式升级为"一键安装即用"模式。架构健康评分稳定在 8.8/10，后续聚焦性能基线验证与大规模稳定性测试。
