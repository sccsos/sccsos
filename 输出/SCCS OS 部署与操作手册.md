<div class="cover-page">

# SCCS OS 部署与操作手册

创新研究院 李锋

v1.1 | 2026 年 7 月

涵盖：环境部署 · 操作指南 · 实战案例

</div>

\newpage

# 目录

- **第1章 环境与部署**
  - 1.1 系统简介
  - 1.2 技术栈
  - 1.3 环境准备
  - 1.4 安装部署
  - 1.5 配置说明
  - 1.6 部署验证
  - 1.7 部署场景案例
- **第2章 操作指南**
  - 2.1 CLI 命令总览
  - 2.2 Agent 管理
  - 2.3 工作流编排
  - 2.4 可观测性
  - 2.5 系统管理
  - 2.6 常见问题
- **第3章 实战案例**
  - 3.1 架构评审工作流
  - 3.2 每日巡检工作流
  - 3.3 多 Agent 并行检索对比
  - 3.4 CI/CD 集成流水线
  - 3.5 异常恢复与故障处理
- **附录**
  - 附录A：项目目录结构
  - 附录B：Agent 定义 YAML 参考
  - 附录C：技术决策清单

\newpage

# 第1章 环境与部署

## 1.1 系统简介

![](images/sccsos-system-architecture-light.png)

*图 1: SCCS OS 系统分层架构图 — 四层架构设计，展现系统全貌*

![](images/sccsos-deployment-architecture-light.png)

*图 2: SCCS OS 部署架构图 — macOS 宿主 + Hermes Agent 安装 + sccsos 工作区 + Profile 隔离 + 运行时数据*

SCCS OS 是一个构建在 Hermes Agent 之上的智能体运行时平台，提供多 Agent 声明式编排、全生命周期管理和可观测性基础设施。

| 模块 | 说明 |
|------|------|
| 核心运行时 | Agent 注册表、生命周期状态机、工作流编排引擎 |
| Agent 管理 | 创建、启动、停止、查询 Agent 运行状态 |
| 工作流引擎 | DAG 编排、模板注入、多步骤流水线 |
| 可观测性 | Span 追踪、Token 审计、结构化日志 |
| CLI 接口 | 15 条命令，6 组全覆盖 |

## 1.2 技术栈

| 组件 | 版本要求 | 说明 |
|------|---------|------|
| Python | >= 3.11 | 运行时环境 |
| Hermes Agent | >= 0.18.0 | 底层 Agent 运行时底座 |
| SQLite | >= 3.38 | 内置数据库（FTS5 支持） |
| PyYAML | >= 6.0 | YAML 配置解析 |
| Click | >= 8.0 | CLI 框架 |
| DeepSeek API | — | LLM 模型服务 |

## 1.3 环境准备

### 1.3.1 前提条件

部署 SCCS OS 前需要完成以下准备工作：

1. 安装 Python 3.11 或更高版本
2. 安装 Hermes Agent（版本 >= 0.18.0）
3. 配置 Hermes profile（至少一个可用 profile）
4. 确保 LLM API 密钥已配置（如 DeepSeek API Key）

### 1.3.2 Hermes Agent 安装

Hermes Agent 是 SCCS OS 的底层运行时底座，必须预先安装。

```bash
## 通过 pip 安装
pip install hermes-agent

## 验证安装
hermes --version
```

安装完成后，通过 Hermes 的交互式配置向导完成基本设置：

```bash
hermes setup
```

### 1.3.3 目录复制式安装（替代方案）

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

**第一步：拷贝源目录到目标位置**

```bash
## 拷贝程序目录
cp -a SRC_AGENT DST_AGENT

## 拷贝 Profile 数据目录
cp -a SRC_PROFILE DST_PROFILE
```

**第二步：清理旧环境运行残留**

```bash
cd DST_PROFILE

## 删除进程 PID 和运行缓存
rm -f gateway.pid processes.json

## 清理临时套接字和锁文件
rm -rf tmp/ sockets/

## 清空历史日志（可选）
rm -rf logs/*.log
```

**第三步：修正目录权限**

```bash
## 程序目录：可执行
chmod -R 755 DST_AGENT
chmod +x DST_AGENT/bin/*

## Profile 数据目录：严格保密
chmod -R 700 DST_PROFILE
chmod 600 DST_PROFILE/.env
```

**第四步：配置环境变量**

```bash
## 写入 ~/.bashrc（替换为实际路径）
cat >> ~/.bashrc << 'EOF'
export HERMES_HOME="DST_PROFILE"
export PATH="DST_AGENT/bin:$PATH"
EOF

## 生效配置
source ~/.bashrc
```

**第五步：重装 Python 依赖**

```bash
cd DST_AGENT
pip install . --force-reinstall
```

**第六步：修复配置文件中的绝对路径**

```bash
## 进入 Profile 目录
cd DST_PROFILE

## 检查并修正 config.yaml 中的路径
## 重点关注：
##   - terminal.cwd：终端默认工作目录
##   - 模型文件路径（如有本地模型）
##   - 自定义技能/定时任务的输出目录
##   - 内网模型服务地址（如 Ollama、向量库 API 地址）
```

`.env` 文件仅需修改路径类变量，API 密钥、Token 等认证参数无需修改。

**第七步：验证安装**

```bash
## 验证环境变量
echo $HERMES_HOME

## 验证 CLI 可用
hermes --version

## 运行环境自检
hermes doctor
```

**一键迁移脚本：**

以下脚本整合上述全部步骤（需手动修改开头的目录路径）：

```bash
#!/bin/bash
## Hermes Agent 目录复制迁移一键修复脚本
## 使用前请修改 AGENT_PATH 和 PROFILE_PATH 为实际路径

AGENT_PATH="/opt/hermes-agent"       # 目标程序目录
PROFILE_PATH="/data/hermes/sccsos"  # 目标 Profile 目录

echo "========== 开始 Hermes 目录复制安装 =========="

## 1. 清理残留
echo "1. 清理旧进程缓存与锁文件..."
rm -f ${PROFILE_PATH}/gateway.pid ${PROFILE_PATH}/processes.json
rm -rf ${PROFILE_PATH}/tmp ${PROFILE_PATH}/sockets
rm -rf ${PROFILE_PATH}/logs/*.log

## 2. 修正权限
echo "2. 配置目录权限..."
chmod -R 755 ${AGENT_PATH}
chmod +x ${AGENT_PATH}/bin/*
chmod -R 700 ${PROFILE_PATH}
chmod 600 ${PROFILE_PATH}/.env

## 3. 写入环境变量（避免重复添加）
echo "3. 配置系统环境变量..."
if ! grep -q "HERMES_HOME" ~/.bashrc; then
cat >> ~/.bashrc << EOF
export HERMES_HOME=${PROFILE_PATH}
export PATH=${AGENT_PATH}/bin:\$PATH
EOF
fi
source ~/.bashrc

## 4. 重装依赖
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

### 1.3.4 Hermes Profile 配置

SCCS OS 依赖 Hermes profile 运行。确保已配置 sccsos profile：

```bash
## 查看现有 profile
hermes profile list

