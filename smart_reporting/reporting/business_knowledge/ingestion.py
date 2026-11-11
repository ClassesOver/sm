"""复用Agno及其底层解析库，补充可核对的行、物理页和DOCX坐标。"""

import hashlib
from collections import Counter
from importlib.metadata import version
from io import BytesIO
from pathlib import PurePosixPath
from uuid import uuid4
from zipfile import BadZipFile, ZipFile

from agno.knowledge.document import Document as AgnoDocument
from agno.knowledge.reader.pdf_reader import PDFReader
from agno.knowledge.reader.text_reader import TextReader
from docx import Document
from docx.oxml import parse_xml
from docx.oxml.ns import qn
from pypdf import PdfReader

from ...workspace import normalize_workspace_path
from .models import DocumentLocator, LocatedFragment, ParsedDocument

MAX_DOCUMENT_BYTES = 20 * 1024 * 1024
MAX_DOCUMENT_CHARS = 2_000_000
MAX_DOCUMENT_PAGES = 200
_MEDIA_TYPES = {
    ".txt": "text/plain", ".md": "text/markdown", ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


class _LocatedPDFReader(PDFReader):
    """只替换Agno的页码猜测/清洗，沿用其reader接口与pypdf解析。"""

    def _pdf_reader_to_documents(
        self, doc_reader: PdfReader, doc_name: str,
        read_images: bool = False, use_uuid_for_id: bool = False,
    ) -> list[AgnoDocument]:
        if read_images:
            raise ValueError("located_reader_mode_unsupported")
        return [
            AgnoDocument(
                id=str(uuid4()) if use_uuid_for_id else f"{doc_name}_{number}", name=doc_name,
                content=page.extract_text(), meta_data={"page": number},
            )
            for number, page in enumerate(doc_reader.pages, start=1)
        ]


def inspect_upload(content: bytes, *, filename: str) -> str:
    """登记前检查封套；只接受文件名，解析始终使用内存流。"""
    normalize_workspace_path(filename, allow_root=False)
    if "/" in filename or "\\" in filename:
        raise ValueError("document_filename_invalid")
    extension = PurePosixPath(filename).suffix.lower()
    if extension not in _MEDIA_TYPES:
        raise ValueError("document_type_unsupported")
    if not isinstance(content, bytes) or not content or len(content) > MAX_DOCUMENT_BYTES:
        raise ValueError("document_size_invalid")
    if extension in (".txt", ".md"):
        if b"\x00" in content or content.startswith((b"%PDF-", b"PK\x03\x04")):
            raise ValueError("document_type_mismatch")
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError as error:
            raise ValueError("document_encoding_invalid") from error
        if len(text) > MAX_DOCUMENT_CHARS:
            raise ValueError("text_limit")
    elif extension == ".pdf" and not content.startswith(b"%PDF-"):
        raise ValueError("document_type_mismatch")
    elif extension == ".docx":
        try:
            with ZipFile(BytesIO(content)) as archive:
                names = set(archive.namelist())
                if not {"[Content_Types].xml", "word/document.xml"}.issubset(names):
                    raise ValueError("document_type_mismatch")
                # XML和关系开销单独有界，避免压缩文件在正文字符限制前膨胀。
                if sum(item.file_size for item in archive.infolist()) > MAX_DOCUMENT_BYTES * 4:
                    raise ValueError("document_expansion_limit")
        except BadZipFile as error:
            raise ValueError("document_type_mismatch") from error
    return _MEDIA_TYPES[extension]


def _text_fragments(content: bytes) -> tuple[LocatedFragment, ...]:
    documents = TextReader(chunk=False).read(BytesIO(content), name="business-document")
    if len(documents) != 1:
        raise ValueError("document_parse_failed")
    fragments = []
    for number, line in enumerate(documents[0].content.splitlines(), start=1):
        if line.strip():
            fragments.append(LocatedFragment(
                locator=DocumentLocator(kind="text_lines", line_start=number, line_end=number), text=line,
            ))
    return tuple(fragments)


def _docx_fragments(content: bytes) -> tuple[LocatedFragment, ...]:
    # Agno3.1.2 DocxReader只拼接paragraphs，未保存表格和定位；仍用其python-docx解析依赖。
    document = Document(BytesIO(content))
    fragments = []
    for number, paragraph in enumerate(document.paragraphs, start=1):
        if paragraph.text.strip():
            fragments.append(LocatedFragment(
                locator=DocumentLocator(kind="docx_paragraph", paragraph=number), text=paragraph.text,
            ))
    for table_number, table in enumerate(document.tables, start=1):
        for row_number, row in enumerate(table.rows, start=1):
            for column_number, cell in enumerate(row.cells, start=1):
                if cell.tables:
                    raise ValueError("nested_docx_tables_require_transcription")
                if cell.text.strip():
                    fragments.append(LocatedFragment(
                        locator=DocumentLocator(kind="docx_table_cell", table=table_number, row=row_number, column=column_number),
                        text=cell.text,
                    ))
    return tuple(fragments)


def _docx_transcription_issues(content: bytes, fragments: tuple[LocatedFragment, ...]) -> tuple[str, ...]:
    # 正文之外的制度条款、内容控件和修订文本不能被漏读后仍称完整解析。
    issues = []
    with ZipFile(BytesIO(content)) as archive:
        for name in archive.namelist():
            if name.startswith(("word/header", "word/footer", "word/footnotes", "word/endnotes", "word/comments")) and name.endswith(".xml"):
                part = parse_xml(archive.read(name))
                if any((node.text or "").strip() for node in part.iter(qn("w:t"))):
                    issues.append("docx_non_body_text_requires_transcription")
                    break
        body = parse_xml(archive.read("word/document.xml"))
        raw_text = "".join(node.text or "" for node in body.xpath(".//w:body//w:t | .//w:body//w:delText"))
        extracted_text = "".join(fragment.text for fragment in fragments)
        # 只比较非空白字符，reader插入的段落分隔不会产生假成功。
        if Counter(char for char in raw_text if not char.isspace()) != Counter(char for char in extracted_text if not char.isspace()):
            issues.append("docx_body_content_requires_transcription")
    return tuple(issues)


def parse_document(content: bytes, *, filename: str) -> ParsedDocument:
    media_type = inspect_upload(content, filename=filename)
    digest = hashlib.sha256(content).hexdigest()
    extension = PurePosixPath(filename).suffix.lower()
    issues: tuple[str, ...] = ()
    parser = f"agno-{version('agno')}/located-v1"
    if extension in (".txt", ".md"):
        fragments = _text_fragments(content)
    elif extension == ".docx":
        parser = f"python-docx-{version('python-docx')}/located-v1"
        fragments = _docx_fragments(content)
        issues = _docx_transcription_issues(content, fragments)
    else:
        pdf = PdfReader(BytesIO(content))
        if pdf.is_encrypted:
            raise ValueError("encrypted_document_unsupported")
        if len(pdf.pages) > MAX_DOCUMENT_PAGES:
            raise ValueError("page_limit")
        documents = _LocatedPDFReader(
            chunk=False, split_on_pages=True, sanitize_content=False,
            page_start_numbering_format="", page_end_numbering_format="",
        ).read(BytesIO(content), name="business-document")
        if len(documents) != len(pdf.pages):
            raise ValueError("document_parse_failed")
        fragments = tuple(
            LocatedFragment(locator=DocumentLocator(kind="pdf_page", page=number), text=document.content)
            for number, document in enumerate(documents, start=1) if document.content.strip()
        )
        # 物理页来自文件顺序；不能沿用reader根据印刷页号推断的meta_data.page。
        if len(fragments) != len(pdf.pages):
            issues = ("page_without_extractable_text",)
    return ParsedDocument(
        original_hash=digest, parser_identity=parser, media_type=media_type,
        status="needs_transcription" if issues else "parsed", fragments=fragments, issue_codes=issues,
    )
