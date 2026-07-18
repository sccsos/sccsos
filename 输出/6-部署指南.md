<div class="cover-page">

# SCCS OS 部署文档

**智能体架构设计师**

版本 v0.4.0 | 2026 年 7 月

</div>

\newpage

# 第一章 概述

## 1.1 文档说明

本文档为 SCCS OS 智能体操作系统的部署指引，涵盖环境准备、安装步骤、配置说明和部署验证。适用于初次部署 SCCS OS 的开发者和运维人员。

## 1.2 系统简介

![SCCS OS 系统分层架构图](images/sccsos-system-architecture-light.png)

*图 2: SCCS OS 系统分层架构图 — 四层架构设计，展现系统全貌*


![SCCS OS 部署架构图](images/sccsos-deployment-architecture-light.png)

*图 1: SCCS OS 部署架构图 — macOS 宿主 + Hermes Agent 安装 + sccsos 工作区 + Profile 隔离 + 运行时数据*

SCCS OS 是一个构建在 Hermes Agent 之上的智能体运行时平台，提供多 Agent 声明式编排、全生命周期管理和可观测性基础设施。

| 模块 | 说明 |
|------|------|
| 核心运行时 | Agent 注册表、生命周期状态机、工作流编排引擎 |
| Agent 管理 | 创建、启动、停止、查询 Agent 运行状态 |
| 工作流引擎 | DAG 编排、模板注入、多步骤流水线 |
| 可观测性 | Span 追踪、Token 审计、结构化日志 |
| CLI 接口 | 15 条命令全覆盖 |

## 1.3 技术栈

| 组件 | 版本要求 | 说明 |
|------|---------|------|
| Python | >= 3.11 | 运行时环境 |
| Hermes Agent | >= 0.18.0 | 底层 Agent 运行时底座 |
| SQLite | >= 3.38 | 内置数据库（FTS5 支持） |
| PyYAML | >= 6.0 | YAML 配置解析 |
| Click | >= 8.0 | CLI 框架 |
| DeepSeek API | — | LLM 模型服务 |

\newpage

# 第二章 环境准备

## 2.1 前提条件

部署 SCCS OS 前需要完成以下准备工作：

1. 安装 Python 3.11 或更高版本
2. 安装 Hermes Agent（版本 >= 0.18.0）
3. 配置 Hermes profile（至少一个可用 profile）
4. 确保 LLM API 密钥已配置（如 DeepSeek API Key）

## 2.2 Hermes Agent 安装

Hermes Agent 是 SCCS OS 的底层运行时底座，必须预先安装。

```bash
# 通过 pip 安装
pip install hermes-agent

# 验证安装
hermes --version
```

安装完成后，通过 Hermes 的交互式配置向导完成基本设置：

```bash
hermes setup
```

## 2.3 目录复制式安装（替代方案）

适用于离线部署、批量克隆、备份恢复等无法通过 `pip install` 在线安装的场景。
通过拷贝已有的 Hermes Agent 安装目录和 Profile 数据目录完成部署。

**适用场景：**

| 场景 | 说明 |
|------|------|
| 离线/内网部署 | 服务器无外网访问权限，无法从 PyPI 安装 |
| 批量节点克隆 | 多台服务器需要完全一致的 Hermes 环境 |
| 备份恢复 | 从备份目录快速恢复运行环境 |
| 环境标准化 | 将预配置好的模板环境分发到多台机器 |

**前置条件：**

准备**两个源目录**和**两个目标目录**：

| 参数 | 含义 | 示例 |
|------|------|------|
| SRC_AGENT | 源 Hermes Agent 程序目录（含 bin/、lib/ 等） | `/backup/hermes-agent/` |
| SRC_PROFILE | 源 Profile 数据目录（含 config.yaml、.env 等） | `/backup/profile-sccsos/` |
| DST_AGENT | 目标机器程序安装目录 | `/opt/hermes-agent/` |
| DST_PROFILE | 目标机器 Profile 数据目录 | `/data/hermes/sccsos/` |

前提要求：

1. 源目录与新服务器的 Python 主版本一致（如均为 Python 3.11+）
2. 源 Hermes Agent 版本 >= 0.18.0
3. 新服务器端口、网络、大模型接口连通性正常
4. 关闭源机器的 Hermes 进程，避免文件锁冲突

**安装步骤：**

第一步：拷贝源目录到目标位置

```bash
# 拷贝程序目录
cp -a SRC_AGENT DST_AGENT

# 拷贝 Profile 数据目录
cp -a SRC_PROFILE DST_PROFILE
```

**第二步：清理旧环境运行残留**

