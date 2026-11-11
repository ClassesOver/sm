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
const directory=process.env.PDF_FORM_EXTENDED_SMOKE_DIRECTORY??'/tmp/pdf-form-extended-browser-20261111-root01'
const port=Number(process.env.PDF_FORM_EXTENDED_SMOKE_PORT??4302),origin='http://127.0.0.1:'+port
const sha=b=>createHash('sha256').update(b).digest('hex')
await mkdir(directory,{recursive:true})
const manifest=await readFile(join(frontend,'../static/.vite/manifest.json'))
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
   const bytes=await response.body(),disk=await readFile(join(frontend,'../static',path.slice('/reports/v1/editor/assets/'.length)))
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
 async function openDesign(id){await page.locator('[data-pdf-ribbon-tab="formDesign"]').click();assert.equal(await command(id).isDisabled(),false);await command(id).click();await panel.waitFor({state:'visible'})}
 async function rectangle(values){for(const[label,value]of Object.entries(values))await panel.getByRole('spinbutton',{name:label,exact:true}).fill(String(value))}
 async function stageCreation(label,fieldKind,parentRevision){
  await panel.screenshot({path:join(directory,label+'-input.png')});await panel.locator('[data-pdf-form-create-apply]').click();await waitOperations(1)
  const staged=await operations();assert.equal(staged[0].fieldKind,fieldKind);assert.equal(staged[0].fieldName,'customer_'+label)
  if(label==='date'){
   assert.equal(staged[0].dateFormat,'yyyy-mm-dd');assert.equal(staged[0].value,'2026-11-11')
   await page.locator('[data-pdf-ribbon-tab="home"]').click();await page.locator('[data-source-command-id="genoffice.pdf.home.edit.undo"]').click();assert.deepEqual(await operations(),[])
   await page.locator('[data-source-command-id="genoffice.pdf.home.edit.redo"]').click();assert.deepEqual(await operations(),staged)
  }
  await panel.getByRole('button',{name:'关闭字段设置',exact:true}).click();return saveActual(label,'createFormField',parentRevision)
 }
 stage='open-real-grant';await page.goto(origin+info.openPath);await ready()
 stage='date-create';await openDesign('addDateField');await panel.getByRole('textbox',{name:'字段名称',exact:true}).fill('customer_date')
 await rectangle({'左下角 X':30,'左下角 Y':180,'宽度':120,'高度':24})
 await panel.getByRole('textbox',{name:'初始值',exact:true}).fill('2026-11-11');await panel.getByRole('combobox',{name:'日期格式',exact:true}).selectOption('yyyy-mm-dd')
 await panel.getByRole('checkbox',{name:'必填',exact:true}).check();await stageCreation('date','date',4)
 stage='choice-create';await openDesign('addDropdown');await panel.getByRole('textbox',{name:'字段名称',exact:true}).fill('customer_choice')
 await rectangle({'左下角 X':80,'左下角 Y':140,'宽度':120,'高度':24})
 await panel.getByRole('textbox',{name:'下拉选项（每行一个）',exact:true}).fill(['One','Two'].join(String.fromCharCode(10)))
 await panel.getByRole('textbox',{name:'初始值',exact:true}).fill('Two');await panel.getByRole('checkbox',{name:'必填',exact:true}).check()
 await stageCreation('choice','choice',5)
 stage='radio-create';await openDesign('addRadioGroup');await panel.getByRole('textbox',{name:'字段名称',exact:true}).fill('customer_radio')
 await panel.getByRole('textbox',{name:'单选按钮（每行：选项,X,Y,宽度,高度,勾选true或false）',exact:true}).fill(['Yes,30,90,20,20,true','No,80,90,20,20,false'].join(String.fromCharCode(10)))
 await panel.getByRole('checkbox',{name:'必填',exact:true}).check();await stageCreation('radio','radio',6)
 stage='fill-real-fields';await page.locator('[data-pdf-ribbon-tab="fillForm"]').click()
 const dateInput=page.locator('.pdf-form-field input[aria-label="customer_date"]'),choiceInput=page.locator('.pdf-form-field select[aria-label="customer_choice"]'),radioInput=page.locator('.pdf-form-field select[aria-label="customer_radio"]')
 assert.equal(await dateInput.inputValue(),'2026-11-11');assert.equal(await dateInput.isEditable(),true)
 assert.equal(await choiceInput.inputValue(),'Two');assert.equal(await radioInput.inputValue(),'Yes')
 await dateInput.fill('2026-12-25');await dateInput.blur();await waitOperations(1)
 await choiceInput.selectOption('One');await waitOperations(2);await radioInput.selectOption('No');await waitOperations(3)
 const fills=await operations();assert.ok(fills.every(op=>op.kind==='setFormValue'))
 assert.deepEqual(fills.map(op=>[op.name,op.value]),[['customer_date','2026-12-25'],['customer_choice','One'],['customer_radio','No']])
 await page.screenshot({path:join(directory,'filled-input.png'),fullPage:true});await persist('filled',7,fills)
 await page.locator('[data-pdf-ribbon-tab="fillForm"]').click();assert.equal(await dateInput.inputValue(),'2026-12-25');assert.equal(await choiceInput.inputValue(),'One');assert.equal(await radioInput.inputValue(),'No')
 stage='properties-move-required';await openDesign('fieldProperties')
 const required=panel.getByRole('checkbox',{name:'customer_date 必填',exact:true});assert.equal(await required.isChecked(),true)
 await required.uncheck();await panel.getByRole('spinbutton',{name:/^customer_date .* 左下角 X$/}).fill('40')
 await panel.getByRole('spinbutton',{name:/^customer_date .* 左下角 Y$/}).fill('190')
 await panel.getByRole('spinbutton',{name:/^customer_date .* 宽度$/}).fill('120');await panel.getByRole('spinbutton',{name:/^customer_date .* 高度$/}).fill('24')
 await panel.screenshot({path:join(directory,'properties-input.png')})
 await required.locator('..').locator('..').locator('[data-pdf-form-properties-apply]').click();await waitOperations(1)
 const property=(await operations())[0];assert.equal(property.kind,'editFormWidget');assert.equal(property.fieldName,'customer_date');assert.equal(property.required,false);assert.deepEqual(property.rect,[40,190,160,214])
 await panel.getByRole('button',{name:'关闭字段设置',exact:true}).click();await saveActual('properties','editFormWidget',8)
 stage='arrange-real-fields';await openDesign('alignFields')
 await panel.getByRole('checkbox',{name:/^customer_date 控件 /}).check();await panel.getByRole('checkbox',{name:/^customer_choice 控件 /}).check()
 await panel.getByRole('combobox',{name:'排列方式',exact:true}).selectOption('left');await panel.screenshot({path:join(directory,'arrange-input.png')})
 await panel.locator('[data-pdf-form-arrange-apply]').click();await waitOperations(1)
 const arrange=(await operations())[0];assert.equal(arrange.kind,'arrangeFormWidgets');assert.equal(arrange.alignment,'left');assert.deepEqual(arrange.targets.map(t=>t.fieldName),['customer_date','customer_choice'])
 await panel.getByRole('button',{name:'关闭字段设置',exact:true}).click();await saveActual('arrange','arrangeFormWidgets',9)
 stage='final-reopened-properties';await openDesign('fieldProperties');assert.equal(await panel.getByRole('checkbox',{name:'customer_date 必填',exact:true}).isChecked(),false)
 assert.equal(await panel.getByRole('spinbutton',{name:/^customer_date .* 左下角 X$/}).inputValue(),'40')
 assert.equal(await panel.getByRole('spinbutton',{name:/^customer_choice .* 左下角 X$/}).inputValue(),'40')
 assert.equal(await panel.locator('[data-pdf-form-properties-apply]').count(),4)
 await page.screenshot({path:join(directory,'reopened-properties.png'),fullPage:true})
 await panel.getByRole('button',{name:'关闭字段设置',exact:true}).click();await page.locator('[data-pdf-ribbon-tab="fillForm"]').click()
 assert.equal(await dateInput.inputValue(),'2026-12-25');assert.equal(await choiceInput.inputValue(),'One');assert.equal(await radioInput.inputValue(),'No')
 await page.screenshot({path:join(directory,'reopened-filled.png'),fullPage:true})
 stage='independent-pypdf';const verify=spawnSync(join(repo,'.venv/bin/python'),[join(frontend,'smoke/pdf-form-extended-verify.py'),directory],{cwd:repo,encoding:'utf8'})
 assert.equal(verify.status,0,verify.stderr);const independent=JSON.parse(verify.stdout);assert.equal(independent.sourceSha256,info.sourceSha256)
 await writeFile(join(directory,'independent.json'),JSON.stringify(independent,null,2))
 await Promise.all(checks);assert.deepEqual(assetErrors,[]);assert.ok(assets.size>0);assert.deepEqual(pageErrors,[]);assert.deepEqual(consoleErrors,[]);assert.deepEqual(httpErrors,[])
 assert.deepEqual(await readFile(join(frontend,'../static/.vite/manifest.json')),manifest)
 const state=await(await fetch(origin+'/__smoke__/state')).json();assert.equal(state.sourceSha256,info.sourceSha256);assert.equal(state.savedRevisions,6)
 const summary={ok:true,directory,scope:'real browser/production assets/PDF.js/grant/cookie/CSRF/packed engine/publication/download/reopen; shared in-memory document/grant/artifact repositories; no HTTP or PDF substitutes',browserVersion:browser.version(),manifestSha256:sha(manifest),sourceSha256:info.sourceSha256,revisions,independent,sourceUnchanged:true,assets:Object.fromEntries(assets),assetErrors,pageErrors,consoleErrors,httpErrors,requests:state.requests}
 await writeFile(join(directory,'summary.json'),JSON.stringify(summary,null,2));console.log(JSON.stringify({ok:true,directory}))
}catch(error){await page?.screenshot({path:join(directory,'failure.png'),fullPage:true}).catch(()=>{});if(page)await page.content().then(html=>writeFile(join(directory,'failure.html'),html)).catch(()=>{});await writeFile(join(directory,'failure.json'),JSON.stringify({stage,error:String(error),assetErrors,pageErrors,consoleErrors,httpErrors},null,2));throw error}
finally{await browser?.close();server.kill();await writeFile(join(directory,'server.log'),serverLog);if(server.exitCode===null)await Promise.race([new Promise(resolve=>server.once('exit',resolve)),delay(5000)]);if(server.exitCode===null)server.kill('SIGKILL')}
