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
const directory=process.env.PDF_FORM_RADIO_NAME_SMOKE_DIRECTORY??'/tmp/pdf-form-radio-name-browser-20261111-root01'
const port=Number(process.env.PDF_FORM_RADIO_NAME_SMOKE_PORT??4346),origin='http://127.0.0.1:'+port
const sha=b=>createHash('sha256').update(b).digest('hex')
await mkdir(directory,{recursive:true})
assert.ok(process.env.PDF_SMOKE_STATIC_DIRECTORY,'PDF_SMOKE_STATIC_DIRECTORY is required for frozen assets')
const staticDirectory=process.env.PDF_SMOKE_STATIC_DIRECTORY
const manifest=await readFile(join(staticDirectory,'.vite/manifest.json'))
await writeFile(join(directory,'build-manifest.json'),manifest)
const server=spawn(join(repo,'.venv/bin/python'),[join(frontend,'smoke/pdf-form-create-server.py'),'--directory',directory,'--port',String(port)],{cwd:repo,env:{...process.env,PYTHONPATH:repo},stdio:'pipe'})
let serverLog='',browser,page,stage='server'
server.stdout.on('data',v=>{serverLog+=v});server.stderr.on('data',v=>{serverLog+=v})
const pageErrors=[],consoleErrors=[],httpErrors=[],checks=[],assetErrors=[],assets=new Map(),revisions=[]
try{
 for(let attempt=0;;attempt++){assert.equal(server.exitCode,null,serverLog);try{if((await fetch(origin+'/__smoke__/state')).ok)break}catch{}assert(attempt<480,serverLog);await delay(250)}
 const info=JSON.parse(await readFile(join(directory,'server-info.json'),'utf8'))
 browser=await chromium.launch({headless:true,...(process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE?{executablePath:process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE}:{})})
 page=await browser.newPage({viewport:{width:1500,height:1100}})
 page.on('pageerror',e=>pageErrors.push(e.message));page.on('console',m=>{if(m.type()==='error')consoleErrors.push(m.text())})
 page.on('response',response=>{
  const path=new URL(response.url()).pathname,status=response.status()
  if(status>=400)httpErrors.push({path,status})
  if(status!==200||!path.startsWith('/reports/v1/editor/assets/')||!(/\.m?js$/).test(path))return
  checks.push((async()=>{
   const bytes=await response.body(),disk=await readFile(join(staticDirectory,path.slice('/reports/v1/editor/assets/'.length)))
   assert.equal(sha(bytes),sha(disk));assets.set(path,sha(bytes))
  })().catch(error=>{assetErrors.push({path,error:String(error)})}))
 })
 const ready=()=>page.waitForFunction(()=>document.querySelector('#report-editor')?.getAttribute('aria-busy')==='false',null,{timeout:60000})
 const operations=()=>page.evaluate(()=>JSON.parse(Object.entries(localStorage).find(([key])=>key.startsWith('native-editor-draft:'))?.[1]??'{}').operations??[])
 const command=id=>page.locator('[data-source-command-id="genoffice.pdf.formDesign.'+id+'"]')

 const panel=page.locator('.pdf-form-create-panel')
 const waitOperations=count=>page.waitForFunction(n=>JSON.parse(Object.entries(localStorage).find(([key])=>key.startsWith('native-editor-draft:'))?.[1]??'{}').operations?.length===n,count)
 async function persist(label,parentRevision,staged,preview=null){
  stage=label+'-save';const saving=page.waitForResponse(r=>r.url().endsWith('/api/save')&&r.request().method()==='POST')
  await page.locator('[data-action="save"]').click();const saved=await saving,payload=await saved.json()
  await writeFile(join(directory,label+'-save.json'),JSON.stringify(payload,null,2))
  assert.equal(saved.status(),200,JSON.stringify(payload));assert.equal(payload.revisionRegistered,true)
  assert.equal(payload.parentRevision,parentRevision);assert.equal(payload.revision,parentRevision+1)
  assert.deepEqual(saved.request().postDataJSON().operations,staged)
  if(preview)assert.equal(saved.request().postDataJSON().confirmedPreviewDigest,preview.previewDigest)
  const link=page.locator('.native-delivery a').filter({hasText:'下载 PDF'});await link.waitFor()
  assert.equal(await link.getAttribute('href'),payload.artifacts.pdf.downloadUrl)
  stage=label+'-download';const downloaded=await page.request.get(payload.artifacts.pdf.downloadUrl)
  assert.equal(downloaded.status(),200);const bytes=await downloaded.body()
  assert.equal(sha(bytes),payload.artifacts.pdf.sha256);assert.equal(bytes.length,payload.artifacts.pdf.size)
  await writeFile(join(directory,label+'-downloaded.pdf'),bytes)
  stage=label+'-reopen';await page.goto(payload.editor.openUrl);await ready()
  const reopened=await page.evaluate(async()=>(await fetch(location.pathname+'/api/context')).json())
  assert.equal(reopened.context.revision,parentRevision+1);assert.equal(reopened.context.sourceFile.sha256,payload.artifacts.pdf.sha256)
  revisions.push({label,preview,staged,payload,reopened});return payload
 }
 async function saveActual(label,kind,parentRevision){
  stage=label+'-actual-preview';await page.locator('[data-pdf-ribbon-tab="edit"]').click()
  const previewing=page.waitForResponse(r=>r.url().endsWith('/api/preview')&&r.request().method()==='POST'&&r.request().postDataJSON().operations?.[0]?.kind===kind)
  await page.getByRole('button',{name:'校验当前修改',exact:true}).click()
  const response=await previewing,preview=await response.json()
  await writeFile(join(directory,label+'-preview.json'),JSON.stringify(preview,null,2))
  assert.equal(response.status(),200,JSON.stringify(preview));assert.deepEqual(preview.appliedOperationIndices,[0]);assert.deepEqual(preview.skippedOperations,[])
  const confirm=page.locator('.pdf-preview-review input[type="checkbox"]');await confirm.waitFor({state:'visible'})
  assert.equal(await confirm.isChecked(),false);const staged=await operations()
  assert.equal(staged.length,1);assert.equal(staged[0].kind,kind)
  await confirm.check();await page.screenshot({path:join(directory,label+'-preview.png'),fullPage:true})
  return persist(label,parentRevision,staged,preview)
 }

 async function openDesign(id){await page.locator('[data-pdf-ribbon-tab="formDesign"]').click();assert.equal(await command(id).isDisabled(),false);await command(id).click()}
 async function coords(target,values){for(const[label,value]of Object.entries(values))await target.getByRole('spinbutton',{name:label,exact:true}).fill(String(value))}
 async function createRadio(){
  stage='radio-create';await openDesign('addRadioGroup');await panel.waitFor({state:'visible'})
  await panel.getByRole('textbox',{name:'字段名称',exact:true}).fill('party.answer')
  await panel.getByRole('textbox',{name:'单选按钮（每行：选项,X,Y,宽度,高度,勾选true或false）',exact:true}).fill('Yes,30,240,20,20,true\nNo,90,240,20,20,false')
  await panel.getByRole('checkbox',{name:'必填',exact:true}).check();await panel.locator('[data-pdf-form-create-apply]').click();await waitOperations(1)
  const staged=await operations();assert.equal(staged[0].fieldKind,'radio');assert.equal(staged[0].radioWidgets.length,2)
  await panel.getByRole('button',{name:'关闭字段设置',exact:true}).click();await saveActual('radio','createFormField',4)
 }
 async function createCode(){
  stage='code-create';await openDesign('addTextField');await panel.waitFor({state:'visible'})
  await panel.getByRole('textbox',{name:'字段名称',exact:true}).fill('party.code');await panel.getByRole('textbox',{name:'初始值',exact:true}).fill('C001')
  await coords(panel,{'左下角 X':30,'左下角 Y':210,'宽度':120,'高度':24});await panel.locator('[data-pdf-form-create-apply]').click();await waitOperations(1)
  await panel.getByRole('button',{name:'关闭字段设置',exact:true}).click();await saveActual('code','createFormField',5)
 }
 stage='open-real-grant';await page.goto(origin+info.openPath);await ready()
 await createRadio();await createCode()
 stage='rename-input';await openDesign('fieldProperties');await panel.waitFor({state:'visible'})
 const name=panel.getByRole('textbox',{name:/^party\.answer .* 新字段名称$/}).nth(1)
 await name.fill('party.code');await name.locator('xpath=../..').getByRole('button',{name:'应用控件属性',exact:true}).click()
 await page.waitForFunction(()=>document.querySelector('.pdf-form-create-panel [role="status"]')?.textContent?.includes('重复'))
 assert.deepEqual(await operations(),[])
 await panel.getByRole('textbox',{name:/^party\.answer .* 新字段名称$/}).nth(1).fill('party.renamedAnswer')
 await panel.getByRole('textbox',{name:/^party\.answer .* 新字段名称$/}).nth(1).locator('xpath=../..').getByRole('button',{name:'应用控件属性',exact:true}).click();await waitOperations(1)
 const renamed=await operations();assert.equal(renamed[0].fieldName,'party.answer');assert.equal(renamed[0].newFieldName,'party.renamedAnswer');assert.equal('rect' in renamed[0],false);assert.equal('required' in renamed[0],false)
 await page.locator('[data-pdf-ribbon-tab="home"]').click();await page.locator('[data-source-command-id="genoffice.pdf.home.edit.undo"]').click();assert.deepEqual(await operations(),[]);await page.locator('[data-source-command-id="genoffice.pdf.home.edit.redo"]').click();assert.deepEqual(await operations(),renamed)
 await panel.getByRole('button',{name:'关闭字段设置',exact:true}).click();await saveActual('renamed','editFormWidget',6)
 stage='renamed-reopened';await openDesign('fieldProperties');await panel.waitFor({state:'visible'});assert.equal(await panel.getByRole('textbox',{name:/^party\.renamedAnswer .* 新字段名称$/}).count(),2);assert.equal(await panel.getByRole('textbox',{name:/^party\.renamedAnswer .* 新字段名称$/}).nth(1).inputValue(),'party.renamedAnswer');assert.equal(await panel.getByRole('textbox',{name:/^party\.answer .* 新字段名称$/}).count(),0);await panel.getByRole('button',{name:'关闭字段设置',exact:true}).click()
 await page.locator('[data-pdf-ribbon-tab="fillForm"]').click();const renamedInput=page.locator('.pdf-form-field select[aria-label="party.renamedAnswer"]');assert.equal(await renamedInput.inputValue(),'Yes');await renamedInput.selectOption('No');await waitOperations(1);const filled=await operations();assert.equal(filled[0].kind,'setFormValue');assert.equal(filled[0].name,'party.renamedAnswer');await persist('filled',7,filled)
 stage='final-reopen';await page.locator('[data-pdf-ribbon-tab="fillForm"]').click();assert.equal(await renamedInput.inputValue(),'No');assert.equal(await page.locator('.pdf-form-field input[aria-label="party.code"]').inputValue(),'C001');assert.equal(await page.locator('.pdf-form-field select[aria-label="party.answer"]').count(),0);await page.screenshot({path:join(directory,'reopened-filled.png'),fullPage:true})
 stage='independent-pypdf';const verify=spawnSync(join(repo,'.venv/bin/python'),[join(frontend,'smoke/pdf-form-radio-name-verify.py'),directory],{cwd:repo,encoding:'utf8'})
 assert.equal(verify.status,0,verify.stderr);const independent=JSON.parse(verify.stdout);assert.equal(independent.sourceSha256,info.sourceSha256)
 await writeFile(join(directory,'independent.json'),JSON.stringify(independent,null,2))
 await Promise.all(checks);assert.deepEqual(assetErrors,[]);assert.ok(assets.size>0);assert.deepEqual(pageErrors,[]);assert.deepEqual(consoleErrors,[]);assert.deepEqual(httpErrors,[])
 assert.deepEqual(await readFile(join(staticDirectory,'.vite/manifest.json')),manifest)
 const state=await(await fetch(origin+'/__smoke__/state')).json();assert.equal(state.sourceSha256,info.sourceSha256);assert.equal(state.savedRevisions,4)
 const summary={ok:true,directory,staticDirectory,scope:'real browser/production assets/PDF.js/grant/cookie/CSRF/packed engine/publication/download/reopen; shared in-memory document/grant/artifact repositories; no HTTP or PDF substitutes',browserVersion:browser.version(),manifestSha256:sha(manifest),sourceSha256:info.sourceSha256,revisions,independent,sourceUnchanged:true,assets:Object.fromEntries(assets),assetErrors,pageErrors,consoleErrors,httpErrors,requests:state.requests}
 await writeFile(join(directory,'summary.json'),JSON.stringify(summary,null,2));console.log(JSON.stringify({ok:true,directory}))
}catch(error){await page?.screenshot({path:join(directory,'failure.png'),fullPage:true}).catch(()=>{});if(page)await page.content().then(html=>writeFile(join(directory,'failure.html'),html)).catch(()=>{});await writeFile(join(directory,'failure.json'),JSON.stringify({stage,error:String(error),assetErrors,pageErrors,consoleErrors,httpErrors},null,2));throw error}
finally{await browser?.close();server.kill();await writeFile(join(directory,'server.log'),serverLog);if(server.exitCode===null)await Promise.race([new Promise(resolve=>server.once('exit',resolve)),delay(5000)]);if(server.exitCode===null)server.kill('SIGKILL')}
