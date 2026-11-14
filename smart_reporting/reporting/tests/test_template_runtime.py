"""模板渲染的实际身份和非阻断验收。"""

import hashlib
import io
from types import SimpleNamespace

import pytest

from smart_reporting.reporting.contract import ReportFileInput
from smart_reporting.reporting.delivery.artifacts_v1 import ReportArtifactManifest
from smart_reporting.reporting.workflow.checkpoint import FileIdentity


def identity(path, raw):
    return FileIdentity(path=path, size=len(raw), sha256=hashlib.sha256(raw).hexdigest())


class TemplateRuntime:
    def __init__(self, raw):
        self.files = {"inputs/template.docx": raw, "reports/frozen.md": "# 标题\n\n数据库收入100".encode()}
        self.template = ReportFileInput(filename="template.docx",
            **identity("inputs/template.docx", raw).model_dump())
        self.manifest = ReportArtifactManifest.model_validate({
            "reportId": "run", "revision": 2, "codingTaskKey": "task",
            "datasetSnapshotHash": "a" * 64, "reportBasisId": "basis",
            "markdown": {**identity("reports/frozen.md", self.files["reports/frozen.md"]).model_dump(), "mediaType": "text/markdown"},
            "citations": [{"citationId": "c1", "datasetId": "d1", "requirementId": "q1", "snapshotHash": "b" * 64}],
            "sections": ["income"], "sectionNumbers": ["1"],
            "headingNumbers": [{"level": 2, "number": "1", "title": "收入", "sectionCode": "income", "anchor": "report-section-income"}],
        })
        self.files["reports/manifest.json"] = self.manifest.model_dump_json(by_alias=True).encode()
        self.result = {"revision": 2, "markdownPath": "reports/frozen.md",
            "artifactManifest": identity("reports/manifest.json", self.files["reports/manifest.json"]).model_dump()}
        self.state = {"report_template_input": {"identity": self.template.model_dump(mode="json", by_alias=True)}}
        self.registered = [identity(path, content).model_dump() for path, content in self.files.items()]
        self.workspace_service = self
        self.state_repository = self

    def _scope(self, _context):
        return {"threadId": "thread"}

    def _state(self, _context):
        return self.state

    def _envelope(self, _context):
        return SimpleNamespace(template_input=self.template)

    async def get(self, run_id):
        assert run_id == "run"
        return SimpleNamespace(payload={"artifacts": self.registered})

    async def _read_identity_bytes(self, thread, file, **_kwargs):
        assert thread == "thread"
        raw = self.files[file.path]
        if identity(file.path, raw) != file:
            raise ValueError("identity changed")
        return raw

    async def _read_identity_model(self, thread, file, model):
        return model.model_validate_json(await self._read_identity_bytes(thread, file))

    async def _write_immutable_artifact(self, thread, path, content):
        assert thread == "thread"
        assert path not in self.files or self.files[path] == content
        self.files[path] = content
        return identity(path, content)

    async def afile_bytes(self, thread, path):
        assert thread == "thread"
        return self.files[path], "application/octet-stream"

    async def apath_exists(self, thread, path):
        assert thread == "thread"
        return path in self.files

    async def _apply_durable_command(self, _context, command):
        self.registered.append(command.payload["artifact"])


def docx_template():
    from docx import Document

    document = Document()
    document.add_paragraph("{{report_title}}")
    document.add_paragraph("{{report_content}}")
    stream = io.BytesIO()
    document.save(stream)
    return stream.getvalue()


@pytest.mark.anyio
async def test_requested_but_unreadable_template_never_silently_uses_default_renderer(monkeypatch):
    from smart_reporting.reporting.workflow.runtime import publication

    runtime = TemplateRuntime(docx_template())
    runtime.state = {"report_request_context": {"deliveryFormat": "docx"}}
    runtime._workflow_result = lambda _state: runtime.result
    monkeypatch.setattr(publication, "_frozen_outline", lambda _state: SimpleNamespace(title="标题"))
    result = await publication.RuntimePublicationMixin._render_and_validate(
        runtime, SimpleNamespace(run_id="run"))
    assert result["validation"]["ok"] is False
    assert result["validationIssues"][0]["code"] == "report_template_generation_failed"
    assert not result.get("wordPath")


