<div class="cover-page">

# 文档与插图生成规范

**智能体架构设计师**

整合版 v1.0 | 2026 年 7 月

</div>

\newpage

# 第一章 总体策略

## 1.1 什么时候用图，什么时候用文字

| 场景 | 推荐方式 | 说明 |
|------|---------|------|
| 系统架构分层 | SVG 架构图 | 分层关系一目了然 |
| 组件间数据流 | SVG 箭头图 | 方向/依赖可视化 |
| 状态机/流程 | SVG 状态图 | 状态转换需要视觉轨迹 |
| 简单的列表/表格 | Markdown 表格 | 纯文字更快、可搜索 |
| 命令行/代码 | 代码块 | 保持可复制 |
| ASCII 框图 | → SVG 替换 | 见第二章规则 |

## 1.2 技术栈

| 工具 | 用途 | 安装 |
|------|------|------|
| 手写 SVG | 矢量图源文件 | — |
| rsvg-convert | SVG → PNG | brew install librsvg |
| pandoc | Markdown → DOCX/PDF | brew install pandoc |
| Hermes architecture-diagram | 深色主题架构图 HTML | 内置 |
| Hermes html-diagram | 全屏交互式 SVG 架构图 | npx skills add ... |

![SCCS OS 系统分层架构图](images/sccsos-system-architecture-light.png)

<div class="img-caption">图 1: SCCS OS 系统分层架构图 — 四层架构示例</div>

\newpage

# 第二章 图片格式与尺寸

## 2.1 两种产出路线

| 路线 | 适用场景 | 格式 | 尺寸标准 |
|------|---------|------|---------|
| 架构插图 | 嵌入 Markdown 文档 | SVG + PNG 双格式 | 自由 viewBox |
| 全屏交互图 | Web 展示/评审 | 自包含 HTML | 100vw × 100vh |

## 2.2 架构插图标准

| 项目 | 标准 |
|------|------|
| SVG viewBox | 自由（依内容，如 0 0 1060 680） |
| PNG 输出 | 2400px 宽（rsvg-convert --width=2400） |
| 双格式 | 同名 .svg + .png 同时保存 |
| 配色 | 浅色调：#ffffff 背景，#334155 正文 |
| 阴影 | filter drop-shadow：dy=1, blur=2, opacity=0.08 |

## 2.3 全屏交互图标准

| 项目 | 标准 |
|------|------|
| SVG viewBox | 0 0 900 506（16:9） |
| HTML 尺寸 | 100vw × 100vh |
| 暗色模式 | CSS 变量 + localStorage + prefers-color-scheme |
| 字体 | JetBrains Mono（Google Fonts） |

\newpage

# 第三章 SVG 箭头标记规范

## 3.1 标准标记定义

```xml
<marker id="arr-blue" markerWidth="8" markerHeight="6" refX="8" refY="3" orient="auto">
  <polygon points="8 3, 0 0, 0 6" fill="#2563eb"/>
</marker>
```

| 参数 | 值 | 说明 |
|------|-----|------|
| markerWidth | 8 | 标记视口宽度 |
| markerHeight | 6 | 标记视口高度 |
| refX | 8 | 尖端在线末端，不越界 |
| refY | 3 | 垂直居中（height/2） |
| 多边形 | 8 3, 0 0, 0 6 | 尖端(8,3) + 左上翼(0,0) + 右下翼(0,6) |

## 3.2 关键设计决策

refX=8 时尖端位于线末端，箭头恰好触及目标盒子边缘不越界。refX=0 时翼展位于线末端，尖端延伸越界。

## 3.3 SCCS OS 6 种箭头

| ID | 颜色 | 用途 |
|----|------|------|
| arr-blue | #2563eb | 核心层调用流 |
| arr-sky | #0284c7 | CLI/API 层调用 |
| arr-indigo | #4f46e5 | 持久化/可观测数据流 |
| arr-rose | #e11d48 | 安全层/权限流 |
| arr-slate | #64748b | 终止/不可逆转换 |
| arr-amber | #d97706 | 状态/并行标记 |

![SCCS OS 核心组件关系图](images/sccsos-component-relationship-light.png)

<div class="img-caption">图 2: 核心组件关系图 — 展示 6 种箭头在架构图中的实际应用</div>

\newpage

# 第四章 生成工作流

## 4.1 架构插图 — 3 轮迭代

### 第 1 轮：初始布局

分析内容 → 确定分层结构 → 手写 SVG → 放置文字元素 → 设置配色 → 定义箭头标记 → 生成 PNG

### 第 2 轮：箭头与对齐

检查箭头坐标：起点在源组件边缘，终点距目标 ≤ 1px。检查标签不重叠箭头线。对齐间距。

### 第 3 轮：最终验证

