// Real UI + HTTP/grants + Agno tools + writer + save/download/reopen.
// Only provider and scoped revision persistence use fixtures.
import assert from 'node:assert/strict'
import {spawn, spawnSync} from 'node:child_process'
import {createHash} from 'node:crypto'
import {mkdir, readFile, writeFile} from 'node:fs/promises'
import {join} from 'node:path'
import {fileURLToPath} from 'node:url'
import {setTimeout as delay} from 'node:timers/promises'
import {chromium} from 'playwright'
import {probeCanvasTextRendering} from './canvas-font-preflight.mjs'

const frontend=fileURLToPath(new URL('../',import.meta.url)),repo=fileURLToPath(new URL('../../../../',import.meta.url))
const directory=process.env.WORKBOOK_AI_CHARTS_DIRECTORY??'/tmp/workbook-ai-charts-browser-20261112'
const staticDirectory=process.env.PDF_SMOKE_STATIC_DIRECTORY??join(frontend,'../static')
const port=Number(process.env.WORKBOOK_AI_CHARTS_PORT??4353),origin=`http://127.0.0.1:${port}`
const sha=bytes=>createHash('sha256').update(bytes).digest('hex')
await mkdir(directory,{recursive:false})
const manifest=await readFile(join(staticDirectory,'.vite/manifest.json'))
const server=spawn(join(repo,'.venv/bin/python'),[join(frontend,'smoke/workbook-ai-charts-server.py'),'--directory',directory,'--port',String(port)],{
 cwd:repo,env:{...process.env,PYTHONPATH:repo,PDF_SMOKE_STATIC_DIRECTORY:staticDirectory},stdio:'pipe'})
