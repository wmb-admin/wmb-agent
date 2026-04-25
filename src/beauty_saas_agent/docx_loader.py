from __future__ import annotations

import io
import zipfile
from pathlib import Path
from typing import List
from xml.etree import ElementTree as ET


WORD_NAMESPACE = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}


def _paragraph_text(paragraph: ET.Element) -> str:
    """提取一个段落节点的纯文本。"""
    chunks: List[str] = []
    for node in paragraph.findall(".//w:t", WORD_NAMESPACE):
        if node.text:
            chunks.append(node.text)
    return "".join(chunks).strip()


def load_docx_text(path: str | Path) -> str:
    """读取 docx 文本内容，按段落拼接。"""
    document_path = Path(path)
    with zipfile.ZipFile(document_path) as archive:
        xml_bytes = archive.read("word/document.xml")

    root = ET.parse(io.BytesIO(xml_bytes)).getroot()
    paragraphs: List[str] = []
    for paragraph in root.findall(".//w:p", WORD_NAMESPACE):
        text = _paragraph_text(paragraph)
        if text:
            paragraphs.append(text)
    return "\n\n".join(paragraphs).strip()
