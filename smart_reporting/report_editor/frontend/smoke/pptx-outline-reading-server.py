"""Outline/Reading真实HTTP夹具，复用已有授权、工作区、原生导入/保存/发布链。"""
import argparse
import asyncio
import runpy
from pathlib import Path

import uvicorn
from pptx.util import Inches, Pt

base = runpy.run_path(str(Path(__file__).with_name('pptx-view-modes-server.py')))


def presentation():
    deck = base['registered_presentation']()
    save = deck.save

    def source_save(stream):
        for index, slide in enumerate(deck.slides):
            slide.shapes[0].text = f'大纲来源标题 {index + 1}'
            slide.shapes[0].text_frame.paragraphs[0].runs[0].font.size = Pt(32)
            for row in range(7):
                shape = slide.shapes.add_textbox(Inches(.5), Inches(1.5 + row * .6), Inches(7), Inches(.5))
                shape.text = f'来源正文 {index + 1}—{row + 1}'
                shape.text_frame.paragraphs[0].runs[0].font.size = Pt(18)
            if index == 1:
                slide._element.set('show', '0')
        blank = deck.slides.add_slide(deck.slide_layouts[6])
        blank.notes_slide.notes_text_frame.text = '空白页讲稿'
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
