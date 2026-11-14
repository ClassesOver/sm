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
import {checkChartDescriptions} from './workbook-chart-descriptions-checks.mjs'

const frontend=fileURLToPath(new URL('../',import.meta.url)),repo=fileURLToPath(new URL('../../../../',import.meta.url))
const directory=process.env.WORKBOOK_CHART_RENDER_DIRECTORY??'/tmp/workbook-chart-render-browser-20261112'
const staticDirectory=process.env.PDF_SMOKE_STATIC_DIRECTORY??join(frontend,'../static')
const port=Number(process.env.WORKBOOK_CHART_RENDER_PORT??4354),origin=`http://127.0.0.1:${port}`
const sha=bytes=>createHash('sha256').update(bytes).digest('hex')
const smokeCase=process.env.WORKBOOK_CHART_RENDER_CASE??'geometry'
assert(['geometry','legend','axis','scale','ticks','category','labels','label-style','label-theme','label-luminance','title','anchor','anchor-types','fill'].includes(smokeCase),'Unknown chart render case')
const legend=smokeCase==='legend',axis=smokeCase==='axis',scale=smokeCase==='scale',ticks=smokeCase==='ticks',category=smokeCase==='category',labels=smokeCase==='labels'
const luminance=smokeCase==='label-luminance',themeCase=smokeCase==='label-theme'||luminance,typography=smokeCase==='label-style'||themeCase
const initialThemeColor=luminance?'#e6b9b8':'#c0504d',changedThemeColor=luminance?'#f6c6ad':'#e97132',seriesColor=luminance?'#3de13d':'#90ee90'
const title=smokeCase==='title',anchor=smokeCase==='anchor'||smokeCase==='anchor-types',anchorTypes=smokeCase==='anchor-types'
const fill=smokeCase==='fill'
await mkdir(directory,{recursive:false})
const fixture=join(frontend,typography?'smoke/workbook-chart-label-style-fixture.py':labels?'smoke/workbook-chart-labels-fixture.py':category?'smoke/workbook-chart-category-fixture.py':ticks?'smoke/workbook-chart-ticks-fixture.py':fill?'smoke/workbook-chart-fill-fixture.py':anchor?'smoke/workbook-chart-anchor-fixture.py':title?'smoke/workbook-chart-title-fixture.py':scale?'smoke/workbook-chart-scale-fixture.py':axis?'smoke/workbook-chart-axis-fixture.py':legend?'smoke/workbook-chart-legend-fixture.py':'smoke/workbook-chart-render-fixture.py'),python=join(repo,'.venv/bin/python')
const created=spawnSync(python,[fixture,anchorTypes?'create-types':'create',join(directory,'input.xlsx')],{cwd:repo,encoding:'utf8',env:{...process.env,PYTHONPATH:repo}})
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
 const context=await browser.newContext({viewport:{width:1560,height:scale||ticks||category||labels||typography||fill?1850:legend||axis?1550:1400}})
 page=await context.newPage()
 if(legend||axis||scale||ticks||category||labels||typography||title||fill)await page.addInitScript(()=>{
  window.__legendTexts=[]
  window.__valueTickTexts=[]
  window.__categoryTexts=[]
  window.__labelStylePaints=[];window.__labelStyleFrames=[]
  const frames=new WeakMap(),stroke=CanvasRenderingContext2D.prototype.strokeRect
  CanvasRenderingContext2D.prototype.strokeRect=function(...args){
   if(this.strokeStyle==='#9aa4ad'&&args[2]>=40&&args[3]>=30){
    const frame={x:args[0],y:args[1],width:args[2],height:args[3]}
    frames.set(this,frame);if(window.__labelStyleFrames.length<5000)window.__labelStyleFrames.push(frame)
   }
   return stroke.apply(this,args)
  }
  const original=CanvasRenderingContext2D.prototype.fillText
  CanvasRenderingContext2D.prototype.fillText=function(...args){
   const frame=frames.get(this),numeric=/^-?\d+\.\d+$/.test(String(args[0]))
   if(frame&&this.font==='11px system-ui'&&!numeric)frame.title=String(args[0])
   if(frame&&numeric&&this.font.includes('system-ui')&&window.__labelStylePaints.length<5000)window.__labelStylePaints.push({title:frame.title,text:String(args[0]),font:this.font,color:String(this.fillStyle).toLowerCase()})
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
 const cdp=await page.context().newCDPSession(page);await cdp.send('Network.enable');await cdp.send('Network.setCacheDisabled',{cacheDisabled:true})
 stage='open';await page.goto(origin+info.openPath)
 await page.waitForFunction(()=>document.querySelector('#report-editor')?.getAttribute('aria-busy')==='false',null,{timeout:60000})
 await page.waitForFunction(()=>window.__sheetsWebCharts?.draws>0&&window.__sheetsWebCharts.store.size>0,null,{timeout:30000})
 await page.evaluate(()=>document.fonts.ready)
 await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))))
 stage='capture'
 const evidence=await page.evaluate(()=>({charts:[...window.__sheetsWebCharts.store.values()].flat(),legendTexts:window.__legendTexts??[],valueTickTexts:window.__valueTickTexts??[],categoryTexts:window.__categoryTexts??[],labelStylePaints:window.__labelStylePaints??[],labelStyleFrames:window.__labelStyleFrames??[]}))
 await writeFile(join(directory,'model.json'),JSON.stringify(evidence,null,2))
 await page.screenshot({path:join(directory,'charts.png'),fullPage:true})
 assert.deepEqual(evidence.charts.map(c=>c.kind),typography?Array(6).fill('bar'):labels?['bar','column','bar','bar','bar','bar','bar','bar']:category?['bar','column','bar','column','bar','bar']:fill?['column','bar','pie','doughnut','column','column']:title||anchor?Array(3).fill('column'):scale||ticks?['bar','column','bar','bar','bar','bar']:axis?['column','bar','column','bar']:legend?Array(5).fill('bar'):['bar','column','bar'])
 if(fill){
  assert.equal(evidence.charts[0].series[0].color,'#136B4A')
  assert.deepEqual(evidence.charts[0].series[0].pointColors,{'2':'#A02040'})
  assert.equal(evidence.charts[1].series[0].pointColors[0],'transparent')
  assert.equal(evidence.charts[4].series[0].colorPreviewUnavailable,true)
  assert.equal(evidence.charts[5].series[0].color,'#2F5597')
  assert(evidence.legendTexts.some(text=>text.includes('填充暂不支持预览')))
 }
 if(title){
  assert(evidence.legendTexts.includes('Quarterly revenue and cost comparison across regions 2026'),'Wide chart must retain the full title')
  assert(evidence.legendTexts.some(text=>text.startsWith('很')&&text.endsWith('…')),'Narrow chart must show a measured ellipsis')
 }
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
 if(labels){
  for(const text of ['A','B','C','D'])assert(evidence.categoryTexts.includes(text),'Missing short category: '+text)
  for(const text of ['3','-5','0','$3.0','-$5.0','12.0','-5.0','$12','200%','400%'])assert(evidence.legendTexts.includes(text),'Missing data label: '+text)
  assert.equal(evidence.charts[3].dataLabels?.points?.[1]?.deleted,true)
  assert.equal(evidence.charts[3].dataLabels?.points?.[2]?.showValue,false)
  assert.equal(evidence.charts[5].dataLabels?.unsupported,true)
  assert.equal(evidence.charts[6].dataLabels?.numberFormat,'0;-0;;')
  assert.equal(evidence.charts[7].dataLabels?.numberFormat,';;;')
 }
 if(typography){
  const expected=[['Default 11px','10.0','11px system-ui','#ffffff'],['Plot 12pt bold','10.0','bold 16px system-ui',themeCase?initialThemeColor:'#ffffff'],['Series and point RGB','10.0','16px system-ui',seriesColor],['Series and point RGB','20.0','12px system-ui','#ffd700'],['Fallback 9pt red','10.0','bold 12px system-ui','#a02040']]
  for(const [title,text,font,color] of expected)assert(evidence.labelStylePaints.some(p=>p.title===title&&p.text===text&&p.font===font&&p.color===color),'Missing actual styled paint: '+JSON.stringify({title,text,font,color}))
  for(const title of ['Unresolved theme','Too large 72pt']){
   assert(evidence.labelStyleFrames.some(frame=>frame.title===title))
   assert(!evidence.labelStylePaints.some(p=>p.title===title),'Unsupported/unfittable style must not produce a false preview')
  }
 }
 if(themeCase){
  await page.screenshot({path:join(directory,'before-theme.png'),fullPage:true})
  stage='theme-replay'
  const settled=()=>page.waitForFunction(()=>!document.querySelector('#report-editor')?.inert,null,{timeout:60000})
  const color=()=>page.evaluate(()=>[...window.__sheetsWebCharts.store.values()].flat().find(c=>c.title==='Plot 12pt bold')?.dataLabels?.style?.color)
  assert.equal((await color()).toLowerCase(),initialThemeColor)
  await page.locator('[data-ribbon-tab="Page Layout"]').click()
  await page.locator('[data-ribbon-menu="theme-colors"]').selectOption('ember');await settled()
  await page.waitForFunction(expected=>[...window.__sheetsWebCharts.store.values()].flat().find(c=>c.title==='Plot 12pt bold')?.dataLabels?.style?.color?.toLowerCase()===expected,changedThemeColor)
  const changed=await color();assert.equal(changed.toLowerCase(),changedThemeColor)
  await page.locator('[data-ribbon-tab="File"]').click()
  await page.locator('[data-ribbon-command="undo"]').click();await settled();assert.equal((await color()).toLowerCase(),initialThemeColor)
  await page.locator('[data-ribbon-command="redo"]').click();await settled();assert.equal(await color(),changed)
  const waiting=page.waitForResponse(r=>r.url().endsWith('/api/save')&&r.request().method()==='POST')
  await page.locator('[data-action="save"]').click()
  const response=await waiting,payload=await response.json();assert.equal(response.status(),200)
  await writeFile(join(directory,'theme-save.json'),JSON.stringify({request:response.request().postDataJSON(),payload},null,2))
  const downloaded=await page.request.get(payload.artifacts.xlsx.downloadUrl);assert.equal(downloaded.status(),200)
  const bytes=await downloaded.body();assert.equal(sha(bytes),payload.artifacts.xlsx.sha256)
  await writeFile(join(directory,'downloaded.xlsx'),bytes)
  await page.goto(payload.editor.openUrl)
  await page.waitForFunction(()=>document.querySelector('#report-editor')?.getAttribute('aria-busy')==='false',null,{timeout:60000})
  await page.waitForFunction(()=>window.__sheetsWebCharts?.store.size>0)
  assert.equal(await color(),changed)
  await page.waitForFunction(expected=>window.__labelStylePaints?.some(p=>p.title==='Plot 12pt bold'&&p.color===expected),changedThemeColor)
  const paints=await page.evaluate(()=>window.__labelStylePaints)
  assert(paints.some(p=>p.title==='Series and point RGB'&&p.color===seriesColor))
  assert(paints.some(p=>p.title==='Series and point RGB'&&p.color==='#ffd700'))
  await writeFile(join(directory,'theme-reopened-paints.json'),JSON.stringify(paints,null,2))
  await page.evaluate(()=>document.fonts.ready)
  await page.screenshot({path:join(directory,'charts.png'),fullPage:true})
 }
 stage='independent-pixels'
 const verified=spawnSync(python,[fixture,anchorTypes?'verify-types':'verify',directory],{cwd:repo,encoding:'utf8',env:{...process.env,PYTHONPATH:repo}})
 assert.equal(verified.status,0,verified.stdout+verified.stderr)
 const independent=JSON.parse(verified.stdout)
 let chartDescriptions
 if(process.env.WORKBOOK_CHART_DESCRIPTIONS_UI==='1'){
  stage='chart-descriptions-ui'
  chartDescriptions=await checkChartDescriptions(page,directory,evidence.charts)
 }
 await Promise.all(checks);assert(assets.size>0)
 assert.equal(sha(await readFile(join(staticDirectory,'.vite/manifest.json'))),sha(manifest))
 assert.deepEqual(pageErrors,[]);assert.deepEqual(consoleErrors,[]);assert.deepEqual(httpErrors,[]);assert.deepEqual(assetErrors,[])
 const state=await(await page.request.get(origin+'/__smoke__/state')).json()
 assert.equal(state.sourceSha256,info.sourceSha256);assert.equal(state.savedRevisions,themeCase?1:0);assert.equal(state.plannerCalls,0)
 assert.equal(sha(await readFile(join(directory,'source.xlsx'))),info.sourceSha256)
 assert.equal(sha(await readFile(join(directory,'input.xlsx'))),info.sourceSha256)
 const summary={ok:true,browserVersion:browser.version(),fontPreflight,manifestSha256:sha(manifest),assets:Object.fromEntries(assets),sourceSha256:info.sourceSha256,independent,chartDescriptions,pageErrors,consoleErrors,httpErrors,assetErrors,state}
 await writeFile(join(directory,'summary.json'),JSON.stringify(summary,null,2));console.log(JSON.stringify({ok:true,directory,assets:assets.size,independent}))
}catch(error){
 await writeFile(join(directory,'failure.json'),JSON.stringify({stage,error:String(error),stack:error.stack,pageErrors,consoleErrors,httpErrors,assetErrors,serverLog},null,2))
 if(page)await page.screenshot({path:join(directory,'failure.png'),fullPage:true}).catch(()=>{})
 throw error
}finally{
 await browser?.close();server.kill('SIGTERM');await writeFile(join(directory,'server.log'),serverLog)
}