## 如无 sccsos profile，创建或切换到现有 profile
hermes profile use sccsos

## 查看 profile 详情
hermes profile show sccsos
```

profile 配置要求：

| 配置项 | 推荐值 | 说明 |
|--------|--------|------|
| 模型 | deepseek-v4-flash | 默认推理模型 |
| 降级模型 | deepseek-chat | API 不可用时的备用模型 |
| 最大对话轮次 | 90 | 防止无限循环 |
| 系统提示语言 | 中文 | 与 SCCS OS 默认语言一致 |

### 1.3.5 Python 依赖检查

SCCS OS 核心依赖极少：

| 依赖 | 用途 | 安装检查 |
|------|------|---------|
| pyyaml | YAML 配置解析 | `python3 -c "import yaml; print(yaml.__version__)"` |
| click | CLI 框架 | `python3 -c "import click; print(click.__version__)"` |

## 1.4 安装部署

### 1.4.1 安装步骤

SCCS OS 通过 pip 以可编辑模式安装：

```bash
## 克隆或进入项目目录
cd /path/to/sccsos

## 安装依赖和 CLI 入口
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

### 1.4.2 初始化项目

在目标工作目录初始化 SCCS OS 项目：

```bash
## 创建项目目录
mkdir my-sccsos-project
cd my-sccsos-project

## 初始化项目
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

### 1.4.3 验证部署

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

## 1.5 配置说明

### 1.5.1 项目配置（sccsos.yaml）

SCCS OS 项目配置文件位于项目根目录，采用 YAML 格式。完整的参考配置见 `配置/sample-config.yaml`。

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

### 1.5.2 Agent 定义格式

Agent 定义文件存放于 agents/ 目录，采用 YAML 格式。预置的示例文件见 `agents/architect.yaml`。

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

示例 Agent 定义（`agents/architect.yaml`）：

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

## 1.6 部署验证

### 1.6.1 基本功能验证

完成安装和初始化后，按以下步骤验证核心功能：

**步骤一：查看已注册 Agent**

```bash
sccsos agent list
```

应显示至少一个已注册的 Agent。

**步骤二：启动 Agent**

```bash
sccsos agent start architect
```

**步骤三：查看运行状态**

```bash
sccsos agent status architect
```

应显示状态为 running，并包含会话 ID。

**步骤四：停止 Agent**

```bash
sccsos agent stop architect
```

**步骤五：查看事件日志**

```bash
sccsos agent logs architect
```

应显示完整的生命周期事件链。

### 1.6.2 工作流验证

使用预置的冒烟测试工作流验证：

```yaml
## 见 workflows/冒烟测试.yaml
name: smoke-test
version: "1.0"
description: 冒烟测试工作流 — 验证 Hermes 连接和 Agent 基本响应
steps:
  - id: hello-agent
    name: 连通性测试
    agent: architect
    prompt: >
      请回复确认信息，仅返回 JSON 格式：
      {"status": "ok", "agent": "architect", "version": "0.4.0"}
```

运行工作流：

```bash
sccsos workflow run workflows/冒烟测试.yaml
sccsos workflow list
```

### 1.6.3 可观测性验证

验证追踪功能：

```bash
## 查看追踪列表
sccsos trace list

## 查看追踪详情
sccsos trace show <trace_id>
```

验证审计功能：

```bash
## 查看审计报告
sccsos audit report

## 查看审计日志
sccsos audit log
```

## 1.7 部署场景案例

### 1.7.1 案例：软件开发团队部署 SCCS OS

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
## 1. 安装 Hermes Agent
pip install hermes-agent
hermes setup

## 2. 创建团队专用 Profile
hermes profile create team-sccsos --clone default
hermes profile use team-sccsos

## 3. 安装 SCCS OS
cd ~/projects/team-sccsos
pip install -e /path/to/sccsos

## 4. 初始化项目
sccsos init
```

**Agent 定义**（`agents/`）：

预置的 Agent 示例文件见：
- `agents/architect.yaml` — 架构设计师
- `agents/code-reviewer.yaml` — 代码审查 Agent
- `agents/doc-writer.yaml` — 文档生成 Agent

```yaml
## agents/architect.yaml — 架构设计师
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
## agents/code-reviewer.yaml — 代码审查 Agent
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
## agents/doc-writer.yaml — 文档生成 Agent
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
## 查看所有 Agent
sccsos agent list

## 启动团队 Agent
sccsos agent start architect
sccsos agent start code-reviewer
sccsos agent start doc-writer

## 运行架构评审工作流
sccsos workflow run workflows/架构评审.yaml

## 查看本周审计报告
sccsos audit report --since 2026-07-14
```

### 1.7.2 案例：企业多团队隔离部署

**场景**：某企业中 A、B 两个部门共享同一台服务器，需要数据完全隔离。

**方案**：利用 Hermes Profile 实现部门级数据隔离，每个部门使用独立的 Profile 和数据库。

多 Profile 配置模板见 `配置/multi-profile-config.yaml`。

```bash
## 为 A 部门创建 Profile
hermes profile create dept-a --clone default
hermes profile use dept-a
sccsos init --project-name sccsos-dept-a

## 为 B 部门创建 Profile
hermes profile create dept-b --clone default
hermes profile use dept-b
sccsos init --project-name sccsos-dept-b
```

每个部门的 Profile 拥有独立的 `HERMES_HOME`、独立的 SQLite 数据库和独立的 config.yaml。

```yaml
## dept-a 的 Agent 定义
name: analyst-a
profile: dept-a
## ...（部门 A 的业务 Agent 配置）

## dept-b 的 Agent 定义
name: analyst-b
profile: dept-b
## ...（部门 B 的业务 Agent 配置）
```

运行隔离验证：

```bash
## 切换到 A 部门
hermes profile use dept-a
sccsos agent list           # 只看到 A 部门的 Agent

## 切换到 B 部门
hermes profile use dept-b
sccsos agent list           # 只看到 B 部门的 Agent
```

\newpage

# 第2章 操作指南

## 2.1 CLI 命令总览

![](images/sccsos-component-relationship-light.png)

*图 3: SCCS OS 核心组件关系图 — CLI 命令背后的核心组件交互*

SCCS OS 提供 15 条命令，分为 5 组：

