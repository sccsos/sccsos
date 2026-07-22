"""Sample template constants for sccsos init --samples.

All default agent, personality, and workflow definitions shipped
with the package.  Used by ``sccsos init --samples``.
"""

# ═══════════════════════════════════════════════════════════════════════
# Agent definitions
# ═══════════════════════════════════════════════════════════════════════

SAMPLE_AGENT = """name: architect
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
"""

SAMPLE_AGENT_DOC = """# Sample agent definition: 文档生成 Agent
name: doc-writer
version: 1.0
description: 技术文档自动生成 Agent — Technical documentation and report generation
personality: doc-writer
profile: sccsos
toolsets:
  - filesystem
  - web-search
tags:
  - core
  - documentation
lifecycle:
  max_turns: 30
  timeout: 900
  auto_recover: true
"""

SAMPLE_AGENT_REVIEW = """# Sample agent definition: 代码审查 Agent
name: code-reviewer
version: 1.0
description: 代码质量审查 Agent — Automated code review and quality analysis
personality: code-reviewer
profile: sccsos
toolsets:
  - filesystem
  - delegate_task
tags:
  - core
  - code-quality
lifecycle:
  max_turns: 40
  timeout: 1200
  auto_recover: true
"""


SAMPLE_AGENT_HERMES_INSTALL = """name: hermes-installer
version: 1.0
description: Hermes Agent 安装配置专家 — One-click Hermes installation and configuration
personality: hermes-installer
profile: sccsos
toolsets:
  - terminal
  - web-search
  - filesystem
tags:
  - core
  - installation
lifecycle:
  max_turns: 50
  timeout: 1800
"""


# ═══════════════════════════════════════════════════════════════════════
# Personality definitions
# ═══════════════════════════════════════════════════════════════════════

SAMPLE_PERSONALITY_ARCHITECT = """name: agent-architect
description: 智能体架构设计师 — Agent architecture design specialist
system_prompt: |
  你是一名资深软件架构师，擅长系统设计、架构评审和技术决策。

  核心职责：
  - 分析项目需求，提炼功能需求和非功能需求
  - 设计系统架构方案，包括模块划分、组件设计和数据流
  - 进行技术选型评估，给出有依据的方案对比
  - 识别潜在技术风险，提供缓解措施

  工作原则：
  - 优先考虑简单实用的方案，避免过度设计
  - 每个建议都必须有明确的业务价值和技术依据
  - 在架构决策中明确记录权衡（trade-off）和备选方案
  - 关注可维护性、可测试性和可部署性

  输出格式要求：
  - 使用清晰的结构化格式（标题、列表、代码块）
  - 复杂架构使用 ASCII 图表或伪代码描述
  - 每个方案都要标注优缺点

model: deepseek-v4-flash
temperature: 0.5
"""

SAMPLE_PERSONALITY_DOC = """name: doc-writer
description: 技术文档自动生成 Agent — Technical documentation and report generation
system_prompt: |
  你是一名资深技术文档工程师，擅长将技术设计转化为清晰、准确的文档。

  核心职责：
  - 根据技术架构和代码实现编写技术文档
  - 生成结构化的 API 文档、部署指南、操作手册
  - 确保文档的一致性和格式规范性
  - 将复杂的技术概念用易于理解的语言表达

  工作原则：
  - 使用标准的文档结构（标题层级、列表、代码块、表格）
  - 每个技术术语首次出现时给出简要解释
  - 示例代码必须实际可运行，并有预期输出说明
  - 文档的读者包括技术人员和初级用户

  输出格式要求：
  - 使用 Markdown 格式输出，需包含完整的目录结构
  - 表格要有表头，使用一致的对齐方式
  - 代码块标注语言类型
  - 复杂流程推荐使用 ASCII 图或 Mermaid 图表

model: deepseek-v4-flash
temperature: 0.4
"""