@pytest.mark.anyio
async def test_initial_template_cannot_replace_durable_identity_through_session_and_request():
    from docx import Document

    from smart_reporting.reporting.workflow.runtime.template_delivery import (
        render_template_delivery,
    )

    runtime = TemplateRuntime(docx_template())
    frozen = runtime.template.model_dump(mode="json", by_alias=True)
    changed = Document()
    changed.add_paragraph("changed layout {{report_title}}")
    changed.add_paragraph("{{report_content}}")
    stream = io.BytesIO()
    changed.save(stream)
    raw = stream.getvalue()
    runtime.files["inputs/template.docx"] = raw
    runtime.template = ReportFileInput(filename="template.docx",
        **identity("inputs/template.docx", raw).model_dump())
    runtime.state["report_template_input"]["identity"] = runtime.template.model_dump(mode="json", by_alias=True)

    async def durable(_run_id):
        return SimpleNamespace(payload={"artifacts": runtime.registered,
            "requestMaterials": {"fileInputs": [], "templateInput": frozen}})

    runtime.get = durable
    result = await render_template_delivery(runtime, SimpleNamespace(run_id="run"), runtime.result,
        SimpleNamespace(title="冻结标题"), "docx")
    assert not result.get("wordPath")
    assert result["validation"]["ok"] is False


@pytest.mark.anyio
async def test_template_runtime_uses_frozen_markdown_and_keeps_template_original():
    from smart_reporting.reporting.workflow.runtime.template_delivery import (
        render_template_delivery,
    )

    original = docx_template()
    runtime = TemplateRuntime(original)
    result = await render_template_delivery(runtime, SimpleNamespace(run_id="run"), runtime.result,
        SimpleNamespace(title="冻结标题"), "docx")

    assert result["wordPath"].startswith("报表/智能分析/run/template/revision-2/")
    assert runtime.files["inputs/template.docx"] == original
    assert result["wordSha256"] == hashlib.sha256(runtime.files[result["wordPath"]]).hexdigest()
    assert result["validation"]["readback"]["ok"] is True
    assert result["validation"]["ok"] is False
    assert any(issue["code"] == "report_template_layout_unverified" for issue in result["validationIssues"])
    assert any(file["path"] == result["wordPath"] for file in runtime.registered)


@pytest.mark.anyio
async def test_template_runtime_registration_failure_preserves_readable_file():
    from smart_reporting.reporting.workflow.runtime.template_delivery import (
        render_template_delivery,
    )

    runtime = TemplateRuntime(docx_template())

    async def fail(_context, _command):
        raise RuntimeError("checkpoint unavailable")

    runtime._apply_durable_command = fail
    result = await render_template_delivery(runtime, SimpleNamespace(run_id="run"), runtime.result,
        SimpleNamespace(title="冻结标题"), "docx")

    assert result["wordPath"] in runtime.files
    assert result["wordSize"] == len(runtime.files[result["wordPath"]])
    assert any(issue["code"] == "report_template_checkpoint_failed" for issue in result["validationIssues"])


@pytest.mark.anyio
async def test_template_runtime_rejects_changed_template_identity_without_output():
    from smart_reporting.reporting.workflow.runtime.template_delivery import (
        render_template_delivery,
    )

    runtime = TemplateRuntime(docx_template())
    runtime.files["inputs/template.docx"] = b"changed"
    result = await render_template_delivery(runtime, SimpleNamespace(run_id="run"), runtime.result,
        SimpleNamespace(title="冻结标题"), "docx")

    assert "wordPath" not in result
    assert result["validation"]["ok"] is False
    assert result["validationIssues"][0]["code"] == "report_template_generation_failed"


