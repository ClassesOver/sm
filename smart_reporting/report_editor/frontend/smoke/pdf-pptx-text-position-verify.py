"""Fixed-fixture check for PDF text geometry without PowerPoint shape autofit."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import runpy
from zipfile import ZipFile
import xml.etree.ElementTree as ET

geometry=runpy.run_path(str(Path(__file__).with_name('pdf-pptx-text-geometry-verify.py')))
NS=geometry['NS']

def verify(source:Path,pptx:Path,rendered:Path):
    result=geometry['verify'](source,pptx,rendered)
    with ZipFile(pptx) as archive:
        root=ET.fromstring(archive.read('ppt/slides/slide1.xml'))
        bodies=root.findall('.//p:sp/p:txBody/a:bodyPr',NS)
        assert bodies
        for body in bodies:
            assert body.find('a:noAutofit',NS) is not None
            assert body.find('a:spAutoFit',NS) is None
            assert body.find('a:normAutofit',NS) is None
            assert all(body.attrib[side+'Ins']=='0' for side in ['l','t','r','b'])
        result['fixedTextBoxCount']=len(bodies)
    for column in result['columns'].values():
        # IR uses tight ink bounds rather than authored baseline X; that
        # residual is recorded, not corrected with a guessed font offset.
        assert abs(column['remainingXErrorPt'])<=1.1,column
    result.update(noShapeAutofit=True,columnXErrorBoundPt=1.1,overallFidelityPassed=False)
    return result

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('source',type=Path);parser.add_argument('pptx',type=Path);parser.add_argument('rendered_pdf',type=Path);parser.add_argument('--output',type=Path)
    args=parser.parse_args();result=verify(args.source,args.pptx,args.rendered_pdf);text=json.dumps(result,indent=2)
    if args.output:
        temp=args.output.with_suffix(args.output.suffix+'.tmp');temp.write_text(text+'\n');temp.replace(args.output)
    print(text)
