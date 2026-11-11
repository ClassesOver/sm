import sys,json,hashlib
from pathlib import Path
from pypdf import PdfReader
from pypdf.generic import ContentStream
root=Path(sys.argv[1]);source=PdfReader(root/'source.pdf');output=PdfReader(root/'shortcut.pdf')
assert len(source.pages)==len(output.pages)==3
for index in range(3):
 if index: assert source.pages[index].extract_text().strip() in output.pages[index].extract_text()
 assert list(source.pages[index].mediabox)==list(output.pages[index].mediabox)
 assert list(source.pages[index].cropbox)==list(output.pages[index].cropbox)
assert 'source page one' not in output.pages[0].extract_text()
found=[];output.pages[0].extract_text(visitor_text=lambda text,cm,tm,font,size:found.append((text,cm,tm,font,size)));rows=[]
for segment,family,size,expected_x in [('AA','LiberationMono',12,24),('BB','LiberationSerif-BoldItalic',18,38.4),('CC','LiberationMono',12,62.412)]:
 text,cm,tm,font,pt=next(value for value in found if value[0].strip()==segment)
 assert family in str(font['/BaseFont']) and abs(pt-size)<.002
 x=tm[4]*cm[0]+tm[5]*cm[2]+cm[4];y=tm[4]*cm[1]+tm[5]*cm[3]+cm[5]
 assert abs(x-expected_x)<.05 and abs(y-350)<.002,(segment,x,y,expected_x)
 descriptor=font['/DescendantFonts'][0].get_object()['/FontDescriptor'].get_object();assert len(descriptor['/FontFile2'].get_object().get_data())>100
 rows.append({'text':segment,'font':str(font['/BaseFont']),'size':pt,'baseline':[x,y]})
colors=[args for args,operator in ContentStream(output.pages[0].get_contents(),output).operations if operator==b'rg'];assert any(list(map(float,color))==[1,0,0] for color in colors)
assert not output.pages[0].get('/Annots') and not output.get_fields()
print(json.dumps({'ok':True,'rows':rows,'selectionColor':[1,0,0],'otherPagesPreserved':True,'sourceSha256':hashlib.sha256((root/'source.pdf').read_bytes()).hexdigest(),'outputSha256':hashlib.sha256((root/'shortcut.pdf').read_bytes()).hexdigest()}))
