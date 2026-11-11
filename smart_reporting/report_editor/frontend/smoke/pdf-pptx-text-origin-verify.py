"""Independent fixed-fixture check for actual PDF baseline-X anchors in PPTX."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import runpy
from zipfile import ZipFile
import xml.etree.ElementTree as ET

position=runpy.run_path(str(Path(__file__).with_name('pdf-pptx-text-position-verify.py')))
NS=position['NS']

def verify(source:Path,pptx:Path,rendered:Path):
    result=position['verify'](source,pptx,rendered)
    with ZipFile(pptx) as archive:
        root=ET.fromstring(archive.read('ppt/slides/slide1.xml'))
        for prefix,column in result['columns'].items():
            shape=next(shape for shape in root.findall('.//p:sp',NS) if ''.join(shape.itertext()).startswith(prefix))
            offset=shape.find('p:spPr/a:xfrm/a:off',NS)
            assert abs(float(offset.attrib['x'])/12700-column['sourceFirstX'])<0.0001
            assert abs(column['remainingXErrorPt'])<=0.03,column
    result.update(sourceBaselineXAnchors=True,columnXErrorBoundPt=0.03,overallFidelityPassed=False)
    return result

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('source',type=Path);parser.add_argument('pptx',type=Path);parser.add_argument('rendered_pdf',type=Path);parser.add_argument('--output',type=Path)
    args=parser.parse_args();result=verify(args.source,args.pptx,args.rendered_pdf);text=json.dumps(result,indent=2)
    if args.output:
        temp=args.output.with_suffix(args.output.suffix+'.tmp');temp.write_text(text+'\n');temp.replace(args.output)
    print(text)
