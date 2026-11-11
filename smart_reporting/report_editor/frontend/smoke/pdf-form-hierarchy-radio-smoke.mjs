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
const directory=process.env.PDF_FORM_HIERARCHY_SMOKE_DIRECTORY??'/tmp/pdf-form-hierarchy-browser-20261111-root01'
const port=Number(process.env.PDF_FORM_HIERARCHY_SMOKE_PORT??4304),origin='http://127.0.0.1:'+port
const sha=b=>createHash('sha256').update(b).digest('hex')
await mkdir(directory,{recursive:true})
const staticDirectory=process.env.PDF_SMOKE_STATIC_DIRECTORY??join(frontend,'../static')
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
 async function createText(label,name,value,y,parentRevision){
  stage=label+'-create';await openDesign('addTextField');await panel.waitFor({state:'visible'})
  await panel.getByRole('textbox',{name:'字段名称',exact:true}).fill(name);await panel.getByRole('textbox',{name:'初始值',exact:true}).fill(value)
  await coords(panel,{'左下角 X':30,'左下角 Y':y,'宽度':120,'高度':24});await panel.getByRole('checkbox',{name:'必填',exact:true}).check()
  await panel.screenshot({path:join(directory,label+'-input.png')});await panel.locator('[data-pdf-form-create-apply]').click();await waitOperations(1)
  const staged=await operations();assert.equal(staged[0].fieldName,name);assert.equal(staged[0].fieldKind,'text');assert.equal(staged[0].value,value)
  if(label==='name'){await page.locator('[data-pdf-ribbon-tab="home"]').click();await page.locator('[data-source-command-id="genoffice.pdf.home.edit.undo"]').click();assert.deepEqual(await operations(),[]);await page.locator('[data-source-command-id="genoffice.pdf.home.edit.redo"]').click();assert.deepEqual(await operations(),staged)}
  await panel.getByRole('button',{name:'关闭字段设置',exact:true}).click();return saveActual(label,'createFormField',parentRevision)
 }
 stage='open-real-grant';await page.goto(origin+info.openPath);await ready()
 await createText('name','party.customer.name','Alice',240,4)
 stage='prefix-conflict';await openDesign('addTextField');await panel.waitFor({state:'visible'});await panel.getByRole('textbox',{name:'字段名称',exact:true}).fill('party')
 await panel.locator('[data-pdf-form-create-apply]').click();await page.waitForFunction(()=>document.querySelector('.pdf-form-create-panel [role="status"]')?.textContent?.includes('前缀'))
 assert.deepEqual(await operations(),[]);await panel.screenshot({path:join(directory,'prefix-conflict.png')});await panel.getByRole('button',{name:'关闭字段设置',exact:true}).click()
 await createText('code','party.customer.code','C001',210,5)
 stage='hierarchical-radio-create';await openDesign('addRadioGroup');await panel.waitFor({state:'visible'})
 await panel.getByRole('textbox',{name:'字段名称',exact:true}).fill('party.consent')
 await panel.getByRole('textbox',{name:'单选按钮（每行：选项,X,Y,宽度,高度,勾选true或false）',exact:true}).fill(['Yes,30,170,20,20,false','No,80,170,20,20,true'].join(String.fromCharCode(10)))
 await panel.getByRole('checkbox',{name:'必填',exact:true}).check();await panel.screenshot({path:join(directory,'radio-input.png')})
 await panel.locator('[data-pdf-form-create-apply]').click();await waitOperations(1);assert.equal((await operations())[0].fieldName,'party.consent')
 await panel.getByRole('button',{name:'关闭字段设置',exact:true}).click();await saveActual('radio','createFormField',6)
 await page.locator('[data-pdf-ribbon-tab="fillForm"]').click();const radioInput=page.locator('.pdf-form-field select[aria-label="party.consent"]')
 assert.equal(await radioInput.inputValue(),'No');assert.deepEqual(await radioInput.locator('option').allTextContents(),['未选择','Yes','No'])
 stage='append-existing-radio';await openDesign('addRadioOption');const radioPanel=page.locator('.pdf-form-radio-extension-panel');await radioPanel.waitFor({state:'visible'})
 assert.equal(await radioPanel.getByRole('combobox',{name:'单选组',exact:true}).locator('option').count(),1)
 await radioPanel.getByRole('textbox',{name:'新增选项值',exact:true}).fill('Maybe')
 await coords(radioPanel,{'左下角 X':130,'左下角 Y':170,'宽度':20,'高度':20});await radioPanel.screenshot({path:join(directory,'append-input.png')})
 await radioPanel.locator('[data-pdf-radio-extension-apply]').click();await waitOperations(1);const appended=await operations()
 assert.equal(appended[0].kind,'appendRadioWidget');assert.equal(appended[0].fieldName,'party.consent');assert.equal(appended[0].exportValue,'Maybe');assert.deepEqual(appended[0].rect,[130,170,150,190]);assert.equal('checked' in appended[0],false)
 await page.locator('[data-pdf-ribbon-tab="home"]').click();await page.locator('[data-source-command-id="genoffice.pdf.home.edit.undo"]').click();assert.deepEqual(await operations(),[])
 await page.locator('[data-source-command-id="genoffice.pdf.home.edit.redo"]').click();assert.deepEqual(await operations(),appended)
 await radioPanel.getByRole('button',{name:'关闭追加单选选项',exact:true}).click();await saveActual('append','appendRadioWidget',7)
 stage='reopen-appended-radio';await page.locator('[data-pdf-ribbon-tab="fillForm"]').click();assert.equal(await radioInput.inputValue(),'No')
 assert.deepEqual(await radioInput.locator('option').allTextContents(),['未选择','Yes','No','Maybe'])
 await page.screenshot({path:join(directory,'append-reopened.png'),fullPage:true});await radioInput.selectOption('Maybe');await waitOperations(1)
 const filled=await operations();assert.equal(filled[0].kind,'setFormValue');assert.equal(filled[0].name,'party.consent');assert.equal(filled[0].value,'Maybe');await persist('filled',8,filled)
 stage='final-hierarchy-reopen';await page.locator('[data-pdf-ribbon-tab="fillForm"]').click()
 assert.equal(await page.locator('.pdf-form-field input[aria-label="party.customer.name"]').inputValue(),'Alice')
 assert.equal(await page.locator('.pdf-form-field input[aria-label="party.customer.code"]').inputValue(),'C001')
 assert.equal(await radioInput.inputValue(),'Maybe');await page.screenshot({path:join(directory,'reopened-filled.png'),fullPage:true})
 stage='independent-pypdf';const verify=spawnSync(join(repo,'.venv/bin/python'),[join(frontend,'smoke/pdf-form-hierarchy-radio-verify.py'),directory],{cwd:repo,encoding:'utf8'})
 assert.equal(verify.status,0,verify.stderr);const independent=JSON.parse(verify.stdout);assert.equal(independent.sourceSha256,info.sourceSha256)
 await writeFile(join(directory,'independent.json'),JSON.stringify(independent,null,2))
 await Promise.all(checks);assert.deepEqual(assetErrors,[]);assert.ok(assets.size>0);assert.deepEqual(pageErrors,[]);assert.deepEqual(consoleErrors,[]);assert.deepEqual(httpErrors,[])
 assert.deepEqual(await readFile(join(staticDirectory,'.vite/manifest.json')),manifest)
 const state=await(await fetch(origin+'/__smoke__/state')).json();assert.equal(state.sourceSha256,info.sourceSha256);assert.equal(state.savedRevisions,5)
 const summary={ok:true,directory,staticDirectory,scope:'real browser/production assets/PDF.js/grant/cookie/CSRF/packed engine/publication/download/reopen; shared in-memory document/grant/artifact repositories; no HTTP or PDF substitutes',browserVersion:browser.version(),manifestSha256:sha(manifest),sourceSha256:info.sourceSha256,revisions,independent,sourceUnchanged:true,assets:Object.fromEntries(assets),assetErrors,pageErrors,consoleErrors,httpErrors,requests:state.requests}
 await writeFile(join(directory,'summary.json'),JSON.stringify(summary,null,2));console.log(JSON.stringify({ok:true,directory}))
}catch(error){await page?.screenshot({path:join(directory,'failure.png'),fullPage:true}).catch(()=>{});if(page)await page.content().then(html=>writeFile(join(directory,'failure.html'),html)).catch(()=>{});await writeFile(join(directory,'failure.json'),JSON.stringify({stage,error:String(error),assetErrors,pageErrors,consoleErrors,httpErrors},null,2));throw error}
finally{await browser?.close();server.kill();await writeFile(join(directory,'server.log'),serverLog);if(server.exitCode===null)await Promise.race([new Promise(resolve=>server.once('exit',resolve)),delay(5000)]);if(server.exitCode===null)server.kill('SIGKILL')}
