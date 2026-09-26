"""Headless CLI 样例资料 fixture 生成与输入解析。

提供：
- `build_notes_txt()`：生成中文技术讲义 TXT（含章节结构与考点条目，足够切片与考点抽取）；
- `build_minimal_docx(paragraphs)`：用标准库 `zipfile` 构造真实最小 DOCX（ZIP 容器）；
- `resolve_smoke_input(file)`：解析 smoke 输入（显式文件或缺省内存生成的讲义）。

安全约束：仅使用标准库，不引入任何生产运行时依赖；绝不写入磁盘敏感信息。
"""

import io
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

from app.cli.errors import EXIT_ASSERTION, CliError

_CONTENT_TYPES_XML = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" \
ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" \
ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>
"""

_RELS_XML = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" \
Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" \
Target="word/document.xml"/>
</Relationships>
"""

_NOTES_TEXT = """数据结构与算法核心讲义

第一章 线性表

线性表是由 n 个数据元素构成的有限序列，是最基础的数据结构。顺序存储使用连续内存，
支持 O(1) 随机访问，但插入与删除平均需要 O(n) 的搬移成本。链式存储由结点通过指针
串联，插入与删除为 O(1)，但随机访问需要 O(n) 的遍历。

第二章 栈与队列

栈遵循后进先出（LIFO）原则，典型应用包括函数调用栈、括号匹配与表达式求值。
队列遵循先进先出（FIFO）原则，典型应用包括广度优先搜索、任务调度与缓冲队列。
循环队列通过取模运算复用存储空间，可有效避免假溢出问题。

第三章 树与二叉树

二叉树每个结点最多有两个子结点。前序遍历按“根、左、右”访问，中序遍历按“左、根、右”
访问，后序遍历按“左、右、根”访问。二叉搜索树的中序遍历结果有序，平均查找复杂度为
O(log n)。平衡二叉树通过旋转维持树高平衡，红黑树是一种常见的自平衡二叉搜索树。

第四章 图与最短路径

图由顶点集合与边集合构成，可分为有向图与无向图。深度优先搜索借助栈或递归实现，
广度优先搜索借助队列实现。Dijkstra 算法求解单源最短路径，适用于边权非负的图；
Floyd 算法可求解任意两点间最短路径，时间复杂度为 O(n^3)。

第五章 排序与查找

冒泡排序与插入排序平均时间复杂度为 O(n^2)，归并排序与快速排序平均为 O(n log n)。
二分查找要求序列有序，时间复杂度为 O(log n)。哈希表通过散列函数实现平均 O(1) 的
查找性能，但需要处理哈希冲突。

核心考点：时间复杂度分析、栈与队列的应用、二叉树的三种遍历、图的搜索与最短路径、
常见排序算法的稳定性与复杂度比较。
"""


def build_notes_txt() -> bytes:
    """生成中文技术讲义 TXT（UTF-8 字节流）。

    Returns:
        bytes: 包含章节结构与考点条目的中文讲义内容。
    """
    return _NOTES_TEXT.encode("utf-8")


def build_minimal_docx(paragraphs: list[str]) -> bytes:
    """构造真实最小 DOCX（ZIP 容器，标准库实现）。

    产出符合 OOXML 最小结构的三段成员：
    - `[Content_Types].xml`
    - `_rels/.rels`
    - `word/document.xml`（每个段落一个 `w:p`，运行内一个 `w:t`）

    Args:
        paragraphs: 段落文本列表（按顺序写入文档正文）。

    Returns:
        bytes: 真实可被 zipfile 解压读取的 DOCX 字节流。
    """
    body_parts: list[str] = []
    for paragraph in paragraphs:
        text = escape(paragraph)
        body_parts.append(f'<w:p><w:r><w:t xml:space="preserve">{text}</w:t></w:r></w:p>')
    document_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body>{''.join(body_parts)}</w:body></w:document>"
    )

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", _CONTENT_TYPES_XML)
        archive.writestr("_rels/.rels", _RELS_XML)
        archive.writestr("word/document.xml", document_xml)
    return buffer.getvalue()


def resolve_smoke_input(file: str | None) -> tuple[bytes, str]:
    """解析 smoke 输入资料：显式文件优先，缺省生成中文讲义。

    Args:
        file: 可选的资料文件路径；为 None 时使用内存生成的中文讲义。

    Returns:
        tuple[bytes, str]: (资料二进制内容, 用于推断格式的文件名)。

    Raises:
        CliError: 显式文件不存在或不可读（退出码 2）。
    """
    if file is None:
        return build_notes_txt(), "cli-smoke-notes.txt"

    path = Path(file)
    if not path.is_file():
        raise CliError(
            f"资料文件不存在或不是常规文件: {file}",
            exit_code=EXIT_ASSERTION,
            remediation="请传入有效的 --file 路径（支持 txt/md/pdf/docx/pptx/png/jpg）。",
        )
    try:
        return path.read_bytes(), path.name
    except OSError as exc:
        raise CliError(
            f"读取资料文件失败: {file}",
            exit_code=EXIT_ASSERTION,
            details={"error": str(exc)},
            remediation="请检查文件权限后重试。",
        ) from exc


__all__ = [
    "build_minimal_docx",
    "build_notes_txt",
    "resolve_smoke_input",
]