SAMPLE_PERSONALITY_REVIEW = """name: code-reviewer
description: 代码质量审查 Agent — Automated code review and quality analysis
system_prompt: |
  你是一名严谨的代码审查专家，擅长发现代码质量问题、安全漏洞和性能瓶颈。

  核心职责：
  - 审查代码的可读性、可维护性和性能
  - 发现潜在的安全漏洞和错误处理缺失
  - 检查代码是否符合项目编码规范
  - 提供具体的改进建议，附带代码示例

  工作原则：
  - 每个问题都必须有明确的依据（代码规范、安全最佳实践、性能原则）
  - 优先发现严重问题（功能缺陷、安全漏洞），再关注代码风格
  - 建议必须可操作，附带修改示例
  - 保持建设性语气，关注代码而非作者

  审查清单：
  1. 错误处理：是否有 try/except，异常是否被静默吞掉
  2. 安全性：是否有注入风险、权限漏洞、敏感信息泄露
  3. 性能：是否有不必要的循环、重复计算、大对象复制
  4. 可读性：变量命名、函数长度、注释质量
  5. 测试：是否有单元测试，边界条件是否覆盖

model: deepseek-v4-flash
temperature: 0.3
"""


SAMPLE_PERSONALITY_HERMES_INSTALL = """name: hermes-installer
description: Hermes Agent 安装配置专家 — One-click Hermes installation and configuration
system_prompt: |
  你是 SCCS OS 的 Hermes Agent 安装配置专家，负责指导用户完成 Hermes Agent 的完整安装、配置和验证流程。

  核心职责：
  - 使用 sccsos hermes install 安装 Hermes Agent（script/git/docker 三种模式）
  - 使用 sccsos hermes setup 配置 LLM Provider、模型和 API Key
  - 使用 sccsos hermes postinstall 安装系统依赖（Browser 引擎等）
  - 使用 sccsos hermes doctor 验证安装完整性
  - 使用 sccsos hermes show 查看当前配置

  工作流程：
  1. 检测当前环境（OS、Python、网络连通性）
  2. 推荐合适的安装方式（国内用户推荐 --china-mirror）
  3. 执行安装并监控进度
  4. 安装后自动同步配置
  5. 验证安装结果并给出后续步骤

  常用命令（按顺序执行）：
  ```bash
  sccsos hermes install                    # 安装 Hermes Agent
  sccsos hermes setup --yes                # 配置 LLM Provider 和 API Key
  sccsos hermes postinstall --yes          # 安装系统依赖
  sccsos hermes doctor                     # 验证安装完整性
  sccsos health                            # 检查 SCCS OS 健康状态
  ```

  注意事项：
  - API Key 优先从环境变量读取（如 DEEPSEEK_API_KEY）
  - 安装后自动同步 model/provider/base_url 到 Hermes 配置
  - 国内用户建议使用 --china-mirror 加速下载
  - git 模式适合二次开发，script 模式适合快速部署

model: deepseek-v4-flash
temperature: 0.4
"""


# ═══════════════════════════════════════════════════════════════════════
# Workflow definitions
# ═══════════════════════════════════════════════════════════════════════

SAMPLE_WORKFLOW_SMOKE = """name: 冒烟测试
description: 快速验证 Agent 环境和工作流引擎是否正常运行
schema_version: '1.1'
parallel_groups: []

steps:
  - id: ping
    name: 连通性测试
    agent: architect
    prompt: |
      请回复以下确认信息，仅返回 JSON 格式：

      {"status": "ok", "agent": "architect", "version": "0.11.4", "message": "Hermes agent is reachable"}

  - id: info
    name: 环境信息
    agent: architect
    prompt: |
      请用 JSON 格式回复当前环境信息，包含：python版本、操作系统、当前工作目录。
"""

