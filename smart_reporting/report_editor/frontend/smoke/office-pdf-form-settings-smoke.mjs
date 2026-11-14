import assert from 'node:assert/strict'
import { spawn } from 'node:child_process'
import { createHash } from 'node:crypto'
import { mkdir,readFile,writeFile } from 'node:fs/promises'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { setTimeout as delay } from 'node:timers/promises'
import { chromium } from 'playwright'
import { checkFormSettingsLayout } from './office-pdf-form-settings-layout.mjs'

const frontend=fileURLToPath(new URL('../',import.meta.url)),repo=fileURLToPath(new URL('../../../../',import.meta.url)),staticDirectory=process.env.PDF_STATIC_ROOT??join(frontend,'../static')
const directory=process.env.PDF_SETTINGS_OUTPUT??'/tmp/office-pdf-form-settings-built-20261112',port=Number(process.env.PDF_SETTINGS_PORT??4382),origin=`http://127.0.0.1:${port}`
const sha=bytes=>createHash('sha256').update(bytes).digest('hex')
await mkdir(directory,{recursive:true})
const manifest=await readFile(join(staticDirectory,'.vite/manifest.json'))
if(process.env.PDF_EXPECTED_MANIFEST_SHA256)assert.equal(sha(manifest),process.env.PDF_EXPECTED_MANIFEST_SHA256)
await writeFile(join(directory,'build-manifest.json'),manifest)
const server=spawn(join(repo,'.venv/bin/python'),[join(frontend,'smoke/office-pdf-form-settings-server.py'),'--directory',directory,'--port',String(port)],{cwd:repo,env:{...process.env,PYTHONPATH:repo,PDF_SMOKE_STATIC_DIRECTORY:staticDirectory},stdio:'pipe'})
let log='',browser,page,stage='server';server.stdout.on('data',data=>{log+=data});server.stderr.on('data',data=>{log+=data})
const errors={page:[],console:[],http:[],assets:[]},checks=[],assets=new Map(),revisions=[]
try{
  for(let attempt=0;;attempt++){assert.equal(server.exitCode,null,log);try{if((await fetch(origin+'/__smoke__/state')).ok)break}catch{}assert(attempt<480,log);await delay(250)}
  const info=JSON.parse(await readFile(join(directory,'server-info.json'),'utf8'))
  browser=await chromium.launch({headless:true});const context=await browser.newContext({viewport:{width:1440,height:900}});page=await context.newPage()
  page.on('pageerror',error=>errors.page.push(error.message));page.on('console',message=>{if(message.type()==='error')errors.console.push(message.text())})
  page.on('response',response=>{
    const path=new URL(response.url()).pathname
    if(response.status()>=400)errors.http.push({path,status:response.status()})
    if(response.status()!==200||!path.startsWith('/reports/v1/editor/assets/')||!(/\.(?:m?js|css)$/).test(path))return
    checks.push((async()=>{const bytes=await response.body(),disk=await readFile(join(staticDirectory,path.slice('/reports/v1/editor/assets/'.length)));assert.equal(sha(bytes),sha(disk));assets.set(path,{sha256:sha(bytes),size:bytes.length})})().catch(error=>errors.assets.push({path,error:String(error)})))
  })
  const ready=()=>page.waitForFunction(()=>document.querySelector('#report-editor')?.getAttribute('aria-busy')==='false',null,{timeout:60000})
  const operations=()=>page.evaluate(()=>JSON.parse(Object.entries(localStorage).find(([key])=>key.startsWith('native-editor-draft:'))?.[1]??'{}').operations??[])
  const waitOperations=count=>page.waitForFunction(count=>JSON.parse(Object.entries(localStorage).find(([key])=>key.startsWith('native-editor-draft:'))?.[1]??'{}').operations?.length===count,count)
  const open=async id=>{await page.locator('[data-pdf-ribbon-tab="formDesign"]').click();await page.locator(`[data-source-command-id="genoffice.pdf.formDesign.${id}"]`).click()}
  const undoRedo=async expected=>{await page.locator('[data-pdf-ribbon-tab="home"]').click();await page.locator('[data-source-command-id="genoffice.pdf.home.edit.undo"]').click();await waitOperations(0);await page.locator('[data-source-command-id="genoffice.pdf.home.edit.redo"]').click();await waitOperations(1);assert.deepEqual(await operations(),expected)}
  async function persist(label,parentRevision){
    const staged=await operations();assert.equal(staged.length,1)
    stage=label+'-preview';await page.locator('[data-pdf-ribbon-tab="edit"]').click()
    const checking=page.waitForResponse(response=>response.url().endsWith('/api/preview')&&response.request().method()==='POST'&&response.request().postDataJSON().operations?.[0]?.kind===staged[0].kind)
    await page.getByRole('button',{name:'校验当前修改',exact:true}).click()
    const preview=await(await checking).json();assert.deepEqual(preview.appliedOperationIndices,[0]);assert.deepEqual(preview.skippedOperations,[])
    await page.locator('.pdf-preview-review input[type=checkbox]').check()
    stage=label+'-save';const saving=page.waitForResponse(response=>response.url().endsWith('/api/save')&&response.request().method()==='POST')
    await page.locator('[data-action=save]').click();const response=await saving,payload=await response.json()
    assert.equal(response.status(),200,JSON.stringify(payload));assert.equal(payload.revisionRegistered,true);assert.equal(payload.revision,parentRevision+1);assert.equal(payload.parentRevision,parentRevision)
    assert.deepEqual(response.request().postDataJSON().operations,staged);assert.equal(response.request().postDataJSON().confirmedPreviewDigest,preview.previewDigest)
    stage=label+'-download';const link=page.locator('.native-delivery a').filter({hasText:'下载 PDF'});await link.waitFor()
    assert.equal(await link.getAttribute('href'),payload.artifacts.pdf.downloadUrl)
    const downloading=page.waitForEvent('download');await link.click();const download=await downloading;assert.equal(await download.failure(),null)
    const bytes=await readFile(await download.path());assert.equal(sha(bytes),payload.artifacts.pdf.sha256);assert.equal(bytes.length,payload.artifacts.pdf.size)
    await writeFile(join(directory,`${label}-downloaded.pdf`),bytes)
    stage=label+'-reopen';await page.goto(payload.editor.openUrl);await ready()
    const context=await page.evaluate(async()=>(await fetch(location.pathname+'/api/context')).json())
    assert.equal(context.context.revision,parentRevision+1);assert.equal(context.context.sourceFile.sha256,payload.artifacts.pdf.sha256)
    revisions.push({label,staged,preview,payload,context})
  }
  await page.goto(origin+info.openPath);await ready()
  stage='layout';const layout=await checkFormSettingsLayout(page,directory)
  if(process.env.PDF_SETTINGS_LAYOUT_ONLY==='1')throw Error('布局基线结束；业务操作未执行')
  stage='radio-create';await open('addRadioGroup')
  const create=page.locator('.pdf-form-create-panel'),rows=create.locator('table[aria-label="单选选项"] tbody tr')
  await create.locator('[data-pdf-radio-row-add]').click();await rows.nth(1).locator('[data-radio-remove]').click();await create.locator('[data-pdf-radio-row-add]').click()
  assert.deepEqual(await rows.locator('[data-radio-value]').evaluateAll(inputs=>inputs.map(input=>input.value)),['Yes','Option3','Option4'])
  await rows.nth(1).locator('[data-radio-value]').fill('No');await rows.nth(1).locator('[data-radio-coordinate="0"]').fill('50');await rows.nth(2).locator('[data-radio-remove]').click();assert.equal(await rows.count(),2);assert.deepEqual(await operations(),[])
  await create.locator('[data-pdf-form-create-name]').fill('invalid..name')
  await create.locator('[data-pdf-radio-row-add]').click();assert.equal(await rows.count(),3)
  await rows.nth(2).locator('[data-radio-value]').fill('Maybe')
  await rows.nth(2).locator('[data-radio-coordinate="0"]').fill('130')
  await rows.nth(2).locator('input[type=radio]').check();assert.equal(await rows.locator('input[type=radio]:checked').count(),1)
  await create.locator('[data-pdf-form-create-apply]').click();await page.waitForFunction(()=>document.querySelector('.pdf-form-create-panel [role=status]')?.textContent?.includes('名称'))
  assert.deepEqual(await operations(),[]);assert.equal(await create.locator('[data-pdf-form-create-name]').inputValue(),'invalid..name');assert.equal(await rows.nth(2).locator('[data-radio-value]').inputValue(),'Maybe')
  await create.locator('[data-pdf-form-create-name]').fill('new_consent');await create.locator('[data-pdf-form-create-apply]').click();await waitOperations(1)
  const radio=await operations();assert.equal(radio[0].radioWidgets.length,3);assert.equal(radio[0].radioWidgets[2].checked,true);assert.deepEqual(radio[0].radioWidgets[2].rect,[130,50,150,70])
  await undoRedo(radio);await page.reload();await ready();assert.deepEqual(await operations(),radio)
  await persist('radio',4)
  stage='text-properties';await open('textProperties');const text=page.locator('.pdf-form-text-properties-panel')
  await text.getByLabel('字号',{exact:true}).fill('18');await text.getByLabel('最大长度（0为不限）',{exact:true}).fill('4')
  await text.locator('[data-pdf-form-text-properties-apply]').click();await page.waitForFunction(()=>document.querySelector('.pdf-form-text-properties-panel [role=status]')?.textContent?.includes('当前文本长度'))
  assert.equal(await text.getByLabel('字号',{exact:true}).inputValue(),'18');assert.equal(await text.getByLabel('最大长度（0为不限）',{exact:true}).inputValue(),'4');assert.deepEqual(await operations(),[])
  await text.getByLabel('最大长度（0为不限）',{exact:true}).fill('32');await text.getByLabel('字体',{exact:true}).selectOption('Courier-Bold');await text.getByLabel('文字对齐',{exact:true}).selectOption('center')
  await text.locator('[data-pdf-form-text-properties-apply]').click();await waitOperations(1);const properties=await operations();assert.equal(properties[0].fontName,'Courier-Bold');assert.equal(properties[0].fontSize,18)
  await undoRedo(properties);await persist('properties',5)
  await open('textProperties');assert.equal(await text.getByLabel('字号',{exact:true}).inputValue(),'18');assert.equal(await text.getByLabel('字体',{exact:true}).inputValue(),'Courier-Bold');await text.locator('header button').click()
  stage='radio-append';await open('addRadioOption');const append=page.locator('.pdf-form-radio-extension-panel')
  const option=await append.getByLabel('单选组',{exact:true}).locator('option').evaluateAll(options=>options.find(option=>option.textContent.startsWith('consent（')).value)
  await append.getByLabel('单选组',{exact:true}).selectOption(option);await append.getByLabel('新增选项值',{exact:true}).fill('Yes');await append.getByLabel('左下角 X',{exact:true}).fill('130');await append.getByLabel('左下角 Y',{exact:true}).fill('130')
  await append.locator('[data-pdf-radio-extension-apply]').click();await page.waitForFunction(()=>document.querySelector('.pdf-form-radio-extension-panel [role=status]')?.textContent?.includes('重复'))
  assert.equal(await append.getByLabel('左下角 X',{exact:true}).inputValue(),'130');assert.equal(await append.getByLabel('新增选项值',{exact:true}).inputValue(),'Yes');assert.deepEqual(await operations(),[])
  await append.getByLabel('新增选项值',{exact:true}).fill('Maybe');await append.locator('[data-pdf-radio-extension-apply]').click();await waitOperations(1);const appended=await operations();assert.equal(appended[0].fieldName,'consent');assert.deepEqual(appended[0].rect,[130,130,150,150])
  await undoRedo(appended);await persist('append',6)
  await open('addRadioOption');const labels=await append.getByLabel('单选组',{exact:true}).locator('option').allTextContents();assert(labels.some(label=>label.startsWith('consent（')&&label.includes('Yes, No, Maybe')&&label.includes('当前：Yes')))
  await page.screenshot({path:join(directory,'reopened.png'),fullPage:true})
  await Promise.all(checks);for(const value of Object.values(errors))assert.deepEqual(value,[])
  assert.deepEqual(await readFile(join(staticDirectory,'.vite/manifest.json')),manifest)
  const state=await(await fetch(origin+'/__smoke__/state')).json();assert.equal(state.sourceSha256,info.sourceSha256);assert.equal(state.savedRevisions,3)
  const evidence={ok:true,directory,browserVersion:browser.version(),manifestSha256:sha(manifest),sourceSha256:info.sourceSha256,layout,revisions,assets:Object.fromEntries(assets),errors,requests:state.requests}
  await writeFile(join(directory,'evidence.json'),JSON.stringify(evidence,null,2));console.log(JSON.stringify({ok:true,directory}))
}catch(error){await page?.screenshot({path:join(directory,'failure.png'),fullPage:true}).catch(()=>{});await writeFile(join(directory,'failure.json'),JSON.stringify({stage,error:String(error),errors},null,2));throw error}
finally{await browser?.close();server.kill();await writeFile(join(directory,'server.log'),log);if(server.exitCode===null)await Promise.race([new Promise(resolve=>server.once('exit',resolve)),delay(5000)]);if(server.exitCode===null)server.kill('SIGKILL')}
