"""独立回读浏览视图真实下载文件，不调用报告/Node 编辑引擎。"""
import argparse
import hashlib
import json
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

from pptx import Presentation


def parts(content):
    with ZipFile(BytesIO(content)) as archive:
        return {name: archive.read(name) for name in archive.namelist() if not name.endswith('/')}


def verify(directory: Path):
    before = (directory / 'source.pptx').read_bytes()
    after = (directory / 'downloaded.pptx').read_bytes()
    original, current = parts(before), parts(after)
    receipt = json.loads((directory / 'save-receipt.json').read_text())
    assert hashlib.sha256(after).hexdigest() == receipt['artifacts']['pptx']['sha256']
    assert original.keys() == current.keys()
    changed = sorted(name for name in original if original[name] != current[name])
    assert changed == ['ppt/notesSlides/notesSlide2.xml', 'ppt/presentation.xml']
    slides = [{'text': slide.shapes[0].text, 'notes': slide.notes_slide.notes_text_frame.text}
              for slide in Presentation(BytesIO(after)).slides]
    assert len(slides) == 2
    assert '正文 2' in slides[0]['text'] and '正文 1' in slides[1]['text']
    assert slides[0]['notes'] == '视图切换保留未失焦讲稿 <&> 😀'
    assert slides[1]['notes'] == '保留讲稿 1'
    result = {
        'ok': True, 'reader': 'python-pptx + ZIP, independent of Node bridge',
        'inputSha256': hashlib.sha256(before).hexdigest(),
        'downloadSha256': hashlib.sha256(after).hexdigest(),
        'orderedSlides': slides, 'verifiedOrder': [1, 0], 'verifiedNoteIdentity': 1,
        'changedParts': changed, 'unchangedParts': len(original) - len(changed),
        'addedParts': [], 'removedParts': [], 'validation': receipt['validation'],
    }
    (directory / 'independent-readback.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('directory', type=Path)
    print(json.dumps(verify(parser.parse_args().directory), ensure_ascii=False))