SAMPLE_WORKFLOW_REVIEW = """name: 架构评审
description: 多角度架构设计方案评审 — 支持需求输入
schema_version: '1.1'
parallel_groups:
  - id: review
    max_concurrent: 3
    steps:
      - doc-review
      - code-review
      - final-review

steps:
  - id: analysis
    name: 需求分析
    agent: architect
    prompt: |
      分析以下需求，提炼出功能需求和非功能需求：

      {{ steps.input.context }}

      请输出结构化的需求分析报告。

  - id: design
    name: 架构设计
    agent: architect
    input: analysis.response
    prompt: |
      基于需求分析结果设计系统架构方案。
      需求分析：{{ steps.analysis.response }}
      请包含：模块划分、组件设计、数据流、技术选型。

  - id: doc-review
    name: 文档评审
    agent: doc-writer
    condition: "{{ steps.design.response | length > 0 }}"
    prompt: |
      评审以下架构设计文档的完整性和清晰度：
      {{ steps.design.response }}
      请给出文档改进建议。

  - id: code-review
    name: 代码审查
    agent: code-reviewer
    condition: "{{ steps.design.response | length > 0 }}"
    prompt: |
      从代码实现角度评审以下架构设计：
      {{ steps.design.response }}
      请关注可测试性、API 设计质量和实现复杂度。

  - id: final-review
    name: 评审总结
    agent: architect
    condition: "{{ steps.design.response | length > 0 }}"
    prompt: |
      综合所有评审意见，输出最终架构评审报告。
      原始设计：{{ steps.design.response }}
      文档意见：{{ steps.doc_review.response }}
      代码意见：{{ steps.code_review.response }}
"""

SAMPLE_WORKFLOW_CONDITION = """name: 条件分支示例
description: 根据需求明确度选择不同处理路径
schema_version: '1.1'
parallel_groups: []

steps:
  - id: clarity-check
    name: 需求明确度评估
    agent: architect
    prompt: |
      评估以下需求的明确程度：
      {{ steps.input.context }}
      如果需求包含具体的功能描述、用户场景或技术指标，回复"明确"。
      否则回复"不够明确"。

  - id: deep-design
    name: 深度设计
    agent: architect
    condition: "{{ '明确' in steps.clarity_check.response }}"
    prompt: |
      需求已明确，执行完整架构设计：
      {{ steps.input.context }}
      请输出详细设计方案。

  - id: clarify-suggest
    name: 澄清建议
    agent: architect
    condition: "{{ '明确' not in steps.clarity_check.response }}"
    prompt: |
      需求不够明确，请给出需求澄清建议：
      {{ steps.input.context }}
      列出需要补充的信息和典型的"5W1H"引导问题。
"""

SAMPLE_WORKFLOW_PARALLEL = """name: 并行检索
description: 多 Agent 并行信息检索与综合
schema_version: '1.1'
parallel_groups:
  - id: search
    max_concurrent: 3
    steps:
      - search-tech
      - search-market
      - search-security

steps:
  - id: search-tech
    name: 技术方案检索
    agent: architect
    prompt: |
      针对以下需求，调研可用的技术方案：
      {{ steps.input.context }}
      列出 2-3 个主流方案并对比优劣。

  - id: search-market
    name: 市场趋势分析
    agent: doc-writer
    prompt: |
      针对以下需求领域，分析当前市场趋势：
      {{ steps.input.context }}
      关注：主流厂商、开源生态、行业标准。

  - id: search-security
    name: 安全合规分析
    agent: code-reviewer
    prompt: |
      分析以下需求涉及的安全和合规考量：
      {{ steps.input.context }}
      列出：安全风险、合规要求、数据隐私。

  - id: synthesize
    name: 综合报告
    agent: architect
    prompt: |
      综合以下多维度调研结果，输出最终建议报告。
      技术方案：{{ steps.search_tech.response }}
      市场趋势：{{ steps.search_market.response }}
      安全合规：{{ steps.search_security.response }}
"""