旧机器进程的 PID 文件、锁文件、临时套接字会导致新环境启动失败：

```bash
cd DST_PROFILE

# 删除进程 PID 和运行缓存
rm -f gateway.pid processes.json

# 清理临时套接字和锁文件
rm -rf tmp/ sockets/

# 清空历史日志（可选）
rm -rf logs/*.log
```

**第三步：修正目录权限**

```bash
# 程序目录：可执行
chmod -R 755 DST_AGENT
chmod +x DST_AGENT/bin/*

# Profile 数据目录：严格保密
chmod -R 700 DST_PROFILE
chmod 600 DST_PROFILE/.env
```

**第四步：配置环境变量**

```bash
# 写入 ~/.bashrc（替换为实际路径）
cat >> ~/.bashrc << 'EOF'
export HERMES_HOME="DST_PROFILE"
export PATH="DST_AGENT/bin:$PATH"
EOF

# 生效配置
source ~/.bashrc
```

**第五步：重装 Python 依赖**

不同服务器的 Python 环境存在差异，必须重新适配依赖：

```bash
cd DST_AGENT
pip install . --force-reinstall
```

**第六步：修复配置文件中的绝对路径**

拷贝的 `config.yaml` 中可能包含源机器的绝对路径，需批量替换：

```bash
# 进入 Profile 目录
cd DST_PROFILE

# 检查并修正 config.yaml 中的路径
# 重点关注：
#   - terminal.cwd：终端默认工作目录
#   - 模型文件路径（如有本地模型）
#   - 自定义技能/定时任务的输出目录
#   - 内网模型服务地址（如 Ollama、向量库 API 地址）
```

`.env` 文件仅需修改路径类变量，API 密钥、Token 等认证参数无需修改。

**第七步：验证安装**

```bash
# 验证环境变量
echo $HERMES_HOME

# 验证 CLI 可用
hermes --version

# 运行环境自检
hermes doctor
```

**一键迁移脚本：**

以下脚本整合上述全部步骤（需手动修改开头的目录路径）：

```bash
#!/bin/bash
# Hermes Agent 目录复制迁移一键修复脚本
# 使用前请修改 AGENT_PATH 和 PROFILE_PATH 为实际路径

AGENT_PATH="/opt/hermes-agent"       # 目标程序目录
PROFILE_PATH="/data/hermes/sccsos"  # 目标 Profile 目录

echo "========== 开始 Hermes 目录复制安装 =========="

# 1. 清理残留
echo "1. 清理旧进程缓存与锁文件..."
rm -rf ${PROFILE_PATH}/gateway.pid ${PROFILE_PATH}/processes.json
rm -rf ${PROFILE_PATH}/tmp ${PROFILE_PATH}/sockets
rm -rf ${PROFILE_PATH}/logs/*.log

# 2. 修正权限
echo "2. 配置目录权限..."
chmod -R 755 ${AGENT_PATH}
chmod +x ${AGENT_PATH}/bin/*
chmod -R 700 ${PROFILE_PATH}
chmod 600 ${PROFILE_PATH}/.env

# 3. 写入环境变量（避免重复添加）
echo "3. 配置系统环境变量..."
if ! grep -q "HERMES_HOME" ~/.bashrc; then
cat >> ~/.bashrc << EOF
export HERMES_HOME=${PROFILE_PATH}
export PATH=${AGENT_PATH}/bin:\$PATH
EOF
fi
source ~/.bashrc

# 4. 重装依赖
echo "4. 重装 Python 依赖..."
cd ${AGENT_PATH}
pip install . --force-reinstall

echo "========== 目录复制安装完成 =========="
echo "HERMES_HOME: $HERMES_HOME"
hermes --version
echo "请手动检查 config.yaml 中的绝对路径是否正确"
```

**两种安装方式对比：**

| 对比维度 | pip 在线安装 | 目录复制式安装 |
|----------|-------------|---------------|
| 网络要求 | 需要 PyPI 访问 | 无需网络（离线可用） |
| 安装速度 | 依赖下载速度 | 本地拷贝，速度快 |
| 版本一致性 | 安装时指定版本 | 与源目录完全一致 |
| 配置迁移 | 需手动配置 | 配置随目录完整迁移 |
| 批量部署 | 每台机器单独安装 | 一次准备，批量分发 |
| 适用场景 | 首次安装、开发环境 | 离线部署、批量克隆、灾备 |

## 2.4 Hermes Profile 配置

SCCS OS 依赖 Hermes profile 运行。确保已配置 sccsos profile：

```bash
# 查看现有 profile
hermes profile list

# 如无 sccsos profile，创建或切换到现有 profile
hermes profile use sccsos

# 查看 profile 详情
hermes profile show sccsos
```