| 命令组 | 命令 | 功能 |
|--------|------|------|
| 系统 | version | 显示版本信息 |
| 系统 | init | 初始化项目 |
| 系统 | health | 系统健康检查 |
| Agent 管理 | agent list | 列出所有 Agent |
| Agent 管理 | agent create | 创建 Agent 定义 |
| Agent 管理 | agent start | 启动 Agent |
| Agent 管理 | agent stop | 停止 Agent |
| Agent 管理 | agent status | 查询运行状态 |
| Agent 管理 | agent logs | 查看事件日志 |
| 工作流 | workflow validate | 验证工作流定义 |
| 工作流 | workflow run | 执行工作流 |
| 工作流 | workflow status | 查询运行状态 |
| 工作流 | workflow cancel | 取消运行中的工作流 |
| 工作流 | workflow list | 列出最近运行记录 |
| 追踪 | trace list | 列出追踪记录 |
| 追踪 | trace show | 查看追踪详情 |
| 审计 | audit report | 生成审计报告 |
| 审计 | audit log | 查看审计日志 |

## 2.2 Agent 管理

### 2.2.1 查看 Agent 列表

列出所有已注册的 Agent：

```bash
sccsos agent list
```

输出示例：

```
Name                 Version    Status       Description
----------------------------------------------------------------------
architect            1.0        registered   智能体架构设计师
test-coder           1.0        registered
```

各列说明：

| 列 | 说明 |
|----|------|
| Name | Agent 名称，定义在 YAML 的 name 字段 |
| Version | 定义版本号 |
| Status | 当前运行状态：registered/running/paused/terminated |
| Description | 功能描述 |

### 2.2.2 创建 Agent

**通过 YAML 文件创建**

```bash
sccsos agent create my-agent -f agents/my-agent.yaml
```

**通过命令行快速创建**

```bash
sccsos agent create my-agent
```

这会在 agents/ 目录下创建一个空的 YAML 模板文件，编辑后即可使用。

### 2.2.3 启动 Agent

启动一个已注册的 Agent：

```bash
sccsos agent start architect
```

启动过程：

1. SCCS OS 从 Registry 读取 Agent 定义
2. 创建 Agent 实例（状态：CREATED）
3. 启动 Agent，分配 Hermes 会话（状态：RUNNING）
4. 事件 recorded 到数据库

成功后输出：

```
Started: architect (agent_a1b2c3d4e5f6)
```

### 2.2.4 停止 Agent

停止运行中的 Agent：

```bash
sccsos agent stop architect
```

停止后状态转换为 TERMINATED，会话资源释放。

### 2.2.5 查询状态

查看 Agent 的详细运行状态和历史事件：

```bash
sccsos agent status architect
```

输出示例：

```
Agent: architect
  ID:     agent_a1b2c3d4e5f6
  Status: running
  Spec:   v1.0
  Profile: sccsos
  Session: ses_f6e5d4c3b2a1
  Recent events (3):
    [created] Agent 'architect' created
    [running] created → running via start
```

### 2.2.6 查看日志

查看 Agent 的生命周期事件记录：

```bash
sccsos agent logs architect
sccsos agent logs architect --limit 50
```

输出按时间倒序排列，每条记录包含时间戳、事件类型和详情。

### 2.2.7 生命周期状态机

![](images/sccsos-lifecycle-state-machine-light.png)

*图 4: Agent 生命周期状态机 — 5 种状态与 8 种转换关系*

SCCS OS 定义了 5 种运行状态：

| 状态 | 说明 | 可转换到 |
|------|------|---------|
| CREATED | Agent 定义已注册，未启动 | RUNNING |
| RUNNING | Agent 正在运行 | PAUSED, FAILED, TERMINATED |
| PAUSED | Agent 已暂停 | RUNNING, TERMINATED |
| FAILED | 运行异常 | RUNNING (restart), TERMINATED |
| TERMINATED | 已终止，资源释放 | （终态） |

## 2.3 工作流编排

![](images/sccsos-workflow-sequence-light.png)

*图 5: Workflow 执行时序图 — 从 DAG 构建到步骤执行、结果聚合的完整流程*

### 2.3.1 工作流定义

工作流使用 YAML 格式定义，支持多步骤编排、依赖管理和模板注入。以下是一个完整的注解示例，涵盖了所有核心特性：

```yaml
## 完整注解示例：技术方案评审工作流
name: tech-review                        # [必填] 工作流名称，用于追踪和审计
version: "1.0"                           # [可选] 语义化版本
description: 技术方案评审 — 需求→设计→评审三步流水线

## ── 并行执行组 ──────────────────────────
## 将无依赖关系的步骤放入同一组，可同时执行以提升效率
parallel_groups:
  - id: research-group                   # 组 ID，用于标识
    steps:                               # 组内的步骤 ID 列表
      - market-analysis
      - feasibility-study
    max_concurrent: 2                    # 最大并行数（建议不超过 3）

## ── 步骤定义 ─────────────────────────────
steps:
  - id: requirements-analysis            # [必填] 步骤唯一 ID
    name: 需求分析                        # [可选] 步骤中文名称
    agent: architect                     # [可选] 执行 Agent（默认 architect）
    prompt: |                            # [推荐] 执行提示词
      分析以下项目需求，提取关键架构约束。

      项目需求：
      {{ steps.input.context }}

      请按以下格式输出：
      1. 核心功能需求
      2. 非功能需求
      3. 技术约束条件
    timeout: 300                          # [可选] 步骤超时秒数
    retry: 1                              # [可选] 失败重试次数

  - id: architecture-design
    name: 架构方案设计
    agent: architect
    prompt: >
      基于以下需求分析，设计系统架构方案。

      需求分析：{{ steps.requirements-analysis.response }}

      输出包含：
      - 分层架构描述
      - 核心组件列表
      - 技术选型建议
    depends_on:                           # [可选] 前置依赖步骤 ID
      - requirements-analysis
    timeout: 600
    retry: 0
```

**字段详细说明**

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| name | string | 是 | — | 工作流名称，用于追踪记录和审计 |
| version | string | 否 | "1.0" | 语义化版本号 |
| description | string | 否 | "" | 工作流功能描述 |
| parallel_groups[].id | string | 条件 | — | 并行组 ID，必须与 steps 配合使用 |
| parallel_groups[].steps | list | 条件 | [] | 组内的步骤 ID 列表 |
| parallel_groups[].max_concurrent | integer | 否 | 2 | 最大并行执行数（不宜超过 3） |
| steps[].id | string | **是** | — | 步骤唯一标识，用于 depends_on 引用和模板变量 |
| steps[].name | string | 否 | "" | 步骤中文名，显示在追踪和日志中 |
| steps[].agent | string | 否 | "architect" | 执行 Agent 名称（须已注册） |
| steps[].prompt | string | 否 | "" | 执行提示词，支持模板语法 |
| steps[].depends_on | list/string | 否 | [] | 前置依赖步骤 ID，可传单个字符串 |
| steps[].timeout | integer | 否 | 600 | 步骤超时秒数（超时标记为失败） |
| steps[].retry | integer | 否 | 0 | 失败自动重试次数（0=不重试） |

