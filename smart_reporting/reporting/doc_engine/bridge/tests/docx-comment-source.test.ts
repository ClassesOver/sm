import assert from 'node:assert/strict'
import {test} from 'node:test'
import {createHash} from 'node:crypto'
import {execFileSync} from 'node:child_process'
import {mkdirSync,writeFileSync} from 'node:fs'
import JSZip from 'jszip'
import {buildDocx} from '../../packages/docx-engine/tests/helpers/build-docx.ts'
import {inspectDocxCommentSource,patchDocxCommentSource} from '../docx-comment-source.ts'
const W='http://schemas.openxmlformats.org/wordprocessingml/2006/main',R='http://schemas.openxmlformats.org/officeDocument/2006/relationships',P='http://schemas.openxmlformats.org/package/2006/relationships'
const comments=`<w:comments xmlns:w="${W}" xmlns:r="${R}"><w:comment w:id="1" w:author="Alice"><w:p><w:hyperlink r:id="rId9"><w:r><w:rPr><w:i/></w:rPr><w:t>旧😀</w:t></w:r></w:hyperlink></w:p></w:comment></w:comments>`
const anchors='<w:p><w:commentRangeStart w:id="1"/><w:r><w:t>Anchor</w:t></w:r><w:commentRangeEnd w:id="1"/><w:r><w:commentReference w:id="1"/></w:r></w:p>'
const rel=(id:string,type:string,target:string,mode='')=>`<Relationship Id="${id}" Type="${R}/${type}" Target="${target}"${mode?` TargetMode="${mode}"`:''}/>`
async function fixture(){return buildDocx({bodyXml:anchors,extraRels:rel('rId8','comments','comments.xml'),extraParts:[{path:'word/comments.xml',xml:comments,contentType:'application/vnd.openxmlformats-officedocument.wordprocessingml.comments+xml'},{path:'word/_rels/comments.xml.rels',xml:`<Relationships xmlns="${P}">${rel('rId9','hyperlink','https://example.test/x','External')}</Relationships>`,contentType:'application/vnd.openxmlformats-package.relationships+xml'},...['commentsExtended','commentsIds','commentsExtensible','people'].map(n=>({path:`word/${n}.xml`,xml:`<x:${n} xmlns:x="urn:opaque"><x:unknown keep="yes"/></x:${n}>`,contentType:'application/xml'}))]})}
async function change(bytes:Uint8Array,path:string,edit:(s:string)=>string){const zip=await JSZip.loadAsync(bytes);zip.file(path,edit(await zip.file(path)!.async('string')));return zip.generateAsync({type:'uint8array'})}
const op=(model:any,text='新😀 & 中文')=>({kind:'editCommentText' as const,sourceId:model.sourceId,targetId:model.commentTargets[0].targetId,expectedCommentsSha256:model.commentTargets[0].expectedCommentsSha256,expectedObjectSha256:model.commentTargets[0].expectedObjectSha256,text})
async function denied(bytes:Uint8Array,reason?:RegExp){const before=Buffer.from(bytes),m=await inspectDocxCommentSource(bytes);assert.ok(m.commentReadOnlyReason||m.commentTargets.some(t=>!t.editableText));if(reason)assert.match(m.commentReadOnlyReason??m.commentTargets[0].readOnlyReason!,reason);await assert.rejects(patchDocxCommentSource(bytes,[{kind:'editCommentText',sourceId:'forged',targetId:'forged',expectedCommentsSha256:'forged',expectedObjectSha256:'forged',text:'x'}]));assert.deepEqual(Buffer.from(bytes),before)}
test('authorized raw DOCX exposes source-bound targets; only actual comments part changes, independently verified',async()=>{
 const bytes=await fixture(),before=Buffer.from(bytes),model=await inspectDocxCommentSource(bytes);assert.equal(model.commentReadOnlyReason,null);assert.equal(model.commentTargets[0].editableText,true);assert.equal(model.sourceSha256,createHash('sha256').update(bytes).digest('hex'))
 const saved=await patchDocxCommentSource(bytes,[op(model)]),again=await inspectDocxCommentSource(saved);assert.equal(again.commentTargets[0].text,'新😀 & 中文');assert.notEqual(again.sourceId,model.sourceId);await assert.rejects(patchDocxCommentSource(saved,[op(model)]))
 const dir='/tmp/word-comment-source-evidence';mkdirSync(dir,{recursive:true});writeFileSync(dir+'/source.docx',bytes);writeFileSync(dir+'/edited.docx',saved);writeFileSync(dir+'/model.json',JSON.stringify(model,null,2))
 const evidence=execFileSync('/home/junge/pros/smart_reporting/.venv/bin/python',['-c',`import sys,zipfile,json\nfrom lxml import etree as E\np=sys.argv[1]\nwith zipfile.ZipFile(p+'/source.docx') as a,zipfile.ZipFile(p+'/edited.docx') as b:\n assert a.namelist()==b.namelist()\n changed=[n for n in a.namelist() if a.read(n)!=b.read(n)]\n assert changed==['word/comments.xml'],changed\n for n in b.namelist():\n  if n.endswith(('.xml','.rels')): E.fromstring(b.read(n))\n ns={'w':'${W}'};r=E.fromstring(b.read('word/comments.xml'));assert r.find('.//w:i',ns) is not None;assert r.find('.//w:hyperlink',ns) is not None\n assert ''.join(r.itertext())=='新😀 & 中文'\n print(json.dumps({'changed':changed,'parts':len(a.namelist()),'all_xml_valid':True}))`,dir],{encoding:'utf8'});writeFileSync(dir+'/zip-lxml.json',evidence)
 const invalid=[op(model),{...op(model),targetId:'late-invalid'}];await assert.rejects(patchDocxCommentSource(bytes,invalid));assert.deepEqual(Buffer.from(bytes),before)
})
test('package/document/comment relationships reject duplicate Id, wrong namespace, DTD, mode, type and actual path drift',async()=>{
 const bytes=await fixture()
 for(const [path,edit] of [
 ['_rels/.rels',(s:string)=>s.replace('</Relationships>',rel('duplicate','officeDocument','word/document.xml')+'</Relationships>')],
 ['word/_rels/document.xml.rels',(s:string)=>s.replace('</Relationships>',rel('rId8','styles','styles.xml')+'</Relationships>')],
 ['word/_rels/document.xml.rels',(s:string)=>s.replace('Target="comments.xml"','Target="comments.xml" TargetMode="External"')],
 ['word/_rels/document.xml.rels',(s:string)=>s.replace('Target="comments.xml"','Target="other.xml"')],
 ['word/_rels/document.xml.rels',(s:string)=>s.replace('<Relationship Id="rId8"','<Relationship xmlns="urn:bad" Id="rId8"')],
 ['word/_rels/document.xml.rels',(s:string)=>s.replace('<Relationships ','<!DOCTYPE Relationships [<!ENTITY x "x">]><Relationships ')],
 ['word/_rels/comments.xml.rels',(s:string)=>s.replace('TargetMode="External"','TargetMode="external"')],
 ['word/_rels/comments.xml.rels',(s:string)=>s.replace('/hyperlink"','/styles"')],
 ['word/_rels/comments.xml.rels',(s:string)=>s.replace('https://example.test/x','https://u:p@example.test')],
 ['[Content_Types].xml',(s:string)=>s.replace('wordprocessingml.comments+xml','wordprocessingml.settings+xml')],
 ] as const)await denied(await change(bytes,path,edit))
})
test('actual settings protection including aliased/entity enforcement is read-only; malformed and hidden settings reject',async()=>{
 const original=await fixture(),zip=await JSZip.loadAsync(original)
 zip.file('word/_rels/document.xml.rels',(await zip.file('word/_rels/document.xml.rels')!.async('string')).replace('</Relationships>',rel('settings','settings','settings.xml')+'</Relationships>'))
 zip.file('[Content_Types].xml',(await zip.file('[Content_Types].xml')!.async('string')).replace('</Types>','<Override PartName="/word/settings.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.settings+xml"/></Types>'))
 for(const enforcement of ['1','true','&#49;','unknown','']){zip.file('word/settings.xml',`<s:settings xmlns:s="${W}"><s:documentProtection${enforcement?` s:enforcement="${enforcement}"`:''}/></s:settings>`);await denied(await zip.generateAsync({type:'uint8array'}))}
 zip.file('word/settings.xml',`<w:settings xmlns:w="${W}"><w:documentProtection w:enforcement="0"/></w:settings>`);assert.equal((await inspectDocxCommentSource(await zip.generateAsync({type:'uint8array'}))).commentReadOnlyReason,null)
 zip.remove('word/settings.xml');await denied(await zip.generateAsync({type:'uint8array'}))
 const hidden=await JSZip.loadAsync(original);hidden.file('word/settings.xml',`<w:settings xmlns:w="${W}"/>`);await denied(await hidden.generateAsync({type:'uint8array'}))
})
test('anchors must be a unique real ordered range/reference in main story; internal links remain read-only',async()=>{
 const bytes=await fixture()
 for(const body of [anchors.replace('<w:commentRangeEnd w:id="1"/>',''),anchors+anchors,anchors.replace('w:id="1"','w:id="2"'),anchors.replace('<w:commentRangeStart w:id="1"/>','<w:commentRangeEnd w:id="1"/>'),anchors.replace('<w:commentRangeStart w:id="1"/>','<w:commentRangeStart xmlns:w="urn:bad" w:id="1"/>')])await denied(await change(bytes,'word/document.xml',s=>s.replace(anchors,body)))
 await denied(await change(bytes,'word/comments.xml',s=>s.replace('r:id="rId9"','w:anchor="bookmark"')))
 const zip=await JSZip.loadAsync(bytes);zip.file('word/header99.xml',`<w:hdr xmlns:w="${W}"><w:p><w:commentReference w:id="1"/></w:p></w:hdr>`);await denied(await zip.generateAsync({type:'uint8array'}))
 const drift=await change(bytes,'word/document.xml',s=>s.replace('Anchor','Different'));assert.notEqual((await inspectDocxCommentSource(drift)).sourceId,(await inspectDocxCommentSource(bytes)).sourceId)
})
test('raw versus normalized changes are read-only and malformed UTF8 is never signed',async()=>{
 const bytes=await fixture();await denied(await change(bytes,'word/comments.xml',s=>s.replace('<w:p>','<w:p><w:pPr><w:pStyle w:val="a"/><w:pStyle w:val="b"/></w:pPr>')),/normaliz/)
 const zip=await JSZip.loadAsync(bytes);zip.file('word/comments.xml',Uint8Array.from([...Buffer.from(comments),0xff]));await denied(await zip.generateAsync({type:'uint8array'}))
})
test('actual central directory duplicates, UTF8 duplicates and Unicode path extra fields reject before JSZip aliasing',async()=>{
 const bytes=await fixture(),dir='/tmp/word-comment-source-evidence';mkdirSync(dir,{recursive:true});writeFileSync(dir+'/zip-base.docx',bytes)
 for(const kind of ['duplicate','unicode','utf8']){const path=dir+'/'+kind+'.docx';execFileSync('/home/junge/pros/smart_reporting/.venv/bin/python',['-c',`import zipfile,sys,struct\na,b,k=sys.argv[1:]\nwith zipfile.ZipFile(a) as src,zipfile.ZipFile(b,'w') as dst:\n for n in src.namelist():dst.writestr(n,src.read(n))\n if k=='duplicate':dst.writestr('word/comments.xml',b'fake')\n elif k=='utf8':\n  dst.writestr('word/中文.xml',b'a');dst.writestr('word/中文.xml',b'b')\n else:\n  z=zipfile.ZipInfo('word/other.xml');z.extra=struct.pack('<HH',0x7075,5)+b'\\x01\\0\\0\\0\\0';dst.writestr(z,b'<x/>')`,dir+'/zip-base.docx',path,kind]);const {readFileSync}=await import('node:fs');await denied(readFileSync(path),/zip/)}
})
test('unresolved or empty internal hyperlinks never gain permission; case aliases cannot shadow an OPC part',async()=>{
 const bytes=await fixture()
 for(const attrs of ['','w:anchor=""','w:docLocation="somewhere"'])await denied(await change(bytes,'word/comments.xml',s=>s.replace('r:id="rId9"',attrs)))
 const zip=await JSZip.loadAsync(bytes);zip.file('word/COMMENTS.XML','<fake/>');await denied(await zip.generateAsync({type:'uint8array'}),/zip/)
})
test('anchor markers outside their actual paragraph/run schema locations stay read-only',async()=>{
 const bytes=await fixture()
 for(const malformed of [anchors.replace('<w:p>','<w:p><w:r>').replace('<w:r><w:t>Anchor','</w:r><w:r><w:t>Anchor'),anchors.replace('<w:r><w:commentReference w:id="1"/></w:r>','<w:commentReference w:id="1"/>')])await denied(await change(bytes,'word/document.xml',s=>s.replace(anchors,malformed)))
})
test('duplicate expanded namespace attributes cannot hide actual protection enforcement',async()=>{
 const bytes=await fixture(),zip=await JSZip.loadAsync(bytes)
 zip.file('word/_rels/document.xml.rels',(await zip.file('word/_rels/document.xml.rels')!.async('string')).replace('</Relationships>',rel('settings','settings','settings.xml')+'</Relationships>'))
 zip.file('[Content_Types].xml',(await zip.file('[Content_Types].xml')!.async('string')).replace('</Types>','<Override PartName="/word/settings.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.settings+xml"/></Types>'))
 zip.file('word/settings.xml',`<w:settings xmlns:w="${W}" xmlns:s="${W}"><w:documentProtection w:enforcement="0" s:enforcement="1"/></w:settings>`)
 await denied(await zip.generateAsync({type:'uint8array'}),/attribute/)
})
test('raw packages without directory entries retain the exact entry set',async()=>{
 const original=await fixture(),zip=await JSZip.loadAsync(original)
 for(const [path,file] of Object.entries(zip.files))if(file.dir)delete zip.files[path]
 const bytes=await zip.generateAsync({type:'uint8array'}),m=await inspectDocxCommentSource(bytes),out=await patchDocxCommentSource(bytes,[op(m)]),reopened=await JSZip.loadAsync(out)
 assert.deepEqual(Object.keys(reopened.files),Object.keys(zip.files))
})
async function withHeader(prefix:string,path:string,target:string){
 const zip=await JSZip.loadAsync(await fixture())
 zip.file(path,`<${prefix}:hdr xmlns:${prefix}="${W}"><${prefix}:p><${prefix}:commentRangeStart ${prefix}:id="1"/><${prefix}:r><${prefix}:t>Other anchor</${prefix}:t></${prefix}:r><${prefix}:commentRangeEnd ${prefix}:id="1"/><${prefix}:r><${prefix}:commentReference ${prefix}:id="1"/></${prefix}:r></${prefix}:p></${prefix}:hdr>`)
 zip.file('word/_rels/document.xml.rels',(await zip.file('word/_rels/document.xml.rels')!.async('string')).replace('</Relationships>',rel('rIdHeader','header',target)+'</Relationships>'))
 zip.file('[Content_Types].xml',(await zip.file('[Content_Types].xml')!.async('string')).replace('</Types>',`<Override PartName="/${path}" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.header+xml"/></Types>`))
 zip.file('word/document.xml',(await zip.file('word/document.xml')!.async('string')).replace('<w:sectPr>','<w:sectPr><w:headerReference w:type="default" r:id="rIdHeader"/>'))
 return zip.generateAsync({type:'uint8array'})
}
test('bound header with legal Unicode namespace prefix cannot hide a second actual comment story',async()=>{
 const bytes=await withHeader('漢','word/header1.xml','header1.xml');writeFileSync('/tmp/word-comment-source-evidence/unicode-story.docx',bytes);await denied(bytes,/anchor_story/)
})
test('bound story outside word directory cannot hide a second actual comment story',async()=>{
 const bytes=await withHeader('w','headers/header1.xml','../headers/header1.xml');writeFileSync('/tmp/word-comment-source-evidence/outside-story.docx',bytes);await denied(bytes,/anchor_story/)
})
test('unknown non-Word XML marker names remain opaque and preserve original bytes',async()=>{
 const zip=await JSZip.loadAsync(await fixture()),path='customXml/opaque.xml',xml='<漢:unknown xmlns:漢="urn:opaque"><漢:commentReference 漢:id="1"/></漢:unknown>'
 zip.file(path,xml);const bytes=await zip.generateAsync({type:'uint8array'}),m=await inspectDocxCommentSource(bytes)
 assert.equal(m.commentReadOnlyReason,null);assert.equal(m.commentTargets[0].editableText,true)
 const out=await JSZip.loadAsync(await patchDocxCommentSource(bytes,[op(m)]));assert.equal(await out.file(path)!.async('string'),xml)
})
test('XML default content type identifies a bound story without an xml extension',async()=>{
 const bytes=await withHeader('w','headers/header1.story','../headers/header1.story'),zip=await JSZip.loadAsync(bytes)
 zip.file('[Content_Types].xml',(await zip.file('[Content_Types].xml')!.async('string')).replace('<Override PartName="/headers/header1.story" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.header+xml"/>','<Default Extension="story" ContentType="application/xml"/>'))
 await denied(await zip.generateAsync({type:'uint8array'}),/anchor_story/)
})
