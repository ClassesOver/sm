"""浏览视图 HTTP 夹具：复用原生导入/发布链，补齐 python-pptx 备注母版登记。"""
import argparse
import asyncio
import runpy
from pathlib import Path

import uvicorn
from lxml import etree
from pptx import Presentation
from pptx.opc.constants import RELATIONSHIP_TYPE as RT
from pptx.oxml.ns import qn

base = runpy.run_path(str(Path(__file__).with_name('pptx-equation-server.py')))


def registered_presentation():
    deck = Presentation()
    save = deck.save

    def registered_save(stream):
        master = next(rel for rel in deck.part.rels.values() if rel.reltype == RT.NOTES_MASTER)
        ids = etree.Element(qn('p:notesMasterIdLst'))
        etree.SubElement(ids, qn('p:notesMasterId')).set(qn('r:id'), master.rId)
        deck._element.insert(deck._element.index(deck._element.find(qn('p:sldMasterIdLst'))) + 1, ids)
        save(stream)

    deck.save = registered_save
    return deck


create_app = base['create_app']
create_app.__globals__['Presentation'] = registered_presentation
if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--directory', type=Path, required=True)
    parser.add_argument('--port', type=int, required=True)
    args = parser.parse_args()
    uvicorn.run(asyncio.run(create_app(args.directory, args.port)), host='127.0.0.1', port=args.port, log_level='warning')