SAMPLE_WORKFLOW_HERMES_SETUP = """name: Hermes 环境配置
description: 一键配置 Hermes Agent 运行环境
schema_version: '1.1'
parallel_groups:
  - id: config
    max_concurrent: 3
    steps:
      - check-env
      - check-deps
      - check-network

steps:
  - id: check-env
    name: 环境检测
    agent: hermes-installer
    prompt: |
      检测当前 Hermes Agent 运行环境，输出检测结果：
      1. Python 版本：`python3 --version`
      2. Hermes CLI 版本：`hermes --version`
      3. HERMES_HOME 路径
      4. 操作系统信息

      以 Markdown 表格输出检测结果，标注每项是否满足运行要求。

  - id: check-deps
    name: 依赖检查
    agent: hermes-installer
    prompt: |
      检查 Hermes Agent 运行所需依赖的安装状态：
      1. git — `git --version`
      2. curl — `curl --version | head -1`
      3. Docker — `docker --version`
      4. 浏览器引擎 — `agent-browser --version`

      对缺失的依赖，给出安装命令。

  - id: check-network
    name: 网络连通性
    agent: hermes-installer
    prompt: |
      测试 Hermes Agent 所需的网络连通性：
      1. DeepSeek API：`curl -s -o /dev/null -w "%{http_code}" https://api.deepseek.com/v1`
      2. Hermes 安装源：`curl -s -o /dev/null -w "%{http_code}" https://hermes-agent.nousresearch.com`
      3.（国内用户）镜像源：`curl -s -o /dev/null -w "%{http_code}" https://res1.hermesagent.org.cn`

      以表格输出每个端点的 HTTP 状态码。对不可达的端点给出解决方案。

  - id: setup-provider
    name: LLM Provider 配置
    agent: hermes-installer
    prompt: |
      配置 Hermes Agent 的 LLM Provider：
      1. 检查环境变量 `DEEPSEEK_API_KEY` 是否已设置
      2. 如未设置，提示用户导出 `export DEEPSEEK_API_KEY=sk-xxx`
      3. 运行 `sccsos hermes setup --yes` 同步配置到 Hermes profile
      4. 验证配置：`hermes -p sccsos config show | grep -A3 "Model"`
      输出配置验证结果。

  - id: install-personalities
    name: 安装 Agent 人格
    agent: hermes-installer
    prompt: |
      从 GitHub 安装 Agent 人格（Personality）配置：

      1. 克隆人格仓库：
         ```bash
         git clone https://github.com/jnMetaCode/agency-agents-zh.git /tmp/agency-agents-zh
         ```

      2. 复制人格文件到项目目录：
         ```bash
         cp -r /tmp/agency-agents-zh/personalities/* ./personalities/
         ```

      3. 列出已安装的人格：
         ```bash
         ls ./personalities/*.yaml | head -20
         ```

      4.（可选）使用指定人格创建 Agent：
         ```bash
         sccsos agent create <personality-name> --personality <name>
         ```

      输出安装结果：成功安装的人格数量、名称列表。

  - id: install-skills
    name: 安装 Hermes 技能
    agent: hermes-installer
    prompt: |
      安装 Hermes Agent 技能（Skills），扩展 Agent 能力：

      1. 从 GitHub 安装 open-webSearch 技能（Web 搜索增强）：
         ```bash
         cd {{ env.HERMES_HOME or "~/.hermes" }}/skills
         git clone https://github.com/Aas-ee/open-webSearch.git
         ```

      2. 安装 effective-html 技能（HTML 生成能力）：
         ```bash
         cd {{ env.HERMES_HOME or "~/.hermes" }}/skills
         git clone https://github.com/plannotator/effective-html.git
         ```

      3. 验证技能安装：
         ```bash
         hermes skills list | grep -E "open-webSearch|effective-html"
         ```

      4. 如果 hermes 命令不可用，技能文件已下载到 skills/ 目录，
         可在 sccsos.yaml 或 Hermes 配置中注册使用。

      输出安装结果：已安装的技能列表。

  - id: verify
    name: 验证与后续步骤
    agent: hermes-installer
    depends_on:
      - setup-provider
      - install-personalities
      - install-skills
    prompt: |
      基于之前的检查结果，输出最终验证报告：
      1. 运行 `sccsos hermes doctor` 检查完整状态
      2. 运行 `sccsos health` 检查 SCCS OS 系统健康度
      3. 后续步骤建议（按优先级排序）
"""


SAMPLE_WORKFLOW_DAILY = """name: 每日巡检
description: 定时巡检任务 — 环境健康检查与报告
schema_version: '1.1'
parallel_groups: []

steps:
  - id: health-check
    name: 环境健康检查
    agent: code-reviewer
    prompt: |
      执行环境健康检查，返回 JSON 报告包含：
      - system: 系统运行状态
      - hermes: Hermes Agent 连接状态
      - agents: 已注册 Agent 状态
"""


# ═══════════════════════════════════════════════════════════════════════
# Pricing
# ═══════════════════════════════════════════════════════════════════════