文字对比度 ≥ 4.5:1。rsvg-convert 合法性验证。同步双格式。嵌入文档验证。

## 4.2 ASCII 图 → SVG 替换

识别含 ┌┐└┘├┤│─ 等字符的 ASCII 框图，设计 16:9 浅色 SVG 替代，生成双格式，替换引用，验证渲染。

![Workflow 执行时序图](images/sccsos-workflow-sequence-light.png)

<div class="img-caption">图 3: Workflow 执行时序图 — 展示从 ASCII 到 SVG 的替换效果</div>

\newpage

# 第五章 配色方案

## 5.1 浅色版（默认）

| 用途 | 色值 | 对比度 |
|------|------|--------|
| 组件标题 | #ffffff + 色块 | 14.4:1 |
| 正文描述 | #334155 | 11.7:1 |
| 辅助文本 | #64748b | 4.5:1 |
| 层标题 | #0369a1 | 8.9:1 |
| 核心组件标题 | #1d4ed8 | 8.9:1 |
| 可观测标签 | #4338ca | 7.2:1 |
| 安全组件 | #be123c | 6.8:1 |
| 状态标记 | #b45309 | 5.7:1 |

## 5.2 组件填充色

| 层 | 填充 | 边框 |
|----|------|------|
| API 层 | #e0f2fe | #0284c7 |
| 核心层 | #dbeafe | #2563eb |
| 安全层 | #fce7f3 | #e11d48 |
| 可观测/数据 | #eef2ff | #6366f1 |
| 基础设施 | #f1f5f9 | #94a3b8 |

![SCCS OS 部署架构图](images/sccsos-deployment-architecture-light.png)

<div class="img-caption">图 4: 部署架构图 — 完整展示浅色调配色方案</div>

\newpage

# 第六章 文件组织

项目目录结构：

```bash
项目/
├── 输出/                           # 项目文档 + 生成输出
│   ├── images/                     # 架构插图
│   ├── 0-目录与索引.md
│   ├── 1-整体设计方案.md
│   ├── 2-企业级可行性方案.md
│   ├── 3-技术架构规格书.md
│   ├── 4-架构评审报告.md
│   ├── 5-第一阶段实施计划.md
│   ├── 6-部署指南.md
│   ├── 7-操作手册.md
│   ├── 8-文档与插图生成规范.md
│   ├── 9-可行性技术方案文档.md
│   ├── 完整技术手册.md
│   ├── 完整技术手册.docx/pdf
│   ├── 整体设计方案.docx/pdf
│   └── ... 其他 .docx/.pdf
├── 脚本/                  # 构建工具
│   ├── 构建全部文档.py
│   ├── 合并完整手册.py
│   ├── 后处理文档.py
│   ├── 新页过滤.lua
│   └── 国标样式.css
├── 数据/                  # SQLite 数据库
├── 测试/                  # 测试用例
├── 配置/                  # 示例配置
└── 外部参考/              # 外部参考文件
```

\newpage

# 第七章 验证清单

## 7.1 插图质量检查

- 所有文字对比度 ≥ 4.5:1（白底）
- 箭头 refX=8，不越界
- 箭头 stroke-width=1，标记 8×6
- 箭头末端距盒子 ≤ 1px
- 无退化三角形箭头
- SVG 可被 rsvg-convert 解析
- PNG 已同步到 输出/插图/
- SVG + PNG 双格式并存

## 7.2 文档引用检查

- Markdown 引用 -light.png（非 -dark.png）
- 图片路径相对于文档目录正确
- DOCX/PDF 生成无 Could not fetch resource 警告

\newpage

# 第八章 DOCX/PDF 文档生成流水线

## 8.1 技术栈

| 工具 | 用途 | 安装 |
|------|------|------|
| pandoc | Markdown → DOCX/PDF | brew install pandoc |
| python-docx | DOCX 后处理 | pip install python-docx |
| weasyprint | PDF 渲染引擎 | brew install weasyprint |
| rsvg-convert | SVG → PNG | brew install librsvg |

## 8.2 SCCS OS 文档生成工作流

三步流水线：pandoc → raw DOCX → python-docx 后处理 → 最终 DOCX，同时 pandoc + weasyprint → PDF。

## 8.3 关键配置

后处理脚本实现全文档微软雅黑、表格实线边框、页脚页码。PDF 样式定义 A4 纸张、页边距、封面居中布局。

## 8.4 重要注意事项

| 注意点 | 说明 |
|--------|------|
| pandoc 图片路径 | 必须从 Markdown 所在目录执行 |
| Lua filter | \\newpage 分页符需 filter 才生效 |
| 微软雅黑字体 | macOS 需手动安装 |
| 管道符陷阱 | 表格行首 | 可能被污染 |

以上就是文档与插图生成规范的全部内容。本规范持续更新，最新版本见 wiki。