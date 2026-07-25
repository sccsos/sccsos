# Hermes 环境变量引用清单（按函数分组）

> 生成: 2026-07-25 | 版本: v0.20.8
> 用途: 排查环境变量传递问题时快速定位哪个函数读/写哪个变量

---

## 一、GETTER 函数（读取 env → 返回路径）

| 函数 | 文件:行 | 读 env | 回退链 |
|------|---------|--------|--------|
| `_get_hermes_home()` | `hermes_cmd.py:86` | `HERMES_HOME` | env → `cfg.home` → `$HOME/hermes/data` |
| `_get_hermes_install_dir()` | `hermes_cmd.py:106` | `HERMES_INSTALL_DIR` | env → `cfg.install_dir` → `$HOME/hermes/agent` |
| `_get_uv_install_dir()` | `hermes_cmd.py:120` | `UV_INSTALL_DIR` | env → `cfg.uv.install_dir` → `$HOME/hermes/data/bin` |
| `_get_uv_cache_dir()` | `hermes_cmd.py:134` | `UV_CACHE_DIR` | env → `cfg.uv.cache_dir` → `$HOME/hermes/data/uv-cache` |
| `_resolve_hermes_binary()` | `hermes_cmd.py:57` | `HERMES_BIN` / `HERMES_BINARY` | env(存在性验证) → `cfg.binary` → `_find_hermes_bin_dir()` → `"hermes"` |
| `_find_hermes_bin_dir()` | `hermes_config_sync.py:148` | `HERMES_BIN_DIR` | env → 6 个候选路径 → `shutil.which("hermes")` |
| `_resolve_hermes_root()` | `hermes_config_sync.py:129` | 无（调用 `_get_hermes_home`） | walkup profile dir → 返回根目录 |
| `_build_hermes_env()` | `hermes_config_sync.py:193` | 无（调用 getter 函数） | 组装 `extra_env` 字典给子进程 |

---

## 二、SETTER 函数（计算路径 → 写入 env）

### 2.1 `_setup_shell_rc()` — `hermes_install.py:262`

写 rc 文件 + 导出到当前会话（`os.environ`）：

| 行 | 写入 env | 值来源 |
|----|----------|--------|
| 289 | `HERMES_HOME` | `home or "$HOME/hermes/data"` |
| 290 | `HERMES_CONFIG_PATH` | 同 `HERMES_HOME` |
| 291 | `HERMES_INSTALL_DIR` | `install_dir or "$HOME/hermes/agent"` |
| 292 | `HERMES_BIN` | `$HERMES_INSTALL_DIR/venv/bin/hermes` |
| 293 | `HERMES_BIN_DIR` | `$HERMES_INSTALL_DIR/venv/bin` |
| 294 | `UV_INSTALL_DIR` | `$HERMES_HOME/bin` |
| 295 | `UV_CACHE_DIR` | `$HERMES_HOME/uv-cache` |
| 296 | `PATH` | `$HERMES_INSTALL_DIR/venv/bin:$HERMES_HOME/bin:$PATH` |

**注意**: 行 301-303 有跳过逻辑 —— 若 rc 文件已有 `HERMES_INSTALL_DIR` 和 `HERMES_CONFIG_PATH`，整个函数（包括上述写入）**全部跳过**。

### 2.2 `install()` hermes_cmd — `hermes_cmd.py:438`

| 行 | 写入 env | 值来源 |
|----|----------|--------|
| 444 | `HERMES_HOME` | `resolved_home` |
| 445 | `HERMES_CONFIG_PATH` | `resolved_home` |
| 446 | `HERMES_INSTALL_DIR` | `resolved_install_dir` |
| 447 | `UV_INSTALL_DIR` | `resolved_uv_bin` |
| 448 | `UV_CACHE_DIR` | `resolved_uv_cache` |
| — | `HERMES_BIN` / `HERMES_BIN_DIR` | ⚠️ **未写入**（由后续 `_setup_shell_rc` 写入） |

