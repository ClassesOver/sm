"""功能区操作经真实授权、文件引擎、签发和 HTTP 下载闭环；仓储使用现有替身。"""

import hashlib
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from openpyxl import Workbook, load_workbook
from pptx import Presentation
from pptx.enum.text import PP_ALIGN
from pptx.util import Inches
from pypdf import PdfReader, PdfWriter

from smart_reporting.app import require_workspace_capability
from smart_reporting.report_editor.native import NativeEditorService
from smart_reporting.report_editor.native_api import create_native_editor_router
from smart_reporting.report_editor.native_import import NativeImportService
from smart_reporting.report_editor.native_import_api import create_native_import_router
from smart_reporting.reporting.tests.test_native_editor_api import Repository as SourceRepository
from smart_reporting.reporting.tests.test_native_publication_nonblocking import (
    Repository as PublicationRepository,
)
from smart_reporting.reporting.tests.test_native_publication_nonblocking import (
    create_publication,
)
from smart_reporting.tests.test_reporting_request_identity import SECRET, _capability


class Repository(SourceRepository, PublicationRepository):
    def __init__(self):
        SourceRepository.__init__(self)
        PublicationRepository.__init__(self)

    async def create_from_source(self, source, **kwargs):
        document = await SourceRepository.create_from_source(self, source, **kwargs)
        key = (document.document_id, 1)
        revision = self.revisions[key]
        self.revisions[key] = revision.model_copy(update={
            "context": revision.context.model_copy(update={"origin": source.origin}),
        })
        return document

    async def complete_revision(self, reservation, **kwargs):
        result = await PublicationRepository.complete_revision(self, reservation, **kwargs)
        self.revisions[(result.document_id, result.revision)] = result
        return result


@pytest.fixture
def anyio_backend():
    return "asyncio"


def source_file(format):
    stream = BytesIO()
    if format == "docx":
        document = Document()
        document.add_paragraph("功能区原始正文")
        document.add_paragraph("保留段落")
        table = document.add_table(rows=2, cols=2)
        table.autofit = False
        table._tbl.tblPr.find(qn("w:tblW")).set(qn("w:type"), "dxa")
        table._tbl.tblPr.find(qn("w:tblW")).set(qn("w:w"), "9000")
        for node in table._tbl.tblGrid:
            node.set(qn("w:w"), "4500")
        for ri, row in enumerate(table.rows):
            for ci, cell in enumerate(row.cells):
                cell.text = f"R{ri}C{ci}"
                cell._tc.get_or_add_tcPr().find(qn("w:tcW")).set(qn("w:w"), "4500")
                cell.paragraphs[0]._p.set(qn("w:rsidR"), f"{ri + 1:04X}{ci + 1:04X}")
                cell.paragraphs[0]._p.get_or_add_pPr().append(OxmlElement("w:mirrorIndents"))
        document.save(stream)
    elif format == "pdf":
        writer = PdfWriter()
        writer.add_blank_page(width=612, height=792)
        writer.add_blank_page(width=500, height=400)
        writer.write(stream)
    elif format == "xlsx":
        workbook = Workbook()
        workbook.active["A1"] = 1
        workbook.active["A1"].number_format = "0.000"
        workbook.active["A2"] = 2
        workbook.active["B1"] = "=SUM(A1:A2)"
        workbook.active.merge_cells("D1:E1")
        workbook.save(stream)
    else:
        presentation = Presentation()
        slide = presentation.slides.add_slide(presentation.slide_layouts[6])
        slide.shapes.add_textbox(Inches(1), Inches(1), Inches(3), Inches(1)).text = "功能区原始正文"
        presentation.save(stream)
    return stream.getvalue()