**Prompt 编写技巧**

| YAML 写法 | 效果 | 适用场景 |
|-----------|------|---------|
| `prompt: "简短提示"` | 单行字符串 | 简单查询、状态检查 |
| `prompt: \|` 后跟缩进块 | **保留换行**，原样输出多行文本 | 复杂指令、分步骤要求 |
| `prompt: >` 后跟缩进块 | **折叠换行**，段落合并为一行 | 长段落文本，段落间自动空格 |

正确的 YAML 块标量缩进：

```yaml
## 推荐：使用 |（竖线）保留换行
prompt: |
  第一段指令。
  第二段指令。

  ## 空行表示段落分隔
  第三段指令。

## 备选：使用 >（大于号）折叠换行
prompt: >
  这是一个长段落，
  所有换行会被折叠成空格，
  直到出现空行才算段落结束。

  这是第二个段落。
```

**步骤命名规范**

- `id` 使用**小写字母 + 连字符**（`kebab-case`），如 `code-review`
- `id` 在同一个工作流内必须唯一
- `name` 使用**中文**，便于在日志和追踪中阅读
- `id` 建议使用动作动词开头：`analyze-requirements`、`generate-code`、`review-result`

### 2.3.2 模板注入

工作流步骤的 `prompt` 支持模板语法（基于 Jinja2 风格），可动态引用前序步骤的输出、运行时输入和上下文变量。模板在执行步骤前实时渲染，后续步骤看到的是渲染后的完整提示词。

#### 一、模板变量速查

| 模板语法 | 类型 | 说明 | 示例值 |
|----------|------|------|--------|
| `{{ steps.step-id.response }}` | **步骤输出** | 前序步骤的完整响应文本 | `"需求分析结果：..."` |
| `{{ steps.step-id.stdout }}` | 步骤输出 | 与 .response 相同（兼容模式） | `"分析报告：..."` |
| `{{ steps.input.context }}` | **运行时输入** | 执行工作流时注入的外部上下文 | `"项目需求文档内容..."` |
| `{{ run_id }}` | 系统变量 | 当前工作流运行的唯一 ID | `wf_a1b2c3d4e5f6` |
| `{{ workflow.name }}` | 系统变量 | 当前工作流名称 | `tech-review` |

#### 二、核心变量详解

**① `{{ steps.<step-id>.response }}` — 前序步骤输出引用**

这是最常用的模板变量。引用某个已完成步骤的完整响应文本，供后续步骤作为输入。

关键规则：

- 引用的步骤必须在 `depends_on` 中声明依赖关系，否则模板渲染时该步骤尚未执行，变量无法解析
- 变量名中的 `step-id` 必须严格匹配工作流中 `steps[].id` 字段的值
- 一个步骤可以引用多个前序步骤的输出，用于信息汇总

```yaml
## 引用单个步骤
steps:
  - id: analysis
    prompt: "分析需求..."

  - id: design
    prompt: |
      基于以下分析结果设计方案：
      {{ steps.analysis.response }}
    depends_on:
      - analysis
```

```yaml
## 引用多个步骤（汇总报告模式）
steps:
  - id: report
    prompt: |
      综合以下信息，生成最终报告：

      ## 需求分析
      {{ steps.analysis.response }}

      ## 架构方案
      {{ steps.design.response }}

      ## 风险评估
      {{ steps.risk-assessment.response }}
    depends_on:
      - analysis
      - design
      - risk-assessment
```

**② `{{ steps.input.context }}` — 运行时上下文注入**

这是将**外部数据传入工作流**的核心机制。工作流引擎在运行时将该变量替换为调用时传入的输入上下文。

典型用法：将需求文档、配置文件、外部数据等作为工作流的输入参数。

```yaml
## 工作流中使用 steps.input.context
steps:
  - id: analyze
    prompt: |
      请分析以下需求文档，提取核心功能和非功能需求。

      ## 输入需求
      {{ steps.input.context }}

      请输出格式化的需求列表。
```

执行时通过环境变量或管道传入：

```bash
## 方式一：环境变量注入（推荐）
export CONTEXT=$(cat docs/项目需求.md)
sccsos workflow run workflows/架构评审.yaml

## 方式二：管道输入
cat docs/项目需求.md | sccsos workflow run workflows/架构评审.yaml

## 方式三：直接传字符串
sccsos workflow run workflows/架构评审.yaml \
  --context "项目需求：实现用户认证系统"
```

**③ `{{ run_id }}` — 运行 ID 引用**

每次工作流执行自动生成唯一 ID，可在提示词中用于标记、追踪或生成唯一输出文件名。

```yaml
steps:
  - id: generate-output
    prompt: |
      生成架构文档，文件命名格式：architecture-{{ run_id }}.md
      文档内容：...
```

#### 三、模板在 YAML 中的写法对比

| 写法 | 示例 | 效果 |
|------|------|------|
| 单行字符串 | `prompt: "分析：{{ steps.analysis.response }}"` | 所有内容在一行，适合短提示 |
| 竖线块 `\|` | `prompt: \|` 换行后缩进 | **保留换行**，模板变量嵌入在段落中，适合结构化提示 |
| 折叠块 `>` | `prompt: >` 换行后缩进 | **折叠换行**，段落合并为空格，模板变量在段落中 |

竖线块中的模板变量写法：

```yaml
prompt: |
  请基于以下信息完成设计。

  ## 背景
  {{ steps.input.context }}

  ## 前序分析
  {{ steps.analysis.response }}

  输出格式：
  1. xxx
  2. yyy
```

#### 四、模板解析规则与注意事项

**变量解析失败时的行为**

| 场景 | 结果 |
|------|------|
| 引用的步骤 ID 不存在 | 模板保持 `{{ steps.unknown.response }}` 原样输出 |
| 引用的步骤尚未执行（未声明依赖） | 模板保持 `{{ steps.analysis.response }}` 原样输出 |
| 引用的步骤输出为空字符串 | 变量替换为空字符串 |
| 变量名拼写错误（大小写不一致） | 模板保持原样输出 |

**注意**：未解析的模板变量不会导致工作流执行失败，但会让 Agent 看到原始模板语法而非实际内容。**请务必在 `depends_on` 中声明所有被引用步骤的依赖关系**。

**转义 `{{` 字面量**

如果提示词中需要包含字面量的双花括号（如输出 JSON、YAML 模板），使用 `{% raw %}` 包裹：

```yaml
prompt: |
  请输出以下 JSON 配置（不要替换变量）：

  {% raw %}
  {
    "name": "{{ project_name }}",
    "version": "{{ version }}"
  }
  {% endraw %}
```

#### 五、常见注入模式

**模式 1：上下文累积（逐层深化）**

每一轮在前序基础上增加分析深度，适合需要逐步深入的分析场景。

