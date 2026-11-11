"""Independent source PDF / PPTX OOXML / rendered PDF spacing verification."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
from zipfile import ZipFile
import xml.etree.ElementTree as ET
import pymupdf

NS={'p':'http://schemas.openxmlformats.org/presentationml/2006/main','a':'http://schemas.openxmlformats.org/drawingml/2006/main'}

def pdf_lines(path:Path):
    document=pymupdf.open(path)
    return [{'text':''.join(span['text'] for span in line['spans']),'x':line['spans'][0]['origin'][0],'baseline':line['spans'][0]['origin'][1],'fonts':[span['font'] for span in line['spans']]} for block in document[0].get_text('dict')['blocks'] for line in block.get('lines',[])]

def verify(source:Path,pptx:Path,rendered:Path):
    original=pdf_lines(source);actual=pdf_lines(rendered)
    result={'sourceSha256':hashlib.sha256(source.read_bytes()).hexdigest(),'pptxSha256':hashlib.sha256(pptx.read_bytes()).hexdigest(),'renderedPdfSha256':hashlib.sha256(rendered.read_bytes()).hexdigest(),'columns':{},'overallFidelityPassed':False}
    for prefix in ['Left column','Right column']:
        source_rows=[line for line in original if line['text'].startswith(prefix)]
        rows=[line for line in actual if line['text'].startswith(prefix)]
        assert len(source_rows)==len(rows)==8
        assert [line['text'] for line in source_rows]==[line['text'] for line in rows]
        source_steps=[b['baseline']-a['baseline'] for a,b in zip(source_rows,source_rows[1:])]
        steps=[b['baseline']-a['baseline'] for a,b in zip(rows,rows[1:])]
        assert all(abs(step-16)<=0.001 for step in source_steps)
        assert all(abs(step-16)<=0.03 for step in steps),(prefix,steps)
        result['columns'][prefix]={'sourceStepsPt':source_steps,'renderedStepsPt':steps,'sourceFirstX':source_rows[0]['x'],'renderedFirstX':rows[0]['x'],'sourceFirstBaseline':source_rows[0]['baseline'],'renderedFirstBaseline':rows[0]['baseline'],'remainingXErrorPt':rows[0]['x']-source_rows[0]['x'],'remainingFirstBaselineErrorPt':rows[0]['baseline']-source_rows[0]['baseline']}
    with ZipFile(pptx) as archive:
        root=ET.fromstring(archive.read('ppt/slides/slide1.xml'))
        assert len(root.findall('.//a:tbl',NS))==1
        assert len(root.findall('.//p:pic',NS))==1
        for prefix in ['Left column','Right column']:
            shape=next(shape for shape in root.findall('.//p:sp',NS) if ''.join(shape.itertext()).startswith(prefix))
            assert shape.find('p:txBody/a:p/a:pPr/a:lnSpc/a:spcPts',NS).attrib['val']=='1600'
        families=sorted(set(node.attrib['typeface'] for node in root.findall('.//a:latin',NS)))
        assert 'Liberation Mono' in families
        result['fontFamilies']=families
    all_text=[line['text'] for line in actual]
    for cell in ['Region','Revenue','Margin','East','12345.67','12.5%','West','9876.54','9.8%']:assert cell in all_text,cell
    code=next(line for line in actual if line['text']=='Code 001 / fixed width')
    assert any('Mono' in font for font in code['fonts']),code
    result.update(ok=True,sourceColumnPitchPt=16,tolerancePt=0.03,tableNoFalseWrapping=True,monospacedCaptionRetained=True,remainingPositionDifferences=True)
    return result

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('source',type=Path);parser.add_argument('pptx',type=Path);parser.add_argument('rendered_pdf',type=Path);parser.add_argument('--output',type=Path)
    args=parser.parse_args();result=verify(args.source,args.pptx,args.rendered_pdf);text=json.dumps(result,indent=2)
    if args.output:args.output.write_text(text)
    print(text)
