"""背景整族显式修订夹具，使用实际writer与独立ZIP/python-pptx回读。"""
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
  from PIL import Image
  image=Image.new('RGB',(30,20),'#35a273');image.save(d/'background.png')
  deck=Presentation()
  for i in range(3):
   slide=deck.slides.add_slide(deck.slide_layouts[6]);slide.shapes.add_textbox(Inches(.3),Inches(.2),Inches(7),Inches(.5)).text=f'背景原始正文 {i+1}';slide.notes_slide.notes_text_frame.text=f'保留讲稿 {i+1}'
  stream=BytesIO();deck.save(stream)
  content=patch_office('pptx',stream.getvalue(),[{'kind':'editSlides','backgroundImages':[dict(slideIndices=[0],bytesBase64=base64.b64encode((d/'background.png').read_bytes()).decode(),extension='png',tile=False)],'backgrounds':[dict(slideIndex=1,color='#EEEEEE'),dict(slideIndex=2,color='#EEEEEE')]}]);assert not source.exists();source.write_bytes(content)
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
   assert media==[n for n in new.namelist() if n.startswith('ppt/media/') and not n.endswith('/')]
   for n in media:assert old.read(n)==new.read(n)
   xml=[etree.fromstring(new.read(f'ppt/slides/slide{i}.xml')) for i in range(1,4)]
   assert xml[0].xpath('boolean(p:cSld/p:bg/p:bgPr/a:blipFill/a:tile)',namespaces=ns)
   assert xml[0].get('showMasterSp')=='0'
   assert xml[1].xpath('string(p:cSld/p:bg/p:bgPr/a:solidFill/a:srgbClr/@val)',namespaces=ns)=='E97132'
   assert xml[2].xpath('boolean(p:cSld/p:bg/p:bgPr/a:gradFill/a:path)',namespaces=ns)
   changed=[n for n in old.namelist() if not n.endswith('/') and old.read(n)!=new.read(n)]
   assert set(changed)<={'ppt/slides/slide1.xml','ppt/slides/slide2.xml','ppt/slides/slide3.xml','ppt/slides/_rels/slide2.xml.rels','ppt/slides/_rels/slide3.xml.rels'},changed
  return dict(savedSha256=sha(saved),savedSize=len(saved),changedParts=changed,mediaPreserved=True,textAndNotesPreserved=True,independentReaders=['ZIP/lxml','python-pptx'])
 return dict(model=inspect_office('pptx',content),size=len(content),sha256=sha(content))
if __name__=='__main__':print(json.dumps(run(json.load(sys.stdin)),ensure_ascii=False))