```yaml
steps:
  - id: basic-analysis
    prompt: "对需求进行初步分析，列出主要功能点。"

  - id: deep-analysis
    prompt: |
      在初步分析基础上进行深化分析。

      初步分析：
      {{ steps.basic-analysis.response }}

      请额外分析：
      1. 各功能点之间的依赖关系
      2. 潜在的技术风险
    depends_on:
      - basic-analysis
```

**模式 2：信息聚合（多源汇总）**

两个或多个无依赖的步骤分头执行，然后由汇总步骤统一整合。

```yaml
parallel_groups:
  - id: parallel-research
    steps:
      - market-analysis
      - tech-feasibility
    max_concurrent: 2

steps:
  - id: market-analysis
    prompt: "分析市场需求..."

  - id: tech-feasibility
    prompt: "评估技术可行性..."

  - id: summary
    prompt: |
      综合以下两份分析，生成决策建议报告。

      市场分析：{{ steps.market-analysis.response }}
      技术可行性：{{ steps.tech-feasibility.response }}
    depends_on:
      - market-analysis
      - tech-feasibility
```

**模式 3：逐步约束输出格式**

通过模板逐步指定输出格式，引导 Agent 按预期格式输出。

```yaml
steps:
  - id: extract-data
    prompt: |
      从以下文档中提取关键数据：
      {{ steps.input.context }}

      仅输出 JSON 格式，不要任何额外文字：
      {
        "requirements": [...],
        "constraints": [...]
      }
```

**模式 4：动态条件选择（人为分支）**

通过在步骤之间传递结构化数据，由后续步骤的 prompt 指令实现分支逻辑。

```yaml
steps:
  - id: decide-approach
    prompt: "分析需求复杂度，输出 'simple' 或 'complex'。"

  - id: simple-impl
    prompt: |
      需求较简单，采用轻量方案实现。

      决策依据：{{ steps.decide-approach.response }}
    depends_on:
      - decide-approach
    # 仅当决定为 simple 时人工选择执行

  - id: complex-impl
    prompt: |
      需求复杂，采用分布式方案。

      决策依据：{{ steps.decide-approach.response }}
    depends_on:
      - decide-approach
    # 仅当决定为 complex 时人工选择执行
```

### 2.3.3 验证工作流

执行工作流前建议先验证 YAML 定义的正确性：

```bash
sccsos workflow validate my-workflow.yaml
```

验证检查项：

1. YAML 格式合法性
2. 步骤 ID 唯一性
3. 依赖关系完整性（无缺失依赖）
4. 循环依赖检测
5. 提示词非空检查

### 2.3.4 执行工作流

```bash
sccsos workflow run my-workflow.yaml
```

执行过程：

1. 加载并验证工作流定义
2. 创建追踪 Span（根 Span = 工作流名称）
3. DAG 解析生成执行层级
4. 按层顺序执行步骤
5. 每个步骤通过 Hermes 适配器委派给 Agent
6. 模板按需渲染
7. 输出缓存供后续步骤引用
8. 记录审计日志

### 2.3.5 查询运行状态

```bash
## 按运行 ID 查询
sccsos workflow status wf_a1b2c3d4e5f6

## 列出最近运行记录
sccsos workflow list
```

### 2.3.6 取消工作流

```bash
sccsos workflow cancel wf_a1b2c3d4e5f6
```

取消后状态标记为 cancelled，正在执行的步骤不会强制中断。

### 2.3.7 工作流最佳实践

#### 1. 步骤粒度控制

| 建议 | 说明 |
|------|------|
| 单步 prompt 控制在 500-2000 字 | 过短 → 输出不充分；过长 → Token 浪费、超时风险增大 |
| 复杂任务拆分为 3-5 步 | 每步聚焦一个子任务，可读性和可调试性更优 |
| 步骤总数不超过 10 步 | 超过 10 步时 DAG 解析和模板渲染开销增加，建议拆分多个工作流 |
| 并行组内步骤数不超过 5 个 | `max_concurrent` 建议设为 2-3，避免 LLM 并发调用争抢 API 配额 |

#### 2. 提示词工程指导

**有效模板结构**：

```yaml
prompt: |
  ## 1. 角色定义（明确 Agent 身份）
  你是一名资深架构师。

  ## 2. 输入上下文（引用模板变量）
  请分析以下项目需求：
  {{ steps.input.context }}

  ## 3. 前置分析（引用前序步骤）
  已有分析结果：
  {{ steps.analysis.response }}

  ## 4. 具体任务（明确要做什么）
  请完成以下任务：
  1. 提取核心需求
  2. 分析技术约束

  ## 5. 输出格式约束（引导输出结构）
  请按以下格式输出：
  - 需求列表
  - 约束列表
```

**推荐做法**：

- ✅ **给 Agent 明确的角色身份** — 开头注明「你是一名架构师」「你是一名代码审查员」
- ✅ **指定输出格式** — 使用列表、表格、JSON 结构引导，减少后处理工作
- ✅ **给出示例** — 「例如：输入 A → 输出 B」比纯描述更准确
- ✅ **避免模糊措辞** — 用「列出 3 个方案」替代「分析一下」
- ❌ **避免过长提示** — 超过 2000 Token 的 prompt 可能产生注意力稀释

#### 3. 模板变量使用原则

| 原则 | 说明 | 反例 |
|------|------|------|
| **引用的步骤必须声明依赖** | 每个 `{{ steps.X.response }}` 都要对应 `depends_on: [X]` | `{{ steps.analysis.response }}` 但无 depends_on |
| **变量名严格匹配步骤 ID** | `step-id` 大小写敏感，连字符不可省略 | 步骤 ID 是 `code-review`，写了 `{{ steps.CodeReview.response }}` |
| **汇总步骤引用多个变量** | 每个变量独占一段，用标题区分 | 所有变量挤在一段内混在一起 |
| **优先使用 `steps.input.context`** | 将外部数据通过注入传入，而非硬编码在 prompt 中 | prompt 中包含上千字的需求全文 |

#### 4. 并行执行策略

```yaml
parallel_groups:
  - id: parallel-tasks
    steps:
      - task-a      # 耗时约 30s
      - task-b      # 耗时约 45s
      - task-c      # 耗时约 25s
    max_concurrent: 3  # 三步并行，总耗时 ≈ 45s（而非 100s）
```

**何时使用并行**：

| 场景 | 串行 | 并行 |
|------|------|------|
| 步骤之间强依赖（B 基于 A 的输出） | ✅ 必须串行 | ❌ 不可行 |
| 独立调研两个不同方向 | ❌ 效率低 | ✅ **总耗时 ≈ 最慢步骤** |
| 同一 Agent 连续执行 | ✅ 单 Agent 串行 | ❌ 可能冲突 |
| 不同 Agent 执行不同任务 | ✅ 安全 | ✅ **推荐并行** |

