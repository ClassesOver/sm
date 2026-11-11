import assert from 'node:assert/strict'
import {test} from 'node:test'
import JSZip from 'jszip'
import {buildDocx} from '../../packages/docx-engine/tests/helpers/build-docx.ts'
import {inspectDocxCrossReferences,patchDocxCrossReference} from '../docx-cross-reference.ts'
const body='<w:p><w:bookmarkStart w:id="1" w:name="Target"/><w:r><w:t>可信 😀 &amp; 原文</w:t></w:r><w:bookmarkEnd w:id="1"/></w:p><w:p data-opaque="keep"><w:pPr><w:keepNext/></w:pPr><w:r><w:rPr><w:b/></w:rPr><w:t>Alpha 😀 Beta</w:t></w:r><w:r><w:t> end</w:t></w:r></w:p>'
async function fixture(bodyXml=body){const bytes=await buildDocx({bodyXml,extraParts:[{path:'word/opaque.xml',xml:'<keep xmlns="urn:unknown">unchanged</keep>',contentType:'application/xml'}]}),model=await inspectDocxCrossReferences(bytes),t=model.targets[1];return{bytes,model,op:{kind:'insertCrossReference' as const,sourceId:model.sourceId!,bookmarkId:model.bookmarks[0]?.bookmarkId??'a'.repeat(64),targetId:t?.targetId??'b'.repeat(64),expectedParagraphSha256:t?.expectedParagraphSha256??'c'.repeat(64),offset:6}}}
test('writes real REF with trusted cache and preserves formatting and every other ZIP part',async()=>{
 const {bytes,model,op}=await fixture();assert.equal(model.readOnlyReason,null)
 const output=await patchDocxCrossReference(bytes,op),before=await JSZip.loadAsync(bytes),after=await JSZip.loadAsync(output),xml=await after.file('word/document.xml')!.async('string')
 assert.ok(xml.includes(' REF Target '+String.fromCharCode(92)+'h '));for(const type of ['begin','separate','end'])assert.ok(xml.includes('<w:fldChar w:fldCharType="'+type+'"/>'))
 assert.ok(xml.includes('<w:t xml:space="preserve">可信 😀 &amp; 原文</w:t>'));assert.ok(xml.includes('<w:p data-opaque="keep"><w:pPr><w:keepNext/></w:pPr>'));assert.equal(xml.split('<w:rPr><w:b/></w:rPr>').length-1,2)
 assert.deepEqual(Object.keys(after.files).sort(),Object.keys(before.files).sort());for(const f of Object.values(before.files))if(!f.dir&&f.name!=='word/document.xml')assert.deepEqual(await after.file(f.name)!.async('uint8array'),await f.async('uint8array'),f.name)
 assert.equal((await inspectDocxCrossReferences(output)).readOnlyReason,null)
})
test('rejects forged identity, client cache/XML, surrogate cuts and self-reference',async()=>{
 const {bytes,op,model}=await fixture()
 for(const bad of [{...op,sourceId:'f'.repeat(64)},{...op,bookmarkId:'f'.repeat(64)},{...op,targetId:'f'.repeat(64)},{...op,expectedParagraphSha256:'f'.repeat(64)},{...op,preview:'forged'},{...op,genXml:'<w:r/>'},{...op,offset:7},{...op,offset:-1},{...op,offset:99},{...op,offset:1.5},{...op,targetId:model.targets[0].targetId,expectedParagraphSha256:model.targets[0].expectedParagraphSha256,offset:1}])await assert.rejects(patchDocxCrossReference(bytes,bad as any))
})
test('rejects duplicate names, cross-paragraph or complex bookmarks and cross-story collisions',async()=>{
 const duplicate=body.replace('<w:p data-opaque','<w:p><w:bookmarkStart w:id="2" w:name="Target"/><w:r><w:t>x</w:t></w:r><w:bookmarkEnd w:id="2"/></w:p><w:p data-opaque')
 const dup=await fixture(duplicate);assert.ok(dup.model.readOnlyReason);await assert.rejects(patchDocxCrossReference(dup.bytes,dup.op))
 const crossing=await fixture(body.replace('<w:bookmarkEnd w:id="1"/>','').replace(' end</w:t></w:r>',' end</w:t></w:r><w:bookmarkEnd w:id="1"/>'));assert.ok(crossing.model.bookmarks[0].readOnlyReason);await assert.rejects(patchDocxCrossReference(crossing.bytes,crossing.op))
 const complex=await fixture(body.replace('<w:r><w:t>可信 😀 &amp; 原文</w:t></w:r>','<w:hyperlink w:anchor="X"><w:r><w:t>可信</w:t></w:r></w:hyperlink>'));assert.ok(complex.model.bookmarks[0].readOnlyReason);await assert.rejects(patchDocxCrossReference(complex.bytes,complex.op))
 const bytes=await buildDocx({bodyXml:body,headerXml:'<w:p><w:bookmarkStart w:id="8" w:name="Target"/><w:r><w:t>header</w:t></w:r><w:bookmarkEnd w:id="8"/></w:p>'}),m=await inspectDocxCrossReferences(bytes);assert.ok(m.readOnlyReason)
})
test('supports empty paragraph and refuses protected sources',async()=>{
 const f=await fixture(body.slice(0,body.indexOf('<w:p data-opaque'))+'<w:p/>');const output=await patchDocxCrossReference(f.bytes,{...f.op,offset:0});assert.ok((await(await JSZip.loadAsync(output)).file('word/document.xml')!.async('string')).includes('<w:p><w:r><w:fldChar'))
 const bytes=await buildDocx({bodyXml:body,extraRels:'<Relationship Id="rSettings" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/settings" Target="settings.xml"/>',extraParts:[{path:'word/settings.xml',xml:'<w:settings xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:documentProtection w:enforcement="1"/></w:settings>',contentType:'application/vnd.openxmlformats-officedocument.wordprocessingml.settings+xml'}]}),m=await inspectDocxCrossReferences(bytes);assert.ok(m.readOnlyReason);await assert.rejects(patchDocxCrossReference(bytes,{...f.op,sourceId:m.sourceId!}))
})
test('preserves quoted greater-than attributes and text-run metadata during a split',async()=>{
 const {bytes,op}=await fixture(body.replace('data-opaque="keep"','data-opaque="keep>value"').replace('<w:t>Alpha','<w:t data-opaque="keep&gt;meta" xml:space="preserve">Alpha'))
 const xml=await(await JSZip.loadAsync(await patchDocxCrossReference(bytes,op))).file('word/document.xml')!.async('string')
 assert.ok(xml.includes('data-opaque="keep>value"'));assert.equal(xml.split('data-opaque="keep&gt;meta"').length-1,2)
})
test('rejects local Word namespace rebinding before accepting a paragraph or bookmark identity',async()=>{
 const {bytes,model,op}=await fixture(body.replace('<w:p data-opaque="keep">','<w:p xmlns:w="urn:fake" data-opaque="keep">'))
 assert.ok(model.readOnlyReason);await assert.rejects(patchDocxCrossReference(bytes,op))
})
test('never rewrites attribute-like text inside unrelated metadata while preserving split whitespace',async()=>{
 const marker='data-opaque="xml:space='+String.fromCharCode(39)+'trap'+String.fromCharCode(39)+'"',f=await fixture(body.replace('<w:t>Alpha','<w:t '+marker+' xml:space="default">Alpha'))
 const xml=await(await JSZip.loadAsync(await patchDocxCrossReference(f.bytes,f.op))).file('word/document.xml')!.async('string')
 assert.equal(xml.split(marker).length-1,2);assert.ok(xml.includes('xml:space="preserve">Alpha '))
})
test('does not mistake a longer XML metadata attribute for xml:space',async()=>{
 const f=await fixture(body.replace('<w:t>Alpha','<w:t xml:spaceExtra="metadata">Alpha'))
 const xml=await(await JSZip.loadAsync(await patchDocxCrossReference(f.bytes,f.op))).file('word/document.xml')!.async('string')
 assert.equal(xml.split('xml:spaceExtra="metadata"').length-1,2);assert.ok(xml.includes('xml:space="preserve">Alpha '))
})
test('decodes numeric XML entities once and remaps bookmark offsets to real UTF16 boundaries',async()=>{
 const encoded='<w:p><w:r><w:t>prefix &#22270;</w:t></w:r><w:bookmarkStart w:id="1" w:name="Target"/><w:r><w:t>&#x1F600;&#38;lt;</w:t></w:r><w:bookmarkEnd w:id="1"/><w:r><w:t> suffix</w:t></w:r></w:p><w:p><w:r><w:t>A&#x1F600;B</w:t></w:r></w:p>',f=await fixture(encoded),r=f.model.bookmarks[0].ranges[0]
 assert.equal(f.model.targets[0].text,'prefix 图😀&lt; suffix');assert.deepEqual({from:r.from,to:r.to,text:r.text},{from:8,to:14,text:'😀&lt;'})
 const xml=await(await JSZip.loadAsync(await patchDocxCrossReference(f.bytes,{...f.op,offset:3}))).file('word/document.xml')!.async('string')
 assert.ok(xml.includes('<w:t xml:space="preserve">A😀</w:t>'));assert.ok(xml.includes('<w:t xml:space="preserve">😀&amp;lt;</w:t>'));assert.ok(xml.includes('<w:t xml:space="preserve">B</w:t>'))
 await assert.rejects(patchDocxCrossReference(f.bytes,{...f.op,offset:2}))
})

test('refuses literal entity sources when the existing editor would double-decode their display',async()=>{
 const f=await fixture(body.replace('可信 😀 &amp; 原文','&amp;#22270;'));assert.equal(f.model.bookmarks[0].ranges[0].text,'&#22270;');assert.ok(f.model.readOnlyReason);await assert.rejects(patchDocxCrossReference(f.bytes,f.op))
})
