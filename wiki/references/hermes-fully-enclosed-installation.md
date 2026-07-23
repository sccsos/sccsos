# Hermes Agent 全封闭安装指南

> 版本: v1.0 | 目录规整 + 环境变量配置 + UV 路径适配

## 一、遗漏目录全量排查

结合 Hermes Agent 官方安装机制、uv 依赖管理、运行时隐性目录，排查出常规部署易遗漏的隐性目录，全部收拢至 `$HOME/hermes`：

- Python 虚拟环境目录
- Agent 会话存储目录
- 技能插件目录
- 运行记忆文件目录
- uv 编译临时目录
- 索引缓存目录
- Git 依赖缓存目录
- 进程运行 PID 目录
- 日志滚动归档目录
- 配置备份目录

核心原则：**零系统散落、全量封闭、路径完全隔离**。

## 二、$HOME/hermes 标准化目录结构

```
$HOME/hermes/
├── agent/                 # HERMES_INSTALL_DIR 程序静态安装目录
│   ├── bin/               # hermes 主程序、CLI 命令、启动脚本
│   ├── lib/               # 静态依赖库、Python 扩展包
│   ├── share/             # 配置模板、官方文档、示例文件
│   ├── include/           # 底层依赖头文件
│   ├── man/               # 帮助手册文档
│   ├── versions/          # 多版本安装备份
│   └── venv/              # Hermes 专属隔离 Python 虚拟环境
├── data/                  # HERMES_HOME 运行读写工作目录
│   ├── config/            # 主配置 config.yaml、环境变量 .env、密钥凭证
│   ├── logs/              # 运行日志、审计日志、日志归档
│   ├── sessions/          # 会话记录、交互缓存
│   ├── skills/            # 自定义技能、算子插件、工作流文件
│   ├── memory/            # Agent 记忆文件存储目录
│   ├── plugins/           # 第三方插件、AI 模型、自定义组件
│   ├── pid/               # 进程 PID、socket 临时运行文件
│   ├── bin/               # UV_INSTALL_DIR（uv/uvx 二进制）
│   └── uv-cache/          # UV_CACHE_DIR Python 依赖全局缓存
│       ├── archives/      # 源码包、wheel 包归档缓存
│       ├── git/           # Git 源码依赖克隆缓存
│       └── metadata/      # 包元数据、版本锁定缓存
```

## 三、四大核心环境变量

```bash
export HOME_HERMES="$HOME/hermes"
export HERMES_INSTALL_DIR="$HOME_HERMES/agent"    # 程序静态安装目录
export HERMES_HOME="$HOME_HERMES/data"               # 业务运行工作目录
export UV_INSTALL_DIR="$HOME_HERMES/data/bin"        # UV 工具本体安装目录
export UV_CACHE_DIR="$HOME_HERMES/data/uv-cache"             # UV Python 依赖缓存
export PATH="$HERMES_INSTALL_DIR/venv/bin:$HOME_HERMES/data/bin:$PATH"
```

### 永久生效（.bashrc / .zshrc）

```bash
cat >> ~/.bashrc << 'EOF'
# Hermes Agent 全封闭安装环境变量
export HOME_HERMES="$HOME/hermes"
export HERMES_INSTALL_DIR="$HOME_HERMES/agent"
export HERMES_HOME="$HOME_HERMES/data"
export UV_INSTALL_DIR="$HOME_HERMES/data/bin"
export UV_CACHE_DIR="$HOME_HERMES/data/uv-cache"
export PATH="$HERMES_INSTALL_DIR/venv/bin:$HOME_HERMES/data/bin:$PATH"
EOF
source ~/.bashrc
```

## 四、一键创建全量目录

```bash
#!/bin/bash
export HOME_HERMES="$HOME/hermes"
mkdir -p \
  $HOME_HERMES/agent/{bin,lib,share,include,man,versions,venv} \
  $HOME_HERMES/data/{config,logs,sessions,skills,memory,plugins,pid,bin} \
  $HOME_HERMES/data/uv-cache/{archives,git,metadata}
```

## 五、UV 二进制找不到问题根治

### 根因

Hermes 安装脚本硬编码读取 `HERMES_HOME/bin/uv`，若 `UV_INSTALL_DIR` 指向其他路径，则安装成功但校验失败。

### 修复方案

**路径原生对齐**：将 `UV_INSTALL_DIR` 直接设为 `$HOME_HERMES/data/bin`，与 Hermes 校验路径一致，无需软链接。

### 增强修复脚本

```bash
#!/bin/bash
export HOME_HERMES="$HOME/hermes"
export HERMES_INSTALL_DIR="$HOME_HERMES/agent"
export HERMES_HOME="$HOME_HERMES/data"
export UV_INSTALL_DIR="$HOME_HERMES/data/bin"
export UV_CACHE_DIR="$HOME_HERMES/data/uv-cache"

mkdir -p \
  $HOME_HERMES/agent/{bin,lib,share,include,man,versions,venv} \
  $HOME_HERMES/data/{config,logs,sessions,skills,memory,plugins,pid,bin} \
  $HOME_HERMES/data/uv-cache/{archives,git,metadata}

# UV 自检与自愈
if [ -f "$UV_INSTALL_DIR/uv" ]; then
    echo "✅ UV 路径匹配: $UV_INSTALL_DIR/uv"
else
    echo "⚠️ UV 未检测到，自动安装..."
    curl -LsSf https://astral.sh/uv/install.sh | \
      UV_INSTALL_DIR=$UV_INSTALL_DIR UV_NO_MODIFY_PATH=1 sh
fi
```

### 完整安装流程

```bash
# 1. 加载环境变量
source ~/.bashrc

# 2. 执行初始化脚本
chmod +x hermes_init.sh && ./hermes_init.sh

# 3. 执行自定义目录安装
./install.sh --prefix $HERMES_INSTALL_DIR
```

## 六、关键注意事项

- **路径双向兼容**：UV 安装输出目录 = Hermes 校验目录，彻底解决 BUG
- **前置环境变量锁定**：脚本优先强制声明四大核心变量
- **自动自愈**：文件检测 + 缺失自动重装，无需人工干预
- **零散落**：所有操作在 `$HOME/hermes` 内完成