async def render_template_fault_case(monkeypatch, failure_stage):
    """供 HTTP 签发故障回归复用：返回实际文件存储 runtime 和渲染结果。"""
    from smart_reporting.reporting.workflow.runtime import template_delivery

    runtime = TemplateRuntime(docx_template())
    if failure_stage == "checkpoint":
        async def fail(_context, _command):
            raise RuntimeError("checkpoint unavailable")

        runtime._apply_durable_command = fail
    elif failure_stage == "pptx_readback":
        from pptx import Presentation

        from smart_reporting.preferences.models import FormatPreferences, resolve_format_preferences
        from smart_reporting.preferences.runtime import REPORT_CONFIGURATION_SNAPSHOT_KEY

        deck = Presentation()
        slide = deck.slides.add_slide(deck.slide_layouts[6])
        slide.shapes.add_textbox(0, 0, 5000000, 3000000).text = '{{report_content}}'
        stream = io.BytesIO()
        deck.save(stream)
        runtime = TemplateRuntime(stream.getvalue())
        runtime.template = runtime.template.model_copy(update={'filename': 'template.pptx'})
        runtime.state['report_template_input']['identity'] = runtime.template.model_dump(mode='json', by_alias=True)
        runtime.state[REPORT_CONFIGURATION_SNAPSHOT_KEY] = {'generatedDate': '2026-11-12',
            'resolvedFormats': {'pptx': resolve_format_preferences(FormatPreferences(common={'signer': '冻结署名'}), 'pptx')}}

        def fail_parse(_file):
            raise ValueError('pptx signature readback unavailable')

        monkeypatch.setattr(template_delivery, '_parse', fail_parse)
    elif failure_stage in {"xlsx_readback", "xlsx_signature_measurement"}:
        from openpyxl import Workbook

        from smart_reporting.preferences.models import FormatPreferences, resolve_format_preferences
        from smart_reporting.preferences.runtime import REPORT_CONFIGURATION_SNAPSHOT_KEY

        book = Workbook()
        book.active['A1'] = '{{report_title}}'
        book.active['A2'] = '{{report_content}}'
        if failure_stage == 'xlsx_signature_measurement':
            from openpyxl.workbook.defined_name import DefinedName

            book.active['A3'] = '=SUM(1,2)'
            book.active['B5'] = 'Original author retained for review'
            book.active['B6'] = '2000-01-01'
            book.defined_names.add(DefinedName('report_signature', attr_text="'Sheet'!$B$5:$B$6"))
        stream = io.BytesIO()
        book.save(stream)
        runtime = TemplateRuntime(stream.getvalue())
        runtime.template = runtime.template.model_copy(update={'filename': 'template.xlsx'})
        runtime.state['report_template_input']['identity'] = runtime.template.model_dump(mode='json', by_alias=True)
        runtime.state[REPORT_CONFIGURATION_SNAPSHOT_KEY] = {'generatedDate': '2026-11-12',
            'resolvedFormats': {'xlsx': resolve_format_preferences(FormatPreferences(common={'signer': '冻结署名'}), 'xlsx')}}

        def fail_parse(_file):
            raise ValueError('xlsx signature readback unavailable')

        if failure_stage == 'xlsx_readback':
            monkeypatch.setattr(template_delivery, '_parse', fail_parse)
        else:
            from PIL import ImageFont

            def fail_font_read(*args, **kwargs):
                raise OSError('template signature font measurement unavailable')

            monkeypatch.setattr(ImageFont, 'truetype', fail_font_read)
    elif failure_stage == "signature_provenance":
        from smart_reporting.preferences.models import FormatPreferences, resolve_format_preferences
        from smart_reporting.preferences.runtime import REPORT_CONFIGURATION_SNAPSHOT_KEY

        runtime.state[REPORT_CONFIGURATION_SNAPSHOT_KEY] = {'generatedDate': '2026-11-12',
            'resolvedFormats': {'word': resolve_format_preferences(FormatPreferences(common={'signer': '冻结署名'}), 'word')}}

        def fail_binding(*args, **kwargs):
            raise ValueError('signature provenance unavailable')

        monkeypatch.setattr(template_delivery, '_template_signature_binding', fail_binding)
    elif failure_stage == "signature_readback":
        from smart_reporting.preferences.models import FormatPreferences, resolve_format_preferences
        from smart_reporting.preferences.runtime import REPORT_CONFIGURATION_SNAPSHOT_KEY

        runtime.state[REPORT_CONFIGURATION_SNAPSHOT_KEY] = {'generatedDate': '2026-11-12',
            'resolvedFormats': {'word': resolve_format_preferences(FormatPreferences(common={'signer': '冻结署名'}), 'word')}}
        import docx

        def fail_document(*args, **kwargs):
            raise ValueError('signature readback unavailable')

        original_parse = template_delivery._parse

        def parse_then_break_signature_readback(file):
            parsed = original_parse(file)
            monkeypatch.setattr(docx, 'Document', fail_document)
            return parsed

        monkeypatch.setattr(template_delivery, '_parse', parse_then_break_signature_readback)
    elif failure_stage == "readback":
        def fail_parse(_file):
            raise ValueError("readback unavailable")

        monkeypatch.setattr(template_delivery, "_parse", fail_parse)
    else:
        raise ValueError("未知模板故障点")
    result = await template_delivery.render_template_delivery(runtime, SimpleNamespace(run_id="run"),
        runtime.result, SimpleNamespace(title="冻结标题"), "xlsx" if failure_stage.startswith("xlsx_") else "pptx" if failure_stage == "pptx_readback" else "docx")
    return runtime, result