SAMPLE_PRICING = """{
  "version": 1,
  "updated": "2026-07-18",
  "description": "LLM model pricing per 1M tokens (USD). [input_price, output_price].",
  "default_input_price": 0.50,
  "default_output_price": 2.00,
  "models": {
    "deepseek-v4-flash":       [0.14, 0.28],
    "deepseek-v4-pro":         [0.44, 0.87],
    "deepseek-chat":           [0.14, 0.28],
    "deepseek-reasoner":       [0.55, 2.19],
    "gpt-4o":                 [2.50, 10.00],
    "gpt-4o-mini":            [0.15, 0.60],
    "claude-sonnet-4":        [3.00, 15.00],
    "claude-haiku-3.5":       [0.80, 4.00],
    "gemini-2.5-flash":        [0.30, 2.50],
    "gemini-2.5-pro":         [1.25, 10.00]
  }
}"""


# ═══════════════════════════════════════════════════════════════════════
# Enriched sccsos.yaml (with --samples)
# ═══════════════════════════════════════════════════════════════════════

SAMPLE_YAML_FULL = """# sccsos v0.16.6 project configuration (full)
project:
  name: sccsos
  version: 0.16.6

hermes:
  profile: sccsos
  binary: hermes
  home: ""                 # HERMES_HOME 覆盖（空值 = 使用环境变量或默认 ~/.hermes）
  code_path: ""            # HERMES_CODE_PATH 覆盖（空值 = 使用环境变量）
  adapter: subprocess
  setup:
    provider: deepseek
    model: deepseek-v4-flash
    api_key: ""
    base_url: "https://api.deepseek.com/v1"

database:
  path: ./data/sccsos.db

defaults:
  hermes_profile: sccsos
  max_turns: 90
  timeout: 1800

logging:
  level: INFO
  format: json
  directory: ./logs
  retention_days: 30

tracing:
  enabled: true
  export_path: ./traces/

pricing:
  path: ./config/pricing.json

agents:
  path: ./agents
  wiki_path: ./wiki
  personalities_path: ./personalities

model_pool:
  enabled: false
  models:
    - name: reasoning
      provider: deepseek
      model: deepseek-v4-flash
      capabilities: [reasoning, code]
    - name: fast
      provider: deepseek
      model: deepseek-v4-flash
      capabilities: [chat, quick]
    - name: preview
      provider: deepseek
      model: deepseek-v4-pro
      capabilities: [analysis, planning]

policies:
  default:
    max_tokens_per_session: 100000
    max_cost_usd: 5.0
    allowed_tools:
      - read_file
      - search_files
      - web_search
      - web_extract
      - terminal
      - delegate_task
    blocked_tools: []
    allowed_commands:
      - hermes
      - git
      - ls
      - cat
      - head
      - tail
      - echo
      - python3
      - pip3
      - node
      - npm
      - which

webhooks:
  enabled: false
  endpoints: []
"""


# ── Registry: all sample files and their content ────────────────────

SAMPLE_FILES = {
    # Personalities
    "personalities/agent-architect.yaml": SAMPLE_PERSONALITY_ARCHITECT,
    "personalities/doc-writer.yaml": SAMPLE_PERSONALITY_DOC,
    "personalities/code-reviewer.yaml": SAMPLE_PERSONALITY_REVIEW,
    "personalities/hermes-installer.yaml": SAMPLE_PERSONALITY_HERMES_INSTALL,
    # Agents
    "agents/architect.yaml": SAMPLE_AGENT,
    "agents/doc-writer.yaml": SAMPLE_AGENT_DOC,
    "agents/code-reviewer.yaml": SAMPLE_AGENT_REVIEW,
    "agents/hermes-installer.yaml": SAMPLE_AGENT_HERMES_INSTALL,
    # Workflows
    "workflows/冒烟测试.yaml": SAMPLE_WORKFLOW_SMOKE,
    "workflows/架构评审.yaml": SAMPLE_WORKFLOW_REVIEW,
    "workflows/条件分支示例.yaml": SAMPLE_WORKFLOW_CONDITION,
    "workflows/并行检索.yaml": SAMPLE_WORKFLOW_PARALLEL,
    "workflows/每日巡检.yaml": SAMPLE_WORKFLOW_DAILY,
    "workflows/hermes-setup.yaml": SAMPLE_WORKFLOW_HERMES_SETUP,
}
"""Map of relative file paths → content for ``sccsos init --samples``."""
