"""母版文字真实 HTTP 夹具：复用工作区、导入、修订与非阻断下载链。"""
import argparse
import asyncio
import copy
import runpy
from pathlib import Path

import uvicorn
from pptx.oxml.ns import qn
from pptx.util import Inches

base = runpy.run_path(str(Path(__file__).with_name('pptx-view-modes-server.py')))


def presentation():
    deck = base['registered_presentation']()
    save = deck.save

    def source_save(stream):
        # 复制有效 textbox 到两页共享的实际母版与版式，避免伪造 UI 模型。
        source = deck.slides[0].shapes[0]._element
        for host, spid, name, text, top in (
            (deck.slide_master, 9001, '母版品牌', '母版来源品牌', 5.6),
            (deck.slide_layouts[6], 9002, '版式品牌', '版式来源品牌', 6.2),
        ):
            shape = copy.deepcopy(source)
            identity = shape.find('.//' + qn('p:cNvPr'))
            identity.set('id', str(spid)); identity.set('name', name)
            shape.find('.//' + qn('a:t')).text = text
            offset = shape.find('.//' + qn('a:off'))
            offset.set('y', str(Inches(top)))
            host.shapes._spTree.append(shape)
        save(stream)

    deck.save = source_save
    return deck


create_app = base['create_app']
create_app.__globals__['Presentation'] = presentation
if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--directory', type=Path, required=True)
    parser.add_argument('--port', type=int, required=True)
    args = parser.parse_args()
    uvicorn.run(asyncio.run(create_app(args.directory, args.port)), host='127.0.0.1', port=args.port, log_level='warning')