**注意**：并行步骤数受 LLM API 并发限制。如果 API 有速率限制（如每分钟 10 次请求），并行组内 `max_concurrent` 不宜超过 5。

#### 5. 调试与排错

| 问题 | 检查点 | 解决方法 |
|------|--------|---------|
| 步骤输出不如预期 | 检查 `prompt` 是否明确指定了输出格式 | 增加格式约束和示例 |
| 模板变量未解析 | 检查 `depends_on` 是否覆盖所有被引用的步骤 ID | 补充缺失的依赖声明 |
| 工作流执行超时 | 检查单个步骤的 `timeout` 设置（默认 600s） | 缩短 prompt 或增大 timeout |
| 并行步骤未并行 | 检查 parallel_groups 中步骤 ID 与实际 steps 中 ID 一致 | 修正 ID 拼写 |
| Agent 使用错误 | 检查 `agent` 字段值是否对应已注册的 Agent 名称 | `sccsos agent list` 确认 |

#### 6. 工作流文件组织规范

```
workflows/
├── 架构评审.yaml        # 项目名 + 场景命名
├── 每日巡检.yaml        # 按功能命名
├── 冒烟测试.yaml        # 按用途命名
└── ci-pipeline.yaml     # 英文短横线命名
```

- 使用**中文文件名**便于团队识别
- 每个工作流文件**只定义一个工作流**
- 工作流文件存放于项目根目录的 `workflows/` 文件夹
- 复杂场景的输入模板文档存放于 `docs/` 文件夹

### 2.4.1 链路追踪

SCCS OS 提供 Span 树结构的链路追踪，每次工作流执行自动生成追踪记录。

**查看追踪列表**

```bash
sccsos trace list
```

输出示例：

```
Trace ID                 Spans    Total (ms)   First Span
----------------------------------------------------------------------
wf_a1b2c3d4e5f6          3        16753        2026-07-14T04:20:39
```

**查看追踪详情**

```bash
sccsos trace show wf_a1b2c3d4e5f6
```

输出示例（树形结构）：

```
Trace: wf_a1b2c3d4e5f6
Spans: 3

✅ workflow:obs-test (8.4s)
  └─ ✅ step:step-one (4.3s)
  └─ ✅ step:step-two (4.1s)
```

每个 Span 包含：

| 属性 | 说明 |
|------|------|
| span_id | Span 唯一 ID |
| parent_span_id | 父 Span ID（构建树结构） |
| name | Span 名称 |
| agent_name | 执行 Agent |
| start_time | 开始时间 |
| end_time | 结束时间 |
| duration_ms | 耗时（毫秒） |
| status | 状态：ok/error |
| events | 关联事件列表 |

### 2.4.2 审计与成本核算

SCCS OS 自动记录所有 LLM 调用和工具调用，支持成本估算。

**生成审计报告**

```bash
sccsos audit report
```

输出示例：

```
Audit Report
  Generated: 2026-07-14T04:20:48

  Total calls:    3
  Total tokens:   40
  Total cost:     $0.0000
  Avg duration:   2791ms
  Success rate:   3/3

  By event type:
    llm_call            3 calls,     40 tokens, $0.0000

  By model:
    deepseek-v4-flash           2 calls, $0.0000

  Cost over time:
    2026-07-14: $0.0000
```

**按时间段审计**

```bash
## 指定起始日期
sccsos audit report --since 2026-07-01

## 按 Agent 筛选
sccsos audit report --agent architect
```

**查看审计日志**

```bash
## 最近 20 条
sccsos audit log

## 指定数量
sccsos audit log --limit 50

## 按 Agent 筛选
sccsos audit log --agent architect
```

**定价表（用于成本估算）：**

| 模型 | 输入价格（每百万 Token） | 输出价格（每百万 Token） |
|------|------------------------|-------------------------|
| deepseek-v4-flash | $0.14 | $0.28 |
| deepseek-v4-pro | $0.44 | $0.87 |
| deepseek-chat | $0.14 | $0.28 |
| deepseek-reasoner | $0.55 | $2.19 |
| claude-sonnet-4 | $3.00 | $15.00 |
| gemini-2.5-flash | $0.30 | $2.50 |

## 2.5 系统管理

### 2.5.1 系统健康检查

```bash
sccsos health
```

检查项包括：

1. 配置加载状态
2. 数据库连接与 Schema
3. Hermes CLI 可达性
4. Agent 注册数量
5. 追踪数据可用性

### 2.5.2 数据库管理

SCCS OS 使用 SQLite 数据库，默认路径为 data/sccsos.db。

数据库包含 6 张表：

| 表名 | 用途 |
|------|------|
| agents | Agent 实例持久化 |
| agent_events | Agent 生命周期事件日志 |
| workflow_runs | 工作流运行记录 |
| workflow_steps | 工作流步骤执行记录 |
| traces | 追踪 Span 数据 |
| audit_log | 审计日志 |

```bash
## 查看数据库大小
ls -lh data/sccsos.db

## 使用 sqlite3 直接查询
sqlite3 data/sccsos.db "SELECT status, count(*) FROM agents GROUP BY status;"
```

### 2.5.3 日志管理

SCCS OS 日志默认输出到控制台和 logs/ 目录。

```bash
## 查看日志目录
ls -lh logs/

## 日志格式（JSON 行）
cat logs/sccsos.log | python3 -m json.tool
```

## 2.6 常见问题

### 2.6.1 安装问题

| 问题 | 原因 | 解决方法 |
|------|------|---------|
| sccsos 命令找不到 | pip 安装路径不在 PATH 中 | 运行 `pip show sccsos` 找到安装路径，加入 PATH |
| Hermes 不可用 | Hermes CLI 未安装或不在 PATH | 确认 `hermes --version` 可正常运行 |
| 数据库初始化失败 | data/ 目录无写入权限 | `mkdir -p data && chmod 755 data` |
| YAML 解析错误 | 配置文件格式不正确 | 使用 `sccsos workflow validate` 检测 |

### 2.6.2 运行时问题

| 问题 | 原因 | 解决方法 |
|------|------|---------|
| Agent 启动失败 | Agent 定义中 profile 不存在 | 检查 Hermes profile 是否存在 |
| Agent 停止失败 | 实例不在内存中 | 使用 `sccsos agent status` 确认当前状态 |
| 工作流执行超时 | 某步骤超过 300 秒限制 | 缩短提示词或增加 timeout 配置 |
| 追踪数据为空 | 数据库首次使用 | 执行一次工作流后即有数据 |
| Token 成本为 0 | Token 为估算值 | 实际成本以模型提供商账单为准 |

### 2.6.3 性能建议

1. 工作流步骤数建议控制在 10 步以内
2. 提示词长度建议不超过 2000 Token
3. 数据库定时备份（`cp data/sccsos.db backup/`）
4. 日志定期清理（默认保留 30 天）
5. 使用 `parallel_groups` 并行执行无依赖步骤以提升吞吐