@pytest.mark.anyio
async def test_pptx_template_uses_durable_slide_outline_without_markdown_manifest():
    from pptx import Presentation

    from smart_reporting.reporting.tests.narrative_helpers import finding, graph
    from smart_reporting.reporting.tests.test_dynamic_checkpoint import _coverage
    from smart_reporting.reporting.workflow.checkpoint import (
        AnalysisDatasetSemantics,
        AnalysisEvidence,
        AnalysisEvidenceManifest,
        ReportingCheckpoint,
    )
    from smart_reporting.reporting.workflow.runtime.slides import build_slide_outline
    from smart_reporting.reporting.workflow.runtime.template_delivery import (
        render_template_delivery,
    )

    presentation = Presentation()
    slide = presentation.slides.add_slide(presentation.slide_layouts[6])
    slide.shapes.add_textbox(0, 0, 3000000, 1000000).text = "{{report_title}} {{report_content}}"
    stream = io.BytesIO()
    presentation.save(stream)
    raw = stream.getvalue()
    runtime = TemplateRuntime(docx_template())
    runtime.files["inputs/template.pptx"] = raw
    runtime.template = ReportFileInput(filename="template.pptx",
        **identity("inputs/template.pptx", raw).model_dump())
    runtime.state["report_template_input"]["identity"] = runtime.template.model_dump(mode="json", by_alias=True)
    evidence = AnalysisEvidenceManifest(
        evidence=(AnalysisEvidence(analysisId="analysis_001", summary="收入同比增长5%",
            datasetIds=("dataset-1",), evidenceFiles=(FileIdentity(path="facts.json", size=1, sha256="a" * 64),),
            citationIds=("citation_001",)),),
        datasetSemantics=(AnalysisDatasetSemantics(datasetId="dataset-1", rowGrain="month",
            duplicateResolution="not_applicable"),))
    findings = graph(finding())
    slide_outline = build_slide_outline(findings, evidence, title="冻结标题")
    runtime.files["reports/slides.json"] = slide_outline.model_dump_json(by_alias=True).encode()
    runtime.files["reports/findings.json"] = findings.model_dump_json(by_alias=True).encode()
    checkpoint = ReportingCheckpoint(revision=2, phase="analysis", outlineHash="a" * 64,
        profileCoverage=_coverage(), evidenceManifest=evidence, findingGraphHash="b" * 64,
        findingGraphFile=identity("reports/findings.json", runtime.files["reports/findings.json"]),
        slideOutlineFile=identity("reports/slides.json", runtime.files["reports/slides.json"]))

    async def get(_run_id):
        return SimpleNamespace(payload={"artifacts": [], "workflowCheckpoint": checkpoint.model_dump(mode="json", by_alias=True)})

    runtime.get = get
    from smart_reporting.preferences.models import FormatPreferences, resolve_format_preferences
    from smart_reporting.preferences.runtime import REPORT_CONFIGURATION_SNAPSHOT_KEY

    prefs = FormatPreferences(common={'signer': '幻灯片冻结署名', 'dateFormat': 'iso'})
    runtime.state[REPORT_CONFIGURATION_SNAPSHOT_KEY] = {'generatedDate': '2026-11-10', 'contentHash': 'f' * 64,
        'resolvedFormats': {'pptx': resolve_format_preferences(prefs, 'pptx')}}
    result = await render_template_delivery(runtime, SimpleNamespace(run_id="run"), {"revision": 2},
        SimpleNamespace(title="冻结标题"), "pptx")

    assert result["pptxPath"] in runtime.files
    assert result["validation"]["readback"]["ok"] is True
    rendered = Presentation(io.BytesIO(runtime.files[result["pptxPath"]]))
    assert "收入发生变化" in rendered.slides[0].shapes[0].text
    assert len(rendered.slides) == 2
    assert '幻灯片冻结署名' in rendered.slides[-1].shapes[0].text
    assert '2026-11-10' in rendered.slides[-1].shapes[0].text
    assert result['validation']['readback']['signature']['configurationHash'] == 'f' * 64


