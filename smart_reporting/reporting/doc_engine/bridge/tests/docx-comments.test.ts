import assert from 'node:assert/strict'
import {test} from 'node:test'
import {createHash} from 'node:crypto'
import {execFileSync} from 'node:child_process'
import {mkdtempSync,writeFileSync,rmSync} from 'node:fs'
import {tmpdir} from 'node:os'
import {join} from 'node:path'
import {buildDocx} from '../../packages/docx-engine/tests/helpers/build-docx.ts'
import {loadDocxZip} from '../../packages/docx-engine/src/zip-load.ts'
import {inspectCommentText,resolveCommentText,type CommentTextSource} from '../docx-comments.ts'
const w='http://schemas.openxmlformats.org/wordprocessingml/2006/main',w14='http://schemas.microsoft.com/office/word/2010/wordml'
const first='<w:comment w:id="1" w:author="甲 &amp; Alice" w:date="2026-11-11T00:00:00Z" w:initials="AL"><w:p w14:paraId="ABCDEF01" w:rsidR="12345678"><w:pPr><w:keepNext/></w:pPr><w:hyperlink r:id="rId5"><w:r><w:rPr><w:i/></w:rPr><w:t>旧😀 &amp; 文本</w:t></w:r></w:hyperlink></w:p></w:comment>'
const second='<w:comment w:id="2" w:author="Bob"><w:p w14:paraId="ABCDEF02"><w:r><w:t>First</w:t></w:r></w:p><w:p><w:r><w:t>Second</w:t></w:r></w:p></w:comment>'
const wrap=(a=first,b=second)=>`<?xml version="1.0" encoding="UTF-8"?><w:comments xmlns:w="${w}" xmlns:w14="${w14}" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" xmlns:x="urn:sentinel">\n<x:before x:v="keep"/>\n${a}\n<x:between/>${b}<x:after>opaque</x:after>\n</w:comments>`
const source=(xml=wrap()):CommentTextSource=>({sourceId:'authorized-doc-version-and-anchor-snapshot',commentsXml:xml,protectedDocument:false})
const info=(s=source())=>inspectCommentText(s)
const operation=(s=source(),index=0,text='新😁 & <文本>')=>{const t=info(s).commentTargets[index];return{kind:'editCommentText' as const,sourceId:s.sourceId,targetId:t.targetId,expectedCommentsSha256:t.expectedCommentsSha256,expectedObjectSha256:t.expectedObjectSha256,text}}
test('source-bound identities and surgical rich text edits preserve all surrounding bytes',()=>{
 const s=source(),a=info(s);assert.equal(a.commentReadOnlyReason,null);assert.equal(a.commentTargets.length,2);assert.equal(a.commentTargets[0].text,'旧😀 & 文本');assert.equal(a.commentTargets[1].text,'First\nSecond');assert.equal(a.commentTargets[0].author,'甲 & Alice')
 assert.deepEqual(info(s),a);assert.notEqual(info({...s,sourceId:'foreign'}).commentTargets[0].targetId,a.commentTargets[0].targetId)
 const out=resolveCommentText(s,[operation(s)]);assert.equal(out.xml,s.commentsXml.replace('<w:t>旧😀 &amp; 文本</w:t>','<w:t xml:space="preserve">新😁 &amp; &lt;文本&gt;</w:t>'));assert.equal(s.commentsXml,wrap())
 assert.notEqual(info(source(wrap(first,second.replace('Second','Changed')))).commentTargets[0].targetId,a.commentTargets[0].targetId)
})
test('whole batch validates before patch; stale foreign duplicate and unknown fields fail',()=>{
 const s=source(),a=operation(s),b=operation(s,1,'One\nTwo')
 assert.equal(inspectCommentText({...s,commentsXml:resolveCommentText(s,[a,b]).xml}).commentTargets[1].text,'One\nTwo')
 for(const bad of [{...b,targetId:'missing'},{...b,sourceId:'foreign'},{...b,expectedCommentsSha256:'bad'},{...b,expectedObjectSha256:'bad'},{...b,part:'word/document.xml'},{...b,kind:'resolve'},a,{...a,text:'different'}])assert.throws(()=>resolveCommentText(s,[a,bad] as any))
 assert.throws(()=>resolveCommentText(s,[]));assert.equal(s.commentsXml,wrap())
})
test('empty text, emoji, entities and existing paragraphs are supported; paragraph changes and invalid XML characters fail',()=>{
 for(const text of ['', '😀😁 & < > " 中文\t ', '旧😁 & 文本']){const s=source(),out=resolveCommentText(s,[operation(s,0,text)]);assert.equal(info({...s,commentsXml:out.xml}).commentTargets[0].text,text)}
 const s=source();assert.equal(info({...s,commentsXml:resolveCommentText(s,[operation(s,1,'\n中文😀')]).xml}).commentTargets[1].text,'\n中文😀')
 for(const text of ['one\ntwo','\u0000','\ud800','\udfff','\ufffe','a\rb'])assert.throws(()=>resolveCommentText(s,[operation(s,0,text)]))
 const noOp=resolveCommentText(s,[operation(s,0,info(s).commentTargets[0].text)]);assert.equal(noOp.xml,s.commentsXml)
})
test('global ambiguous identity, protection and namespace errors produce no targets',()=>{
 for(const s of [{...source(),protectedDocument:true},source(wrap(first,first)),source(wrap(first,second.replace('ABCDEF02','ABCDEF01'))),source(wrap().replace(`xmlns:w="${w}"`,'xmlns:w="foreign"')),source(wrap().replace(' w:id="1"','')),source(wrap().replace('</w:comments>',''))]){const a=info(s);assert.ok(a.commentReadOnlyReason);assert.equal(a.commentTargets.length,0);assert.throws(()=>resolveCommentText(s,[operation()]))}
})
test('unsupported target structures stay read-only without authorizing loss of formatting or namespace semantics',()=>{
 for(const replacement of ['<w:drawing/>','<w:fldChar w:fldCharType="begin"/>','<w:ins w:id="9"/>','<w:tab/>','<x:unknown/>','<w:rPrChange/>']){
  const s=source(wrap(first.replace('<w:t>',replacement+'<w:t>'))),a=info(s);assert.ok(a.commentTargets[0].readOnlyReason);assert.equal(a.commentTargets[0].editableText,false);assert.throws(()=>resolveCommentText(s,[operation(s)]));assert.equal(a.commentTargets[1].editableText,true)
 }
 for(const xml of [first.replace('<w:p ','<w:p xmlns:w="foreign" '),first.replace('<w:t>','<w:t w:custom="keep">'),first.replace('<w:t>旧😀 &amp; 文本</w:t>','<w:t/>'),first.replace('<w:i/>','<w:custom/>')]){const s=source(wrap(xml));assert.equal(info(s).commentTargets[0].editableText,false);assert.throws(()=>resolveCommentText(s,[operation(s)]))}
})
test('actual DOCX keeps modern parts, relationships and raw unknown neighbors; independent ZIP/lxml verifies output',async()=>{
 const s=source(),bytes=await buildDocx({bodyXml:'<w:p w:rsidR="AABB"><w:commentRangeStart w:id="1"/><w:r><w:t>Anchor</w:t></w:r><w:commentRangeEnd w:id="1"/><w:r><w:commentReference w:id="1"/></w:r></w:p>',extraRels:'<Relationship Id="rId40" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/comments" Target="comments.xml"/>',extraParts:[{path:'word/comments.xml',xml:s.commentsXml,contentType:'application/vnd.openxmlformats-officedocument.wordprocessingml.comments+xml'},...['commentsExtended','commentsIds','commentsExtensible','people'].map(name=>({path:`word/${name}.xml`,xml:`<x:${name} xmlns:x="urn:opaque"><x:keep/></x:${name}>`,contentType:'application/xml'})),{path:'word/_rels/comments.xml.rels',xml:'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId5" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink" Target="https://example.test" TargetMode="External"/></Relationships>',contentType:'application/vnd.openxmlformats-package.relationships+xml'}]})
 const zip=await loadDocxZip(bytes),original=await loadDocxZip(bytes),out=resolveCommentText(s,[operation(s),operation(s,1,'One\nTwo')]);zip.file('word/comments.xml',out.xml);const saved=await zip.generateAsync({type:'uint8array',compression:'DEFLATE'}),reopened=await loadDocxZip(saved)
 for(const n of Object.keys(original.files))if(!original.files[n].dir&&n!=='word/comments.xml')assert.deepEqual(await original.file(n)!.async('uint8array'),await reopened.file(n)!.async('uint8array'))
 const dir=mkdtempSync(join(tmpdir(),'docx-comments-'));try{writeFileSync(join(dir,'source.docx'),bytes);writeFileSync(join(dir,'edited.docx'),saved);writeFileSync(join(dir,'expected.xml'),out.xml);execFileSync('/home/junge/pros/smart_reporting/.venv/bin/python',['-c',`import sys,zipfile\nfrom lxml import etree as E\np=sys.argv[1]\nwith zipfile.ZipFile(p+'/source.docx') as a,zipfile.ZipFile(p+'/edited.docx') as b:\n assert b.testzip() is None\n for n in b.namelist():\n  if n.endswith(('.xml','.rels')): E.fromstring(b.read(n))\n assert [n for n in a.namelist() if a.read(n)!=b.read(n)]==['word/comments.xml']\n assert b.read('word/comments.xml')==open(p+'/expected.xml','rb').read()\n ns={'w':'${w}','x':'urn:sentinel'}\n r=E.fromstring(b.read('word/comments.xml'))\n assert len(r.findall('x:before',ns))==len(r.findall('x:between',ns))==len(r.findall('x:after',ns))==1\n assert r.find('.//w:hyperlink',ns) is not None\n assert r.find('.//w:i',ns) is not None`,dir])}finally{rmSync(dir,{recursive:true,force:true})}
 assert.equal(createHash('sha256').update(out.xml).digest('hex').length,64)
})
test('XML entity spelling, numeric characters and prefix rebinding cannot bypass safe target checks',()=>{
 for(const bad of ['&bogus;','&#0;','&#xD800;','&#x110000;','&#65534;']){
  const s=source(wrap(first.replace('旧😀 &amp; 文本',bad)));const a=info(s);assert.ok(a.commentReadOnlyReason||a.commentTargets[0].readOnlyReason,bad);assert.throws(()=>resolveCommentText(s,[operation()]))
 }
 for(const xml of [first.replace('<w:p ','<w:p xmlns:r="foreign" '),first.replace('w:id="1"','w:id="01"')]){
  const s=source(wrap(xml));assert.ok(info(s).commentReadOnlyReason||info(s).commentTargets[0].readOnlyReason)
 }
 const s=source(wrap(first.replace('旧😀 &amp; 文本','&#x1F600; &lt; &#38;')));assert.equal(info(s).commentTargets[0].text,'😀 < &');assert.equal(info({...s,commentsXml:resolveCommentText(s,[operation(s,0,'😁 & >')]).xml}).commentTargets[0].text,'😁 & >')
})
test('literal or referenced line breaks inside a run are read-only rather than guessed as paragraph separators',()=>{
 for(const text of ['Line\nBreak','Line\rBreak','Line&#10;Break','Line&#13;Break']){const s=source(wrap(first.replace('旧😀 &amp; 文本',text)));assert.equal(info(s).commentTargets[0].editableText,false,text)}
})