\newpage

# 第3章 实战案例

## 3.1 案例：架构评审工作流

**目标**：对新项目的架构设计方案进行多 Agent 协同评审。

**工作流定义**（对应文件：`workflows/架构评审.yaml`）：

```yaml
name: architecture-review
version: "1.0"
description: 多 Agent 协同架构评审工作流
steps:
  - id: requirements-analysis
    name: 需求分析
    agent: architect
    prompt: >
      你是一名资深架构师。请分析以下项目需求，
      提炼出关键的功能需求、非功能需求和技术约束。

      项目需求：
      {{ steps.input.context }}

      请输出：
      1. 核心功能需求列表
      2. 非功能需求（性能、可用性、安全性等）
      3. 技术约束条件
      4. 潜在的技术风险点

  - id: architecture-design
    name: 架构方案设计
    agent: architect
    prompt: >
      基于以下需求分析结果，设计系统架构方案。

      需求分析：
      {{ steps.requirements-analysis.response }}

      请输出：
      1. 总体架构图描述（分层架构/模块划分）
      2. 核心组件及其职责
      3. 关键技术选型及理由
      4. 数据流设计
      5. 部署方案建议
    depends_on:
      - requirements-analysis

  - id: risk-assessment
    name: 风险评估
    agent: architect
    prompt: >
      请对以下架构方案进行全面的风险评估。

      架构方案：
      {{ steps.architecture-design.response }}

      请评估：
      1. 技术可行性风险
      2. 性能与扩展性风险
      3. 安全合规风险
      4. 实施与交付风险
      5. 风险缓解措施建议
    depends_on:
      - architecture-design

  - id: review-summary
    name: 评审总结
    agent: architect
    prompt: >
      请根据以上所有分析，生成完整的架构评审总结报告。

      需求分析：{{ steps.requirements-analysis.response }}
      架构方案：{{ steps.architecture-design.response }}
      风险评估：{{ steps.risk-assessment.response }}

      报告格式：## 架构评审报告
      ### 1. 需求概述
      ### 2. 架构方案
      ### 3. 风险评估
      ### 4. 评审结论
      ### 5. 后续行动项
    depends_on:
      - architecture-design
      - risk-assessment
```

**执行命令**：

```bash
## 注入需求文档
export requirements=$(cat docs/项目需求.md)

## 运行评审工作流
sccsos workflow run workflows/架构评审.yaml
sccsos workflow status <run-id>
sccsos trace show <trace-id>
```

**输入文件**：`docs/项目需求.md` — 一份示例项目需求文档，可直接修改后复用。

## 3.2 案例：日常巡检工作流

**目标**：每天早上自动检查系统状态，生成运维日报。

**工作流定义**（对应文件：`workflows/每日巡检.yaml`）：

```yaml
name: daily-inspection
version: "1.0"
description: 每日系统巡检工作流
steps:
  - id: health-check
    name: 系统健康检查
    agent: architect
    prompt: >
      执行系统健康检查。请使用 sccsos health 命令的输出，评估以下方面：
      1. 数据库连接状态
      2. Hermes Agent 连通性
      3. Agent 注册数量
      4. 追踪数据可用性
      请输出 Markdown 格式的健康检查报告。

  - id: audit-summary
    name: 审计汇总
    agent: architect
    prompt: >
      请根据审计记录的汇总信息，输出今日审计简报：
      - 总 Token 消耗
      - 各 Agent 调用次数
      - 失败率统计
      使用简洁的表格格式输出。

  - id: inspection-report
    name: 巡检报告生成
    agent: architect
    prompt: >
      综合以下两份信息，生成完整的每日巡检报告。
      健康检查：{{ steps.health-check.response }}
      审计汇总：{{ steps.audit-summary.response }}
      报告格式：
      ## 每日巡检报告
      ### 1. 系统健康状态
      ### 2. 运行概况
      ### 3. 异常记录
      ### 4. 建议措施
    depends_on:
      - health-check
      - audit-summary
```

**执行命令**：

```bash
## 执行日常巡检
sccsos workflow run workflows/每日巡检.yaml

## 查看审计报告
sccsos audit report --since $(date -d 'yesterday' +%Y-%m-%d)
```

## 3.3 案例：多 Agent 并行检索对比

**目标**：同时对同一问题使用不同策略进行检索，对比结果。

**工作流定义**（对应文件：`workflows/并行检索.yaml`）：

```yaml
name: parallel-research
version: "1.0"
description: 并行检索对比工作流

parallel_groups:
  - id: research-group
    steps:
      - deep-research
      - web-quick
    max_concurrent: 2

steps:
  - id: deep-research
    name: 深度检索
    agent: architect
    prompt: >
      请对以下研究问题进行深度技术调研：
      {{ steps.input.context }}
      调研要求：
      1. 搜索权威技术来源
      2. 给出至少 3 种可行的技术方案
      3. 对每种方案进行优缺点分析
      4. 给出推荐方案及理由

  - id: web-quick
    name: 快速检索
    agent: code-reviewer
    prompt: >
      请对以下研究问题进行快速业界实践调研：
      {{ steps.input.context }}
      输出要求：
      1. 列出 3-5 个实际落地案例
      2. 业界主流趋势总结

  - id: synthesis
    name: 综合报告
    agent: doc-writer
    prompt: >
      综合两份调研结果，生成对比分析报告。
      深度调研：{{ steps.deep-research.response }}
      快速调研：{{ steps.web-quick.response }}
      报告格式：## 技术选型对比报告
      ### 1. 候选方案对比表
      ### 2. 业界实践参考
      ### 3. 综合推荐
    depends_on:
      - deep-research
      - web-quick
```

**执行命令**：

```bash
## 运行并行检索（研究问题通过模板变量注入）
sccsos workflow run workflows/并行检索.yaml
```

## 3.4 案例：CI/CD 集成流水线

**目标**：将 SCCS OS 工作流集成到 CI/CD 流水线中，实现自动化代码审查和文档生成。

**场景**：开发者在 Git 提交 PR 后，自动触发架构审查和代码质量检查。