def ribbon_operations(format, model):
    if format == "docx":
        paragraph = model["blocks"][0]
        anchor = {key: paragraph[key] for key in ("blockId", "expectedObjectSha256")}
        section = model["sections"][-1]
        table = next(block for block in model["blocks"] if block["type"] == "table")
        return [
            {"kind": "insertTableColumn", "blockId": table["blockId"], "expectedObjectSha256": table["expectedObjectSha256"], "index": 1},
            {"kind": "replaceParagraph", **anchor, "text": "功能区保存正文"},
            {"kind": "setParagraphSpacing", **anchor, "spaceBefore": 240, "spaceAfter": 240, "lineSpacing": 2},
            {"kind": "setSectionLayout", "sectionId": section["sectionId"],
             "expectedSectionSha256": section["expectedSectionSha256"],
             "values": {"orientation": "landscape", "pageWidth": 16838, "pageHeight": 11906, "columns": 2}},
            {"kind": "setParagraphLink", **anchor, "from": 0, "to": 3,
             "href": "https://example.test/report?source=word&mode=review"},
        ]
    if format == "pdf":
        return [
            {"kind": "cropPage", "pageId": model["pages"][0]["pageId"], "rect": [18, 24, 590, 760]},
            {"kind": "rotatePage", "pageId": model["pages"][0]["pageId"], "delta": 90},
            {"kind": "reorderPages", "pageIds": [page["pageId"] for page in reversed(model["pages"])]},
        ]
    if format == "xlsx":
        return [{"kind": "applyCellEdits", "edits": [
            {"sheetName": "Sheet", "row": 1, "column": 0, "writeValue": True, "cell": {"value": 3}},
            {"sheetName": "Sheet", "row": 0, "column": 2, "writeValue": True,
             "cell": {"value": None, "formula": "=SUM(A1:A2)"}},
        ]}]
    element = next(element for element in model["slides"][0]["elements"] if element["editable"] and element["text"])
    return [{"kind": "editSlides", "edits": [{"slideIndex": 0, "elementId": element["id"], "text": "功能区保存正文"}],
             "slideSize": {"cx": 9000000, "cy": 7200000},
             "paragraphFormatting": [
                 {"slideIndex": 0, "elementId": element["id"], "align": "right",
                  "lineSpacingPct": 200, "spaceBeforePt": 12.5, "spaceAfterPt": 0,
                  "bullet": "number", "numType": "romanLcPeriod", "startAt": 3,
                  "bulletHangEmu": 171450, "bulletSizePct": 125, "bulletColor": "#0F9ED5", "rtl": False},
                 {"slideIndex": 0, "elementId": element["id"], "indentDelta": 1},
                 {"slideIndex": 0, "elementId": element["id"], "indentDelta": -1},
             ]}]


def assert_file_readback(format, content):
    stream = BytesIO(content)
    if format == "docx":
        document = Document(stream)
        assert [paragraph.text for paragraph in document.paragraphs] == ["功能区保存正文", "保留段落"]
        table = document.tables[0]
        assert [[cell.text for cell in row.cells] for row in table.rows] == [["R0C0", "", "R0C1"], ["R1C0", "", "R1C1"]]
        assert [node.get(qn("w:w")) for node in table._tbl.tblGrid] == ["4500", "2250", "2250"]
        for ri, row in enumerate(table.rows):
            for ci in [0, 2]:
                para = row.cells[ci].paragraphs[0]._p
                assert para.get(qn("w:rsidR")) == f"{ri + 1:04X}{1 if ci == 0 else 2:04X}"
                assert para.find(qn("w:pPr")).find(qn("w:mirrorIndents")) is not None
        links = document.paragraphs[0]._p.findall(qn("w:hyperlink"))
        assert len(links) == 1
        assert "".join(node.text or "" for node in links[0].iter(qn("w:t"))) == "功能区"
        relationship = document.part.rels[links[0].get(qn("r:id"))]
        assert relationship.is_external
        assert relationship.target_ref == "https://example.test/report?source=word&mode=review"
        paragraph = document.paragraphs[0].paragraph_format
        assert paragraph.space_before.twips == paragraph.space_after.twips == 240
        assert paragraph.line_spacing == 2
        section = document.sections[-1]
        assert (section.page_width.twips, section.page_height.twips) == (16838, 11906)
        assert int(section._sectPr.find(qn("w:cols")).get(qn("w:num"))) == 2
    elif format == "pdf":
        reader = PdfReader(stream)
        assert [(float(page.mediabox.width), float(page.mediabox.height)) for page in reader.pages] == [(500, 400), (612, 792)]
        assert list(reader.pages[1].cropbox) == [18, 24, 590, 760]
        assert reader.pages[1].get("/Rotate") == 90
    elif format == "xlsx":
        sheet = load_workbook(stream).active
        assert sheet["A2"].value == 3
        assert sheet["B1"].value == sheet["C1"].value == "=SUM(A1:A2)"
        assert sheet["A1"].number_format == "0.000"
        assert "D1:E1" in sheet.merged_cells
    else:
        deck = Presentation(stream)
        assert (deck.slide_width, deck.slide_height) == (9000000, 7200000)
        shape = deck.slides[0].shapes[0]
        assert shape.text == "功能区保存正文"
        assert (shape.left, shape.top, shape.width, shape.height) == (900000, 960000, 2700000, 960000)
        paragraph = shape.text_frame.paragraphs[0]
        assert paragraph.alignment == PP_ALIGN.RIGHT
        assert paragraph.line_spacing == 2.0
        assert paragraph.space_before.pt == 12.5
        assert paragraph.space_after.pt == 0
        props = paragraph._p.get_or_add_pPr()
        assert props.get("rtl") == "0"
        assert int(props.get("lvl", "0")) == 0
        assert props.get("marL") == "171450" and props.get("indent") == "-171450"
        auto = props.find(qn("a:buAutoNum"))
        assert auto is not None and auto.get("type") == "romanLcPeriod" and auto.get("startAt") == "3"
        assert props.find(qn("a:buSzPct")).get("val") == "125000"
        assert props.find(qn("a:buClr")).find(qn("a:srgbClr")).get("val") == "0F9ED5"


