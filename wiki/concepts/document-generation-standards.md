# 文档生成规范

> 最后更新: 2026-07-26

## 作者署名规范

所有 SCCS OS 技术文档的作者署名为 **创新研究院 李锋**。

### 适用文件范围

| 文件类型 | 示例 | 作者字段 |
|---------|------|---------|
| 部署与操作手册 | `SCCS OS 部署与操作手册.md` | `**创新研究院 李锋**` |
| 测试验证手册 | `SCCS OS 测试验证与操作手册.md` | `**创新研究院 李锋**` |
| 设计/评审文档 | `整体设计方案.md` / `架构评审报告.md` | `评审人: 创新研究院 李锋` |
| 企业版/轻量化手册 | `SCCS OS 企业级商用版部署与操作手册.md` | `**创新研究院 李锋**` |
| 脚本/生成工具 | `合并完整手册.py` | `description: 创新研究院 李锋` |

### 禁止使用的作者标识

- ❌ `**智能体架构设计师**` — 这是 Hermes Agent 角色名称，非文档作者
- ❌ `description: 智能体架构设计师` — 文档上下文中的描述也统一使用真实作者

### 例外（保持原状）

以下文件中的 `智能体架构设计师` 是 **Agent 角色类型定义**，不是文档作者，保持不变：

| 文件 | 原因 |
|------|------|
| `agents/architect.yaml` | Agent 定义，描述 Agent 的职责角色 |
| `personalities/agent-architect.yaml` | 角色设定，描述 AI Agent 人格 |
| `sccsos/cli/sample_templates.py` | CLI 初始化模板中的 Agent 示例定义 |

## 图片与图形规范

所有技术文档中的流程图、架构图、决策树必须以 **图片（PNG/SVG）** 嵌入，禁止使用 ASCII art 代码块。

### 原则

| 内容类型 | 禁止 | 允许 |
|---------|------|------|
| 系统架构 | ```` ``` ```` 中的 ASCII art | `![](images/sccsos-system-architecture-light.png)` |
| 部署架构 | ```` ``` ```` 中的 ASCII 线框图 | `![](images/sccsos-deployment-architecture-light.png)` |
| 流程图/决策树 | ```` ```mermaid ```` 代码块 | `![](images/sccsos-deployment-decision-tree-light.png)` |
| 生命周期状态机 | ```` ``` ```` 中的 ASCII 箭头图 | `![](images/sccsos-lifecycle-state-machine-light.png)` |

### 图片生成工具链

```bash
# 1. 创建 SVG 源文件
# 2. 转换为 PNG（用于 pandoc DOCX/PDF 嵌入）
rsvg-convert --width=2400 --format=png diagram.svg -o diagram.png

# 3. SVG + PNG 放入 输出/images/
cp diagram.svg diagram.png 输出/images/

# 4. Markdown 引用
![图标题](images/diagram.png)
*图序号: 描述文字*
```

### 现有图片清单

| 文件 | 用途 |
|------|------|
| `sccsos-system-architecture-light` | 系统四层架构图 |
| `sccsos-deployment-architecture-light` | 部署架构（macOS 宿主 + Hermes + sccsos） |
| `sccsos-enterprise-deployment-light` | 企业级全量部署全景（K8s + 中间件 + 可观测） |
| `sccsos-deployment-decision-tree-light` | 部署方案选择决策树 |
| `sccsos-lifecycle-state-machine-light` | Agent 5 状态状态机 |
| `sccsos-workflow-sequence-light` | 工作流执行时序图 |
| `sccsos-component-relationship-light` | 模块依赖关系图 |
| `sccsos-feasibility-architecture` | 可行性方案架构图 |
