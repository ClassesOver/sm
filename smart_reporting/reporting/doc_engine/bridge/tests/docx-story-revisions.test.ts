import assert from 'node:assert/strict'
import {test} from 'node:test'
import JSZip from 'jszip'
import {parseDocx,saveDocx} from '../../packages/docx-engine/src/index.ts'
import {buildDocx} from '../../packages/docx-engine/tests/helpers/build-docx.ts'
import {inspectStoryRevisions,resolveStoryRevisions} from '../docx-story-revisions.ts'
const ns='xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
const ins='<w:ins w:id="7" w:author="Ann"><w:r><w:t>new</w:t></w:r></w:ins>'
const del='<w:del w:id="8" w:author="Bob"><w:r><w:delText>old</w:delText></w:r></w:del>'
const fixture=async(kind='footnote',payload=ins+del)=>{
 const note=kind==='footnote'||kind==='endnote',path=note?`word/${kind}s.xml`:'word/header1.xml'
 const xml=note?`<w:${kind}s ${ns}><w:${kind} w:id="2"><w:p><w:r><w:${kind}Ref/></w:r>${payload}</w:p></w:${kind}><w:${kind} w:id="3"><w:p><w:r><w:t>sentinel note</w:t></w:r></w:p></w:${kind}></w:${kind}s>`:`<w:hdr ${ns}><w:p>${payload}<w:bookmarkStart w:id="42" w:name="keep"/></w:p></w:hdr>`
 const bytes=await buildDocx({bodyXml:note?`<w:p><w:r><w:${kind}Reference w:id="2"/></w:r></w:p>`:'<w:p><w:r><w:t>body</w:t></w:r></w:p>',extraRels:`<Relationship Id="rId40" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/${note?kind+'s':'header'}" Target="${note?kind+'s.xml':'header1.xml'}"/>`,sectPrExtra:note?'':'<w:headerReference w:type="default" r:id="rId40"/>',extraParts:[{path,xml,contentType:note?`application/vnd.openxmlformats-officedocument.wordprocessingml.${kind}s+xml`:'application/vnd.openxmlformats-officedocument.wordprocessingml.header+xml'},{path:'customXml/keep.xml',xml:'<keep>opaque</keep>',contentType:'application/xml'}]})
 return{bytes,parsed:await parseDocx(bytes),path,xml}
}
test('story decisions save through source models and independently reopen actual parts',async()=>{
 for(const kind of ['footnote','endnote','header'])for(const action of ['accept','reject'] as const){
  const{bytes,parsed,path}=await fixture(kind),info=await inspectStoryRevisions(parsed);assert.equal(info.targets.length,2)
  const target=info.targets[0];assert.equal(target.partPath,path);assert.equal(target.originalRevisionId,'7')
  const options=await resolveStoryRevisions(parsed,[{targetId:target.targetId,expectedPartSha256:target.expectedPartSha256,expectedWrapperSha256:target.expectedWrapperSha256,action}])
  const out=await saveDocx(parsed,parsed.blocks.filter(b=>!b.hidden).map(b=>({kind:'original',docxIndex:b.docxIndex!})),options)
  const zip=await JSZip.loadAsync(out),xml=await zip.file(path)!.async('string');assert.ok(!xml.includes('<w:ins'));assert.ok(xml.includes(del));assert.equal(xml.includes('<w:t>new</w:t>'),action==='accept');assert.ok(kind==='header'?xml.includes('w:name="keep"'):xml.includes('sentinel note'))
  assert.equal(await zip.file('customXml/keep.xml')!.async('string'),'<keep>opaque</keep>')
  const before=await JSZip.loadAsync(bytes);assert.equal(await zip.file('word/document.xml')!.async('string'),await before.file('word/document.xml')!.async('string'))
  assert.equal((await inspectStoryRevisions(await parseDocx(out))).targets.length,1)
 }
})
test('rejects stale identities, extra payload, duplicate operations and duplicate source ids atomically',async()=>{
 const{parsed}=await fixture(),target=(await inspectStoryRevisions(parsed)).targets[0],op={targetId:target.targetId,expectedPartSha256:target.expectedPartSha256,expectedWrapperSha256:target.expectedWrapperSha256,action:'accept' as const}
 for(const bad of [{...op,expectedPartSha256:'stale'},{...op,expectedWrapperSha256:'stale'},{...op,xml:'injected'},{...op,targetId:'foreign'}])await assert.rejects(resolveStoryRevisions(parsed,[op,bad] as any))
 await assert.rejects(resolveStoryRevisions(parsed,[op,op]));assert.ok(!parsed.footnotes[0].revisionsResolved)
 const duplicate=await fixture('footnote',ins+ins);const info=await inspectStoryRevisions(duplicate.parsed);assert.equal(info.targets.length,0);assert.ok(info.readOnly.some(r=>r.reason==='docx_story_revision_id_ambiguous'))
})
test('independent output verifier rejects non-target ZIP tampering and missing decisions',async()=>{
 const{parsed,bytes}=await fixture(),target=(await inspectStoryRevisions(parsed)).targets[0],op={targetId:target.targetId,expectedPartSha256:target.expectedPartSha256,expectedWrapperSha256:target.expectedWrapperSha256,action:'accept' as const}
 const{verifyStoryRevisionOutput}=await import('../docx-story-revisions.ts'),options=await resolveStoryRevisions(parsed,[op]),out=await saveDocx(parsed,parsed.blocks.filter(b=>!b.hidden).map(b=>({kind:'original',docxIndex:b.docxIndex!})),options)
 assert.equal((await verifyStoryRevisionOutput(parsed,[op],out)).verified,true)
 await assert.rejects(verifyStoryRevisionOutput(parsed,[op],bytes))
 const zip=await JSZip.loadAsync(out);zip.file('customXml/keep.xml','<tampered/>');await assert.rejects(verifyStoryRevisionOutput(parsed,[op],await zip.generateAsync({type:'uint8array'})))
})
test('verifies only the source writer timestamp and revision increment in core metadata',async()=>{
 const source=await fixture(),zip=await JSZip.loadAsync(source.bytes);zip.file('docProps/core.xml','<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dcterms="http://purl.org/dc/terms/"><cp:revision>4</cp:revision><dcterms:modified>2026-01-01T00:00:00Z</dcterms:modified><cp:keywords>keep</cp:keywords></cp:coreProperties>')
 const parsed=await parseDocx(await zip.generateAsync({type:'uint8array'})),target=(await inspectStoryRevisions(parsed)).targets[0],ops=[{targetId:target.targetId,expectedPartSha256:target.expectedPartSha256,expectedWrapperSha256:target.expectedWrapperSha256,action:'accept' as const}],options=await resolveStoryRevisions(parsed,ops),out=await saveDocx(parsed,parsed.blocks.filter(b=>!b.hidden).map(b=>({kind:'original',docxIndex:b.docxIndex!})),options)
 const{verifyStoryRevisionOutput}=await import('../docx-story-revisions.ts');assert.equal((await verifyStoryRevisionOutput(parsed,ops,out)).verified,true)
 const tampered=await JSZip.loadAsync(out);tampered.file('docProps/core.xml',(await tampered.file('docProps/core.xml')!.async('string')).replace('keep','forged'));await assert.rejects(verifyStoryRevisionOutput(parsed,ops,await tampered.generateAsync({type:'uint8array'})))
})
test('unsupported note serialization boundaries remain read-only',async()=>{
 const source=await fixture(),zip=await JSZip.loadAsync(source.bytes),xml=await zip.file('word/footnotes.xml')!.async('string')
 for(const extra of ['<w:footnote w:id="9"/>','<w:footnote w:id="2"><w:p><w:r><w:t>duplicate note id</w:t></w:r></w:p></w:footnote>']){
  zip.file('word/footnotes.xml',xml.replace('</w:footnotes>',extra+'</w:footnotes>'))
  const info=await inspectStoryRevisions(await parseDocx(await zip.generateAsync({type:'uint8array'})));assert.equal(info.targets.length,0);assert.ok(info.readOnly.length)
 }
})
