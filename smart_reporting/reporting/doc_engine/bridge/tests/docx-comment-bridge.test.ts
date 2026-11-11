import assert from 'node:assert/strict'
import {test} from 'node:test'
import {execFileSync} from 'node:child_process'
import {mkdtempSync,readFileSync,rmSync,writeFileSync,existsSync} from 'node:fs'
import {tmpdir} from 'node:os'
import {join,resolve} from 'node:path'
import JSZip from 'jszip'
import {buildDocx} from '../../packages/docx-engine/tests/helpers/build-docx.ts'

const W='http://schemas.openxmlformats.org/wordprocessingml/2006/main',R='http://schemas.openxmlformats.org/officeDocument/2006/relationships'
const rel=`<Relationship Id="rId8" Type="${R}/comments" Target="comments.xml"/>`
const comments=`<w:comments xmlns:w="${W}"><w:comment w:id="1" w:author="Alice"><w:p><w:r><w:t>Original note</w:t></w:r></w:p></w:comment></w:comments>`
const body='<w:p><w:commentRangeStart w:id="1"/><w:r><w:t>Anchor</w:t></w:r><w:commentRangeEnd w:id="1"/><w:r><w:commentReference w:id="1"/></w:r></w:p>'
const bridge=resolve(import.meta.dirname,'../edit-docx.ts')
function run(dir:string,request:unknown){
 const requestPath=join(dir,'request.json');writeFileSync(requestPath,JSON.stringify(request))
 return execFileSync(process.execPath,['--import','tsx',bridge,requestPath],{encoding:'utf8',cwd:resolve(import.meta.dirname,'../..')})
}
async function fixture(){return buildDocx({bodyXml:body,extraRels:rel,extraParts:[{path:'word/comments.xml',xml:comments,contentType:'application/vnd.openxmlformats-officedocument.wordprocessingml.comments+xml'}]})}

test('edit-docx inspect and patch expose authorized comment targets and write only comments.xml',async()=>{
 const dir=mkdtempSync(join(tmpdir(),'docx-comment-bridge-'))
 try{
  const source=await fixture(),input=join(dir,'source.docx'),output=join(dir,'edited.docx');writeFileSync(input,source)
  const model=JSON.parse(run(dir,{kind:'inspect',input}))
  assert.equal(model.comments.commentReadOnlyReason,null);assert.equal(model.comments.commentTargets[0].editableText,true)
  const target=model.comments.commentTargets[0]
  const receipt=JSON.parse(run(dir,{kind:'patch',input,output,operations:[{kind:'editCommentText',sourceId:target.sourceId,targetId:target.targetId,expectedCommentsSha256:target.expectedCommentsSha256,expectedObjectSha256:target.expectedObjectSha256,text:'Updated note'}]}))
  assert.equal(receipt.sourceSha256,model.sourceSha256);assert.equal(receipt.size,readFileSync(output).length)
  const before=await JSZip.loadAsync(source),after=await JSZip.loadAsync(readFileSync(output))
  for(const path of Object.keys(before.files))if(!before.files[path]!.dir){const a=await before.file(path)!.async('uint8array'),b=await after.file(path)!.async('uint8array');if(path==='word/comments.xml')assert.notDeepEqual(b,a);else assert.deepEqual(b,a,path)}
 }finally{rmSync(dir,{recursive:true,force:true})}
})

test('edit-docx rejects mixed or stale comment edits without creating output or mutating source',async()=>{
 const dir=mkdtempSync(join(tmpdir(),'docx-comment-bridge-'))
 try{
  const input=join(dir,'source.docx'),source=await fixture();writeFileSync(input,source)
  const model=JSON.parse(run(dir,{kind:'inspect',input})),target=model.comments.commentTargets[0]
  const comment={kind:'editCommentText',sourceId:target.sourceId,targetId:target.targetId,expectedCommentsSha256:target.expectedCommentsSha256,expectedObjectSha256:target.expectedObjectSha256,text:'Changed'}
  const mixed=join(dir,'mixed.docx')
  assert.throws(()=>run(dir,{kind:'patch',input,output:mixed,operations:[comment,{kind:'replaceParagraph',blockId:'x',expectedObjectSha256:'x',text:'x'}]}))
  assert.equal(existsSync(mixed),false)
  const stale=join(dir,'stale.docx')
  assert.throws(()=>run(dir,{kind:'patch',input,output:stale,operations:[{...comment,sourceId:'forged'}]}))
  assert.equal(existsSync(stale),false)
  const zip=await JSZip.loadAsync(source);zip.file('word/comments.xml',comments.replace('<w:r><w:t>Original note</w:t></w:r>','<w:hyperlink><w:r><w:t>Original note</w:t></w:r></w:hyperlink>'))
  const readOnlyPath=join(dir,'read-only.docx');writeFileSync(readOnlyPath,await zip.generateAsync({type:'uint8array'}))
  const readOnlyModel=JSON.parse(run(dir,{kind:'inspect',input:readOnlyPath})),readOnly=readOnlyModel.comments.commentTargets[0]
  assert.equal(readOnly.editableText,false)
  const denied=join(dir,'read-only-output.docx')
  assert.throws(()=>run(dir,{kind:'patch',input:readOnlyPath,output:denied,operations:[{kind:'editCommentText',sourceId:readOnly.sourceId,targetId:readOnly.targetId,expectedCommentsSha256:readOnly.expectedCommentsSha256,expectedObjectSha256:readOnly.expectedObjectSha256,text:'Changed'}]}))
  assert.equal(existsSync(denied),false);assert.deepEqual(readFileSync(input),Buffer.from(source))
 }finally{rmSync(dir,{recursive:true,force:true})}
})
