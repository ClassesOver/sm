import assert from 'node:assert/strict'
import {test} from 'node:test'
import {createHash} from 'node:crypto'
import {execFileSync} from 'node:child_process'
import {mkdtempSync,writeFileSync,rmSync} from 'node:fs'
import {tmpdir} from 'node:os'
import {join} from 'node:path'
import JSZip from 'jszip'
import {parseDocx,saveDocx} from '../../packages/docx-engine/src/index.ts'
import {buildDocx} from '../../packages/docx-engine/tests/helpers/build-docx.ts'
import {inspectTextRevisions,resolveTextRevisions,recordTextRevisions} from '../docx-revisions.ts'
import {normalizeDocxTrackedChanges} from '../../../../report_editor/frontend/src/docx-tracked-changes.ts'
const hash=(s:string)=>createHash('sha256').update(s).digest('hex')
const ins='<w:ins w:id="7" w:author="甲 &amp; Ann"><w:r w:rsidR="DDEE"><w:rPr><w:b/><w:custom w:val="keep"/></w:rPr><w:t xml:space="preserve"> 新 &amp; 😀 </w:t></w:r></w:ins>'
const del='<w:del w:id="7" w:author="Bob"><w:r><w:rPr><w:i/></w:rPr><w:delText xml:space="preserve"> 旧 &lt;文本&gt; </w:delText></w:r></w:del>'
const prefix='<w:p w:rsidR="AABBCCDD"><w:pPr><w:keepNext/><w:custom/></w:pPr><w:bookmarkStart w:id="1" w:name="anchor"/><w:commentRangeStart w:id="2"/><w:r><w:t>保留</w:t></w:r><w:commentRangeEnd w:id="2"/><w:r><w:commentReference w:id="2"/></w:r><w:bookmarkEnd w:id="1"/>'
const xml=prefix+ins+del+'<w:custom w:val="untouched"/></w:p>'
const sibling='<w:p w:rsidR="11223344"><w:r><w:t>Sibling</w:t></w:r></w:p>'
const open=async(value=xml)=>{const bytes=await buildDocx({bodyXml:value+sibling,extraRels:'<Relationship Id="rId40" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/comments" Target="comments.xml"/>',extraParts:[{path:'word/comments.xml',xml:'<w:comments xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:comment w:id="2" w:author="Reviewer"><w:p><w:r><w:t>Keep comment</w:t></w:r></w:p></w:comment></w:comments>',contentType:'application/vnd.openxmlformats-officedocument.wordprocessingml.comments+xml'},{path:'customXml/sentinel.xml',xml:'<opaque>preserve</opaque>',contentType:'application/xml'}]}),parsed=await parseDocx(bytes);return{bytes,parsed,block:parsed.blocks[0]}}
const op=(block:any,revisionId:string,action:'accept'|'reject'='accept')=>({blockId:'block-a',expectedObjectSha256:hash(block.originalXml!),revisionId,action})
test('four decisions preserve exact surrounding XML and independently reopen actual ZIP/XML',async()=>{
 for(const [index,action,replacement] of [[0,'accept',ins.replace(/^<w:ins[^>]*>/,'').replace('</w:ins>','')],[0,'reject',''],[1,'accept',''],[1,'reject',del.replace(/^<w:del[^>]*>/,'').replace('</w:del>','').replaceAll('w:delText','w:t')]] as const){
  const{bytes,parsed,block}=await open(),info=inspectTextRevisions(block,'block-a');assert.equal(info.revisionReadOnlyReason,null);assert.equal(info.reviewTargets.length,2);assert.notEqual(info.reviewTargets[0].revisionId,info.reviewTargets[1].revisionId);assert.equal(info.reviewTargets[0].author,'甲 & Ann')
  const result=resolveTextRevisions(block,'block-a',[op(block,info.reviewTargets[index].revisionId,action)]);assert.equal(result.xml,block.originalXml!.replace(index===0?ins:del,replacement))
  const out=await saveDocx(parsed,parsed.blocks.map(b=>b===block?{kind:'xml' as const,docxIndex:b.docxIndex!,xml:result.xml}:{kind:'original' as const,docxIndex:b.docxIndex!}));assert.equal((await parseDocx(out)).blocks[0].originalXml,result.xml)
  const a=await JSZip.loadAsync(bytes),b=await JSZip.loadAsync(out);assert.deepEqual(Object.keys(b.files).sort(),Object.keys(a.files).sort());for(const n of Object.keys(a.files))if(!a.files[n].dir&&n!=='word/document.xml')assert.deepEqual(await a.file(n)!.async('uint8array'),await b.file(n)!.async('uint8array'))
  const dir=mkdtempSync(join(tmpdir(),'docx-revision-'));try{writeFileSync(join(dir,'out.docx'),out);writeFileSync(join(dir,'expected.xml'),result.xml);execFileSync('/home/junge/pros/smart_reporting/.venv/bin/python',['-c',`import sys,zipfile\nfrom lxml import etree\np=sys.argv[1]\nwith zipfile.ZipFile(p+'/out.docx') as z:\n assert z.testzip() is None\n for n in z.namelist():\n  if n.endswith(('.xml','.rels')): etree.fromstring(z.read(n))\n root=etree.fromstring(z.read('word/document.xml'))\n ns={'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}\n p0=root.find('w:body/w:p',ns)\n expected=etree.fromstring(open(p+'/expected.xml','rb').read().replace(b'<w:p ',b'<w:p xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" ',1))\n assert etree.tostring(p0,method='c14n',exclusive=True)==etree.tostring(expected,method='c14n',exclusive=True)\n assert p0.get('{'+ns['w']+'}rsidR')=='AABBCCDD'`,dir])}finally{rmSync(dir,{recursive:true,force:true})}
 }
})
test('validates whole snapshot batch before returning XML and rejects stale conflicting or unknown input',async()=>{
 const{block}=await open(),targets=inspectTextRevisions(block,'block-a').reviewTargets,a=op(block,targets[0].revisionId),b=op(block,targets[1].revisionId,'reject');const r=resolveTextRevisions(block,'block-a',[a,b]);assert.ok(!r.xml.includes('<w:ins'));assert.ok(!r.xml.includes('<w:del'));assert.equal(block.originalXml,xml)
 for(const bad of [{...b,expectedObjectSha256:'stale'},{...b,blockId:'foreign'},{...b,revisionId:'missing'},{...b,action:'all'},{...b,xml:'forged'},a,{...a,action:'reject'}])assert.throws(()=>resolveTextRevisions(block,'block-a',[a,bad] as any))
 assert.throws(()=>resolveTextRevisions(block,'block-a',[]));assert.throws(()=>resolveTextRevisions(block,'block-b',[a]));assert.throws(()=>resolveTextRevisions({...block,originalXml:xml.replace('保留','changed')},'block-a',[a]))
})
test('unsupported structures have explicit read-only reasons',async()=>{
 const{block}=await open();const cases:[string,string][]=[
 [xml.replace(ins,ins.replace('</w:ins>',del+'</w:ins>')),'docx_revision_nested_unsupported'],
 [xml.replace(ins,'<w:moveTo w:id="9"><w:r><w:t>x</w:t></w:r></w:moveTo>'),'docx_revision_complex_unsupported'],
 [xml.replace('<w:keepNext/>','<w:rPrChange w:id="8"/>'),'docx_revision_complex_unsupported'],
 [xml.replace(ins,'<w:hyperlink>'+ins+'</w:hyperlink>'),'docx_revision_nested_unsupported'],
 [xml.replace(ins,ins.replace('w:id="7" ','')),'docx_revision_id_missing'],
 [xml.replace(ins,ins.replace('<w:b/>','<w:ins w:id="9"/>')),'docx_revision_nested_unsupported'],
 [xml.replace(ins,ins.replace('<w:t ', '<w:drawing/><w:t ')),'docx_revision_payload_unsupported'],
 [xml.replace(ins,ins.replace('<w:b/><w:custom w:val="keep"/>','')),'docx_revision_empty_properties_unsupported'],
 [xml.replace(ins,'<w:ins w:id="7"/>'),'docx_revision_payload_unsupported'],
 [xml.replace(ins,ins.replace('w:author="甲 &amp; Ann"','w:author="a > b"')),'docx_revision_payload_unsupported'],
 [xml.replace('<w:p ', '<w:p xmlns:w="foreign" '),'docx_revision_namespace_unsupported']]
 for(const [originalXml,reason] of cases){const fake={...block,originalXml},info=inspectTextRevisions(fake,'block-a');assert.equal(info.revisionReadOnlyReason,reason);assert.equal(info.reviewTargets.length,0);assert.throws(()=>resolveTextRevisions(fake,'block-a',[op(fake,'missing')]))}
 assert.equal(inspectTextRevisions({...block,type:'table'},'block-a').revisionReadOnlyReason,'docx_revision_block_unsupported');assert.equal(inspectTextRevisions(block,'block-a',true).revisionReadOnlyReason,'docx_revision_protected');assert.throws(()=>resolveTextRevisions(block,'block-a',[op(block,inspectTextRevisions(block,'block-a').reviewTargets[0].revisionId)],true),/docx_revision_protected/)
})
test('single quotes and identical wrappers have deterministic source-bound identities',async()=>{
 const{block}=await open(prefix+ins+ins+del.replaceAll('"',"'")+'</w:p>'),a=inspectTextRevisions(block,'block-a');assert.deepEqual(a,inspectTextRevisions(block,'block-a'));assert.equal(new Set(a.reviewTargets.map(t=>t.revisionId)).size,3);assert.notEqual(a.reviewTargets[0].revisionId,inspectTextRevisions(block,'block-b').reviewTargets[0].revisionId)
 const out=resolveTextRevisions(block,'block-a',[op(block,a.reviewTargets[2].revisionId,'reject')]);assert.ok(out.xml.includes(ins+ins));assert.ok(!out.xml.includes('w:delText'));const plain=await open(sibling);assert.deepEqual(inspectTextRevisions(plain.block,'block-a'),{reviewTargets:[],revisionReadOnlyReason:null})
})
test('records one source-anchored text replacement with server identity and preserves source run formatting',async()=>{
 const{block}=await open('<w:p w:rsidR="AABBCCDD"><w:r><w:rPr><w:b/></w:rPr><w:t>前旧后</w:t></w:r></w:p>')
 const result=recordTextRevisions(block,'block-a',[{blockId:'block-a',expectedObjectSha256:hash(block.originalXml!),from:1,to:2,text:'新'}],'user-17','2026-11-13T02:03:04Z')
 assert.deepEqual(result.runs.map(run=>[run.text,run.ins?.author,run.ins?.date,run.del?.author,run.del?.date,run.rawRPr]),[
  ['前',undefined,undefined,undefined,undefined,'<w:rPr><w:b/></w:rPr>'],
  ['旧',undefined,undefined,'user-17','2026-11-13T02:03:04Z','<w:rPr><w:b/></w:rPr>'],
  ['新','user-17','2026-11-13T02:03:04Z',undefined,undefined,'<w:rPr><w:b/></w:rPr>'],
  ['后',undefined,undefined,undefined,undefined,'<w:rPr><w:b/></w:rPr>'],
 ])
 assert.equal(block.originalXml,'<w:p w:rsidR="AABBCCDD"><w:r><w:rPr><w:b/></w:rPr><w:t>前旧后</w:t></w:r></w:p>')
})
test('rejects stale, repeated, revision-bearing and complex inline sources before recording',async()=>{
 const{block}=await open('<w:p><w:r><w:t>simple</w:t></w:r></w:p>')
 const op={blockId:'block-a',expectedObjectSha256:hash(block.originalXml!),from:1,to:3,text:'x'}
 for(const bad of [{...op,expectedObjectSha256:'stale'},{...op,from:3,to:3,text:''},{...op,from:99,to:100},{...op,text:'',from:2,to:2},{...op,author:'forged'}])assert.throws(()=>recordTextRevisions(block,'block-a',[bad] as any,'user-17','2026-11-13T02:03:04Z'))
 const emoji=await open('<w:p><w:r><w:t>s😀mple</w:t></w:r></w:p>')
 assert.throws(()=>recordTextRevisions(emoji.block,'block-a',[{...op,expectedObjectSha256:hash(emoji.block.originalXml!),from:2,to:2}],'user-17','2026-11-13T02:03:04Z'))
 assert.throws(()=>recordTextRevisions(block,'block-a',[op,op],'user-17','2026-11-13T02:03:04Z'))
 const revision=await open('<w:p><w:ins w:id="1" w:author="old"><w:r><w:t>x</w:t></w:r></w:ins></w:p>')
 assert.throws(()=>recordTextRevisions(revision.block,'block-a',[{...op,expectedObjectSha256:hash(revision.block.originalXml!)}],'user-17','2026-11-13T02:03:04Z'))
 const complex=await open('<w:p><w:hyperlink r:id="rId1"><w:r><w:t>x</w:t></w:r></w:hyperlink></w:p>')
 assert.throws(()=>recordTextRevisions(complex.block,'block-a',[{...op,expectedObjectSha256:hash(complex.block.originalXml!)}],'user-17','2026-11-13T02:03:04Z'))
})
test('disjoint tracked input in one paragraph writes source-bound revisions and preserves other package parts',async()=>{
 const{bytes,parsed,block}=await open('<w:p w:rsidR="AABBCCDD"><w:pPr><w:keepNext/></w:pPr><w:r><w:rPr><w:b/></w:rPr><w:t>前😀甲中乙尾</w:t></w:r></w:p>')
 const anchor={docxIndex:0,blockId:'block-a',expectedObjectSha256:hash(block.originalXml!),editable:true}
 const baseline={type:'doc',content:[{type:'docParagraph',attrs:{docxIndex:0},content:[{type:'text',text:'前😀甲中乙尾'}]}]}
 const live={type:'doc',content:[{type:'docParagraph',attrs:{docxIndex:0},content:[
  {type:'text',text:'前😀'},{type:'text',text:'甲',marks:[{type:'del'}]},{type:'text',text:'新😀',marks:[{type:'ins'}]},
  {type:'text',text:'中'},{type:'text',text:'乙',marks:[{type:'del'}]},{type:'text',text:'另',marks:[{type:'ins'}]},{type:'text',text:'尾'},
 ]}]}
 const edits=normalizeDocxTrackedChanges(baseline,live,[anchor]).operations.map(({kind,...edit})=>edit)
 assert.equal(edits.length,2)
 const recorded=recordTextRevisions(block,'block-a',edits,'user-17','2026-11-13T02:03:04Z')
 const output=await saveDocx(parsed,parsed.blocks.map(item=>item===block?{kind:'generated' as const,block:{type:'paragraph' as const,rawPAttrs:' w:rsidR="AABBCCDD"',rawPPr:block.rawPPr,format:block.format,runs:recorded.runs}}:{kind:'original' as const,docxIndex:item.docxIndex!}))
 const reopened=(await parseDocx(output)).blocks[0]
 assert.equal(inspectTextRevisions(reopened,'block-a').reviewTargets.length,4)
 assert.equal(reopened.runs!.filter(run=>!run.del).map(run=>run.text).join(''),'前😀新😀中另尾')
 assert.equal(reopened.runs!.filter(run=>!run.ins).map(run=>run.text).join(''),'前😀甲中乙尾')
 const originalZip=await JSZip.loadAsync(bytes),outputZip=await JSZip.loadAsync(output)
 assert.deepEqual(Object.keys(originalZip.files).sort(),Object.keys(outputZip.files).sort())
 for(const name of Object.keys(originalZip.files))if(!originalZip.files[name].dir&&name!=='word/document.xml')assert.deepEqual(await outputZip.file(name)!.async('uint8array'),await originalZip.file(name)!.async('uint8array'))
 const directory=process.env.DOCX_TRACKED_OUTPUT??mkdtempSync(join(tmpdir(),'docx-disjoint-tracked-'))
 try{
  writeFileSync(join(directory,'source.docx'),bytes);writeFileSync(join(directory,'output.docx'),output)
  const readback=execFileSync('/home/junge/pros/smart_reporting/.venv/bin/python',['-c',String.raw`
import sys,json,zipfile,hashlib
from pathlib import Path
from lxml import etree as E
p=Path(sys.argv[1]);ns={'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
with zipfile.ZipFile(p/'source.docx') as source,zipfile.ZipFile(p/'output.docx') as out:
 assert source.namelist()==out.namelist()
 for name in out.namelist():
  if name.endswith(('.xml','.rels')):E.fromstring(out.read(name))
  if name!='word/document.xml':assert source.read(name)==out.read(name)
 root=E.fromstring(out.read('word/document.xml'));paragraph=root.find('w:body/w:p',ns)
 assert paragraph.get('{'+ns['w']+'}rsidR')=='AABBCCDD'
 changes=paragraph.xpath('./w:ins|./w:del',namespaces=ns);assert len(changes)==4
 assert len({node.get('{'+ns['w']+'}id') for node in changes})==4
 for node in changes:
  assert node.get('{'+ns['w']+'}author')=='user-17'
  assert node.get('{'+ns['w']+'}date')=='2026-11-13T02:03:04Z'
  assert all(run.find('w:rPr/w:b',ns) is not None for run in node.findall('w:r',ns))
 final=''.join(paragraph.xpath('./w:r/w:t/text()|./w:ins/w:r/w:t/text()',namespaces=ns))
 original=''.join(paragraph.xpath('./w:r/w:t/text()|./w:del/w:r/w:delText/text()',namespaces=ns))
 assert final=='前😀新😀中另尾' and original=='前😀甲中乙尾'
 print(json.dumps({'ok':True,'finalText':final,'originalText':original,'revisionCount':len(changes),'untouchedParts':len(out.namelist())-1,'sha256':hashlib.sha256((p/'output.docx').read_bytes()).hexdigest()},ensure_ascii=False))
`,directory],{encoding:'utf8'})
  writeFileSync(join(directory,'independent-readback.json'),readback)
 }finally{if(!process.env.DOCX_TRACKED_OUTPUT)rmSync(directory,{recursive:true,force:true})}
})
