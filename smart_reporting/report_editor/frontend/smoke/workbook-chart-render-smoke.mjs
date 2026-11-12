// Actual production canvas paint and independent screenshot/OOXML checks.
import assert from 'node:assert/strict'
import {spawn,spawnSync} from 'node:child_process'
import {createHash} from 'node:crypto'
import {mkdir,readFile,writeFile} from 'node:fs/promises'
import {join} from 'node:path'
import {fileURLToPath} from 'node:url'
import {setTimeout as delay} from 'node:timers/promises'
import {chromium} from 'playwright'
import {probeCanvasTextRendering} from './canvas-font-preflight.mjs'

const frontend=fileURLToPath(new URL('../',import.meta.url)),repo=fileURLToPath(new URL('../../../../',import.meta.url))
const directory=process.env.WORKBOOK_CHART_RENDER_DIRECTORY??'/tmp/workbook-chart-render-browser-20261112'
const staticDirectory=process.env.PDF_SMOKE_STATIC_DIRECTORY??join(frontend,'../static')
const port=Number(process.env.WORKBOOK_CHART_RENDER_PORT??4354),origin=`http://127.0.0.1:${port}`
const sha=bytes=>createHash('sha256').update(bytes).digest('hex')
const smokeCase=process.env.WORKBOOK_CHART_RENDER_CASE??'geometry'
assert(['geometry','legend','axis','scale','ticks','category'].includes(smokeCase),'Unknown chart render case')
const legend=smokeCase==='legend',axis=smokeCase==='axis',scale=smokeCase==='scale',ticks=smokeCase==='ticks',category=smokeCase==='category'
await mkdir(directory,{recursive:false})
const fixture=join(frontend,category?'smoke/workbook-chart-category-fixture.py':ticks?'smoke/workbook-chart-ticks-fixture.py':scale?'smoke/workbook-chart-scale-fixture.py':axis?'smoke/workbook-chart-axis-fixture.py':legend?'smoke/workbook-chart-legend-fixture.py':'smoke/workbook-chart-render-fixture.py'),python=join(repo,'.venv/bin/python')
const created=spawnSync(python,[fixture,'create',join(directory,'input.xlsx')],{cwd:repo,encoding:'utf8',env:{...process.env,PYTHONPATH:repo}})
assert.equal(created.status,0,created.stdout+created.stderr)
const manifest=await readFile(join(staticDirectory,'.vite/manifest.json'))
const server=spawn(python,[join(frontend,'smoke/workbook-ai-charts-server.py'),'--directory',directory,'--port',String(port),'--source',join(directory,'input.xlsx')],{
 cwd:repo,env:{...process.env,PYTHONPATH:repo,PDF_SMOKE_STATIC_DIRECTORY:staticDirectory},stdio:'pipe'})
