// 冻结前端、真实NativeService/Node/修订/签名下载；AI配色候选为显式HTTP夹具。
import assert from 'node:assert/strict'
import {createHash} from 'node:crypto'
import {mkdir,readFile,writeFile} from 'node:fs/promises'
import {spawn,spawnSync} from 'node:child_process'
import {resolve,join} from 'node:path'
import {fileURLToPath} from 'node:url'
import {setTimeout as delay} from 'node:timers/promises'
import {chromium} from 'playwright'
import {assertChartAboveCells} from './office-xlsx-chart-layering-smoke.mjs'

const frontend=fileURLToPath(new URL('../',import.meta.url)),repo=resolve(frontend,'../../..')
const directory=process.env.XLSX_NAMESPACE_DIRECTORY,staticRoot=process.env.XLSX_NAMESPACE_STATIC_ROOT,engineRoot=process.env.AGENT_REPORTING_WORKBOOK_ENGINE_DIR
const selectedCases=(process.env.XLSX_NAMESPACE_CASES??'default,arbitrary,mixed').split(',').map(value=>value.trim())
assert.ok(selectedCases.length&&selectedCases.every(value=>['default','arbitrary','mixed'].includes(value))&&new Set(selectedCases).size===selectedCases.length,'XLSX_NAMESPACE_CASES必须为不重复的default/arbitrary/mixed逗号列表')
const verifyLayering=process.env.XLSX_VERIFY_CHART_LAYERING==='1'
assert.ok(directory&&staticRoot&&engineRoot,'显式指定证据、冻结构建和隔离Node桥目录')
await mkdir(directory,{recursive:true})
const sha=bytes=>createHash('sha256').update(bytes).digest('hex'),manifestSha=sha(await readFile(join(staticRoot,'.vite/manifest.json')))
assert.equal(manifestSha,process.env.XLSX_NAMESPACE_EXPECTED_MANIFEST_SHA256)
const protectedFiles=[join(staticRoot,'.vite/manifest.json'),join(engineRoot,'dist/cli.mjs'),join(repo,'smart_reporting/reporting/workbook_engine/dist/cli.mjs'),join(repo,'smart_reporting/reporting/workbook_engine/packages/xlsx-engine/src/chart-edit.ts'),...['smoke.mjs','server.py','verify.py'].map(s=>join(frontend,'smoke/office-xlsx-chart-namespace-'+s)),join(frontend,'smoke/office-xlsx-chart-layering-smoke.mjs')]
const fileHashes=Object.fromEntries(await Promise.all(protectedFiles.map(async name=>[name,sha(await readFile(name))])))
const port=Number(process.env.XLSX_NAMESPACE_PORT??4422),origin=`http://127.0.0.1:${port}`
let logs='',browser,page,stage='server',routeError
const server=spawn(join(repo,'.venv/bin/python'),[join(frontend,'smoke/office-xlsx-chart-namespace-server.py'),'--directory',directory,'--port',String(port),'--static-root',staticRoot,'--cases',selectedCases.join(',')],{cwd:repo,env:{...process.env,PYTHONPATH:repo,TMPDIR:'/dev/shm',PYTHONDONTWRITEBYTECODE:'1'},stdio:['ignore','pipe','pipe']})
server.stdout.on('data',x=>logs+=x);server.stderr.on('data',x=>logs+=x)
const results=[],errors=[],assetChecks=[],assets=new Map(),aiEvidence=[]
try{
 let info
 for(let attempt=0;attempt<240;attempt++){
  if(server.exitCode!==null)throw new Error('宿主提前退出：'+logs)
  try{const response=await fetch(origin+'/__smoke__/state');if(response.ok){info=JSON.parse(await readFile(join(directory,'server-info.json'),'utf8'));break}}catch{}
  await delay(250)
 }
 assert.ok(info,'宿主启动超时：'+logs)
 assert.deepEqual(Object.keys(info.cases),selectedCases)
 browser=await chromium.launch({headless:true,...(process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE?{executablePath:process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE}:{})})
 for(const [name,source] of Object.entries(info.cases)){
  stage=name+':open';page=await browser.newPage({viewport:{width:1440,height:1000},acceptDownloads:true})
  page.on('pageerror',e=>errors.push({case:name,message:e.message}));page.on('console',m=>{if(m.type()==='error')errors.push({case:name,message:m.text()})})
  page.on('dialog',dialog=>dialog.type()==='beforeunload'?dialog.accept():dialog.dismiss())
  page.on('response',response=>{
   const path=new URL(response.url()).pathname,prefix='/reports/v1/editor/assets/'
   if(response.status()>=400)errors.push({case:name,status:response.status(),path})
   if(response.status()===200&&path.startsWith(prefix)&&/\.(?:js|css)$/.test(path))assetChecks.push(response.body().then(async bytes=>{const expected=await readFile(join(staticRoot,path.slice(prefix.length)));assert.equal(sha(bytes),sha(expected));assets.set(path,{sha256:sha(bytes),size:bytes.length})}).catch(e=>errors.push({case:name,error:String(e)})))
  })
  let job,csrf,accepted=0
  await page.route('**/api/workbook-ai/**',async route=>{try{
   const request=route.request(),path=new URL(request.url()).pathname.split('/api/workbook-ai/')[1]
   if(path.endsWith('/events'))return route.fulfill({contentType:'text/event-stream',body:'id: 1\nevent: progress\ndata: {"sequence":1,"kind":"terminal","status":"succeeded"}\n\n'})
   if(request.method()==='POST')assert.equal(request.headers()['x-csrf-token'],csrf)
   if(path==='start'){
    const input=request.postDataJSON();assert.equal(input.expectedSha256,source.sha256);assert.equal(input.scope,'workbook')
    assert.ok(input.operations.some(op=>op.kind==='applyChartEdits'&&op.edits.some(e=>e.title==='Browser saved & 图表')))
    assert.ok(input.operations.some(op=>op.kind==='applyChartEdits'&&op.edits.some(e=>e.dataLabels==='value')))
    const operation={kind:'applyChartEdits',edits:[{chartPath:'xl/charts/chart1.xml',seriesColors:{'0':'#2F9E6E'}}]}
    job={editId:'namespace-'+name,status:'succeeded',snapshotSha256:sha(JSON.stringify(input.operations)),proposal:{summary:'显式夹具：只把来源图表系列填充改为绿色',operations:[operation]},base:input.operations,combined:[...input.operations,operation]}
    aiEvidence.push({case:name,fixture:true,input,operation});return route.fulfill({json:job})
   }
   if(path.endsWith('/accept')){const input=request.postDataJSON();assert.deepEqual(input.operations,job.base);assert.equal(input.snapshotSha256,job.snapshotSha256);accepted++;return route.fulfill({json:{accepted:true,operations:job.combined}})}
   if(path.includes('cancel'))return route.fulfill({json:{status:'cancelled'}})
   assert.ok(job);return route.fulfill({json:job})
  }catch(error){routeError=String(error);return route.fulfill({status:500,json:{detail:routeError}})}})
  await page.goto(origin+source.editor.url)
  await page.locator('.workbook-grid canvas').first().waitFor({timeout:60000})
  await page.waitForFunction(()=>document.querySelector('#report-editor')?.getAttribute('aria-busy')==='false')
  const base=`/reports/v1/native/${source.documentId}/1/api`,context=await page.request.get(origin+base+'/context').then(r=>r.json());csrf=context.csrfToken
  assert.equal(context.context.sourceFile.sha256,source.sha256);assert.equal(context.aiEnabled,true)
  const draft=()=>page.evaluate(()=>Object.entries(localStorage).filter(([key])=>key.startsWith('native-editor-draft:')).flatMap(([,value])=>JSON.parse(value).operations))
  const waitEdit=edit=>page.waitForFunction(edit=>Object.entries(localStorage).filter(([key])=>key.startsWith('native-editor-draft:')).some(([,value])=>JSON.parse(value).operations.some(op=>op.kind==='applyChartEdits'&&op.edits.some(e=>Object.entries(edit).every(([k,v])=>JSON.stringify(e[k])===JSON.stringify(v))))),edit)
  const command=async id=>{await page.locator('[data-ribbon-tab="Chart Design"]').click();await page.locator(`[data-ribbon-command="${id}"]`).click()}
  stage=name+':title';await command('chart-title');const dialog=page.getByRole('dialog',{name:'编辑图表设计',exact:true});await dialog.waitFor()
  assert.equal(await dialog.getByLabel('图表标题',{exact:true}).inputValue(),'Original')
  await dialog.getByLabel('图表标题',{exact:true}).fill('Browser saved & 图表');await dialog.locator('[data-chart-design-submit]').click();await waitEdit({title:'Browser saved & 图表'})
  stage=name+':labels';await command('chart-labels');await dialog.getByLabel('数据标签',{exact:true}).selectOption('value');await dialog.locator('[data-chart-design-submit]').click();await waitEdit({dataLabels:'value'})
  stage=name+':color-fixture-adopt';await page.locator('[data-action="office-edit-ai"]').click();const panel=page.locator('.workbook-native-ai');await panel.waitFor()
  await panel.getByLabel('AI 授权范围',{exact:true}).selectOption('workbook');await panel.locator('textarea').fill('将Summary的唯一图表系列填充改为#2F9E6E；保留标题、值标签和其他内容。')
  await panel.locator('[type=submit]').click();await panel.locator('.native-ai-preview').waitFor();const before=await draft();assert.equal(before.some(op=>op.kind==='applyChartEdits'&&op.edits.some(e=>e.seriesColors)),false)
  await panel.locator('.native-ai-accept').click();await waitEdit({seriesColors:{'0':'#2F9E6E'}});assert.equal(accepted,1)
  stage=name+':save';const saving=page.waitForResponse(response=>response.url()===origin+base+'/save'&&response.request().method()==='POST')
  await page.locator('[data-action=save]').click();const response=await saving,payload=response.request().postDataJSON(),saved=await response.json();assert.equal(response.status(),200,JSON.stringify(saved))
  assert.equal(saved.revision,2);assert.equal(saved.parentRevision,1);assert.equal(saved.revisionRegistered,true);assert.ok(saved.artifacts.xlsx.downloadUrl)
  await page.waitForFunction(()=>!document.querySelector('#report-editor')?.inert&&document.querySelector('.save-state-label')?.textContent?.includes('已保存'))
  await writeFile(join(directory,name,'save-response.json'),JSON.stringify({status:response.status(),payload,saved},null,2))
  stage=name+':download';const [download]=await Promise.all([page.waitForEvent('download'),page.locator('[data-action="xlsx-download"]').click()]);assert.equal(await download.failure(),null)
  const downloaded=await readFile(await download.path());assert.equal(sha(downloaded),saved.artifacts.xlsx.sha256);assert.equal(downloaded.length,saved.artifacts.xlsx.size)
  await writeFile(join(directory,name,'downloaded.xlsx'),downloaded)
  const state=await page.request.get(origin+'/__smoke__/state').then(r=>r.json()),registered=state.saved.find(row=>row.documentId===source.documentId&&row.revision===2)
  assert.equal(registered.sha256,sha(downloaded));assert.equal(registered.parentRevision,1)
  stage=name+':reopen';await page.goto(new URL(saved.editor.openUrl,origin).href);await page.locator('.workbook-grid canvas').first().waitFor({timeout:60000});await page.waitForFunction(()=>document.querySelector('#report-editor')?.getAttribute('aria-busy')==='false')
  await command('chart-title');await dialog.waitFor();assert.equal(await dialog.getByLabel('图表标题',{exact:true}).inputValue(),'Browser saved & 图表');await dialog.locator('[data-chart-design-cancel]').click()
  await command('chart-descriptions');const descriptions=page.getByRole('dialog',{name:'图表说明',exact:true});await descriptions.waitFor();assert.match(await descriptions.innerText(),/#2F9E6E/i);await descriptions.locator('[data-chart-descriptions-close]').click()
  let chartLayering
  if(verifyLayering){stage=name+':layering-pixels';await page.waitForTimeout(250);chartLayering=await assertChartAboveCells(page,{screenshotPath:join(directory,name,'reopened.png')})}
  else await page.screenshot({path:join(directory,name,'reopened.png')})
  results.push({case:name,sourceSha256:source.sha256,documentId:source.documentId,revision:2,parentRevision:1,downloadUrl:saved.artifacts.xlsx.downloadUrl,downloadedSha256:sha(downloaded),size:downloaded.length,validation:saved.validation,registered,uiEdits:['title','labels','explicit-HTTP-color-candidate-adopted'],reopenedTitleAndColor:true,...(chartLayering?{chartLayering}:{})})
  await page.close();page=undefined
 }
 stage='independent-verifier';const verified=spawnSync(join(repo,'.venv/bin/python'),[join(frontend,'smoke/office-xlsx-chart-namespace-verify.py'),'--directory',directory,'--cases',selectedCases.join(',')],{cwd:repo,env:{...process.env,PYTHONDONTWRITEBYTECODE:'1'},encoding:'utf8',maxBuffer:5*1024*1024});assert.equal(verified.status,0,verified.stderr);const independent=JSON.parse(verified.stdout)
 await writeFile(join(directory,'independent-check.json'),JSON.stringify(independent,null,2));await Promise.all(assetChecks);assert.deepEqual(errors,[]);assert.equal(routeError,undefined)
 for(const [name,hash] of Object.entries(fileHashes))assert.equal(sha(await readFile(name)),hash,'运行中来源变化：'+name)
 const evidence={ok:true,directory,selectedCases,verifyLayering,browserVersion:browser.version(),manifestSha256:manifestSha,fileHashes,results,independent,aiEvidence,assets:Object.fromEntries(assets),errors,boundary:'真实冻结前端/NativeService/Node/修订及签名下载；内存修订仓储、受控配色AI候选HTTP夹具；非真实模型、生产环境或桌面Excel验收'}
 await writeFile(join(directory,'evidence.json'),JSON.stringify(evidence,null,2));console.log(JSON.stringify({ok:true,directory,cases:results.length,assets:assets.size,downloads:results.map(({case:name,downloadedSha256,size})=>({case:name,sha256:downloadedSha256,size}))}))
}catch(error){if(page)await page.screenshot({path:join(directory,'failure.png')}).catch(()=>{});await writeFile(join(directory,'failure.json'),JSON.stringify({stage,error:String(error),stack:error.stack,routeError,errors},null,2));throw error}
finally{await browser?.close();server.kill('SIGTERM');await writeFile(join(directory,'server.log'),logs)}
