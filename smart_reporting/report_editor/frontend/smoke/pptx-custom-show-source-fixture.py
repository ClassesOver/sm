"""自定义放映显式修订夹具，使用实际writer与独立ZIP/python-pptx回读。"""
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
  deck=Presentation()
  for i in range(3):
   slide=deck.slides.add_slide(deck.slide_layouts[6]);slide.shapes.add_textbox(Inches(.3),Inches(.2),Inches(7),Inches(.5)).text=f'自定义来源页 {i+1}';slide.notes_slide.notes_text_frame.text=f'保留讲稿 {i+1}'
  stream=BytesIO();deck.save(stream)
  content=patch_office('pptx',stream.getvalue(),[{'kind':'editSlides','customShows':[dict(id='cs-a',name='重点',slideIndices=[2,0,2]),dict(id='cs-b',name='保留',slideIndices=[1])]}]);assert not source.exists();source.write_bytes(content)
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
   import posixpath
   ns['r']='http://schemas.openxmlformats.org/officeDocument/2006/relationships'
   doc=etree.fromstring(new.read('ppt/presentation.xml'));rels=etree.fromstring(new.read('ppt/_rels/presentation.xml.rels'));by_id={r.get('Id'):posixpath.normpath(posixpath.join('ppt',r.get('Target'))) for r in rels}
   order=[by_id[r] for r in doc.xpath('p:sldIdLst/p:sldId/@r:id',namespaces=ns)]
   shows=[dict(id=s.get('id'),name=s.get('name'),slideIndices=[order.index(by_id[r]) for r in s.xpath('p:sldLst/p:sld/@r:id',namespaces=ns)]) for s in doc.xpath('p:custShowLst/p:custShow',namespaces=ns)]
   assert shows==[dict(id='0',name='重点改名',slideIndices=[0,2,2]),dict(id='1',name='保留',slideIndices=[1])],shows
   assert set(old.namelist())==set(new.namelist())
   changed=[n for n in old.namelist() if not n.endswith('/') and old.read(n)!=new.read(n)];assert changed==['ppt/presentation.xml'],changed
  return dict(savedSha256=sha(saved),savedSize=len(saved),changedParts=changed,shows=shows,allOtherPartsPreserved=True,textAndNotesPreserved=True,independentReaders=['ZIP/lxml','python-pptx'])
 return dict(model=inspect_office('pptx',content),size=len(content),sha256=sha(content))
if __name__=='__main__':print(json.dumps(run(json.load(sys.stdin)),ensure_ascii=False))
