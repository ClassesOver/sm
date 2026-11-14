"""真实 Python→CLI→OOXML 图片批注回读，ZIP/XML 为独立验收方。"""
import base64
import hashlib
import json
import subprocess
from io import BytesIO
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from openpyxl import Workbook, load_workbook
from PIL import Image


S = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
V = 'urn:schemas-microsoft-com:vml'
O = 'urn:schemas-microsoft-com:office:office'


def test_note_picture_native_roundtrip_preserves_text_other_notes_and_unknown_parts(tmp_path, monkeypatch):
    from smart_reporting.report_editor.native_office import patch_office
    from smart_reporting.reporting.delivery import xlsx

    source_engine = Path(xlsx.__file__).resolve().parents[1] / 'workbook_engine'
    # 只创建源码入口符号链接，避免共享 dist 的部署 bundle 覆盖。
    engine = tmp_path / 'engine'
    engine.mkdir()
    for name in ('bridge', 'packages', 'node_modules', 'package.json', 'tsconfig.json', 'tsconfig.base.json'):
        (engine / name).symlink_to(source_engine / name)
    monkeypatch.setenv('AGENT_REPORTING_WORKBOOK_ENGINE_DIR', str(engine))
    reader = tmp_path / 'picture-snapshot.mts'
    reader.write_text(
        "import {readFileSync} from 'node:fs';"
        f"import {{readNotePictures}} from {json.dumps((source_engine / 'packages/xlsx-engine/src/note-pictures.ts').as_uri())};"
        "const snapshot=await readNotePictures(new Uint8Array(readFileSync(process.argv[2])));"
        "console.log(JSON.stringify({sheets:snapshot.sheets,pictures:snapshot.pictures.map(({bytes,...rest})=>rest),issues:snapshot.issues}));"
    )

    def snapshot(content):
        path = tmp_path / 'snapshot.xlsx'
        path.write_bytes(content)
        result = subprocess.run([str(engine / 'node_modules/.bin/tsx'), str(reader), str(path)],
                                check=True, capture_output=True, text=True, cwd=engine)
        return json.loads(result.stdout.strip().splitlines()[-1])

    book = Workbook()
    book.active.title = 'Report'
    book.active['A1'] = '保留原始正文'
    book.create_sheet('Other')['B2'] = '=2+3'
    output = BytesIO()
    book.save(output)
    original = output.getvalue()
    output = BytesIO()
    with ZipFile(BytesIO(original)) as old, ZipFile(output, 'w') as new:
        for item in old.infolist():
            new.writestr(item, old.read(item.filename))
        new.writestr('customXml/keep.bin', b'foreign\x00\xff')
    original = patch_office('xlsx', output.getvalue(), [{
        'kind': 'applySheetNotes', 'sheetName': 'Report', 'notes': [
            {'row': 0, 'column': 0, 'author': '作者甲', 'text': '保留批注文字'},
            {'row': 2, 'column': 2, 'author': '作者乙', 'text': '另一批注'},
        ],
    }])
    pixels = BytesIO()
    Image.new('RGBA', (13, 7), (17, 80, 130, 90)).save(pixels, format='PNG')
    png = pixels.getvalue()
    source_identity = snapshot(original)['sheets'][0]['sourceIdentity']
    operation = {'kind': 'setNotePicture', 'sheetName': 'Report', 'row': 0, 'column': 0,
                 'sourceIdentity': source_identity, 'picture': {
                     'mediaType': 'image/png', 'bytesBase64': base64.b64encode(png).decode(),
                     'size': len(png), 'sha256': hashlib.sha256(png).hexdigest(),
                     'widthPx': 13, 'heightPx': 7, 'name': '签名.png'}}
    changed = patch_office('xlsx', original, [operation])
    reopened = load_workbook(BytesIO(changed))
    assert reopened['Report']['A1'].value == '保留原始正文'
    assert reopened['Other']['B2'].value == '=2+3'
    assert reopened['Report']['A1'].comment.text == '保留批注文字'
    assert reopened['Report']['A1'].comment.author == '作者甲'
    assert reopened['Report']['C3'].comment.text == '另一批注'
    with ZipFile(BytesIO(original)) as before, ZipFile(BytesIO(changed)) as after:
        assert after.read('customXml/keep.bin') == b'foreign\x00\xff'
        comment_part = next(n for n in before.namelist() if n.endswith('.xml') and ET.fromstring(before.read(n)).tag == f'{{{S}}}comments')
        assert before.read(comment_part) == after.read(comment_part)
        vml = next(n for n in after.namelist() if n.endswith('.vml'))
        fills = [n for n in ET.fromstring(after.read(vml)).iter(f'{{{V}}}fill') if f'{{{O}}}relid' in n.attrib]
        assert len(fills) == 1
        rid = fills[0].attrib[f'{{{O}}}relid']
        rels_path = str(Path(vml).parent / '_rels' / (Path(vml).name + '.rels'))
        relationship = next(n for n in ET.fromstring(after.read(rels_path)) if n.attrib['Id'] == rid)
        assert relationship.attrib['Type'].endswith('/image')
        assert relationship.attrib.get('TargetMode') is None
        media = 'xl/media/' + Path(relationship.attrib['Target']).name
        assert after.read(media) == png
        allowed = {vml, rels_path, media, '[Content_Types].xml'}
        for name in before.namelist():
            if name not in allowed:
                assert before.read(name) == after.read(name), name
    current = snapshot(changed)
    assert current['issues'] == []
    assert current['pictures'][0]['sha256'] == hashlib.sha256(png).hexdigest()
    removed = patch_office('xlsx', changed, [{**operation, 'sourceIdentity': current['sheets'][0]['sourceIdentity'], 'picture': None}])
    assert snapshot(removed)['pictures'] == []
    with ZipFile(BytesIO(removed)) as after:
        assert media not in after.namelist()
        with ZipFile(BytesIO(original)) as before:
            assert after.read(comment_part) == before.read(comment_part)
        assert after.read('customXml/keep.bin') == b'foreign\x00\xff'