let serverLog='',browser,page,stage='server'
server.stdout.on('data',data=>{serverLog+=data});server.stderr.on('data',data=>{serverLog+=data})
const pageErrors=[],consoleErrors=[],httpErrors=[],assetErrors=[],checks=[],assets=new Map(),saves=[]
try{
 for(let attempt=0;;attempt++){
  assert.equal(server.exitCode,null,serverLog)
  try{if((await fetch(origin+'/__smoke__/state',{signal:AbortSignal.timeout(1500)})).ok)break}catch{}
  assert(attempt<240,serverLog);await delay(250)
 }
 const info=JSON.parse(await readFile(join(directory,'server-info.json'),'utf8'))
 browser=await chromium.launch({headless:true,...(process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE?{executablePath:process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE}:{})})
 stage='canvas-font-preflight'
 const fontPreflight=await probeCanvasTextRendering(browser)
 await writeFile(join(directory,'canvas-font-preflight.json'),JSON.stringify(fontPreflight,null,2))
 assert.equal(fontPreflight.ok,true,'Canvas text is not renderable in this browser environment: '+JSON.stringify(fontPreflight))
 page=await browser.newPage({viewport:{width:1560,height:1200}})
 // Force network bytes on each revision reopen so every loaded asset can be
 // hashed directly, rather than treating a valid cache 304 as a byte response.
 const cdp=await page.context().newCDPSession(page)
 await cdp.send('Network.enable');await cdp.send('Network.setCacheDisabled',{cacheDisabled:true})
 page.on('pageerror',error=>pageErrors.push(error.message))
 page.on('console',message=>{if(message.type()==='error')consoleErrors.push(message.text())})
 page.on('response',response=>{
  const path=new URL(response.url()).pathname
  if(response.status()>=400)httpErrors.push({path,status:response.status()})
  if(path.startsWith('/reports/v1/editor/assets/')&&/\.(?:js|css)$/.test(path))checks.push((async()=>{
   assert.equal(response.status(),200)
   const bytes=await response.body(),disk=await readFile(join(staticDirectory,path.slice('/reports/v1/editor/assets/'.length)))
   assert.equal(sha(bytes),sha(disk));assets.set(path,sha(bytes))
  })().catch(error=>assetErrors.push({path,error:String(error)})))
 })
 const ready=()=>page.waitForFunction(()=>document.querySelector('#report-editor')?.getAttribute('aria-busy')==='false',null,{timeout:60000})
 const operations=()=>page.evaluate(()=>Object.entries(localStorage).filter(([key])=>key.startsWith('native-editor-draft:')).flatMap(([,value])=>JSON.parse(value).operations??[]))
 const waitKind=(kind,present)=>page.waitForFunction(({kind,present})=>Object.entries(localStorage).filter(([key])=>key.startsWith('native-editor-draft:')).some(([,value])=>(JSON.parse(value).operations??[]).some(op=>op.kind===kind))===present,{kind,present})
 stage='open';await page.goto(origin+info.openPath);await ready()
 stage='manual-draft';await page.locator('[data-u-comp="defined-name"] input').fill('A1')
 await page.locator('[data-u-comp="defined-name"] input').press('Enter')
 await page.locator('[data-ribbon-command="bold"]').click()
 await waitKind('applyCellEdits',true)
 const manual=await operations();assert(manual.length>0)
 const panel=page.locator('.workbook-native-ai')
 async function generate(instruction){
  await page.locator('[data-action="office-edit-ai"]').click();await panel.waitFor()
  await panel.locator('select').selectOption('workbook')
  await panel.locator('textarea').fill(instruction)
  await panel.locator('[type=submit]').click()
  await panel.locator('.native-ai-preview').waitFor({timeout:60000})
  assert.match(await panel.locator('.native-ai-preview').innerText(),/xl\/charts\/chart1.xml/)
 }
 async function saveAndReopen(name,parent){
  const waiting=page.waitForResponse(response=>response.url().endsWith('/api/save')&&response.request().method()==='POST')
  await page.locator('[data-action="save"]').click()
  const response=await waiting,payload=await response.json();assert.equal(response.status(),200,JSON.stringify(payload))
  assert.equal(payload.revisionRegistered,true);assert.equal(payload.parentRevision,parent);assert.equal(payload.revision,parent+1)
  await writeFile(join(directory,name+'-save.json'),JSON.stringify({request:response.request().postDataJSON(),payload},null,2))
  const link=page.locator('[data-action="xlsx-download"]');await link.waitFor()
  assert.equal(await link.getAttribute('href'),payload.artifacts.xlsx.downloadUrl)
  const downloaded=await page.request.get(payload.artifacts.xlsx.downloadUrl);assert.equal(downloaded.status(),200)
  const bytes=await downloaded.body();assert.equal(sha(bytes),payload.artifacts.xlsx.sha256)
  await writeFile(join(directory,name+'.xlsx'),bytes)
  await page.goto(payload.editor.openUrl);await ready()
  const reopened=await page.evaluate(async()=>await(await fetch(location.pathname+'/api/context')).json())
  assert.equal(reopened.context.revision,parent+1);assert.equal(reopened.context.sourceFile.sha256,sha(bytes))
  const actual=await page.request.get(page.url()+'/api/file');assert.equal(actual.status(),200);assert.equal(sha(await actual.body()),sha(bytes))
  await page.screenshot({path:join(directory,name+'-reopened.png'),fullPage:true})
  saves.push({name,payload,reopened})
 }
 stage='edit-candidate';await generate('仅修改 Sheet 的 xl/charts/chart1.xml，标题 Updated、横向条形图、底部图例；保留另一张同名图表'+(process.env.WORKBOOK_AI_CHARTS_AXIS_TITLES==='1'?'；添加轴标题：分类 Quarter、数值 Amount (USD)':''))
 assert.deepEqual(await operations(),manual)
 await panel.locator('.native-ai-accept').click();await waitKind('applyChartEdits',true)
 const adopted=await operations();assert.deepEqual(adopted.slice(0,manual.length),manual)
 stage='undo-redo';await panel.locator('.native-ai-undo').click();await waitKind('applyChartEdits',false)
 assert.deepEqual(await operations(),manual)
 await panel.locator('.native-ai-redo').click();await waitKind('applyChartEdits',true)
 assert.deepEqual(await operations(),adopted)
 stage='save-edit';await saveAndReopen('edited',4)
 stage='discard-delete';await generate('删除 Sheet 的 xl/charts/chart1.xml，保留 chart2')
 const beforeDelete=await operations();await panel.locator('.native-ai-discard').click()
 await panel.locator('.native-ai-preview').waitFor({state:'hidden'})
 assert.deepEqual(await operations(),beforeDelete)
 stage='accept-delete';await generate('删除 Sheet 的 xl/charts/chart1.xml，保留 chart2')
 await panel.locator('.native-ai-accept').click();await waitKind('applyChartDeletions',true)
 stage='save-delete';await saveAndReopen('deleted',5)
 stage='independent-checks'
 const verified=spawnSync(join(repo,'.venv/bin/python'),[join(frontend,'smoke/workbook-ai-charts-verify.py'),directory],{cwd:repo,encoding:'utf8'})
 assert.equal(verified.status,0,verified.stdout+verified.stderr)
 const independent=JSON.parse(verified.stdout)
 await Promise.all(checks);assert(assets.size>0)
 assert.equal(sha(await readFile(join(staticDirectory,'.vite/manifest.json'))),sha(manifest))
 assert.deepEqual(pageErrors,[]);assert.deepEqual(consoleErrors,[]);assert.deepEqual(httpErrors,[]);assert.deepEqual(assetErrors,[])
 const state=await(await page.request.get(origin+'/__smoke__/state')).json()
 assert.equal(state.sourceSha256,info.sourceSha256);assert.equal(state.savedRevisions,2);assert.equal(state.plannerCalls,3)
 const summary={ok:true,scope:'real UI/HTTP/grant/cookie/CSRF/Agno tools/writer/publication/download/reopen; ScriptedModel provider and scoped memory repository',browserVersion:browser.version(),fontPreflight,manifestSha256:sha(manifest),assets:Object.fromEntries(assets),manual,adopted,saves,independent,pageErrors,consoleErrors,httpErrors,assetErrors,state}
 await writeFile(join(directory,'summary.json'),JSON.stringify(summary,null,2));console.log(JSON.stringify({ok:true,directory,assets:assets.size,independent}))
}catch(error){
 await writeFile(join(directory,'failure.json'),JSON.stringify({ok:false,stage,error:String(error),stack:error.stack,pageErrors,consoleErrors,httpErrors,assetErrors,serverLog},null,2))
 if(page)await page.screenshot({path:join(directory,'failure.png'),fullPage:true}).catch(()=>{})
 throw error
}finally{
 await browser?.close();server.kill('SIGTERM');await writeFile(join(directory,'server.log'),serverLog)
}