```yaml
## workflows/ci-pipeline.yaml
name: ci-code-review
version: "1.0"
description: CI/CD 代码审查与质量检查流水线

steps:
  - id: code-analysis
    name: 代码分析
    agent: code-reviewer
    prompt: >
      请分析以下 Pull Request 的代码变更：
      PR 信息：
      - 分支：{{ git.branch }}
      - 变更文件数：{{ git.changed_files }}
      - 变更行数：{{ git.additions }} 行增加 + {{ git.deletions }} 行删除

      审查重点：
      1. 代码风格是否符合规范
      2. 是否存在安全漏洞
      3. 是否缺少异常处理
      4. 测试覆盖率是否足够

  - id: architecture-impact
    name: 架构影响评估
    agent: architect
    prompt: >
      评估本次代码变更对系统架构的影响。
      代码分析结果：{{ steps.code-analysis.response }}
      评估维度：
      1. 是否引入新的依赖
      2. 是否改变模块边界
      3. 是否影响现有接口兼容性
      4. 是否需要补充架构文档

  - id: auto-comment
    name: 自动生成评审意见
    agent: doc-writer
    prompt: >
      请根据以下两份报告，生成 Pull Request 评审意见。
      代码分析：{{ steps.code-analysis.response }}
      架构影响：{{ steps.architecture-impact.response }}
      输出格式：
      ## Code Review 总结
      ### ✅ 合规项
      ### ⚠️ 建议项
      ### ❌ 必须修改项
    depends_on:
      - code-analysis
      - architecture-impact

parallel_groups:
  - id: review-group
    steps:
      - code-analysis
      - architecture-impact
    max_concurrent: 2
```

**CI/CD 集成方式**：

```yaml
## GitHub Actions 示例
name: SCCS OS Code Review
on: [pull_request]
jobs:
  review:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Run SCCS OS Review
        run: |
          export GIT_BRANCH="${{ github.head_ref }}"
          export GIT_CHANGED_FILES="${{ steps.changed-files.outputs.count }}"
          sccsos workflow run workflows/ci-pipeline.yaml
```

## 3.5 案例：异常恢复与故障处理

**目标**：当 Agent 工作流执行失败时，自动诊断原因并尝试恢复。

**场景**：某工作流执行到步骤 3 时超时失败，需要诊断原因并根据策略进行恢复。

```yaml
## workflows/error-recovery.yaml
name: error-recovery-demo
version: "1.0"
description: 异常恢复演练工作流

steps:
  - id: diagnose
    name: 故障诊断
    agent: architect
    prompt: >
      请分析以下工作流执行失败的记录：

      失败信息：
      - 工作流：{{ failed_workflow_name }}
      - 失败步骤：{{ failed_step_id }}
      - 错误类型：{{ error_type }}
      - 错误详情：{{ error_message }}

      请诊断：
      1. 失败直接原因
      2. 根因分析
      3. 是否可恢复

  - id: recovery-plan
    name: 恢复方案
    agent: architect
    prompt: >
      基于故障诊断结果，制定恢复方案。

      诊断结果：{{ steps.diagnose.response }}

      请输出：
      1. 推荐恢复策略（重试/跳过/回滚）
      2. 受影响的其他步骤
      3. 预防措施建议
    depends_on:
      - diagnose

  - id: recovery-report
    name: 恢复报告
    agent: doc-writer
    prompt: >
      生成故障恢复报告。
      诊断：{{ steps.diagnose.response }}
      恢复方案：{{ steps.recovery-plan.response }}
      报告格式：## 故障恢复报告
      ### 1. 故障概述
      ### 2. 根因分析
      ### 3. 恢复措施
      ### 4. 预防建议
    depends_on:
      - recovery-plan
```

**手动恢复操作步骤**：

```bash
## 1. 查看工作流状态确认失败
sccsos workflow status <failed-run-id>

## 2. 查看追踪详情定位故障步骤
sccsos trace show <trace-id>

## 3. 检查 Agent 日志
sccsos agent logs architect --limit 30

## 4. 重新执行（手动修正参数后）
sccsos workflow run workflows/架构评审.yaml

## 5. 验证恢复后状态
sccsos health
```

\newpage

# 附录A：项目目录结构

```
sccsos/
├── AGENTS.md                       # 项目语境文件
├── pyproject.toml                  # 项目配置与打包
├── sccsos.yaml                     # SCCS OS 项目配置
├── sccsos/                        # 核心包
│   ├── cli.py                      # CLI 入口（click 框架）
│   ├── core/
│   │   ├── registry.py             # Agent 注册表
│   │   ├── lifecycle.py            # 生命周期状态机
│   │   ├── orchestrator.py         # Workflow 引擎
│   │   ├── database.py             # SQLite 持久化
│   │   ├── hermes_adapter.py       # Hermes 桥接
│   │   └── config.py               # 配置加载器
│   ├── agents/
│   │   └── architect.yaml          # 示例 Agent 定义
│   ├── workflows/
│   │   └── feature-dev.yaml        # 示例 Workflow 定义
│   ├── observability/
│   │   ├── tracer.py               # 链路追踪
│   │   ├── auditor.py              # Token 审计
│   │   └── logger.py               # 结构化日志
│   └── security/                   # 安全层（预留）
├── agents/                         # Agent 定义目录
│   ├── architect.yaml              # 架构设计师
│   ├── code-reviewer.yaml          # 代码审查 Agent
│   └── doc-writer.yaml             # 文档生成 Agent
├── workflows/                      # Workflow 定义目录
│   ├── 架构评审.yaml               # 架构评审工作流
│   ├── 每日巡检.yaml               # 每日巡检工作流
│   ├── 冒烟测试.yaml               # 冒烟测试工作流
│   └── 并行检索.yaml               # 并行检索工作流
├── docs/                           # 输入文档
│   └── 项目需求.md                 # 示例项目需求文档
├── 配置/                           # 示例配置文件
│   ├── sample-config.yaml          # 项目配置参考
│   └── multi-profile-config.yaml   # 多 Profile 配置参考
├── 测试/                           # 测试用例
│   ├── test_workflow_validate.py   # 工作流验证测试
│   └── test_agent_definition.py    # Agent 定义验证测试
├── 外部参考/                       # 外部参考文件
├── 数据/                           # SQLite 数据库
├── 输出/                           # 生成的 DOCX/PDF
└── 脚本/                           # 构建工具
```

\newpage

# 附录B：Agent 定义 YAML 参考

```yaml
# agents/architect.yaml — 架构设计师
name: architect
version: 1.0
description: 智能体架构设计师 — Agent architecture design specialist
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

完整示例见 `agents/` 目录下的三个 Agent 定义文件。

\newpage

# 附录C：技术决策清单

| 决策 | 选择 | 理由 |
|------|------|------|
| Agent 定义格式 | YAML + JSON Schema | 与 Hermes config.yaml 一致 |
| 编排模式 | 声明式 DAG + 本地顺序 | 避免分布式复杂度 |
| 状态持久化 | SQLite + JSON | Hermes 已用 SQLite 复用 |
| CLI 框架 | click | 轻量、成熟、Python 原生 |
| 配置管理 | YAML + 环境变量 | 与 Hermes 惯例对齐 |
| 追踪格式 | 自定义 JSON → 可导出 OpenTelemetry | 零外部依赖起步 |
| 安全策略 | 默认拒绝（白名单模式） | 最小权限原则 |
| 适配层 | 抽象基类（ABC）模式 | 生产/测试可切换 |
| Hermes 集成 | 子进程 delegate_task | 轻量隔离 |
