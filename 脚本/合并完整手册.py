#!/usr/bin/env python3
"""
SCCS OS 文档拆分生成脚本
将 10 篇独立文档重组为两份独立手册：
  1. SCCS OS 立项与设计手册（第1~4章 + 附录）
  2. SCCS OS 部署与操作手册（第1~2章 + 附录）
第二部（评审与实施）被移除。
章节已重编号，两份文档各自独立。

用法:
    python3 脚本/合并完整手册.py
"""

from pathlib import Path
import re, shutil

WORKSPACE = Path("/Users/smart/dev/hermesws/sccsos")
DOCS_DIR = WORKSPACE / "输出"
OUTPUT_DIR = WORKSPACE / "输出"
IMAGES_DIR = DOCS_DIR / "images"


def read(fname):
    p = DOCS_DIR / fname
    if not p.exists():
        p = WORKSPACE / fname
    return open(p, encoding='utf-8').read()


def strip_cover_page(text):
    text = re.sub(r'<div class="cover-page">.*?</div>\s*\n*', '', text, flags=re.DOTALL)
    return text


def strip_header_meta(text):
    text = re.sub(r'^> .*\n', '', text)
    text = re.sub(r'^---\n', '', text, count=1)  # 仅移除文档头部的第一个 ---（分隔元数据与正文）
    text = re.sub(r'^#\n', '', text, flags=re.MULTILINE)
    return text


# ── 封面 ──────────────────────────────────────────────

def cover_design():
    return """<div class="cover-page">

# SCCS OS 立项与设计手册

创新研究院 李锋

v1.0 | 2026 年 7 月

涵盖：SCCS-T 产品体系 · 项目概述 · 可行性方案 · 系统架构 · 技术规格

</div>

\\newpage

# 目录

- **第1章 项目概述**
- **第2章 可行性方案**
- **第3章 系统架构**
- **第4章 技术规格**
- **附录**
  - 附录A：项目目录结构
  - 附录B：Agent 定义 YAML 参考
  - 附录C：技术决策清单

\\newpage

"""


def cover_ops():
    return """<div class="cover-page">

# SCCS OS 部署与操作手册

创新研究院 李锋

v1.0 | 2026 年 7 月

涵盖：环境部署 · 操作指南

</div>

\\newpage

# 目录

- **第1章 环境与部署**
- **第2章 操作指南**
- **第3章 实战案例**
- **附录**
  - 附录A：项目目录结构
  - 附录B：Agent 定义 YAML 参考
  - 附录C：技术决策清单

\\newpage

"""


# ── 内容：立项与设计 ─────────────────────────