let serverLog='',browser,page,stage='server'
server.stdout.on('data',data=>{serverLog+=data});server.stderr.on('data',data=>{serverLog+=data})
const pageErrors=[],consoleErrors=[],httpErrors=[],assetErrors=[],checks=[],assets=new Map()
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
 page=await browser.newPage({viewport:{width:1560,height:scale||ticks||category?1850:legend||axis?1550:1400}})
 if(legend||axis||scale||ticks||category)await page.addInitScript(()=>{
  window.__legendTexts=[]
  window.__valueTickTexts=[]
  window.__categoryTexts=[]
  const original=CanvasRenderingContext2D.prototype.fillText
  CanvasRenderingContext2D.prototype.fillText=function(...args){
   if(this.font==='11px system-ui'&&window.__legendTexts.length<5000)window.__legendTexts.push(String(args[0]))
   if(this.font==='9px system-ui'&&window.__valueTickTexts.length<5000)window.__valueTickTexts.push(String(args[0]))
   if(this.font==='10px system-ui'&&window.__categoryTexts.length<5000)window.__categoryTexts.push(String(args[0]))
   return original.apply(this,args)
  }
 })
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
 stage='open';await page.goto(origin+info.openPath)
 await page.waitForFunction(()=>document.querySelector('#report-editor')?.getAttribute('aria-busy')==='false',null,{timeout:60000})
 await page.waitForFunction(()=>window.__sheetsWebCharts?.draws>0&&window.__sheetsWebCharts.store.size>0,null,{timeout:30000})
 await page.evaluate(()=>document.fonts.ready)
 await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))))
 stage='capture'
 const evidence=await page.evaluate(()=>({charts:[...window.__sheetsWebCharts.store.values()].flat(),legendTexts:window.__legendTexts??[],valueTickTexts:window.__valueTickTexts??[],categoryTexts:window.__categoryTexts??[]}))
 await writeFile(join(directory,'model.json'),JSON.stringify(evidence,null,2))
 await page.screenshot({path:join(directory,'charts.png'),fullPage:true})
 assert.deepEqual(evidence.charts.map(c=>c.kind),category?['bar','column','bar','column','bar','bar']:scale||ticks?['bar','column','bar','bar','bar','bar']:axis?['column','bar','column','bar']:legend?Array(5).fill('bar'):['bar','column','bar'])
 if(legend){
  assert(evidence.legendTexts.includes('Live Revenue'));assert(evidence.legendTexts.includes('Costs & tax'))
  assert(!evidence.legendTexts.includes('STALE'))
 }
 if(axis){
  for(const title of ['Quarter','Amount (USD)','Year & quarter','USD','Group'])assert(evidence.legendTexts.includes(title),'Missing axis title: '+title)
  assert(!evidence.legendTexts.includes('DO NOT DRAW'));assert(!evidence.legendTexts.includes('OLD GROUP'))
 }
 if(scale){
  assert.equal(evidence.charts[0].axes?.value.scaling?.min,2)
  assert.equal(evidence.charts[2].axes?.value.scaling?.reversed,true)
  assert(evidence.legendTexts.some(text=>text.includes('暂不支持')))
 }
 if(ticks){
  for(const text of ['-600','400','-22.5','0%','10%','50%'])assert(evidence.valueTickTexts.includes(text),'Missing numeric label: '+text)
  assert.equal(evidence.charts[2].axes?.value.scaling?.majorUnit,0.1)
  assert.equal(evidence.charts[2].axes?.value.numberFormat,'0%')
 }
 if(category){
  for(const text of ['Alpha','Gamma','Fourth','10%','25%','50%','75%','External A'])assert(evidence.categoryTexts.includes(text),'Missing category: '+text)
  assert(!evidence.categoryTexts.includes('STALE'))
  assert(evidence.categoryTexts.some(text=>text.startsWith('Long external')&&text.endsWith('…')))
  assert.equal(evidence.charts[2].axes?.category.reversed,true)
 }
 stage='independent-pixels'
 const verified=spawnSync(python,[fixture,'verify',directory],{cwd:repo,encoding:'utf8',env:{...process.env,PYTHONPATH:repo}})
 assert.equal(verified.status,0,verified.stdout+verified.stderr)
 const independent=JSON.parse(verified.stdout)
 await Promise.all(checks);assert(assets.size>0)
 assert.equal(sha(await readFile(join(staticDirectory,'.vite/manifest.json'))),sha(manifest))
 assert.deepEqual(pageErrors,[]);assert.deepEqual(consoleErrors,[]);assert.deepEqual(httpErrors,[]);assert.deepEqual(assetErrors,[])
 const state=await(await page.request.get(origin+'/__smoke__/state')).json()
 assert.equal(state.sourceSha256,info.sourceSha256);assert.equal(state.savedRevisions,0);assert.equal(state.plannerCalls,0)
 const summary={ok:true,browserVersion:browser.version(),fontPreflight,manifestSha256:sha(manifest),assets:Object.fromEntries(assets),sourceSha256:info.sourceSha256,independent,pageErrors,consoleErrors,httpErrors,assetErrors,state}
 await writeFile(join(directory,'summary.json'),JSON.stringify(summary,null,2));console.log(JSON.stringify({ok:true,directory,assets:assets.size,independent}))
}catch(error){
 await writeFile(join(directory,'failure.json'),JSON.stringify({stage,error:String(error),stack:error.stack,pageErrors,consoleErrors,httpErrors,assetErrors,serverLog},null,2))
 if(page)await page.screenshot({path:join(directory,'failure.png'),fullPage:true}).catch(()=>{})
 throw error
}finally{
 await browser?.close();server.kill('SIGTERM');await writeFile(join(directory,'server.log'),serverLog)
}
