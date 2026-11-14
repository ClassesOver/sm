"""去背景完整源族显式修订夹具，使用实际writer与独立ZIP/python-pptx回读。"""
import base64,hashlib,json,sys
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile
from lxml import etree
from pptx import Presentation
from pptx.util import Inches
from smart_reporting.report_editor.native_office import inspect_office,patch_office
from smart_reporting.report_editor.slides_render import render_pptx_tree

def sha(b):return hashlib.sha256(b).hexdigest()
def run(p):
 d=Path(p['directory']);source=d/'source.pptx'
 if p['mode']=='create':
  from PIL import Image,ImageDraw
  image=Image.new('RGBA',(1040,600),'white');draw=ImageDraw.Draw(image);draw.rectangle((260,150,780,450),fill='#C81E1E');draw.rectangle((450,250,550,350),fill='white');image.save(d/'source-image.png')
  deck=Presentation()
  for i in range(3):
   slide=deck.slides.add_slide(deck.slide_layouts[6]);slide.shapes.add_textbox(Inches(.3),Inches(.2),Inches(7),Inches(.5)).text=f'去背景保留正文 {i+1}';slide.notes_slide.notes_text_frame.text=f'保留讲稿 {i+1}'
   if i<2:
    pic=slide.shapes.add_picture(str(d/'source-image.png'),Inches(1),Inches(1),Inches(6),Inches(3.46));pic.crop_left=.1;pic.crop_top=.05;pic.rotation=13
  stream=BytesIO();deck.save(stream);assert not source.exists();source.write_bytes(stream.getvalue())
 content=source.read_bytes()
 if p.get('operations'):content=patch_office('pptx',content,p['operations'])
 if p.get('output'):
  target=Path(p['output']);assert not target.exists();target.write_bytes(content)
 if p['mode']=='render':return render_pptx_tree(content)
 if p['mode']=='verify':
  output=Path(p['file']);saved=output.read_bytes();a,b=Presentation(source),Presentation(output)
  assert len(a.slides)==len(b.slides)==3
  assert [s.notes_slide.notes_text_frame.text for s in a.slides]==[s.notes_slide.notes_text_frame.text for s in b.slides]
  assert [[x.text for x in s.shapes if x.has_text_frame] for s in a.slides]==[[x.text for x in s.shapes if x.has_text_frame] for s in b.slides]
  ns={'a':'http://schemas.openxmlformats.org/drawingml/2006/main','p':'http://schemas.openxmlformats.org/presentationml/2006/main'}
  with ZipFile(source) as old,ZipFile(output) as new:
   assert old.testzip() is None and new.testzip() is None
   media=[n for n in old.namelist() if n.startswith('ppt/media/') and not n.endswith('/')]
   for n in media:assert old.read(n)==new.read(n)
   import posixpath
   from PIL import Image
   ns['r']='http://schemas.openxmlformats.org/officeDocument/2006/relationships'
   def picture_media(zip,index):
    slide=etree.fromstring(zip.read(f'ppt/slides/slide{index}.xml'));rid=slide.xpath('string(p:cSld/p:spTree/p:pic/p:blipFill/a:blip/@r:embed)',namespaces=ns);rels=etree.fromstring(zip.read(f'ppt/slides/_rels/slide{index}.xml.rels'));target=next(r.get('Target') for r in rels if r.get('Id')==rid);return posixpath.normpath(posixpath.join('ppt/slides',target))
   oldpic=etree.fromstring(old.read('ppt/slides/slide1.xml')).xpath('p:cSld/p:spTree/p:pic',namespaces=ns)[0];newpic=etree.fromstring(new.read('ppt/slides/slide1.xml')).xpath('p:cSld/p:spTree/p:pic',namespaces=ns)[0]
   assert etree.tostring(oldpic.find('p:spPr',ns))==etree.tostring(newpic.find('p:spPr',ns))
   assert oldpic.find('p:blipFill/a:srcRect',ns).attrib==newpic.find('p:blipFill/a:srcRect',ns).attrib
   newmedia=picture_media(new,1);oldmedia=picture_media(old,1);assert picture_media(new,2)==oldmedia and new.read(oldmedia)==old.read(oldmedia)
   processed=Image.open(BytesIO(new.read(newmedia))).convert('RGBA');original=Image.open(BytesIO(old.read(oldmedia))).convert('RGBA');assert processed.size==original.size==(1040,600)
   assert processed.getpixel((0,0))[3]==0 and processed.getpixel((300,200))[3]==255 and processed.getpixel((500,300))==original.getpixel((500,300))
   assert all(newpx[:3]==oldpx[:3] for newpx,oldpx in zip(processed.getdata(),original.getdata()) if newpx[3]>0)
   changed=[n for n in old.namelist() if not n.endswith('/') and old.read(n)!=new.read(n)];added=[n for n in new.namelist() if not n.endswith('/') and n not in old.namelist()]
   assert set(changed)<={'[Content_Types].xml','ppt/slides/slide1.xml','ppt/slides/_rels/slide1.xml.rels'},changed;assert added==[newmedia],added
   alpha=dict(mediaPath=newmedia,mediaSha256=sha(new.read(newmedia)),originalMediaSha256=sha(old.read(oldmedia)),width=1040,height=600,edgeAlpha=0,subjectAlpha=255,enclosedWhitePreserved=True,sharedOriginalImagePreserved=True)
  return dict(savedSha256=sha(saved),savedSize=len(saved),changedParts=changed,alpha=alpha,addedParts=added,unrelatedPartsPreserved=True,textAndNotesPreserved=True,independentReaders=['ZIP/lxml','python-pptx'])
 return dict(model=inspect_office('pptx',content),size=len(content),sha256=sha(content))
if __name__=='__main__':print(json.dumps(run(json.load(sys.stdin)),ensure_ascii=False))
