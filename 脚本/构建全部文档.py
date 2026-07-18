#!/usr/bin/env python3
"""
SCCS OS 全量文档生成流水线
为所有 MD 文档生成 GB 标准 DOCX + PDF。
支持增量构建（跳过已生成且源文件未更新的文档）。

用法:
    python3 脚本/构建全部文档.py              # 构建全部
    python3 脚本/构建全部文档.py --force       # 强制重建全部
"""

import subprocess, sys, os, hashlib, json
from pathlib import Path

WORKSPACE = Path("/Users/smart/dev/hermesws/sccsos")
DOCS_DIR = WORKSPACE / "输出"
OUTPUT_DIR = WORKSPACE / "输出"
IMAGES_DIR = DOCS_DIR / "images"
SCRIPT_DIR = WORKSPACE / "脚本"
CSS_PATH = SCRIPT_DIR / "国标样式.css"
REFERENCE_DOCX = SCRIPT_DIR / "参考模板.docx"
NEWPAGE_FILTER = SCRIPT_DIR / "新页过滤.lua"
NEWPAGE_HTML_FILTER = SCRIPT_DIR / "新页过滤.html.lua"
POST_PROCESS_SCRIPT = SCRIPT_DIR / "后处理文档.py"
STATE_FILE = SCRIPT_DIR / "构建状态.json"

FORCE = "--force" in sys.argv

# 文档清单：所有需要生成 DOCX/PDF 的 MD 文档
DOCUMENTS = [
    {
        "name": "文档目录",
        "title": "SCCS OS 文档目录",
        "source": DOCS_DIR / "0-目录与索引.md",
        "workdir": DOCS_DIR,
    },
    {
        "name": "整体设计方案",
        "title": "SCCS OS 整体设计方案",
        "source": DOCS_DIR / "1-整体设计方案.md",
        "workdir": DOCS_DIR,
    },
    {
        "name": "企业级可行性方案",
        "title": "SCCS OS 企业级可行性方案",
        "source": DOCS_DIR / "2-企业级可行性方案.md",
        "workdir": DOCS_DIR,
    },
    {
        "name": "技术架构规格书",
        "title": "SCCS OS 技术架构规格书",
        "source": DOCS_DIR / "3-技术架构规格书.md",
        "workdir": DOCS_DIR,
    },
    {
        "name": "架构评审报告",
        "title": "SCCS OS 架构评审报告",
        "source": DOCS_DIR / "4-架构评审报告.md",
        "workdir": DOCS_DIR,
    },
    {
        "name": "第一阶段实施计划",
        "title": "SCCS OS 第一阶段实施计划",
        "source": DOCS_DIR / "5-第一阶段实施计划.md",
        "workdir": DOCS_DIR,
    },
    {
        "name": "部署指南",
        "title": "SCCS OS 部署指南",
        "source": DOCS_DIR / "6-部署指南.md",
        "workdir": DOCS_DIR,
    },
    {
        "name": "操作手册",
        "title": "SCCS OS 操作手册",
        "source": DOCS_DIR / "7-操作手册.md",
        "workdir": DOCS_DIR,
    },
    {
        "name": "文档与插图生成规范",
        "title": "文档与插图生成规范",
        "source": DOCS_DIR / "8-文档与插图生成规范.md",
        "workdir": DOCS_DIR,
    },
    {
        "name": "可行性技术方案文档",
        "title": "基于 Hermes Agent 构建 SCCS OS 可行性技术方案文档",
        "source": DOCS_DIR / "9-可行性技术方案文档.md",
        "workdir": DOCS_DIR,
    },
    # 合辑：由 合并完整手册.py 生成，此处只构建 DOCX/PDF
    {
        "name": "SCCS OS 立项与设计手册",
        "title": "SCCS OS 立项与设计手册",
        "source": OUTPUT_DIR / "SCCS OS 立项与设计手册.md",
        "workdir": OUTPUT_DIR,
    },
    {
        "name": "SCCS OS 部署与操作手册",
        "title": "SCCS OS 部署与操作手册",
        "source": OUTPUT_DIR / "SCCS OS 部署与操作手册.md",
        "workdir": OUTPUT_DIR,
    },
]


def file_hash(path):
    """快速文件哈希（前 4KB + 大小）。"""
    if not path.exists():
        return ""
    size = path.stat().st_size
    with open(path, "rb") as f:
        head = f.read(4096)
    return hashlib.md5(head).hexdigest()[:12] + f":{size}"


def load_state():
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def save_state(state):
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False))


def needs_rebuild(source, output_docx, output_pdf, state_key, state):
    if FORCE:
        return True
    source_h = file_hash(source)
    prev = state.get(state_key, {})
    if source_h != prev.get("source_hash"):
        return True
    if output_docx and not output_docx.exists():
        return True
    if output_pdf and not output_pdf.exists():
        return True
    if output_docx.exists() and output_pdf.exists():
        src_mtime = source.stat().st_mtime
        if output_docx.stat().st_mtime >= src_mtime and output_pdf.stat().st_mtime >= src_mtime:
            return False
    return True




def preprocess_md(content):
    """预处理Markdown：清除标题中的 \. 转义（如 1\. → 1.），清除段首 \."""
    import re
    # 标题中的 \. 转义：移除任意数量反斜杠（如 1\. 或 3\.2 → 1. / 3.2）
    content = re.sub(r'^(#+)\s*(\d+(?:\.\d+)*)\\*\.', r'\1 \2.', content, flags=re.MULTILINE)
    # 段首的 \. → .
    content = re.sub(r'^\.', '.', content, flags=re.MULTILINE)
    return content


