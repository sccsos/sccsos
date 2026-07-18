# SCCS OS 文档目录

> 最后更新: 2026-07-14
> 项目阶段: Phase 1 — 核心框架（规划中）

| # | 文档 | 说明 |
|---|------|------|
| **1** | [整体设计方案](1-整体设计方案.md) | 项目概述、系统架构、组件规格、技术决策全景 |
| **2** | [企业级可行性方案](2-企业级可行性方案.md) | 商业可行性、团队配置、工期排期、立项摘要 |
| **3** | [技术架构规格书](3-技术架构规格书.md) | 核心组件详细设计、接口定义、数据模型 |
| **4** | [架构评审报告](4-架构评审报告.md) | Phase 1 架构设计评审、风险检查、改进建议 |
| **5** | [第一阶段实施计划](5-第一阶段实施计划.md) | 详细任务分解、编码顺序、交付验收标准 |
|| **6** | [部署指南](6-部署指南.md) | 环境准备、安装部署、配置说明、部署验证 |
|| **7** | [操作手册](7-操作手册.md) | CLI 详解、Agent管理、工作流编排、可观测性、常见问题 |
|| **8** | [文档与插图生成规范](8-文档与插图生成规范.md) | 文档插图规范、SVG 箭头、生成工作流 |
|| **9** | [可行性技术方案文档](9-可行性技术方案文档.md) | 完整可行性论证、团队配置、工期排期 |
|| **DOCX** | [完整手册](完整技术手册.docx) | 三部曲合辑，53页 |
|| **DOCX** | [文档目录](文档目录.docx) | GB 标准格式 Word 文档 |
|| **DOCX** | [整体方案](整体设计方案.docx) | GB 标准格式 Word 文档 |
|| **DOCX** | [可行性方案](企业级可行性方案.docx) | GB 标准格式 Word 文档 |
|| **DOCX** | [技术规格书](技术架构规格书.docx) | GB 标准格式 Word 文档 |
|| **DOCX** | [架构评审](架构评审报告.docx) | GB 标准格式 Word 文档 |
|| **DOCX** | [实施计划](第一阶段实施计划.docx) | GB 标准格式 Word 文档 |
|| **DOCX** | [部署指南](部署指南.docx) | GB 标准格式 Word 文档 |
|| **DOCX** | [操作手册](操作手册.docx) | GB 标准格式 Word 文档 |
|| **DOCX** | [生成规范](文档与插图生成规范.docx) | GB 标准格式 Word 文档 |
|| **DOCX** | [可行性方案（完整）](可行性技术方案文档.docx) | GB 标准格式 Word 文档 |
|| **PDF** | [完整手册 PDF](完整技术手册.pdf) | 三部曲合辑，53页 |
|| **PDF** | [文档目录 PDF](文档目录.pdf) | A4 格式 |
|| **PDF** | [整体方案 PDF](整体设计方案.pdf) | A4 格式，5 页 |
|| **PDF** | [可行性方案 PDF](企业级可行性方案.pdf) | A4 格式 |
|| **PDF** | [技术规格书 PDF](技术架构规格书.pdf) | A4 格式 |
|| **PDF** | [架构评审 PDF](架构评审报告.pdf) | A4 格式 |
|| **PDF** | [实施计划 PDF](第一阶段实施计划.pdf) | A4 格式 |
|| **PDF** | [部署指南 PDF](部署指南.pdf) | A4 格式，7 页 |
|| **PDF** | [操作手册 PDF](操作手册.pdf) | A4 格式，10 页 |
|| **PDF** | [生成规范 PDF](文档与插图生成规范.pdf) | A4 格式 |
|| **PDF** | [可行性方案（完整）PDF](可行性技术方案文档.pdf) | A4 格式 |

## 架构插图

| # | 文件名 | 说明 | 格式 |
|---|--------|------|------|
| 1 | `images/sccsos-system-architecture-*` | 系统分层架构图（4 层） | 🌙 Dark / ☀️ Light |
| 2 | `images/sccsos-component-relationship-*` | 核心组件关系图 | 🌙 Dark / ☀️ Light |
| 3 | `images/sccsos-lifecycle-state-machine-*` | Agent 生命周期状态机 | 🌙 Dark / ☀️ Light |
| 4 | `images/sccsos-workflow-sequence-*` | Workflow 执行时序图 | 🌙 Dark / ☀️ Light |
| 5 | `images/sccsos-deployment-architecture-*` | 部署架构图 | 🌙 Dark / ☀️ Light |

> 每幅插图包含 3 种格式（HTML/SVG/PNG）和 2 种风格（🌊蓝色深色/☀️浅色），共 6 个文件。浅色版适用于打印/PDF 输出。底纹网格已去除，深色版以蓝色为基调。
## 外部参考

| 位置 | 说明 |
|------|------|
| `wiki/concepts/ADR-002-agentos-feasibility-plan.md` | ADR: 技术可行性分析与实施规划 |
| `wiki/concepts/agentos-architecture-framework.md` | 7 大关注域、5 项原则 |
| `wiki/concepts/ADR-001-multi-agent-architecture.md` | 多智能体架构 ADR |
| `profiles/sccsos/SOUL.md` | 智能体架构设计师人格路由 |
| `profiles/sccsos/config.yaml` | sccsos profile 配置 |
