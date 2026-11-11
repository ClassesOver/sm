"""Read the actual downloaded complex-fixture PPTX without invoking its writer."""
from __future__ import annotations
import argparse,hashlib,json
from pathlib import Path
from zipfile import ZipFile
import xml.etree.ElementTree as ET
NS={'p':'http://schemas.openxmlformats.org/presentationml/2006/main','a':'http://schemas.openxmlformats.org/drawingml/2006/main'}
def verify(path,source_origin=None):
    data=path.read_bytes()
    expected_x={'Left column':418846,'Right column':4038346}
    if source_origin is not None:
        import pymupdf
        with pymupdf.open(source_origin) as source:
            lines=[line for block in source[0].get_text('dict')['blocks'] for line in block.get('lines',[])]
        for prefix in expected_x:
            rows=[line for line in lines if ''.join(span['text'] for span in line['spans']).startswith(prefix)]
            assert len(rows)==8
            origins=[row['spans'][0]['origin'][0] for row in rows]
            assert all(abs(x-origins[0])<0.0001 for x in origins)
            expected_x[prefix]=round(origins[0]*12700)
    with ZipFile(path) as archive:
        root=ET.fromstring(archive.read('ppt/slides/slide1.xml'))
        shapes=root.findall('.//p:sp',NS)
        assert len(root.findall('.//a:tbl',NS))==1
        assert len(root.findall('.//p:pic',NS))==1
        columns={}
        for prefix,x in expected_x.items():
            shape=next(shape for shape in shapes if ''.join(shape.itertext()).startswith(prefix))
            assert shape.find('p:txBody/a:p/a:pPr/a:lnSpc/a:spcPts',NS).attrib['val']=='1600'
            offset=shape.find('p:spPr/a:xfrm/a:off',NS).attrib
            assert int(offset['x'])==x and int(offset['y'])==1046480
            assert shape.find('p:txBody/a:bodyPr',NS).attrib['wrap']=='none'
            if source_origin is not None:
                body=shape.find('p:txBody/a:bodyPr',NS)
                assert body.find('a:noAutofit',NS) is not None
                assert all(body.attrib.get(key)=='0' for key in ['lIns','tIns','rIns','bIns'])
            text=''.join(shape.itertext())
            for n in range(1,9):assert prefix+' line '+str(n)+':' in text
            columns[prefix]={'lineExactPt':16,'offsetEmu':offset,'lineCount':8}
        cell_text=[''.join(cell.itertext()) for cell in root.findall('.//a:tc',NS)]
        assert cell_text==['Region','Revenue','Margin','East','12345.67','12.5%','West','9876.54','9.8%'],cell_text
        families=sorted(set(node.attrib['typeface'] for node in root.findall('.//a:latin',NS)))
        assert all(font in families for font in ['DejaVu Sans','Liberation Mono','Liberation Sans','Liberation Serif'])
        assert any(name.startswith('ppt/media/') for name in archive.namelist())
    return {'ok':True,'sha256':hashlib.sha256(data).hexdigest(),'size':len(data),'columns':columns,'tableCount':1,'pictureCount':1,'fontFamilies':families,'overallFidelityPassed':False,'manualReview':True,**({'sourceOriginSha256':hashlib.sha256(source_origin.read_bytes()).hexdigest(),'sourceBaselineXAnchors':True} if source_origin is not None else {})}
if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('pptx',type=Path);parser.add_argument('--output',type=Path);parser.add_argument('--source-origin',type=Path);args=parser.parse_args();result=verify(args.pptx,args.source_origin);text=json.dumps(result,indent=2)
    if args.output:args.output.write_text(text)
    print(text)
