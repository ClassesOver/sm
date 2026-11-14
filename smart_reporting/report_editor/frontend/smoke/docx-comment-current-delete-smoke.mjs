// Fixture API routes, real Chromium UI, Python/Node DOCX patch, downloaded bytes and independent ZIP/lxml readback.
import assert from 'node:assert/strict'
import { spawn, spawnSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import { access, mkdir, mkdtemp, readFile, symlink, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { resolve, join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { setTimeout as delay } from 'node:timers/promises'
import { chromium } from 'playwright'

const frontend=fileURLToPath(new URL('../',import.meta.url)),repo=fileURLToPath(new URL('../../../../',import.meta.url))
const staticRoot=resolve(process.env.DOCX_COMMENT_DELETE_STATIC_ROOT??''),sharedStatic=resolve(frontend,'../static')
assert.ok(process.env.DOCX_COMMENT_DELETE_STATIC_ROOT,'set DOCX_COMMENT_DELETE_STATIC_ROOT to an isolated Vite output directory')
assert.notEqual(staticRoot,sharedStatic,'never run this smoke against shared static assets')
const port=Number(process.env.DOCX_COMMENT_DELETE_PORT??4199),base='http://127.0.0.1:'+port
const output=process.env.DOCX_COMMENT_DELETE_SMOKE_DIR??await mkdtemp(join(tmpdir(),'docx-comment-current-delete-'))
const resumeFrom=process.env.DOCX_COMMENT_DELETE_RESUME_FROM?resolve(process.env.DOCX_COMMENT_DELETE_RESUME_FROM):null
const runtime=process.env.DOCX_COMMENT_DELETE_ENGINE_DIR??join(output,'engine'),mediaType='application/vnd.openxmlformats-officedocument.wordprocessingml.document'
const sha=bytes=>createHash('sha256').update(bytes).digest('hex')
const manifestSha=sha(await readFile(join(staticRoot,'.vite/manifest.json')))
await mkdir(output,{recursive:true})
try{await access(join(runtime,'dist/edit-docx.mjs'))}catch{
 await mkdir(runtime,{recursive:true})
 for(const name of ['bridge','packages','node_modules','package.json'])try{await access(join(runtime,name))}catch{await symlink(join(repo,'smart_reporting/reporting/doc_engine',name),join(runtime,name))}
 const bundled=spawnSync('npm',['run','bundle:bridges'],{cwd:runtime,encoding:'utf8',timeout:120000})
 assert.equal(bundled.status,0,bundled.stderr)
}
const pythonSource=[
 'import base64,json,sys',
 'from io import BytesIO',
 'from pathlib import Path',
 'from zipfile import ZipFile',
 'from lxml import etree',
 'from smart_reporting.reporting.delivery.docx_native import inspect_docx,patch_docx',
 'from smart_reporting.reporting.tests.test_docx_comment_text_host import source',
 'p=json.load(sys.stdin)',
 'if p["mode"]=="create":',
 ' data=source();Path(p["path"]).write_bytes(data);print(json.dumps({"bytes":base64.b64encode(data).decode(),"model":inspect_docx(data)}))',
 'elif p["mode"]=="patch":',
 ' data=Path(p["source"]).read_bytes();out=patch_docx(data,p["operations"]);Path(p["output"]).write_bytes(out);print(json.dumps({"bytes":base64.b64encode(out).decode(),"model":inspect_docx(out)}))',
 'elif p["mode"]=="inspect":',
 ' data=Path(p["source"]).read_bytes();print(json.dumps({"bytes":base64.b64encode(data).decode(),"model":inspect_docx(data)}))',
 'elif p["mode"]=="verify":',
 ' before=Path(p["source"]).read_bytes();saved=base64.b64decode(p["bytes"])',
 ' with ZipFile(BytesIO(before)) as a,ZipFile(BytesIO(saved)) as b:',
 '  assert b.testzip() is None and a.namelist()==b.namelist()',
 '  for n in b.namelist():',
 '   if n.endswith((".xml",".rels")):etree.fromstring(b.read(n))',
 '  x=etree.fromstring(a.read("word/document.xml"));y=etree.fromstring(b.read("word/document.xml"))',
 '  ns={"w":"http://schemas.openxmlformats.org/wordprocessingml/2006/main"}',
 '  assert x.xpath(".//w:body//w:t/text()",namespaces=ns)==y.xpath(".//w:body//w:t/text()",namespaces=ns)',
 '  assert y.xpath(".//w:commentRangeStart|.//w:commentRangeEnd|.//w:commentReference",namespaces=ns)==[]',
 '  assert etree.fromstring(b.read("word/comments.xml")).xpath(".//w:comment",namespaces=ns)==[]',
 '  changed=[n for n in a.namelist() if a.read(n)!=b.read(n)]',
 ' print(json.dumps({"changedParts":changed,"bodyText":y.xpath(".//w:body//w:t/text()",namespaces=ns)}))',
].join('\n')
const python=input=>{
 const result=spawnSync(join(repo,'.venv/bin/python'),['-c',pythonSource],{cwd:repo,input:JSON.stringify(input),encoding:'utf8',maxBuffer:20*1024*1024,timeout:120000,env:{...process.env,PYTHONPATH:repo,AGENT_REPORTING_DOC_ENGINE_DIR:runtime}})
 assert.equal(result.status,0,result.stderr);return JSON.parse(result.stdout.trim())
}
const sourcePath=join(output,'revision-1.docx'),savedPath=join(output,'revision-2.docx')
let initial
if(resumeFrom){
 const original=python({mode:'inspect',source:join(resumeFrom,'revision-1.docx')})
 await writeFile(sourcePath,Buffer.from(original.bytes,'base64'));initial=original
 await writeFile(savedPath,await readFile(join(resumeFrom,'revision-2.docx')))
}else initial=python({mode:'create',path:sourcePath})
const root=initial.model.commentThreads.targets.find(target=>target.parentId===null)
assert.ok(root?.canDelete,'native fixture must provide one authorized root comment')
const deleteOperation={kind:'deleteComment',sourceId:root.sourceId,targetId:root.targetId,expectedCommentsSha256:root.expectedCommentsSha256,expectedObjectSha256:root.expectedObjectSha256}
const state={revisions:{1:initial},payload:null}
try{
 const resumed=python({mode:'inspect',source:savedPath})
 if(resumed.model.sourceSha256!==initial.model.sourceSha256&&resumed.model.commentThreads.targets.length===0){
  state.revisions[2]=resumed;state.payload={operations:[deleteOperation]};
 }
}catch(error){if(!String(error.message).includes('ENOENT'))throw error}
let server,browser
const chunks=new Map(),errors=[]
try{
 server=spawn('./node_modules/.bin/vite',['preview','--host','127.0.0.1','--port',String(port),'--strictPort','--outDir',staticRoot],{cwd:frontend,stdio:'ignore'})
 let serving=false
 for(let n=0;n<120;n++){try{if((await fetch(base+'/reports/v1/editor/assets/native.html')).ok){serving=true;break}}catch{}await delay(250)}
 assert.equal(serving,true,'isolated built preview unavailable')
 browser=await chromium.launch({headless:true,...(process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE?{executablePath:process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE}:{})})
 const page=await browser.newPage({viewport:{width:1440,height:900}})
 page.on('pageerror',error=>errors.push(error.message));page.on('console',message=>{if(message.type()==='error')errors.push(message.text())})
 page.on('response',response=>{const path=new URL(response.url()).pathname,assetBase='/reports/v1/editor/assets/';if(response.ok()&&/\.(?:m?js|css)$/.test(path)&&path.startsWith(assetBase+'assets/'))chunks.set(path,response.body().then(async bytes=>{assert.equal(sha(bytes),sha(await readFile(join(staticRoot,path.slice(assetBase.length)))),path);return sha(bytes)}))})
 const revisionOf=request=>Number(new URL(request.url()).pathname.split('/')[5])
 await page.route('**/reports/v1/native/fixture-current-delete/*/api/context',route=>{
  const revision=revisionOf(route.request()),entry=state.revisions[revision],bytes=Buffer.from(entry.bytes,'base64')
  const published=resumeFrom&&revision===2?{word:{downloadUrl:'/current-comment-delete.docx',size:bytes.length,sha256:entry.model.sourceSha256}}:undefined
  return route.fulfill({json:{context:{documentId:'fixture-current-delete',format:'docx',revision,parentRevision:revision>1?revision-1:null,scope:{database:'f',companyId:'f',userId:'f',threadId:'f'},sourceFile:{path:'revision-'+revision+'.docx',size:bytes.length,sha256:entry.model.sourceSha256,mediaType},origin:'report'},...(published?{artifacts:published}:{}),csrfToken:'fixture-csrf',capabilities:{docx_editor:true},editingEnabled:true}})
 })
 await page.route('**/reports/v1/native/fixture-current-delete/*/api/file',route=>route.fulfill({body:Buffer.from(state.revisions[revisionOf(route.request())].bytes,'base64'),contentType:mediaType}))
 await page.route('**/reports/v1/native/fixture-current-delete/*/api/preview',route=>{
  const model=state.revisions[revisionOf(route.request())].model
  return route.fulfill({json:{sourceSha256:model.sourceSha256,draftSha256:model.sourceSha256,model}})
 })
 await page.route('**/reports/v1/native/fixture-current-delete/*/api/save',async route=>{
  assert.equal(state.payload,null,'one current-comment delete save only')
  const revision=revisionOf(route.request()),payload=route.request().postDataJSON()
  assert.equal(payload.operations.length,1);assert.deepEqual(payload.operations[0],deleteOperation)
  state.revisions[revision+1]=python({mode:'patch',source:sourcePath,output:savedPath,operations:payload.operations});state.payload=payload
  await writeFile(join(output,'delete-operation-checkpoint.json'),JSON.stringify({sourceSha256:initial.model.sourceSha256,operations:payload.operations}))
  const bytes=Buffer.from(state.revisions[revision+1].bytes,'base64')
  return route.fulfill({json:{documentId:'fixture-current-delete',revision:revision+1,parentRevision:revision,revisionRegistered:true,artifacts:{word:{downloadUrl:'/current-comment-delete.docx',size:bytes.length,sha256:sha(bytes)}},editor:{openUrl:'/reports/v1/native/fixture-current-delete/'+(revision+1)},validation:{ok:false,issues:[{code:'fixture_review_pending',message:'批注删除专项保留验收告警'}]}}})
 })
 await page.route('**/current-comment-delete.docx',route=>route.fulfill({body:Buffer.from(state.revisions[2].bytes,'base64'),contentType:mediaType,headers:{'Content-Disposition':'attachment; filename="comment-deleted.docx"'}}))
 await page.route(/\/reports\/v1\/native\/fixture-current-delete\/\d+$/,async route=>route.fulfill({body:await readFile(join(staticRoot,'native.html')),contentType:'text/html'}))
 const open=async revision=>{await page.goto(base+'/reports/v1/native/fixture-current-delete/'+revision);await page.locator('.docx-source-home').waitFor({timeout:60000})}
 const draft=()=>page.evaluate(()=>{const key=Object.keys(localStorage).find(value=>value.startsWith('native-editor-draft:v1:'));return key?JSON.parse(localStorage.getItem(key)).operations:[]})
 if(!state.payload){
  await open(1)
  await page.locator('.tiptap').evaluate(element=>element.editor.commands.setTextSelection(3))
  await page.locator('[data-tab-id="review"]').click()
  const remove=page.locator('[data-action="comment-delete-current"]')
  assert.equal(await remove.isVisible(),true);assert.equal(await remove.isEnabled(),true)
  const dialog=page.waitForEvent('dialog'),click=remove.click(),confirm=await dialog;assert.match(confirm.message(),/删除此批注/);await confirm.accept();await click
  assert.deepEqual(await draft(),[deleteOperation])
  await page.screenshot({path:join(output,'current-comment-deleted-draft.png'),fullPage:true})
  await page.locator('[data-action="save"]').dispatchEvent('click')
  await page.waitForFunction(()=>document.querySelector('.save-state-label')?.textContent.includes('已保存修订 2'),null,{timeout:60000})
  assert.equal(await page.getByText('批注删除专项保留验收告警',{exact:true}).count(),1)
 }
 await open(2)
 let downloaded,downloadEvidence
 if(resumeFrom){
  const response=await page.evaluate(async url=>{const response=await fetch(url);return {status:response.status,contentDisposition:response.headers.get('content-disposition'),bytes:Array.from(new Uint8Array(await response.arrayBuffer()))}},'/current-comment-delete.docx')
  downloaded=Buffer.from(response.bytes)
  downloadEvidence={mode:'raw-http',url:base+'/current-comment-delete.docx',status:response.status,contentDisposition:response.contentDisposition}
 }else{
  const downloadPromise=page.waitForEvent('download');await page.getByRole('link',{name:'下载 Word',exact:true}).click()
  const download=await downloadPromise
  downloaded=Buffer.from(await page.evaluate(async url=>Array.from(new Uint8Array(await(await fetch(url)).arrayBuffer())),'/current-comment-delete.docx'))
  assert.equal(download.suggestedFilename(),'comment-deleted.docx')
  downloadEvidence={mode:'browser-download',url:download.url(),suggestedFilename:download.suggestedFilename()}
 }
assert.equal(sha(downloaded),sha(await readFile(savedPath)),'download URL bytes must match the saved DOCX artifact')
 await writeFile(join(output,'downloaded.docx'),downloaded)
 const verified=python({mode:'verify',source:sourcePath,bytes:downloaded.toString('base64')})
 assert.equal(sha(downloaded),state.revisions[2].model.sourceSha256)
 assert.deepEqual(state.revisions[2].model.commentThreads.targets,[])
 await page.goto(base+'/reports/v1/native/fixture-current-delete/2');await page.locator('.docx-source-home').waitFor({timeout:60000});await page.locator('[data-tab-id="review"]').click()
 const reopenedRemove=page.locator('[data-action="comment-delete-current"]')
 assert.equal(await reopenedRemove.isDisabled(),true)
 await page.screenshot({path:join(output,'current-comment-deleted-reopened.png'),fullPage:true})
 const loadedChunks=Object.fromEntries(await Promise.all([...chunks].map(async([path,promise])=>[path,await promise])))
 assert.deepEqual(errors,[])
 assert.equal(sha(await readFile(join(staticRoot,'.vite/manifest.json'))),manifestSha)
 const result={ok:true,apiRoutesAreFixtures:true,realPythonNodeBridge:true,buildManifestSha256:manifestSha,sourceSha256:initial.model.sourceSha256,outputSha256:state.revisions[2].model.sourceSha256,priorSuccessfulSaveRecovered:!!resumeFrom,saveRequestsInRecoveryRun:resumeFrom?0:1,operation:state.payload.operations[0],downloadEvidence,downloadedSha256:sha(downloaded),savedArtifactSha256:sha(await readFile(savedPath)),changedParts:verified.changedParts,bodyText:verified.bodyText,reopenedCommentTargets:state.revisions[2].model.commentThreads.targets.length,loadedChunks,errors}
 await writeFile(join(output,'result.json'),JSON.stringify(result,null,2));console.log(JSON.stringify({ok:true,output,buildManifestSha256:manifestSha,changedParts:verified.changedParts,outputSha256:result.outputSha256,loadedJavascript:chunks.size}))
}catch(error){await writeFile(join(output,'failure.json'),JSON.stringify({message:String(error),stack:error.stack,saved:!!state.payload},null,2));throw error}
finally{await browser?.close();server?.kill()}
