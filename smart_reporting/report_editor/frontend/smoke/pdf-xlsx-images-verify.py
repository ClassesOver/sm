"""Independent openpyxl/Pillow/OOXML checks for xlsx-normal-images.pdf."""
from __future__ import annotations
import argparse
import hashlib
import json
import math
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile
import xml.etree.ElementTree as ET
from openpyxl import load_workbook
from PIL import Image, ImageDraw, ImageChops

NS={'x':'http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing','a':'http://schemas.openxmlformats.org/drawingml/2006/main'}
EMU=12700
EXPECTED=[[(40,190,80,40),(190,180,40,80),(350,260,70,40)],[(20,170,80,40),(170,160,40,80),(330,240,50,40)],[(130,40,40,80),(100,190,80,40),(60,350,40,70)]]

def verify(path:Path)->dict:
    workbook=load_workbook(path)
    assert workbook.sheetnames==['Page 1','Page 2','Page 3'],workbook.sheetnames
    image=Image.new('RGBA',(80,40));draw=ImageDraw.Draw(image)
    draw.rectangle((0,0,39,19),fill=(255,0,0,255));draw.rectangle((40,0,79,19),fill=(0,255,0,128))
    draw.rectangle((0,20,39,39),fill=(0,0,255,255));draw.rectangle((40,20,79,39),fill=(255,255,0,255))
    clockwise=image.transpose(Image.Transpose.ROTATE_270)
    ccw=image.transpose(Image.Transpose.ROTATE_90)
    expected_pixels=[[image,ccw,image.crop((0,0,70,40))],[image,ccw,image.crop((0,0,50,40))],[clockwise,image,clockwise.crop((0,0,40,70))]]
    checks=[]
    with ZipFile(path) as archive:
        media=[name for name in archive.namelist() if name.startswith('xl/media/')]
        assert len(media)==9,len(media)
        for page,sheet in enumerate(workbook,1):
            values=[cell.value for row in sheet for cell in row if cell.value is not None]
            assert 'Editable report page '+str(page) in values
            assert 12345.67 in values
            labels=[cell for row in sheet for cell in row if isinstance(cell.value,str) and '图片位置参考区' in cell.value]
            assert len(labels)==1
            origin_row=labels[0].row-1+2
            assert len(sheet._images)==3
            drawing_path='xl/drawings/drawing'+str(page)+'.xml'
            drawing=ET.fromstring(archive.read(drawing_path))
            rels=ET.fromstring(archive.read('xl/drawings/_rels/drawing'+str(page)+'.xml.rels'))
            targets={rel.attrib['Id']:'xl/'+rel.attrib['Target'].removeprefix('../') for rel in rels}
            def marker(element):
                col=int(element.findtext('x:col',namespaces=NS));row=int(element.findtext('x:row',namespaces=NS))
                coloff=int(element.findtext('x:colOff',namespaces=NS));rowoff=int(element.findtext('x:rowOff',namespaces=NS))
                left=0.0
                from openpyxl.utils import get_column_letter
                for i in range(col):
                    letter=get_column_letter(i+1)
                    dim=sheet.column_dimensions.get(letter)
                    left+=(64 if dim is None else max(1,math.floor(dim.width*7+5+0.5)))*0.75
                assert row>=origin_row
                assert all(sheet.row_dimensions[i+1].height==15 for i in range(origin_row,row+1))
                return left+coloff/EMU,(row-origin_row)*15+rowoff/EMU
            anchors=drawing.findall('x:twoCellAnchor',NS)
            assert len(anchors)==3
            for position,anchor in enumerate(anchors):
                name=anchor.find('x:pic/x:nvPicPr/x:cNvPr',NS).attrib['name']
                assert name=='pdf-page-'+str(page)+'-image-'+str(position+1),name
                left,top=marker(anchor.find('x:from',NS));right,bottom=marker(anchor.find('x:to',NS))
                actual=(left,top,right-left,bottom-top)
                expected=EXPECTED[page-1][position]
                assert all(abs(a-e)<0.001 for a,e in zip(actual,expected)),(name,actual,expected)
                embed=anchor.find('x:pic/x:blipFill/a:blip',NS).attrib['{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed']
                pixel=Image.open(BytesIO(archive.read(targets[embed]))).convert('RGBA')
                reference=expected_pixels[page-1][position].resize(pixel.size,Image.Resampling.NEAREST)
                # PDFium antialiases transformed image edges. Interior RGBA values
                # are independent exact samples; allow only the one-pixel seams.
                samples=[]
                for fx,fy in [(0.2,0.2),(0.8,0.2),(0.2,0.8),(0.8,0.8)]:
                    point=(int(pixel.width*fx),int(pixel.height*fy))
                    assert pixel.getpixel(point)==reference.getpixel(point),(name,point,pixel.getpixel(point),reference.getpixel(point))
                    samples.append(pixel.getpixel(point))
                assert pixel.getextrema()[3]==(128,255)
                checks.append({'name':name,'boxPt':actual,'pixels':pixel.size,'alpha':pixel.getextrema()[3],'rgbaSamples':samples})
    data=path.read_bytes()
    return {'ok':True,'sha256':hashlib.sha256(data).hexdigest(),'size':len(data),'editableNumericCells':True,'imageCount':len(checks),'images':checks}

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('xlsx',type=Path);parser.add_argument('--output',type=Path)
    args=parser.parse_args();result=verify(args.xlsx);text=json.dumps(result,ensure_ascii=False,indent=2)
    if args.output:args.output.write_text(text+'\n')
    print(text)