def build_part1():
    text = ""

    ch1 = read("1-整体设计方案.md")
    m = re.search(r'(## 1\. 项目概述.*?)(?=## 2\.|\Z)', ch1, re.DOTALL)
    if m:
        text += "\n# 第1章 项目概述\n\n"
        content = m.group(1)
        content = content.replace("## 1. 项目概述", "")
        content = content.replace("### ", "## ")
        text += content.strip()

    text += "\n\n\\newpage\n\n"
    text += "\n# 第2章 可行性方案\n\n"

    feas = read("9-可行性技术方案文档.md")
    feas = strip_header_meta(feas)

    sections_to_extract = [
        (r'(## 1\\. 方案概述.*?)(?=## 2\\.)', "## 1. 方案概述"),
        (r'(## 2\\. 核心概念定位厘清.*?)(?=## 3\\.)', "## 2. 核心概念定位厘清"),
        (r'(## 3\\. 方案可行性核心优势.*?)(?=## 4\\.)', "## 3. 核心优势"),
        (r'(## 4\\. 核心短板与针对性改造方案.*?)(?=## 5\\.)', "## 4. 核心短板与改造"),
        (r'(## 5\\. 两大落地实施路线.*?)(?=## 6\\.)', "## 5. 落地路线"),
        (r'(## 6\\. 方案对比.*?)(?=## 7\\.)', "## 6. 方案对比"),
        (r'(## 7\\. 最终结论与落地建议.*?)(?=## 8\\.)', "## 7. 结论"),
    ]

    for pat, heading in sections_to_extract:
        m = re.search(pat, feas, re.DOTALL)
        if m:
            content = m.group(1)
            content = content.replace(heading, f"## {heading.strip('# ')}")
            text += content.strip() + "\n\n"

    text += "\n\n\\newpage\n\n"
    text += "\n# 第3章 系统架构\n\n"

    m = re.search(r'(## 2\. 系统架构.*?)(?=## 3\.|\Z)', ch1, re.DOTALL)
    if m:
        content = m.group(1)
        content = content.replace("## 2. 系统架构", "## 3.1 分层架构")
        # 重编号子节 2.x → 3.1.x
        content = re.sub(r'^### 2\.1 ', '### 3.1.1 ', content, flags=re.MULTILINE)
        content = re.sub(r'^### 2\.2 ', '### 3.1.2 ', content, flags=re.MULTILINE)
        text += content.strip() + "\n\n"

    m = re.search(r'(## 3\. 核心组件规格.*?)(?=## 4\.|\Z)', ch1, re.DOTALL)
    if m:
        content = m.group(1)
        # 重编号子节 3.x → 3.2.x
        content = re.sub(r'^### \d+\.(\d+) ', lambda m: f'### 3.2.{int(m.group(1))} ', content, flags=re.MULTILINE)
        content = content.replace("## 3. 核心组件规格", "## 3.2 核心组件")
        text += content.strip() + "\n\n"

    text += "\n\n\\newpage\n\n"
    text += "\n# 第4章 技术规格\n\n"

    spec = read("3-技术架构规格书.md")
    spec = strip_header_meta(spec)

    for tag, title in [("1. 数据模型", "4.1 数据模型"),
                       ("2. 接口定义", "4.2 接口定义"),
                       ("3. 数据库 Schema", "4.3 数据库 Schema"),
                       ("4. 错误处理规范", "4.4 错误处理"),
                       ("5. 配置规范", "4.5 配置规范")]:
        m = re.search(fr'(## {re.escape(tag)}.*?)(?=## \d+\. |\Z)', spec, re.DOTALL)
        if m:
            content = m.group(1)
            content = content.replace(f"## {tag}", f"## {title}")
            text += content.strip() + "\n\n"

    # ── 统一清理 ──
    # 1. 降级内联 H1（不在 第N章 级别的）→ H2（跳过代码块保护注释）
    parts = re.split(r'(```[\w]*\n.*?```)', text, flags=re.DOTALL)
    for i, p in enumerate(parts):
        if i % 2 == 0:
            parts[i] = re.sub(r'^# (?!第\d+章)', r'## ', p, flags=re.MULTILINE)
    text = ''.join(parts)
    # 2. 清除标题中的 \. 转义（如 1\. → 1.）
    text = re.sub(r'^(#+)\s*(\d+)\\.', r'\1 \2.', text, flags=re.MULTILINE)
    # 3. 清除段首的 \. 转义（如 \.foo → .foo）
    text = re.sub(r'^\.', '.', text, flags=re.MULTILINE)

    return text


# ── 内容：部署与操作 ─────────────────────────

def remap_chapters(text, prefix):
    """将源文档的中文章节编号映射为小节编号。
    
    prefix=1: `第一章 概述` → `## 1.1 概述`, 内部 `## 1.1 文档说明` → `### 1.1.1`
    prefix=2: `第一章 概述` → `## 2.1 概述`, 内部 `## 1.1 文档说明` → `### 2.1.1`
    
    通过按章切分避免交叉匹配——章节标题的替换不影响其内部内容。
    """
    CN = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6,
          "七": 7, "八": 8, "九": 9, "十": 10}

    # 按「# 第X章 ...」切分，保留分隔符
    parts = re.split(r'^(?=# 第[一二三四五六七八九十]+章\s)', text, flags=re.MULTILINE)
    result = []
    current_num = 0

    for part in parts:
        m = re.match(r'^# 第([一二三四五六七八九十]+)章\s+(.*)', part, flags=re.MULTILINE)
        if m:
            cn = m.group(1)
            current_num = CN.get(cn, 1)
            title = m.group(2).strip()
            result.append(f"\n## {prefix}.{current_num} {title}\n")
            # 章节标题之后的内容（同一 part 内）
            body = part[m.end():]
            if body.strip():
                def renumber(m2):
                    sub = m2.group(2)  # 节内编号（group1=章号, group2=节号）
                    return f"### {prefix}.{current_num}.{sub} "
                body = re.sub(r'^## (\d+)\\.(\d+)\s+', renumber, body, flags=re.MULTILINE)
                body = re.sub(r'^# ', r'## ', body, flags=re.MULTILINE)
                body = re.sub(r'\n{0,2}\\\newpage\n{0,2}(?=\S)', '\n', body, flags=re.MULTILINE)
                result.append(body)
        elif current_num > 0:
            # 章节内部内容：重新编号子节，去 \\newpage
            def renumber(m2):
                sub = m2.group(2)
                return f"### {prefix}.{current_num}.{sub} "
            part = re.sub(r'^## (\d+)\\.(\d+)\s+', renumber, part, flags=re.MULTILINE)
            # 内联 H1（非章节标题，如"# 通过 pip 安装"）降为 H2
            part = re.sub(r'^# ', r'## ', part, flags=re.MULTILINE)
            part = re.sub(r'\n{0,2}\\\newpage\n{0,2}(?=\S)', '\n', part, flags=re.MULTILINE)
            result.append(part)
        else:
            # 去除文档头部在封面之后、第一章之前的 \newpage（合并到合辑后冗余）
            part = re.sub(r'^\\newpage\n*', '', part)
            if part.strip():
                result.append(part)

    return "".join(result).strip()