def generate_docx(md_source, doc_name, workdir):
    """生成 DOCX：预处理 + pandoc + python-docx 后处理。"""
    raw_docx = OUTPUT_DIR / f"{doc_name}_原始.docx"
    final_docx = OUTPUT_DIR / f"{doc_name}.docx"
    preprocessed = OUTPUT_DIR / f"_{doc_name}_tmp.md"

    # 预处理：清除 \. 转义等
    md_content = open(md_source, encoding='utf-8').read()
    md_content = preprocess_md(md_content)
    preprocessed.write_text(md_content, encoding='utf-8')

    cmd = [
        "pandoc", str(preprocessed),
        "--from", "markdown+raw_tex",
        "--lua-filter=" + str(NEWPAGE_FILTER),
        "--reference-doc=" + str(REFERENCE_DOCX),
        "-o", str(raw_docx),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(workdir))
    if result.returncode != 0:
        print(f"  ❌ pandoc 失败: {result.stderr[:500]}")
        return False

    result = subprocess.run(
        [sys.executable, str(POST_PROCESS_SCRIPT), str(raw_docx), str(final_docx)],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print(f"  ❌ 后处理失败: {result.stderr[:500]}")
        return False

    if raw_docx.exists():
        raw_docx.unlink()

    print(f"  ✅ DOCX: {final_docx.name} ({final_docx.stat().st_size // 1024} KB)")
    return True


def generate_pdf(md_path, doc_name, workdir):
    """生成 PDF：MD → pandoc(html) → WeasyPrint，与 DOCX 同源。"""
    output_pdf = OUTPUT_DIR / f"{doc_name}.pdf"
    preprocessed = OUTPUT_DIR / f"_{doc_name}_tmp.md"

    # 与 DOCX 同源：先做同样的预处理
    md_content = open(md_path, encoding='utf-8').read()
    md_content = preprocess_md(md_content)
    preprocessed.write_text(md_content, encoding='utf-8')

    cmd = [
        "pandoc", str(preprocessed),
        "--from", "markdown+raw_tex",
        "--to", "html5",
        "--lua-filter=" + str(NEWPAGE_HTML_FILTER),
        "--standalone",
        "-c", str(CSS_PATH),
        "-o", str(output_pdf),
        "--pdf-engine=weasyprint",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(workdir))
    if result.returncode != 0:
        print(f"  ⚠️  WeasyPrint stderr: {result.stderr[:500]}")
        if not output_pdf.exists():
            print(f"  ❌ PDF 生成失败")
            return False

    if output_pdf.exists():
        print(f"  ✅ PDF:  {output_pdf.name} ({output_pdf.stat().st_size // 1024} KB)")
        return True
    else:
        print(f"  ❌ PDF 未生成")
        return False


def main():
    print("=" * 60)
    print("  SCCS OS 全量文档生成流水线")
    if FORCE:
        print("  [强制重建模式]")
    print("=" * 60)

    state = load_state()
    stats = {"built": 0, "skipped": 0, "failed": 0}

    for doc in DOCUMENTS:
        name = doc["name"]
        title = doc["title"]
        source = doc["source"]
        workdir = doc["workdir"]
        output_docx = OUTPUT_DIR / f"{name}.docx"
        output_pdf = OUTPUT_DIR / f"{name}.pdf"

        if not source.exists():
            print(f"\n  ⏭️  {title} — 源文件不存在: {source}")
            continue

        state_key = f"{name}"
        if not needs_rebuild(source, output_docx, output_pdf, state_key, state):
            print(f"\n  ⏭️  {title} — 已最新，跳过")
            stats["skipped"] += 1
            continue

        print(f"\n{'='*50}")
        print(f"  📄 {title} ({name})")
        print(f"  📁 {source.name}")
        print(f"{'='*50}")

        ok = True

        print(f"\n  📦 DOCX 生成...")
        docx_ok = generate_docx(source, name, workdir)
        if not docx_ok:
            stats["failed"] += 1
            ok = False

        print(f"  📄 PDF 生成...")
        pdf_ok = generate_pdf(source, name, workdir)
        if not pdf_ok:
            stats["failed"] += 1
            ok = False

        if ok:
            state[state_key] = {
                "source_hash": file_hash(source),
                "built_at": __import__("datetime").datetime.now().isoformat(),
            }
            stats["built"] += 1

    save_state(state)

    print(f"\n{'='*60}")
    print(f"  ✅ 文档生成完成")
    print(f"{'='*60}")
    print(f"\n📊 统计:")
    print(f"   📗 新建/更新: {stats['built']} 篇")
    print(f"   ⏭️  跳过(已最新): {stats['skipped']} 篇")
    print(f"   ❌ 失败: {stats['failed']} 篇")
    print(f"\n📁 输出目录: {OUTPUT_DIR}")
    print(f"\n📄 输出文件:")
    for f in sorted(OUTPUT_DIR.glob("*.docx")):
        if "_原始" not in f.name:
            print(f"   📦 {f.name:50s} {f.stat().st_size // 1024:>4d} KB")
    for f in sorted(OUTPUT_DIR.glob("*.pdf")):
        print(f"   📄 {f.name:50s} {f.stat().st_size // 1024:>4d} KB")


if __name__ == "__main__":
    main()