profile 配置要求：

| 配置项 | 推荐值 | 说明 |
|--------|--------|------|
| 模型 | deepseek-v4-flash | 默认推理模型 |
| 降级模型 | deepseek-chat | API 不可用时的备用模型 |
| 最大对话轮次 | 90 | 防止无限循环 |
| 系统提示语言 | 中文 | 与 SCCS OS 默认语言一致 |

## 2.5 Python 依赖检查

SCCS OS 核心依赖极少：

| 依赖 | 用途 | 安装检查 |
|------|------|---------|
| pyyaml | YAML 配置解析 | `python3 -c "import yaml; print(yaml.__version__)"` |
| click | CLI 框架 | `python3 -c "import click; print(click.__version__)"` |

\newpage

# 第三章 安装部署

## 3.1 安装步骤

SCCS OS 通过 pip 以可编辑模式安装：

```bash
# 克隆或进入项目目录
cd /path/to/sccsos

# 安装依赖和 CLI 入口
pip install -e .
```

安装完成后验证 CLI 可用：

```bash
sccsos version
```

预期输出：

```
sccsos v0.4.0
```

## 3.2 初始化项目

在目标工作目录初始化 SCCS OS 项目：

```bash
# 创建项目目录
mkdir my-sccsos-project
cd my-sccsos-project

# 初始化项目
sccsos init
```

初始化会自动创建以下目录结构：

| 目录/文件 | 说明 |
|-----------|------|
| sccsos.yaml | 项目配置文件 |
| agents/ | Agent 定义目录 |
| data/ | SQLite 数据库目录 |
| logs/ | 日志文件目录 |
| traces/ | 追踪数据目录 |
| config/ | 配置示例目录 |
| tests/ | 测试目录 |

## 3.3 验证部署

运行健康检查确认所有组件正常工作：

```bash
sccsos health
```

预期输出示例：

```
sccsos v0.4.0
  Config: sccsos v0.4.0
  Database: ok (0 agents)
  Hermes:   OK
  Agents:   1 registered
  Traces:   0 available
```

各项说明：

| 检查项 | 正常状态 | 异常处理 |
|--------|---------|---------|
| Config | 显示项目名称和版本 | 检查 sccsos.yaml 是否存在 |
| Database | ok + agent 数量 | 检查 data/ 目录权限 |
| Hermes | OK | 确认 Hermes CLI 已安装且在 PATH 中 |
| Agents | 显示已注册 Agent 数 | 检查 agents/ 目录下的 YAML 文件 |

\newpage

# 第四章 配置说明

## 4.1 项目配置（sccsos.yaml）

SCCS OS 项目配置文件位于项目根目录，采用 YAML 格式：

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| project.name | string | sccsos | 项目名称 |
| project.version | string | 0.4.0 | 项目版本 |
| database.path | string | ./data/sccsos.db | SQLite 数据库路径 |
| defaults.hermes_profile | string | sccsos | 默认 Hermes profile |
| defaults.max_turns | integer | 90 | 最大对话轮次 |
| defaults.timeout | integer | 1800 | 超时秒数（30 分钟） |
| logging.level | string | INFO | 日志级别 |
| logging.format | string | json | 日志格式 |
| logging.directory | string | ./logs | 日志目录 |
| tracing.enabled | boolean | true | 是否启用追踪 |

## 4.2 Agent 定义格式

Agent 定义文件存放于 agents/ 目录，采用 YAML 格式：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| name | string | 是 | Agent 唯一标识名 |
| version | string | 否 | 语义化版本号 |
| description | string | 否 | 功能描述 |
| personality | string | 否 | 映射到 Hermes personality |
| profile | string | 否 | Hermes profile 名称 |
| toolsets | list | 否 | 启用的工具集 |
| tags | list | 否 | 分类标签 |
| lifecycle.max_turns | integer | 否 | 最大对话轮次 |
| lifecycle.timeout | integer | 否 | 超时秒数 |

示例 Agent 定义：

```yaml
name: architect
version: 1.0
description: 智能体架构设计师
personality: agent-architect
profile: sccsos
toolsets:
  - llm-wiki
  - filesystem
  - web-search
tags:
  - core
  - architecture
lifecycle:
  max_turns: 90
  timeout: 1800
  auto_recover: true
```

\newpage

# 第五章 部署验证

## 5.1 基本功能验证

完成安装和初始化后，按以下步骤验证核心功能：

### 步骤一：查看已注册 Agent

```bash
sccsos agent list
```

应显示至少一个已注册的 Agent。

