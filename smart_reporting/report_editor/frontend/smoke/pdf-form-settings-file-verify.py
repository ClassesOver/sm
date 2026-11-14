"""独立回读字段设置烟测下载文件，不调用产品读写或颜色实现。"""
import argparse
import hashlib
import json
from pathlib import Path

from pypdf import PdfReader
from pypdf.generic import ContentStream


def verify(directory: Path):
    names = ['source', 'radio-downloaded', 'properties-downloaded', 'append-downloaded']
    readers = [PdfReader(directory / f'{name}.pdf') for name in names]
    fields = [{str(ref.get_object()['/T']): ref.get_object()
               for ref in reader.trailer['/Root']['/AcroForm']['/Fields']} for reader in readers]
    text_name = 'customer_detail_detail_detail_detail_detail_detail'
    assert set(fields[0]) == {text_name, 'status', 'consent'}
    source_pages = readers[0].pages
    for reader in readers[1:]:
        assert len(reader.pages) == len(source_pages)
        for before, after in zip(source_pages, reader.pages, strict=True):
            # 渲染器会增加成对 q/Q 隔离外观；正文操作数与其它操作符须保持。
            commands = lambda page, pdf: [(operands, operator) for operands, operator in ContentStream(page.get_contents(), pdf).operations if operator not in (b'q', b'Q')]
            assert commands(before, readers[0]) == commands(after, reader)
            depth = 0
            for _, operator in ContentStream(after.get_contents(), reader).operations:
                depth += 1 if operator == b'q' else -1 if operator == b'Q' else 0
                assert depth >= 0
            assert depth == 0
            assert before.extract_text() == after.extract_text()
            for key in ['/MediaBox', '/CropBox', '/Rotate', '/UserUnit']:
                assert str(before.get(key)) == str(after.get(key))

    def field_state(field):
        return {key: str(field.get(key)) for key in ['/FT', '/T', '/V', '/DV', '/Ff', '/Opt', '/DA', '/Q', '/MaxLen']}, [
            (list(widget.get_object()['/Rect']), str(widget.get_object().get('/AS')))
            for widget in field['/Kids']]

    for index in range(1, 4):
        assert set(fields[index]) == {*fields[0], 'new_consent'}
        changed = {1: set(), 2: {text_name}, 3: {'consent'}}[index]
        for name in fields[index - 1]:
            if name not in changed:
                assert field_state(fields[index - 1][name]) == field_state(fields[index][name])
        new = fields[index]['new_consent']
        assert list(new['/Opt']) == ['Yes', 'No', 'Maybe'] and str(new['/V']) == '/2'
        assert [list(ref.get_object()['/Rect']) for ref in new['/Kids']] == [[10, 50, 30, 70], [50, 50, 70, 70], [130, 50, 150, 70]]
        assert [str(ref.get_object()['/AS']) for ref in new['/Kids']] == ['/Off', '/Off', '/2']
    for index in [2, 3]:
        text = fields[index][text_name]
        assert str(text['/V']) == 'Alice' and int(text['/MaxLen']) == 32 and int(text['/Q']) == 1
        assert '/Courier-Bold 18 Tf' in str(text['/DA'])
        assert list(text['/Kids'][0].get_object()['/Rect']) == [30, 240, 180, 270]
    appended = fields[3]['consent']
    assert list(appended['/Opt']) == ['Yes', 'No', 'Maybe'] and str(appended['/V']) == '/0'
    assert [list(ref.get_object()['/Rect']) for ref in appended['/Kids']] == [[30, 130, 50, 150], [80, 130, 100, 150], [130, 130, 150, 150]]
    assert [str(ref.get_object()['/AS']) for ref in appended['/Kids']] == ['/0', '/Off', '/Off']
    return {'ok': True, 'pages': len(source_pages), 'pageDrawingCommandsAndGeometryPreserved': True,
            'balancedGraphicsStateWrappersNormalized': True,
            'unchangedFieldValuesAndWidgetGeometryPreserved': True,
            'radioSelectionAndAppendPreserved': True, 'textFontSizeAlignmentAndLengthVerified': True,
            'files': {name: hashlib.sha256((directory / f'{name}.pdf').read_bytes()).hexdigest() for name in names}}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('directory', type=Path)
    args = parser.parse_args()
    print(json.dumps(verify(args.directory), ensure_ascii=False, indent=2))
