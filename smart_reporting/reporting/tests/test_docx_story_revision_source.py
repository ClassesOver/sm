"""Independent ZIP/lxml acceptance of model-backed fixed-source story decisions."""
import base64
import json
import subprocess
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

from lxml import etree

ENGINE = Path(__file__).resolve().parents[1] / 'doc_engine'


def test_story_model_save_has_exact_decision_and_preserves_unrelated_parts():
    # A separate JS process exercises the real engine; Python independently reads OOXML.
    script = r'''
import {parseDocx,saveDocx} from './packages/docx-engine/src/index.ts'
import {buildDocx} from './packages/docx-engine/tests/helpers/build-docx.ts'
import {inspectStoryRevisions,resolveStoryRevisions,verifyStoryRevisionOutput} from './bridge/docx-story-revisions.ts'
const result=[]
for(const kind of ['footnote','endnote','header','footer'])for(const action of ['accept','reject']){
 const note=kind==='footnote'||kind==='endnote',part=note?`${kind}s`:`${kind}1`,path=`word/${part}.xml`,root=note?`${kind}s`:kind==='header'?'hdr':'ftr'
 const wrapper='<w:del w:id="11" w:author="Ann"><w:r><w:delText>old text</w:delText></w:r></w:del>'
 const p=`<w:p><w:r><w:t>keep</w:t></w:r>${wrapper}<w:bookmarkStart w:id="90" w:name="sentinel"/></w:p>`
 const xml=`<w:${root} xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">${note?`<w:${kind} w:id="2">${p}</w:${kind}>`:p}</w:${root}>`
 const bytes=await buildDocx({bodyXml:note?`<w:p><w:r><w:${kind}Reference w:id="2"/></w:r></w:p>`:'<w:p><w:r><w:t>Body unchanged</w:t></w:r></w:p>',sectPrExtra:note?'':`<w:${kind}Reference w:type="default" r:id="rId40"/>`,extraRels:`<Relationship Id="rId40" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/${note?kind+'s':kind}" Target="${part}.xml"/>`,extraParts:[{path,xml,contentType:`application/vnd.openxmlformats-officedocument.wordprocessingml.${note?kind+'s':kind}+xml`},{path:'customXml/sentinel.xml',xml:'<sentinel>opaque</sentinel>',contentType:'application/xml'}]})
 const parsed=await parseDocx(bytes),target=(await inspectStoryRevisions(parsed)).targets[0]
 const ops=[{targetId:target.targetId,expectedPartSha256:target.expectedPartSha256,expectedWrapperSha256:target.expectedWrapperSha256,action}]
 const options=await resolveStoryRevisions(parsed,ops),out=await saveDocx(parsed,parsed.blocks.filter(b=>!b.hidden).map(b=>({kind:'original',docxIndex:b.docxIndex})),options)
 await verifyStoryRevisionOutput(parsed,ops,out)
 result.push({kind,action,path,before:Buffer.from(bytes).toString('base64'),after:Buffer.from(out).toString('base64')})
}
console.log(JSON.stringify(result))
'''
    run = subprocess.run(['node', '--import', 'tsx', '--input-type=module'], input=script,
                         text=True, cwd=ENGINE, capture_output=True, check=True)
    cases = json.loads(run.stdout)
    assert len(cases) == 8
    ns = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
    for case in cases:
        with ZipFile(BytesIO(base64.b64decode(case['before']))) as before, ZipFile(BytesIO(base64.b64decode(case['after']))) as after:
            assert after.testzip() is None
            assert set(before.namelist()) == set(after.namelist())
            for name in before.namelist():
                if not name.endswith('/') and name != case['path']:
                    assert before.read(name) == after.read(name), (case['kind'], case['action'], name)
                if name.endswith(('.xml', '.rels')):
                    etree.fromstring(after.read(name))
            root = etree.fromstring(after.read(case['path']))
            assert not root.xpath('//w:del|//w:ins', namespaces=ns)
            assert root.xpath('//w:bookmarkStart/@w:name', namespaces=ns) == ['sentinel']
            text = ''.join(root.xpath('//w:t/text()', namespaces=ns))
            assert text == ('keepold text' if case['action'] == 'reject' else 'keep')