### 步骤二：启动 Agent

```bash
sccsos agent start architect
```

### 步骤三：查看运行状态

```bash
sccsos agent status architect
```

应显示状态为 running，并包含会话 ID。

### 步骤四：停止 Agent

```bash
sccsos agent stop architect
```

### 步骤五：查看事件日志

```bash
sccsos agent logs architect
```

应显示完整的生命周期事件链。

## 5.2 工作流验证

创建测试工作流文件 test-wf.yaml：

```yaml
name: smoke-test
version: 1.0
description: 冒烟测试工作流
steps:
  - id: greet
    name: 问候
    agent: architect
    prompt: "Say 'SCCS OS deployment verification successful'"
```

运行工作流：
```bash
sccsos workflow run test-wf.yaml
sccsos workflow list
```

## 5.3 可观测性验证

验证追踪功能：
```bash
# 查看追踪列表
sccsos trace list

# 查看追踪详情
sccsos trace show <trace_id>
```

验证审计功能：
```bash
# 查看审计报告
sccsos audit report

# 查看审计日志
sccsos audit log
```

\newpage

# 第六章 部署场景案例

## 6.1 案例：软件开发团队部署 SCCS OS

**场景**：某软件开发团队（5 人）需要搭建内部智能体平台，支撑日常的架构设计评审、代码审查、文档生成等任务。

**需求分析**：

| 需求 | 说明 |
|------|------|
| 团队角色 | 架构师 1 人、后端开发 3 人、前端开发 1 人 |
| 主要任务 | 架构设计评审、代码审查、技术文档生成、API 接口设计 |
| 模型需求 | DeepSeek 为主，Claude 辅助复杂推理 |
| 数据隔离 | 各项目数据互相独立 |

**部署步骤**：

```bash
# 1. 安装 Hermes Agent
pip install hermes-agent
hermes setup

# 2. 创建团队专用 Profile
hermes profile create team-sccsos --clone default
hermes profile use team-sccsos

# 3. 安装 SCCS OS
cd ~/projects/team-sccsos
pip install -e /path/to/sccsos

# 4. 初始化项目
sccsos init
```

**Agent 定义**（`agents/`）：

```yaml
# architect.yaml — 架构设计师
name: architect
version: 1.0
description: 架构设计与评审 Agent
profile: team-sccsos
toolsets:
  - llm-wiki
  - web-search
  - filesystem
lifecycle:
  max_turns: 60
  timeout: 1800
---
# code-reviewer.yaml — 代码审查 Agent
name: code-reviewer
version: 1.0
description: 代码质量审查 Agent
profile: team-sccsos
toolsets:
  - filesystem
  - delegate_task
lifecycle:
  max_turns: 40
  timeout: 1200
---
# doc-writer.yaml — 文档生成 Agent
name: doc-writer
version: 1.0
description: 技术文档自动生成 Agent
profile: team-sccsos
toolsets:
  - filesystem
  - web-search
lifecycle:
  max_turns: 30
  timeout: 900
```

**日常操作流程**：

```bash
# 查看所有 Agent
sccsos agent list

# 启动团队 Agent
sccsos agent start architect
sccsos agent start code-reviewer
sccsos agent start doc-writer

# 运行架构评审工作流
sccsos workflow run workflows/架构评审.yaml

# 查看本周审计报告
sccsos audit report --since 2026-07-14
```

## 6.2 案例：企业多团队隔离部署

**场景**：某企业中 A、B 两个部门共享同一台服务器，需要数据完全隔离。

**方案**：利用 Hermes Profile 实现部门级数据隔离，每个部门使用独立的 Profile 和数据库。

```bash
# 为 A 部门创建 Profile
hermes profile create dept-a --clone default
hermes profile use dept-a
sccsos init --project-name sccsos-dept-a

# 为 B 部门创建 Profile
hermes profile create dept-b --clone default
hermes profile use dept-b
sccsos init --project-name sccsos-dept-b
```

每个部门的 Profile 拥有独立的 `HERMES_HOME`、独立的 SQLite 数据库和独立的 config.yaml。

```yaml
# dept-a 的 Agent 定义
name: analyst-a
profile: dept-a
# ...（部门 A 的业务 Agent 配置）

# dept-b 的 Agent 定义
name: analyst-b
profile: dept-b
# ...（部门 B 的业务 Agent 配置）
```

运行隔离验证：

```bash
# 切换到 A 部门
hermes profile use dept-a
sccsos agent list           # 只看到 A 部门的 Agent

# 切换到 B 部门
hermes profile use dept-b
sccsos agent list           # 只看到 B 部门的 Agent
```
