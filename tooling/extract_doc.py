#!/usr/bin/env python3
"""Zero-dependency DOCX to Markdown Extractor.

Extracts text, headings, lists, and tables from .docx files using only Python's
standard library (zipfile and xml.etree.ElementTree).
"""

from __future__ import annotations

import argparse
import re
import sys
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

NS = {
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
}


def _get_styles(z: zipfile.ZipFile) -> Dict[str, Dict[str, Any]]:
    styles_map: Dict[str, Dict[str, Any]] = {}
    if "word/styles.xml" not in z.namelist():
        return styles_map

    try:
        tree = ET.fromstring(z.read("word/styles.xml"))
        for style in tree.findall("w:style", NS):
            style_id = style.attrib.get(f"{{{NS['w']}}}styleId", "")
            name_el = style.find("w:name", NS)
            name = name_el.attrib.get(f"{{{NS['w']}}}val", "").lower() if name_el is not None else ""

            level = 0
            if "heading 1" in name or name == "title":
                level = 1
            elif "heading 2" in name or name == "subtitle":
                level = 2
            elif "heading 3" in name:
                level = 3
            elif "heading 4" in name:
                level = 4
            elif "heading 5" in name:
                level = 5
            elif "heading 6" in name:
                level = 6

            styles_map[style_id] = {
                "name": name,
                "heading_level": level,
                "is_bullet": "bullet" in name,
                "is_number": "number" in name or "list" in name,
                "is_toc": "toc" in name,
            }
    except Exception:
        pass
    return styles_map


def _extract_paragraph_text(p: ET.Element) -> str:
    text_parts = []
    for node in p.iter(f"{{{NS['w']}}}t"):
        if node.text:
            text_parts.append(node.text)
    return "".join(text_parts).strip()


def _render_table(tbl: ET.Element) -> List[str]:
    rows: List[List[str]] = []
    for tr in tbl.findall("w:tr", NS):
        row_cells: List[str] = []
        for tc in tr.findall("w:tc", NS):
            cell_texts = []
            for p in tc.findall("w:p", NS):
                txt = _extract_paragraph_text(p)
                if txt:
                    cell_texts.append(txt)
            cell_content = " ".join(cell_texts).replace("|", "\\|").replace("\n", " ").strip()
            row_cells.append(cell_content)
        if any(c for c in row_cells):
            rows.append(row_cells)

    if not rows:
        return []

    # 规整列数
    max_cols = max(len(r) for r in rows)
    normalized_rows = [r + [""] * (max_cols - len(r)) for r in rows]

    lines: List[str] = []
    # Header
    header = normalized_rows[0]
    lines.append("| " + " | ".join(header) + " |")
    lines.append("| " + " | ".join(["---"] * max_cols) + " |")

    # Data
    for r in normalized_rows[1:]:
        lines.append("| " + " | ".join(r) + " |")

    lines.append("")
    return lines


def extract_docx_to_markdown(docx_path: Path | str, skip_toc: bool = True) -> str:
    docx_file = Path(docx_path)
    if not docx_file.exists():
        raise FileNotFoundError(f"文件未找到: {docx_file}")

    with zipfile.ZipFile(docx_file) as z:
        if "word/document.xml" not in z.namelist():
            raise ValueError(f"不是合法的 DOCX 文档 (缺少 word/document.xml): {docx_file}")

        styles = _get_styles(z)
        tree = ET.fromstring(z.read("word/document.xml"))
        body = tree.find("w:body", NS)
        if body is None:
            return ""

        output_lines: List[str] = []

        for child in body:
            tag = child.tag.split("}")[-1]
            if tag == "p":
                text = _extract_paragraph_text(child)
                if not text:
                    continue

                # 检查段落样式
                pPr = child.find("w:pPr", NS)
                style_val = ""
                if pPr is not None:
                    pStyle = pPr.find("w:pStyle", NS)
                    if pStyle is not None:
                        style_val = pStyle.attrib.get(f"{{{NS['w']}}}val", "")

                style_info = styles.get(style_val, {})
                heading_level = style_info.get("heading_level", 0)

                # 兜底识别正文前缀标题 (如: 1 引言, 2.1 结构, 3.2.1 流程, 一、总体设计)
                if heading_level == 0:
                    if re.match(r"^(\d+(\.\d+)*|[第0-9一二三四五六七八九十]+)[、\s]+[^\s]+", text) and len(text) < 60:
                        if re.match(r"^\d+\s+[^\s]+", text):
                            heading_level = 1
                        elif re.match(r"^\d+\.\d+\s+[^\s]+", text):
                            heading_level = 2
                        elif re.match(r"^\d+\.\d+\.\d+\s+[^\s]+", text):
                            heading_level = 3

                # 跳过 TOC
                if skip_toc and style_info.get("is_toc", False):
                    continue

                if heading_level > 0:
                    hashes = "#" * heading_level
                    output_lines.append(f"\n{hashes} {text}\n")
                elif style_info.get("is_bullet", False):
                    output_lines.append(f"* {text}")
                elif style_info.get("is_number", False):
                    output_lines.append(f"1. {text}")
                else:
                    output_lines.append(text)

            elif tag == "tbl":
                tbl_lines = _render_table(child)
                if tbl_lines:
                    output_lines.extend(tbl_lines)

    # 规范化连续多行空行
    raw_md = "\n".join(output_lines)
    clean_md = re.sub(r"\n{3,}", "\n\n", raw_md).strip()
    return clean_md + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="零依赖 DOCX 转 Markdown 结构化提取工具")
    parser.add_argument("file", nargs="?", help="指定待转换的 .docx 文件")
    parser.add_argument("-o", "--output", help="输出 Markdown 文件路径")
    parser.add_argument("--all", action="store_true", help="提取当前目录下所有 .docx 文件")
    parser.add_argument("-d", "--output-dir", default="docs/specs_extracted", help="批量输出目录 (默认 docs/specs_extracted)")

    args = parser.parse_args()

    if args.all:
        output_dir = Path(args.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        docx_files = list(Path(".").glob("*.docx"))
        if not docx_files:
            print("未在当前目录下找到 .docx 文件。")
            return 0

        print(f"📦 开始批量提取 {len(docx_files)} 个文档至 {output_dir}/ ...")
        for f in docx_files:
            out_file = output_dir / f"{f.stem}.md"
            content = extract_docx_to_markdown(f)
            out_file.write_text(content, encoding="utf-8")
            print(f"  ✅ {f.name} -> {out_file.name} ({len(content.splitlines())} 行)")
        return 0

    if not args.file:
        parser.print_help()
        return 1

    in_file = Path(args.file)
    try:
        md_text = extract_docx_to_markdown(in_file)
        if args.output:
            out_path = Path(args.output)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(md_text, encoding="utf-8")
            print(f"✅ 成功提取至: {out_path} ({len(md_text.splitlines())} 行)")
        else:
            print(md_text)
        return 0
    except Exception as e:
        print(f"❌ 提取失败: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
