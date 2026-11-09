from __future__ import annotations

import json
import subprocess
import tempfile
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

import pytest
from openpyxl import Workbook, load_workbook
from openpyxl.comments import Comment


def _run_cli(request: dict) -> str:
    root = Path(__file__).resolve().parents[1] / 'workbook_engine'
    cli = root / 'dist' / 'cli.mjs'
    with tempfile.TemporaryDirectory(prefix='notes-cli-') as directory:
        request_path = Path(directory) / 'request.json'
        request_path.write_text(json.dumps(request), encoding='utf-8')
        result = subprocess.run(['node', str(cli), str(request_path)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr or result.stdout
    return result.stdout


def _inspect(path: Path) -> dict:
    return json.loads(_run_cli({'kind': 'inspect', 'input': str(path)}))


def test_cli_reads_and_patches_openpyxl_legacy_notes_without_losing_other_authors_sheets_or_source(tmp_path):
    source_path = tmp_path / 'openpyxl-notes.xlsx'
    output_path = tmp_path / 'edited.xlsx'
    workbook = Workbook()
    notes = workbook.active
    notes.title = 'Notes'
    notes['A1'].comment = Comment('first & <literal>', 'Alice')
    notes['B2'].comment = Comment('remove this note', 'Bob')
    other = workbook.create_sheet('Other')
    other['C3'].comment = Comment('other sheet remains', 'Carol')
    workbook.save(source_path)
    original = source_path.read_bytes()

    model = _inspect(source_path)
    note_model = model['sheets'][0]['notes']
    assert note_model.get('readOnlyReason') is None
    assert note_model['notes'] == [
        {'row': 0, 'column': 0, 'author': 'Alice', 'text': 'first & <literal>'},
        {'row': 1, 'column': 1, 'author': 'Bob', 'text': 'remove this note'},
    ]
    operation = {'kind': 'patchSheetNotes', 'sheetName': 'Notes', 'sourceIdentity': note_model['sourceIdentity'], 'changes': [
        {'row': 0, 'column': 0, 'text': 'edited <literal> & text'},
        {'row': 1, 'column': 1, 'text': None},
    ]}
    _run_cli({'kind': 'patch', 'input': str(source_path), 'output': str(output_path), 'operations': [operation]})

    patched = output_path.read_bytes()
    readback = load_workbook(BytesIO(patched), data_only=False)
    assert readback['Notes']['A1'].comment.text == 'edited <literal> & text'
    assert readback['Notes']['A1'].comment.author == 'Alice'
    assert readback['Notes']['B2'].comment is None
    assert readback['Other']['C3'].comment.text == 'other sheet remains'
    assert readback['Other']['C3'].comment.author == 'Carol'
    assert source_path.read_bytes() == original
    before_zip, after_zip = ZipFile(BytesIO(original)), ZipFile(BytesIO(patched))
    assert 'xl/comments/comment1.xml' in before_zip.namelist()
    assert 'xl/comments/comment2.xml' in before_zip.namelist()
    assert before_zip.read('xl/worksheets/sheet2.xml') == after_zip.read('xl/worksheets/sheet2.xml')
    assert before_zip.read('xl/worksheets/_rels/sheet2.xml.rels') == after_zip.read('xl/worksheets/_rels/sheet2.xml.rels')

    second_model = _inspect(output_path)
    current = second_model['sheets'][0]['notes']
    final_path = tmp_path / 'last-note-deleted.xlsx'
    _run_cli({'kind': 'patch', 'input': str(output_path), 'output': str(final_path), 'operations': [{
        'kind': 'patchSheetNotes', 'sheetName': 'Notes', 'sourceIdentity': current['sourceIdentity'],
        'changes': [{'row': 0, 'column': 0, 'text': None}],
    }]})
    final = load_workbook(final_path)
    assert final['Notes']['A1'].comment is None
    assert final['Other']['C3'].comment.text == 'other sheet remains'
    final_zip = ZipFile(final_path)
    assert 'xl/comments/comment1.xml' not in final_zip.namelist()
    assert 'xl/comments/comment2.xml' in final_zip.namelist()
    assert source_path.read_bytes() == original


def _rewrite(source: bytes, output: Path, replacements: dict[str, bytes]) -> None:
    with ZipFile(BytesIO(source)) as before, ZipFile(output, 'w') as after:
        for name in before.namelist():
            after.writestr(name, replacements.get(name, before.read(name)))
        for name, value in replacements.items():
            if name not in before.namelist():
                after.writestr(name, value)


def _one_note(path: Path) -> bytes:
    workbook = Workbook()
    workbook.active['A1'].comment = Comment('original', 'Alice')
    workbook.save(path)
    return path.read_bytes()


@pytest.mark.parametrize('fault', ['image-vml', 'threaded', 'source-identity'])
def test_cli_notes_rejects_unsafe_sources_without_creating_output_or_mutating_original(tmp_path, fault):
    source_path = tmp_path / 'original.xlsx'
    original = _one_note(source_path)
    source_identity = _inspect(source_path)['sheets'][0]['notes']['sourceIdentity']
    replacements = {}
    with ZipFile(BytesIO(original)) as archive:
        if fault == 'image-vml':
            path = next(name for name in archive.namelist() if name.endswith('.vml'))
            rels = path.rsplit('/', 1)[0] + '/_rels/' + path.rsplit('/', 1)[1] + '.rels'
            replacements[rels] = b'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="image" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="../media/image.png"/></Relationships>'
        elif fault == 'threaded':
            rels = 'xl/worksheets/_rels/sheet1.xml.rels'
            replacements[rels] = archive.read(rels).replace(b'</Relationships>', b'<Relationship Id="thread" Type="http://schemas.microsoft.com/office/spreadsheetml/2018/threadedcomments" Target="../threadedComments/thread1.xml"/></Relationships>')
    unsafe_path = tmp_path / 'unsafe.xlsx'
    _rewrite(original, unsafe_path, replacements)
    unsafe = unsafe_path.read_bytes()
    if fault != 'source-identity':
        model = _inspect(unsafe_path)['sheets'][0]['notes']
        assert model['readOnlyReason']
        assert 'VML' in model['readOnlyReason'] if fault == 'image-vml' else '线程' in model['readOnlyReason']
    output = tmp_path / 'must-not-exist.xlsx'
    with pytest.raises(AssertionError, match='VML|线程|身份'):
        _run_cli({'kind': 'patch', 'input': str(unsafe_path), 'output': str(output), 'operations': [{
            'kind': 'patchSheetNotes', 'sheetName': 'Sheet',
            'sourceIdentity': 'f' * 64 if fault == 'source-identity' else source_identity,
            'changes': [{'row': 0, 'column': 0, 'text': None}],
        }]})
    assert not output.exists()
    assert unsafe_path.read_bytes() == unsafe
    assert source_path.read_bytes() == original


def test_cli_note_patch_preserves_simple_foreign_vml_and_last_delete_keeps_foreign_object(tmp_path):
    original_path = tmp_path / 'original.xlsx'
    original = _one_note(original_path)
    with ZipFile(BytesIO(original)) as archive:
        path = next(name for name in archive.namelist() if name.endswith('.vml'))
        foreign = b'<v:shape xmlns:v="urn:schemas-microsoft-com:vml" id="foreign-button"><v:textbox><div>untouched button</div></v:textbox></v:shape>'
        drawing = archive.read(path).replace(b'</xml>', foreign + b'</xml>')
    source_path = tmp_path / 'foreign.xlsx'
    _rewrite(original, source_path, {path: drawing})
    source_bytes = source_path.read_bytes()
    source = _inspect(source_path)['sheets'][0]['notes']
    assert not source.get('readOnlyReason')
    edited = tmp_path / 'edited-foreign.xlsx'
    _run_cli({'kind': 'patch', 'input': str(source_path), 'output': str(edited), 'operations': [{
        'kind': 'patchSheetNotes', 'sheetName': 'Sheet', 'sourceIdentity': source['sourceIdentity'],
        'changes': [{'row': 0, 'column': 0, 'text': 'new text'}],
    }]})
    assert load_workbook(edited).active['A1'].comment.author == 'Alice'
    with ZipFile(edited) as archive:
        assert archive.read(path) == drawing  # A text-only edit must not rewrite any VML.
    final = tmp_path / 'foreign-last-deleted.xlsx'
    latest = _inspect(edited)['sheets'][0]['notes']
    _run_cli({'kind': 'patch', 'input': str(edited), 'output': str(final), 'operations': [{
        'kind': 'patchSheetNotes', 'sheetName': 'Sheet', 'sourceIdentity': latest['sourceIdentity'],
        'changes': [{'row': 0, 'column': 0, 'text': None}],
    }]})
    assert load_workbook(final).active['A1'].comment is None
    with ZipFile(final) as archive:
        assert foreign in archive.read(path)
        assert b'legacyDrawing' in archive.read('xl/worksheets/sheet1.xml')
        assert b'vmlDrawing' in archive.read('xl/worksheets/_rels/sheet1.xml.rels')
        assert b'/xl/comments/comment1.xml' not in archive.read('[Content_Types].xml')
    assert source_path.read_bytes() == source_bytes
    assert original_path.read_bytes() == original