def build_part3():
    text = ""

    # ── 第1章 环境与部署 ──
    text += "\n# 第1章 环境与部署\n\n"
    deploy = read("6-部署指南.md")
    deploy = strip_cover_page(deploy)
    deploy = strip_header_meta(deploy)
    deploy = remap_chapters(deploy, prefix=1)
    text += deploy.strip() + "\n\n"

    # ── 第2章 操作指南 ──
    text += "\n# 第2章 操作指南\n\n"
    ops = read("7-操作手册.md")
    ops = strip_cover_page(ops)
    ops = strip_header_meta(ops)
    ops = remap_chapters(ops, prefix=2)
    text += ops.strip() + "\n\n"

    return text


# ── 附录（两份文档共用） ──────────────────────

def build_appendix():
    text = "\n\n\\newpage\n\n"
    text += "\n\n# 附录\n\n"

    text += "\n# 附录A：项目目录结构\n\n"
    text += """```
sccsos/
├── AGENTS.md                       # 项目语境
├── sccsos/                        # 核心包
│   ├── __init__.py
│   ├── cli.py                      # CLI 入口（click 框架）
│   ├── core/
│   │   ├── registry.py             # Agent 注册表
│   │   ├── lifecycle.py            # 生命周期状态机
│   │   ├── orchestrator.py         # Workflow 引擎
│   │   ├── database.py             # SQLite 持久化
│   │   ├── hermes_adapter.py       # Hermes 桥接
│   │   └── config.py               # 配置加载器
│   ├── agents/                     # Agent 定义 YAML
│   ├── workflows/                  # Workflow 定义 YAML
│   ├── observability/
│   │   ├── tracer.py               # 链路追踪
│   │   ├── auditor.py              # Token 审计
│   │   └── logger.py               # 结构化日志
│   └── security/                   # 安全层（预留）
├── 文档/                           # 源文档（Markdown + 插图）
├── 输出/                           # 生成的 DOCX/PDF
├── 脚本/                           # 构建工具
├── 数据/                           # SQLite 数据库
├── 测试/                           # 测试用例
├── 配置/                           # 示例配置
├── 外部参考/                       # 外部参考文件
└── pyproject.toml                  # 项目配置
```\n\n"""

    text += "\n\\newpage\n\n"
    text += "\n# 附录B：Agent 定义 YAML 参考\n\n"
    text += """```yaml
# agents/architect.yaml
name: architect
version: 1.0
description: 创新研究院 李锋
personality: agent-architect
profile: agentos
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
```\n\n"""

    text += "\n\\newpage\n\n"
    text += "\n# 附录C：技术决策清单\n\n"
    text += """| 决策 | 选择 | 理由 |
|------|------|------|
| Agent 定义格式 | YAML + JSON Schema | 与 Hermes config.yaml 一致 |
| 编排模式 | 声明式 DAG + 本地顺序 | 避免分布式复杂度 |
| 状态持久化 | SQLite + JSON | Hermes 已用 SQLite 复用 |
| CLI 框架 | click | 轻量、成熟、Python 原生 |
| 配置管理 | YAML + 环境变量 | 与 Hermes 惯例对齐 |
| 追踪格式 | 自定义 JSON → 可导出 OpenTelemetry | 零外部依赖起步 |
| 安全策略 | 默认拒绝（白名单模式） | 最小权限原则 |
| 适配层 | 抽象基类（ABC）模式 | 生产/测试可切换 |
| Hermes 集成 | 子进程 delegate_task | 轻量隔离 |\n\n"""

    return text


# ── 通用后处理 ────────────────────────────────

def strip_hlines(text):
    """移除章节间的 --- 分隔线（保留代码块内的 ---）。"""
    parts = re.split(r'(```[\w]*\n.*?```)', text, flags=re.DOTALL)
    for i, p in enumerate(parts):
        if i % 2 == 0:
            parts[i] = re.sub(r'^---\s*$', '', p, flags=re.MULTILINE)
    return ''.join(parts)

