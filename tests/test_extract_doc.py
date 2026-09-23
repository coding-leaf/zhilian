import tempfile
import unittest
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

from tooling.extract_doc import extract_docx_to_markdown


class TestExtractDoc(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp_dir.name)

    def tearDown(self):
        self.tmp_dir.cleanup()

    def _create_dummy_docx(
        self,
        filename: str,
        paragraphs: list[tuple[str, str]],
        tables: list[list[list[str]]] | None = None,
    ):
        docx_path = self.tmp_path / filename
        ns_w = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"

        # 构造 document.xml
        root = ET.Element(f"{{{ns_w}}}document")
        body = ET.SubElement(root, f"{{{ns_w}}}body")

        for text, style in paragraphs:
            p = ET.SubElement(body, f"{{{ns_w}}}p")
            if style:
                pPr = ET.SubElement(p, f"{{{ns_w}}}pPr")
                pStyle = ET.SubElement(pPr, f"{{{ns_w}}}pStyle")
                pStyle.set(f"{{{ns_w}}}val", style)
            r = ET.SubElement(p, f"{{{ns_w}}}r")
            t = ET.SubElement(r, f"{{{ns_w}}}t")
            t.text = text

        if tables:
            for tbl_data in tables:
                tbl = ET.SubElement(body, f"{{{ns_w}}}tbl")
                for row_data in tbl_data:
                    tr = ET.SubElement(tbl, f"{{{ns_w}}}tr")
                    for cell_text in row_data:
                        tc = ET.SubElement(tr, f"{{{ns_w}}}tc")
                        p = ET.SubElement(tc, f"{{{ns_w}}}p")
                        r = ET.SubElement(p, f"{{{ns_w}}}r")
                        t = ET.SubElement(r, f"{{{ns_w}}}t")
                        t.text = cell_text

        # 构造 styles.xml
        styles_root = ET.Element(f"{{{ns_w}}}styles")
        h1 = ET.SubElement(styles_root, f"{{{ns_w}}}style")
        h1.set(f"{{{ns_w}}}styleId", "Heading1")
        name1 = ET.SubElement(h1, f"{{{ns_w}}}name")
        name1.set(f"{{{ns_w}}}val", "heading 1")

        with zipfile.ZipFile(docx_path, "w") as z:
            z.writestr("word/document.xml", ET.tostring(root, encoding="utf-8"))
            z.writestr("word/styles.xml", ET.tostring(styles_root, encoding="utf-8"))

        return docx_path

    def test_extract_headings_and_tables(self):
        paras = [
            ("项目主标题", "Heading1"),
            ("这是正文描述第一段。", ""),
            ("1.1 二级小节", ""),
        ]
        tables = [
            [["表头A", "表头B"], ["数据1", "数据2"]],
        ]
        docx_file = self._create_dummy_docx("test_sample.docx", paras, tables)

        md = extract_docx_to_markdown(docx_file)
        self.assertIn("# 项目主标题", md)
        self.assertIn("这是正文描述第一段。", md)
        self.assertIn("## 1.1 二级小节", md)
        self.assertIn("| 表头A | 表头B |", md)
        self.assertIn("| 数据1 | 数据2 |", md)

    def test_non_existent_file(self):
        with self.assertRaises(FileNotFoundError):
            extract_docx_to_markdown(self.tmp_path / "not_found.docx")


if __name__ == "__main__":
    unittest.main()