@pytest.mark.anyio
@pytest.mark.parametrize("format", ["docx", "pdf", "xlsx", "pptx"])
async def test_ribbon_operations_use_real_http_save_download_and_reopen(tmp_path, format):
    publication, _, downloads = await create_publication(tmp_path)
    publication.repository = Repository()
    publication.validator = AsyncMock(side_effect=RuntimeError("ribbon_acceptance_review"))
    editor = NativeEditorService(publication.workspace, publication.repository, publication.editor_grants,
                                 report_editor=None, docx_enabled=True, pdf_enabled=True,
                                 office_enabled=True, publication=publication)
    importer = NativeImportService(publication.workspace, publication.repository, publication.editor_grants)
    app = FastAPI()
    app.state.agentos_context = SimpleNamespace(settings=SimpleNamespace(workspace_hmac_secret=SECRET))
    app.middleware("http")(require_workspace_capability)
    app.include_router(create_native_import_router(importer, enabled=True))
    app.include_router(create_native_editor_router(publication.editor_grants, editor=editor,
                                                  download_service=downloads, cookie_secure=False))
    original = source_file(format)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        uploaded = await client.post("/reports/v1/native/import",
                                     headers={"X-Workspace-Thread": "thread-1", "X-Workspace-Capability": _capability()},
                                     data={"requestId": f"ribbon-import-{format}"},
                                     files={"file": (f"source.{format}", original)})
        assert uploaded.status_code == 200, uploaded.text
        opened = await client.get(uploaded.json()["editor"]["url"], follow_redirects=True)
        assert opened.status_code == 200, opened.text
        base = opened.url.path + "/api"
        response = await client.get(base + "/context")
        assert response.status_code == 200, response.text
        context = response.json()
        assert context["editingEnabled"] and context["context"]["format"] == format
        assert context["context"]["origin"] == "upload"
        headers = {"Origin": "http://test", "X-CSRF-Token": context["csrfToken"]}
        payload = {"expectedSha256": hashlib.sha256(original).hexdigest(), "operations": []}
        preview = await client.post(base + "/preview", headers=headers, json=payload)
        assert preview.status_code == 200, preview.text
        payload["operations"] = ribbon_operations(format, preview.json()["model"])
        payload["requestId"] = f"ribbon-save-{format}"
        saved = await client.post(base + "/save", headers=headers, json=payload)
        assert saved.status_code == 200, saved.text
        result = saved.json()
        assert result["revisionRegistered"] and result["revision"] == 2 and result["parentRevision"] == 1
        assert not result["validation"]["ok"]
        assert any(issue["code"] == "native_validation_failed" for issue in result["validation"]["issues"])
        artifact = result["artifacts"]["word" if format == "docx" else format]
        downloaded = await client.get(artifact["downloadUrl"])
        assert downloaded.status_code == 200, downloaded.text
        assert hashlib.sha256(downloaded.content).hexdigest() == artifact["sha256"]
        assert_file_readback(format, downloaded.content)
        retried = await client.post(base + "/save", headers=headers, json=payload)
        assert retried.status_code == 200, retried.text
        assert retried.json()["revision"] == 2
        assert retried.json()["artifacts"]["word" if format == "docx" else format]["sha256"] == artifact["sha256"]
        assert (await client.get(base + "/file")).content == original
        reopened = await client.get(result["editor"]["openUrl"], follow_redirects=True)
        assert reopened.status_code == 200, reopened.text
        assert (await client.get(reopened.url.path + "/api/file")).content == downloaded.content
