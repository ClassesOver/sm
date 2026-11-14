import assert from 'node:assert/strict'
import {createHash} from 'node:crypto'
import {spawn} from 'node:child_process'
import {once} from 'node:events'
import {copyFile,mkdir,readFile,writeFile} from 'node:fs/promises'
import {join} from 'node:path'
import {fileURLToPath} from 'node:url'
import {setTimeout as delay} from 'node:timers/promises'
import {chromium} from 'playwright'

const toolFrontend=fileURLToPath(new URL('../',import.meta.url)),repo=process.env.SCATTER_VALUE_LABELS_REPO_DIRECTORY
const out=process.env.SCATTER_REOPEN_DIRECTORY,staticRoot=process.env.PDF_SMOKE_STATIC_DIRECTORY
const receiptPath=process.env.SCATTER_REOPEN_RECEIPT,artifactPath=process.env.SCATTER_REOPEN_ARTIFACT
const wrapper=process.env.SCATTER_VALUE_LABELS_SERVER_WRAPPER,engineRoot=process.env.AGENT_REPORTING_WORKBOOK_ENGINE_DIR
const port=Number(process.env.SCATTER_REOPEN_PORT??4393),origin=`http://127.0.0.1:${port}`
const sha=bytes=>createHash('sha256').update(bytes).digest('hex')
assert(repo&&out&&staticRoot&&receiptPath&&artifactPath&&wrapper&&engineRoot)
await mkdir(out,{recursive:false})
const frozenInputs={}
for(const path of [fileURLToPath(import.meta.url),join(toolFrontend,'smoke/workbook-scatter-value-labels-reopen-server.py'),join(toolFrontend,'smoke/workbook-scatter-value-labels-browser-smoke.mjs'),wrapper,receiptPath]){
 const name=path.slice(path.lastIndexOf('/')+1);await copyFile(path,join(out,name));frozenInputs[name]=sha(await readFile(join(out,name)))
}
await writeFile(join(out,'tool-inputs.json'),JSON.stringify(frozenInputs,null,2))
const receipt=JSON.parse(await readFile(receiptPath,'utf8')),expected=receipt.context.sourceFile
assert.equal(receipt.context.revision,5);assert.equal(receipt.context.parentRevision,4)
assert.equal(sha(await readFile(artifactPath)),expected.sha256)
const enginePath=join(engineRoot,'dist/cli.mjs'),runtimeBefore={path:enginePath,sha256:sha(await readFile(enginePath))}
const manifestPath=join(staticRoot,'.vite/manifest.json'),manifestSha256=sha(await readFile(manifestPath))
const server=spawn(join(repo,'.venv/bin/python'),[join(out,wrapper.slice(wrapper.lastIndexOf('/')+1)),join(out,'workbook-scatter-value-labels-reopen-server.py'),'--directory',out,'--receipt',receiptPath,'--artifact',artifactPath,'--port',String(port)],{cwd:repo,env:{...process.env,PYTHONPATH:repo},stdio:'pipe'})
let serverLog='',browser,page,stage='server';server.stdout.on('data',bytes=>serverLog+=bytes);server.stderr.on('data',bytes=>serverLog+=bytes)
const errors=[],consoleErrors=[],httpErrors=[],assetHashes={},assetChecks=[]
try{
 for(let attempt=0;;attempt++){
  assert.equal(server.exitCode,null,serverLog)
  try{if((await fetch(origin+'/__smoke__/state',{signal:AbortSignal.timeout(1500)})).ok)break}catch{}
  assert(attempt<240,serverLog);await delay(250)
 }
 const info=JSON.parse(await readFile(join(out,'server-info.json'),'utf8'));assert.deepEqual(info.context,receipt.context)
 browser=await chromium.launch({headless:true,executablePath:process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE??'/snap/bin/chromium'})
 page=await browser.newPage({viewport:{width:1600,height:1050}});page.setDefaultTimeout(20000)
 page.on('pageerror',error=>errors.push(error.message));page.on('console',message=>{if(message.type()==='error')consoleErrors.push(message.text())})
 page.on('response',response=>{const path=new URL(response.url()).pathname;if(response.status()>=400)httpErrors.push({path,status:response.status()});if(path.startsWith('/reports/v1/editor/assets/')&&/\.(?:js|css)$/.test(path))assetChecks.push((async()=>{const bytes=await response.body();assert.equal(sha(bytes),sha(await readFile(join(staticRoot,decodeURIComponent(path.slice('/reports/v1/editor/assets/'.length))))));assetHashes[path]=sha(bytes)})())})
 // Reuse the already frozen Canvas instrumentation, without executing its save flow.
 const originalHarness=await readFile(join(out,'workbook-scatter-value-labels-browser-smoke.mjs'),'utf8')
 const marker='  await page.addInitScript(() => {';const start=originalHarness.indexOf(marker),end=originalHarness.indexOf('\n  })',start)
 assert(start>=0&&end>start);const instrumentation=originalHarness.slice(start+marker.length,end)
 await page.addInitScript({content:'(()=>{'+instrumentation+'\n})()'})
 stage='download-existing-r5'
 const download=await page.request.get(origin+info.downloadPath)
 const downloaded=await download.body();assert.equal(download.status(),200);assert.equal(sha(downloaded),expected.sha256);assert.equal(downloaded.length,expected.size)
 await writeFile(join(out,'downloaded-existing-r5.xlsx'),downloaded)
 await writeFile(join(out,'download-response.json'),JSON.stringify({status:download.status(),headers:download.headers(),sha256:sha(downloaded),size:downloaded.length,newAuthorizationForExistingRevision:true},null,2))
 stage='open-existing-r5';await page.goto(origin+info.openPath)
 await page.waitForFunction(()=>document.querySelector('#report-editor')?.getAttribute('aria-busy')==='false',null,{timeout:90000})
 assert.equal(new URL(page.url()).pathname,'/reports/v1/native/parent-document/5')
 await page.waitForFunction(()=>[...(window.__sheetsWebCharts?.store.values()??[])].flat().length===2)
 await page.waitForFunction(()=>['0%','25%','50%','0.00','1.25','2.50'].every(text=>window.__scatterValueLabels.some(label=>label.text===text)))
 const charts=await page.evaluate(()=>[...window.__sheetsWebCharts.store.values()].flat().map(chart=>({title:chart.title,chartPath:chart.chartPath,kind:chart.kind,design:chart.design,dataLabels:chart.dataLabels,series:chart.series.map(series=>({marker:series.marker,numberFormat:series.numberFormat,valuesRef:series.valuesRef,xValuesRef:series.xValuesRef}))})))
 for(const chart of charts){assert.equal(chart.kind,'scatter');assert.equal(chart.dataLabels?.showValue,true);assert.equal(chart.design?.dataLabels,'value');assert.equal(chart.series[0].marker,'none')}
 assert.equal(charts.find(chart=>chart.title==='Scatter value labels').series[0].numberFormat,'0%')
 assert.equal(charts.find(chart=>chart.title==='Scatter no labels').series[0].numberFormat,'0.00')
 const geometry=await page.evaluate(()=>({labels:window.__scatterValueLabels,linePoints:window.__scatterLinePoints}))
 const labels=[...new Map(geometry.labels.filter(label=>['0%','25%','50%','0.00','1.25','2.50'].includes(label.text)).map(label=>[JSON.stringify([label.text,label.x,label.y,label.canvasId,label.transform]),label])).values()]
 assert.deepEqual(labels.map(label=>label.text).sort(),['0%','0.00','1.25','2.50','25%','50%'].sort())
 for(const label of labels){assert.equal(label.textAlign,'center');assert.equal(label.textBaseline,'alphabetic');assert(geometry.linePoints.some(point=>point.canvasId===label.canvasId&&point.strokeStyle==='#1b7f5a'&&point.x===label.x&&point.y===label.y+8&&JSON.stringify(point.transform)===JSON.stringify(label.transform)))}
 const command=async id=>{await page.locator('[data-ribbon-tab="Chart Design"]').click();await page.locator(`[data-ribbon-command="${id}"]`).click()}
 const pane=()=>page.locator('.workbook-chart-format-pane:not([hidden])')
 for(const chart of charts){
  await command('chart-descriptions');await page.locator(`[data-select-chart="${chart.chartPath}"]`).click();await command('chart-format-pane');await pane().waitFor()
  assert.equal(await pane().getByLabel('数据标签',{exact:true}).inputValue(),'value')
  assert.equal(await pane().getByLabel('标签数字格式',{exact:true}).count(),0);assert.equal(await pane().getByLabel('标签位置',{exact:true}).count(),0)
  assert.deepEqual(await pane().getByLabel('数据标签',{exact:true}).locator('option').allTextContents(),['无','值'])
  await page.screenshot({path:join(out,chart.title==='Scatter value labels'?'r5-percent-pane.png':'r5-decimal-pane.png'),fullPage:true})
  await pane().getByRole('button',{name:'关闭图表格式',exact:true}).click();await pane().waitFor({state:'hidden'})
 }
 await page.screenshot({path:join(out,'r5-reopened.png'),fullPage:true})
 const state=await(await page.request.get(origin+'/__smoke__/state')).json();assert.equal(state.postSaveRequests,0);assert.equal(state.sourceSha256,expected.sha256);assert.deepEqual(state.context,receipt.context)
 assert.equal(state.requests.filter(request=>request.method==='POST').length,0)
 await Promise.all(assetChecks);assert(assetChecks.length>0);assert.deepEqual(errors,[]);assert.deepEqual(consoleErrors,[]);assert.deepEqual(httpErrors,[])
 assert.equal(sha(await readFile(manifestPath)),manifestSha256);const runtimeAfter={path:enginePath,sha256:sha(await readFile(enginePath))};assert.deepEqual(runtimeAfter,runtimeBefore)
 await writeFile(join(out,'evidence.json'),JSON.stringify({ok:true,resumedExistingRevision:5,originalSaveResponseAvailable:false,context:info.context,downloadedSha256:sha(downloaded),downloadSize:downloaded.length,charts,geometry,uniqueLabels:labels,state,manifestSha256,assetHashes,runtimeBefore,runtimeAfter,frozenInputs,serverPid:server.pid,browserVersion:browser.version(),errors,consoleErrors,httpErrors},null,2))
 console.log(JSON.stringify({ok:true,directory:out,resumedExistingRevision:5,postSaveRequests:state.postSaveRequests,downloadedSha256:sha(downloaded),assets:assetChecks.length}))
}catch(error){const state=await fetch(origin+'/__smoke__/state',{signal:AbortSignal.timeout(1500)}).then(response=>response.json()).catch(()=>null);await writeFile(join(out,'failure.json'),JSON.stringify({stage,error:String(error),stack:error.stack,state,serverLog,serverPid:server.pid,errors,consoleErrors,httpErrors},null,2));await page?.screenshot({path:join(out,'failure.png'),fullPage:true}).catch(()=>{});throw error}
finally{await browser?.close();if(server.exitCode===null){const exited=once(server,'exit');server.kill('SIGTERM');await exited}await writeFile(join(out,'server.log'),serverLog)}