def strip_newpage(text):
    """移除小节间的 \\newpage，保留章（# 第N章）和附录（# 附录）之间的分页。
    
    规则：
    - 封面→目录→正文：保留（前3个）
    - 第N章之前：保留
    - 附录之前：保留
    - 附录内子节之前：保留
    - 其余小节之间（## / ###）：移除
    """
    parts = text.split('\\newpage')  # split on literal \\newpage in markdown
    result = []
    for i, part in enumerate(parts):
        result.append(part)
        if i == len(parts) - 1:
            break
        # 看 part 之后第一个非空行
        next_lines = part.strip().split('\n')
        after_last = next_lines[-1] if next_lines else ''
        # 分割点后的内容
        after = parts[i+1].strip()
        first_line = after.split('\n')[0] if after else ''
        # 需要保留的情况
        keep = False
        if first_line.startswith('# 第') or first_line.startswith('# 附录') or first_line.startswith('# 目录'):
            keep = True
        # 前一段以 附录X 结尾（附录内子节分页也保留）
        if after_last.strip().startswith('- **附录'):
            keep = True
        if keep:
            result.append('\\newpage')
    return ''.join(result)

def fix_images(text):
    """修复图片引用：去重括号、补路径、去冗余alt。"""
    # 1. 去重右括号：![alt](url)) → ![alt](url)
    text = re.sub(r"!\[([^\]]*)\]\(([^)]*)\)\)", r"![\1](\2)", text)
    # 2. 补 images/ 路径
    text = re.sub(r"!\[([^\]]*)\]\(images/", r"![\1](images/", text)
    # 3. 去冗余alt: 图片后紧跟 *图* 标题则alt置空(避免pandoc渲染为独立段落)
    text = re.sub(
        r'!\[([^\]]*)\]\(([^)]+)\)\s*\n\s*\n\s*(\*图)',
        r'![](\2)\n\n\3',
        text
    )
    return text

def count(text):
    lines = text.count('\n')
    chars = len(text)
    return lines, chars


def sync_images():
    OUTPUT_IMAGES = OUTPUT_DIR / "images"
    OUTPUT_IMAGES.mkdir(parents=True, exist_ok=True)
    copied = 0
    for png in sorted(IMAGES_DIR.glob("*.png")):
        dest = OUTPUT_IMAGES / png.name
        if png.resolve() != dest.resolve():
            shutil.copy2(png, dest)
            copied += 1
    return copied


def write_md(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)


# ── 主流程 ────────────────────────────────────

def build():
    print("=" * 60)
    print("  SCCS OS 文档拆分生成")
    print("=" * 60)

    print("\n📝 生成内容模块...")
    part1 = build_part1()
    part3 = build_part3()
    appendix = build_appendix()

    # ── 文档一：立项与设计手册 ──
    print("\n📘 组装《SCCS OS 立项与设计手册》...")
    doc1 = cover_design()
    doc1 += part1
    doc1 += appendix
    doc1 = fix_images(doc1)
    doc1 = strip_hlines(doc1)
    doc1 = strip_newpage(doc1)
    l1, c1 = count(doc1)

    f1 = OUTPUT_DIR / "SCCS OS 立项与设计手册.md"
    write_md(f1, doc1)
    print(f"   ✅ {f1.name}  —  {l1} 行 / {c1:,} 字符  (约 {max(c1 // 300 // 2, 50)} 页)")

    # ── 文档二：部署与操作手册 ──
    print("\n📗 组装《SCCS OS 部署与操作手册》...")
    doc2 = cover_ops()
    doc2 += part3
    doc2 += appendix
    doc2 = fix_images(doc2)
    doc2 = strip_hlines(doc2)
    doc2 = strip_newpage(doc2)
    l2, c2 = count(doc2)

    f2 = OUTPUT_DIR / "SCCS OS 部署与操作手册.md"
    write_md(f2, doc2)
    print(f"   ✅ {f2.name}  —  {l2} 行 / {c2:,} 字符  (约 {max(c2 // 300 // 2, 50)} 页)")

    # ── 图片同步 ──
    img_cnt = sync_images()
    print(f"\n🖼️  同步 {img_cnt} 张图片到 输出/images/")

    # ── 清理旧合辑 ──
    old = OUTPUT_DIR / "完整技术手册.md"
    if old.exists():
        old.unlink()
        print(f"🗑️  已移除旧版 完整技术手册.md")

    print(f"\n{'=' * 60}")
    print(f"  生成完成：2 份独立文档")
    print(f"  📘 SCCS OS 立项与设计手册.md")
    print(f"  📗 SCCS OS 部署与操作手册.md")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    build()