@pytest.mark.anyio
async def test_template_runtime_binds_frozen_word_signature_and_restores_identical_output():
    from docx import Document

    from smart_reporting.preferences.models import FormatPreferences, resolve_format_preferences
    from smart_reporting.preferences.runtime import REPORT_CONFIGURATION_SNAPSHOT_KEY
    from smart_reporting.reporting.workflow.runtime.template_delivery import (
        render_template_delivery,
    )

    document = Document()
    document.add_paragraph('{{report_title}}')
    document.add_paragraph('{{report_content}}')
    signature = document.add_paragraph('{{report_signature}}')
    signature.alignment = 0
    signature.runs[0].bold = True
    stream = io.BytesIO()
    document.save(stream)
    runtime = TemplateRuntime(stream.getvalue())
    prefs = FormatPreferences(common={'signer': '通用署名'}, word={'common': {'signer': '本次Word署名', 'dateFormat': 'slash'},
        'signature': {'description': '冻结复核说明'}})
    runtime.state[REPORT_CONFIGURATION_SNAPSHOT_KEY] = {'generatedDate': '2026-11-12', 'contentHash': 'c' * 64,
        'resolvedFormats': {'word': resolve_format_preferences(prefs, 'word')}}
    result = await render_template_delivery(runtime, SimpleNamespace(run_id='run'), runtime.result,
        SimpleNamespace(title='冻结标题'), 'docx')
    assert result['validation']['readback']['ok'] is True
    assert result['validation']['readback']['signature']['configurationHash'] == 'c' * 64
    output = Document(io.BytesIO(runtime.files[result['wordPath']]))
    assert [p.text for p in output.paragraphs][-3:] == ['本次Word署名', '2026/11/12', '冻结复核说明']
    assert output.paragraphs[-3].alignment == 0
    assert output.paragraphs[-3].runs[0].bold is True
    restored = await render_template_delivery(runtime, SimpleNamespace(run_id='run'), runtime.result,
        SimpleNamespace(title='冻结标题'), 'docx', restore_only=True)
    assert restored['wordSha256'] == result['wordSha256']
    assert restored['wordPath'] == result['wordPath']


@pytest.mark.anyio
async def test_xlsx_template_runtime_uses_frozen_signature_and_restores_same_file():
    from openpyxl import Workbook, load_workbook

    from smart_reporting.preferences.models import FormatPreferences, resolve_format_preferences
    from smart_reporting.preferences.runtime import REPORT_CONFIGURATION_SNAPSHOT_KEY
    from smart_reporting.reporting.workflow.runtime.template_delivery import (
        render_template_delivery,
    )

    book = Workbook()
    book.active['A1'] = '{{report_title}}'
    book.active['A2'] = '{{report_content}}'
    book.active['B3'] = '=SUM(1,2)'
    stream = io.BytesIO()
    book.save(stream)
    runtime = TemplateRuntime(stream.getvalue())
    runtime.template = runtime.template.model_copy(update={'filename': 'template.xlsx'})
    runtime.state['report_template_input']['identity'] = runtime.template.model_dump(mode='json', by_alias=True)
    prefs = FormatPreferences(common={'signer': '通用署名'}, xlsx={'common': {'signer': '工作簿冻结署名'}})
    runtime.state[REPORT_CONFIGURATION_SNAPSHOT_KEY] = {'generatedDate': '2026-11-10', 'contentHash': 'e' * 64,
        'resolvedFormats': {'xlsx': resolve_format_preferences(prefs, 'xlsx')}}
    result = await render_template_delivery(runtime, SimpleNamespace(run_id='run'), runtime.result,
        SimpleNamespace(title='冻结标题'), 'xlsx')
    assert result['validation']['readback']['ok'] is True
    output = load_workbook(io.BytesIO(runtime.files[result['xlsxPath']]))
    assert output['报告落款']['A2'].value == '工作簿冻结署名'
    assert output['报告落款']['A3'].value == '2026年11月10日'
    assert output.active['B3'].value == '=SUM(1,2)'
    restored = await render_template_delivery(runtime, SimpleNamespace(run_id='run'), runtime.result,
        SimpleNamespace(title='冻结标题'), 'xlsx', restore_only=True)
    assert restored['xlsxSha256'] == result['xlsxSha256']
    assert restored['xlsxPath'] == result['xlsxPath']
