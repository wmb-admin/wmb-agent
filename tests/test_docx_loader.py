from __future__ import annotations

import tempfile
import unittest
import zipfile
from pathlib import Path

from beauty_saas_agent.docx_loader import load_docx_text


class DocxLoaderTestCase(unittest.TestCase):
    def test_load_docx_text_reads_plain_paragraphs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            docx_path = Path(temp_dir) / "sample.docx"
            document_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>
    <w:p><w:r><w:t>第一段</w:t></w:r></w:p>
    <w:p><w:r><w:t>第二段</w:t></w:r></w:p>
  </w:body>
</w:document>
"""
            with zipfile.ZipFile(docx_path, "w") as archive:
                archive.writestr("word/document.xml", document_xml)

            self.assertEqual(load_docx_text(docx_path), "第一段\n\n第二段")


if __name__ == "__main__":
    unittest.main()