路径来源：
- `resolved_home = home or _get_hermes_home()`
- `resolved_install_dir = install_dir or _get_hermes_install_dir()`

### 2.3 `_install_git()` — `hermes_install.py:92`

子进程 env（仅 pip install 子进程可见）：

| 行 | 写入 env | 值 |
|----|----------|-----|
| 162 | `HERMES_HOME` | `hermes_home` |
| 163 | `HERMES_CONFIG_PATH` | `hermes_home` |
| 164 | `HERMES_INSTALL_DIR` | `final_install_dir` |
| 165 | `UV_INSTALL_DIR` | `final_uv_install` |
| 166 | `UV_CACHE_DIR` | `final_uv_cache` |

### 2.4 `_install_script()` — `hermes_install.py:325`

子进程 env（仅 bash 子进程可见）：

| 行 | 写入 env | 值 |
|----|----------|-----|
| 361 | `HERMES_HOME` | `resolved_home` |
| 362 | `HERMES_CONFIG_PATH` | `resolved_home` |
| 363 | `HERMES_INSTALL_DIR` | `resolved_install` |
| 364 | `UV_INSTALL_DIR` | `resolved_uv_bin` |
| 365 | `UV_CACHE_DIR` | `resolved_uv_cache` |

---

## 三、CONSUMER 函数（读取 env 用于子进程）

### 3.1 `_build_hermes_env()` — `hermes_config_sync.py:193`

组装 `extra_env` 字典传给 `_run_hermes(extra_env=...)`：

| 行 | key | 值来源 |
|----|-----|--------|
| 210 | `HERMES_HOME` | `_resolve_hermes_root()` |
| 211 | `HERMES_CONFIG_PATH` | 同 `HERMES_HOME` |
| 214 | `HERMES_INSTALL_DIR` | `_get_hermes_install_dir()` |
| 221 | `UV_INSTALL_DIR` | `_get_uv_install_dir()` |
| 224 | `UV_CACHE_DIR` | `_get_uv_cache_dir()` |
| 220 | `PATH` | `_find_hermes_bin_dir()` + `os.environ["PATH"]` |

**调用者**: `_auto_apply_config()`, `install()`

### 3.2 `_run_hermes()` — `hermes_cmd.py:146`

子进程继承 `os.environ` 合并 `extra_env`。

---

## 四、环境变量流动总图

```
sccsos.yaml/默认值
    ↓
_get_hermes_home() / _get_hermes_install_dir() / _get_uv_install_dir() / _get_uv_cache_dir()
    ↓
install() → os.environ[HERMES_HOME/INSTALL_DIR/UV_*]          ← 行 444-448
    ↓
_setup_shell_rc() → rc 文件 + os.environ[HERMES_BIN/BIN_DIR] ← 行 292-293
    ↓
_find_hermes_bin_dir() → os.environ[PATH]                      ← 行 462-466 (install时)
    ↓
_resolve_hermes_binary() → 返回全路径                           ← 行 63: 验证存在性
    ↓
_run_hermes([binary, ...]) → subprocess.run                     ← 行 164
    ↓
_auto_apply_config()
  └→ _build_hermes_env() → extra_env → _run_hermes(extra_env=...)
```

## 五、常见问题排查

| 现象 | 检查点 |
|------|--------|
| `HERMES CLI not found` | `HERMES_BIN` env 是否存在且指向真实文件; `_resolve_hermes_binary` 返回什么 |
| profile 未创建 | `_run_hermes(["--version"])` 是否成功; `_auto_apply_config` 是否被调用 |
| env-setup 后未生效 | rc 文件已有 env → 跳过 → `os.environ` 未更新; 检查 `_setup_shell_rc` 的跳过逻辑 |
| 路径不对 | `_build_hermes_env()` 的 `extra_env` 值; `_resolve_hermes_root()` 是否 walkup 正确 |
