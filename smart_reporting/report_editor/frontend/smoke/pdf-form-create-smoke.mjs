// Frozen production assets; real grant/cookie/CSRF, packed engine, publication and download.
import assert from 'node:assert/strict'
import {spawn,spawnSync} from 'node:child_process'
import {createHash} from 'node:crypto'
import {mkdir,readFile,writeFile} from 'node:fs/promises'
import {join} from 'node:path'
import {fileURLToPath} from 'node:url'
import {setTimeout as delay} from 'node:timers/promises'
import {chromium} from 'playwright'
const frontend=fileURLToPath(new URL('../',import.meta.url)),repo=fileURLToPath(new URL('../../../../',import.meta.url))
const directory=process.env.PDF_FORM_CREATE_SMOKE_DIRECTORY??'/tmp/pdf-form-create-browser-20261111-final01'
const port=Number(process.env.PDF_FORM_CREATE_SMOKE_PORT??4301),origin='http://127.0.0.1:'+port
const sha=b=>createHash('sha256').update(b).digest('hex')
await mkdir(directory,{recursive:true})
const manifest=await readFile(join(frontend,'../static/.vite/manifest.json'))
await writeFile(join(directory,'build-manifest.json'),manifest)
const server=spawn(join(repo,'.venv/bin/python'),[join(frontend,'smoke/pdf-form-create-server.py'),'--directory',directory,'--port',String(port)],{cwd:repo,env:{...process.env,PYTHONPATH:repo},stdio:'pipe'})
let serverLog='',browser,page,stage='server'
server.stdout.on('data',v=>{serverLog+=v});server.stderr.on('data',v=>{serverLog+=v})
const pageErrors=[],consoleErrors=[],httpErrors=[],checks=[],assets=new Map(),revisions=[]
try{
 for(let attempt=0;;attempt++){assert.equal(server.exitCode,null,serverLog);try{if((await fetch(origin+'/__smoke__/state')).ok)break}catch{}assert(attempt<480,serverLog);await delay(250)}
 const info=JSON.parse(await readFile(join(directory,'server-info.json'),'utf8'))
 browser=await chromium.launch({headless:true,...(process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE?{executablePath:process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE}:{})})
 page=await browser.newPage({viewport:{width:1500,height:1100}})
 page.on('pageerror',e=>pageErrors.push(e.message));page.on('console',m=>{if(m.type()==='error')consoleErrors.push(m.text())})
 page.on('response',response=>{const path=new URL(response.url()).pathname;if(response.status()>=400)httpErrors.push({path,status:response.status()});if(!path.startsWith('/reports/v1/editor/assets/')||!path.endsWith('.js'))return;checks.push((async()=>{const bytes=await response.body(),disk=await readFile(join(frontend,'../static',path.slice('/reports/v1/editor/assets/'.length)));assert.equal(sha(bytes),sha(disk));assets.set(path,sha(bytes))})())})
 const ready=()=>page.waitForFunction(()=>document.querySelector('#report-editor')?.getAttribute('aria-busy')==='false',null,{timeout:60000})
 const operations=()=>page.evaluate(()=>JSON.parse(Object.entries(localStorage).find(([key])=>key.startsWith('native-editor-draft:'))?.[1]??'{}').operations??[])
 const command=id=>page.locator('[data-source-command-id="genoffice.pdf.formDesign.'+id+'"]')
 async function saveActual(label,kind,parentRevision){
  stage=label+'-actual-preview';await page.locator('[data-pdf-ribbon-tab="edit"]').click()
  const previewing=page.waitForResponse(r=>r.url().endsWith('/api/preview')&&r.request().method()==='POST'&&r.request().postDataJSON().operations?.[0]?.kind===kind)
  await page.getByRole('button',{name:'校验当前修改',exact:true}).click()
  const response=await previewing,preview=await response.json();await writeFile(join(directory,label+'-preview.json'),JSON.stringify(preview,null,2));assert.equal(response.status(),200,JSON.stringify(preview));assert.deepEqual(preview.appliedOperationIndices,[0]);assert.deepEqual(preview.skippedOperations,[])
  const confirm=page.locator('.pdf-preview-review input[type="checkbox"]');await confirm.waitFor({state:'visible'});assert.equal(await confirm.isChecked(),false)
  const staged=await operations();assert.equal(staged.length,1);assert.equal(staged[0].kind,kind)
  await confirm.check();await page.screenshot({path:join(directory,label+'-preview.png'),fullPage:true})
  stage=label+'-save';const saving=page.waitForResponse(r=>r.url().endsWith('/api/save')&&r.request().method()==='POST');await page.locator('[data-action="save"]').click();const saved=await saving,payload=await saved.json()
  assert.equal(saved.status(),200,JSON.stringify(payload));assert.equal(payload.revisionRegistered,true);assert.equal(payload.parentRevision,parentRevision);assert.equal(payload.revision,parentRevision+1);assert.deepEqual(saved.request().postDataJSON().operations,staged);assert.equal(saved.request().postDataJSON().confirmedPreviewDigest,preview.previewDigest)
  const link=page.locator('.native-delivery a').filter({hasText:'下载 PDF'});await link.waitFor();assert.equal(await link.getAttribute('href'),payload.artifacts.pdf.downloadUrl)
  stage=label+'-download';const downloaded=await page.request.get(payload.artifacts.pdf.downloadUrl);assert.equal(downloaded.status(),200);const bytes=await downloaded.body();assert.equal(sha(bytes),payload.artifacts.pdf.sha256);assert.equal(bytes.length,payload.artifacts.pdf.size);await writeFile(join(directory,label+'-downloaded.pdf'),bytes)
  stage=label+'-reopen';await page.goto(payload.editor.openUrl);await ready();const reopened=await page.evaluate(async()=>(await fetch(location.pathname+'/api/context')).json());assert.equal(reopened.context.revision,parentRevision+1);assert.equal(reopened.context.sourceFile.sha256,payload.artifacts.pdf.sha256)
  revisions.push({label,preview,staged,payload,reopened});return payload
 }
 stage='open-real-grant';await page.goto(origin+info.openPath);await ready();await page.locator('[data-pdf-ribbon-tab="formDesign"]').click();assert.equal(await command('addTextField').isDisabled(),false);await command('addTextField').click()
 const panel=page.locator('.pdf-form-create-panel');await panel.waitFor({state:'visible'})
 await panel.getByRole('textbox',{name:'字段名称',exact:true}).fill('customer')
 for(const [label,value]of [['左下角 X','30'],['左下角 Y','180'],['宽度','120'],['高度','24']])await panel.getByRole('spinbutton',{name:label,exact:true}).fill(value)
 await panel.getByRole('checkbox',{name:'必填',exact:true}).check();await panel.screenshot({path:join(directory,'create-input.png')})
 stage='stage-create-undo-redo';await panel.locator('[data-pdf-form-create-apply]').click();await page.waitForFunction(()=>JSON.parse(Object.entries(localStorage).find(([key])=>key.startsWith('native-editor-draft:'))?.[1]??'{}').operations?.length===1)
 const created=await operations();assert.deepEqual(created,[{kind:'createFormField',sourceSha256:info.sourceSha256,pageId:'sha256:'+info.sourceSha256+':page:0',fieldName:'customer',fieldKind:'text',rect:[30,180,150,204],required:true}])
 await page.locator('[data-pdf-ribbon-tab="home"]').click();await page.locator('[data-source-command-id="genoffice.pdf.home.edit.undo"]').click();assert.deepEqual(await operations(),[]);await page.locator('[data-source-command-id="genoffice.pdf.home.edit.redo"]').click();assert.deepEqual(await operations(),created)
 await panel.getByRole('button',{name:'关闭字段设置',exact:true}).click();const first=await saveActual('create','createFormField',4)
 stage='reopened-real-fill';await page.locator('[data-pdf-ribbon-tab="fillForm"]').click();const fill=page.locator('.pdf-form-field input[aria-label="customer"]');await fill.waitFor();assert.equal(await fill.isEditable(),true);await fill.fill('Browser verified');await fill.blur();await page.waitForFunction(()=>JSON.parse(Object.entries(localStorage).find(([key])=>key.startsWith('native-editor-draft:'))?.[1]??'{}').operations?.[0]?.kind==='setFormValue');assert.equal(await fill.inputValue(),'Browser verified')
 await page.locator('[data-pdf-ribbon-tab="home"]').click();await page.locator('[data-source-command-id="genoffice.pdf.home.edit.undo"]').click();assert.deepEqual(await operations(),[])
 stage='edit-required-property';await page.locator('[data-pdf-ribbon-tab="formDesign"]').click();await command('fieldProperties').click();await panel.waitFor({state:'visible'});const required=panel.getByRole('checkbox',{name:'customer 必填',exact:true});assert.equal(await required.isChecked(),true);await required.uncheck();await panel.locator('[data-pdf-form-required-apply]').click();await page.waitForFunction(()=>JSON.parse(Object.entries(localStorage).find(([key])=>key.startsWith('native-editor-draft:'))?.[1]??'{}').operations?.[0]?.kind==='editFormFieldRequired');assert.equal((await operations())[0].sourceSha256,first.artifacts.pdf.sha256);assert.equal((await operations())[0].required,false);await panel.getByRole('button',{name:'关闭字段设置',exact:true}).click();await saveActual('required','editFormFieldRequired',5)
 stage='final-required-reopen';await page.locator('[data-pdf-ribbon-tab="formDesign"]').click();await command('fieldProperties').click();await panel.waitFor({state:'visible'});assert.equal(await panel.getByRole('checkbox',{name:'customer 必填',exact:true}).isChecked(),false);await page.screenshot({path:join(directory,'reopened.png'),fullPage:true})
 stage='independent-pypdf';const code=[
 'import json,sys,hashlib',
 'from pypdf import PdfReader',
 'source=PdfReader(sys.argv[1]);created=PdfReader(sys.argv[2]);edited=PdfReader(sys.argv[3])',
 'assert not source.get_fields()',
 'result=[]',
 'for reader,required in ((created,True),(edited,False)):',
 " assert list(reader.get_fields())==['customer']",
 ' assert len(reader.pages)==len(source.pages)',
 ' assert all(a.extract_text()==b.extract_text() for a,b in zip(reader.pages,source.pages))',
 ' for a,b in zip(reader.pages,source.pages):',
 '  assert list(a.mediabox)==list(b.mediabox) and list(a.cropbox)==list(b.cropbox) and a.rotation==b.rotation',
 '  assert b.get_contents().get_data() in a.get_contents().get_data()',
 " root=reader.trailer['/Root']['/AcroForm']['/Fields'];assert len(root)==1",
 " field=root[0].get_object();assert field['/FT']=='/Tx' and field['/T']=='customer' and bool(field.get('/Ff',0)&2)==required",
 " kids=field['/Kids'];assert len(kids)==1;widget=kids[0].get_object();assert widget['/Subtype']=='/Widget'",
 " assert widget['/Parent'].indirect_reference==root[0] and widget['/P'].indirect_reference==reader.pages[0].indirect_reference",
 " assert list(reader.pages[0]['/Annots'])==list(kids) and widget['/AP']['/N'].get_data()",
 " result.append({'required':required,'fieldNames':list(reader.get_fields()),'bodyPreserved':True,'appearanceVerified':True})",
 "print(json.dumps({'checks':result,'sourceSha256':hashlib.sha256(open(sys.argv[1],'rb').read()).hexdigest()}))"
 ].join(String.fromCharCode(10))
 const verify=spawnSync(join(repo,'.venv/bin/python'),['-c',code,join(directory,'source.pdf'),join(directory,'create-downloaded.pdf'),join(directory,'required-downloaded.pdf')],{cwd:repo,encoding:'utf8'});assert.equal(verify.status,0,verify.stderr);const independent=JSON.parse(verify.stdout);assert.equal(independent.sourceSha256,info.sourceSha256);await writeFile(join(directory,'independent.json'),JSON.stringify(independent,null,2))
 await Promise.all(checks);assert.deepEqual(pageErrors,[]);assert.deepEqual(consoleErrors,[]);assert.deepEqual(httpErrors,[]);assert.deepEqual(await readFile(join(frontend,'../static/.vite/manifest.json')),manifest)
 const state=await(await fetch(origin+'/__smoke__/state')).json();assert.equal(state.sourceSha256,info.sourceSha256);assert.equal(state.savedRevisions,2)
 const summary={ok:true,directory,scope:'real browser/production assets/PDF.js/grant/cookie/CSRF/packed engine/publication/download/reopen; shared in-memory document/grant/artifact repositories; no HTTP or PDF substitutes',browserVersion:browser.version(),manifestSha256:sha(manifest),sourceSha256:info.sourceSha256,revisions,independent,sourceUnchanged:true,assets:Object.fromEntries(assets),pageErrors,consoleErrors,httpErrors,requests:state.requests}
 await writeFile(join(directory,'summary.json'),JSON.stringify(summary,null,2));console.log(JSON.stringify({ok:true,directory}))
}catch(error){await page?.screenshot({path:join(directory,'failure.png'),fullPage:true}).catch(()=>{});if(page)await page.content().then(html=>writeFile(join(directory,'failure.html'),html)).catch(()=>{});await writeFile(join(directory,'failure.json'),JSON.stringify({stage,error:String(error),pageErrors,consoleErrors,httpErrors},null,2));throw error}
finally{await browser?.close();server.kill();await writeFile(join(directory,'server.log'),serverLog);if(server.exitCode===null)await Promise.race([new Promise(resolve=>server.once('exit',resolve)),delay(5000)]);if(server.exitCode===null)server.kill('SIGKILL')}
