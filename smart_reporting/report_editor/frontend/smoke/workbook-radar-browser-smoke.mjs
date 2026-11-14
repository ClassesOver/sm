import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { spawn, spawnSync } from 'node:child_process'
import { mkdir, readFile, writeFile } from 'node:fs/promises'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { setTimeout as delay } from 'node:timers/promises'
import { chromium } from 'playwright'

const frontend=fileURLToPath(new URL('../',import.meta.url)), repo=fileURLToPath(new URL('../../../../',import.meta.url))
const out=process.env.WORKBOOK_RADAR_DIRECTORY??'/tmp/workbook-radar-browser-20261113', staticRoot=process.env.PDF_SMOKE_STATIC_DIRECTORY??'/tmp/workbook-axis-hit-static-radar-20261113', port=Number(process.env.WORKBOOK_RADAR_PORT??4384), origin=`http://127.0.0.1:${port}`, python=join(repo,'.venv/bin/python'), sha=b=>createHash('sha256').update(b).digest('hex')
await mkdir(out,{recursive:false})
const fixture=spawnSync(python,[join(frontend,'smoke/workbook-radar-browser-fixture.py'),join(out,'fixture.xlsx')],{cwd:repo,encoding:'utf8'});assert.equal(fixture.status,0,fixture.stderr)
const manifestSha256=sha(await readFile(join(staticRoot,'.vite/manifest.json')))
const server=spawn(python,[join(frontend,'smoke/workbook-ai-charts-server.py'),'--directory',out,'--port',String(port),'--source',join(out,'fixture.xlsx')],{cwd:repo,env:{...process.env,PYTHONPATH:repo,PDF_SMOKE_STATIC_DIRECTORY:staticRoot},stdio:'pipe'})
let serverLog='',browser,page,stage='server';server.stdout.on('data',d=>{serverLog+=d});server.stderr.on('data',d=>{serverLog+=d})
const errors=[],consoleErrors=[],httpErrors=[],assetHashes={},assetChecks=[]
try {
 for(let attempt=0;;attempt++){assert.equal(server.exitCode,null,serverLog);try{if((await fetch(origin+'/__smoke__/state',{signal:AbortSignal.timeout(1500)})).ok)break}catch{}assert(attempt<240,serverLog);await delay(250)}
 const info=JSON.parse(await readFile(join(out,'server-info.json'),'utf8'));browser=await chromium.launch({headless:true,executablePath:process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE??'/snap/bin/chromium'});page=await browser.newPage({viewport:{width:1600,height:1100}});page.setDefaultTimeout(20000)
 page.on('pageerror',e=>errors.push(e.message));page.on('console',m=>{if(m.type()==='error')consoleErrors.push(m.text())});page.on('response',response=>{const path=new URL(response.url()).pathname;if(response.status()>=400)httpErrors.push({path,status:response.status()});if(path.startsWith('/reports/v1/editor/assets/')&&/\.(?:js|css)$/.test(path))assetChecks.push((async()=>{const bytes=await response.body(),disk=await readFile(join(staticRoot,decodeURIComponent(path.slice('/reports/v1/editor/assets/'.length))));assert.equal(sha(bytes),sha(disk),`served asset differs: ${path}`);assetHashes[path]=sha(bytes)})())})
 const ready=()=>page.waitForFunction(()=>document.querySelector('#report-editor')?.getAttribute('aria-busy')==='false',null,{timeout:90000}), command=async id=>{await page.locator('[data-ribbon-tab="Chart Design"]').click();await page.locator(`[data-ribbon-command="${id}"]`).click()},pane=()=>page.locator('.workbook-chart-format-pane:not([hidden])'),draft=()=>page.evaluate(()=>Object.entries(localStorage).filter(([key])=>key.startsWith('native-editor-draft:')).flatMap(([,value])=>JSON.parse(value).operations??[]))
 await page.addInitScript(()=>{
  window.__radarText=[];window.__radarGeometry={rings:[],markers:[],transfers:[]}
  const paths=new WeakMap(),prototype=CanvasRenderingContext2D.prototype
  const ids=new WeakMap();let nextId=0
  const canvasInfo=canvas=>{if(!ids.has(canvas))ids.set(canvas,++nextId);const rect=canvas.getBoundingClientRect();return {id:ids.get(canvas),width:canvas.width,height:canvas.height,rect:{x:rect.x,y:rect.y,width:rect.width,height:rect.height}}}
  const screen=(context,x,y)=>{const point=context.getTransform().transformPoint({x,y});return {x:point.x,y:point.y,canvas:canvasInfo(context.canvas)}}
  const drawImage=prototype.drawImage;prototype.drawImage=function(source,...args){if(source instanceof HTMLCanvasElement){const m=this.getTransform();window.__radarGeometry.transfers.push({source:canvasInfo(source),destination:canvasInfo(this.canvas),args,matrix:{a:m.a,b:m.b,c:m.c,d:m.d,e:m.e,f:m.f}})}return drawImage.call(this,source,...args)}
  const begin=prototype.beginPath;prototype.beginPath=function(){paths.set(this,[]);return begin.call(this)}
  for(const key of ['moveTo','lineTo']){const original=prototype[key];prototype[key]=function(x,y){paths.get(this)?.push(screen(this,x,y));return original.call(this,x,y)}}
  const stroke=prototype.stroke;prototype.stroke=function(...args){const points=paths.get(this);if(this.strokeStyle==='#e3e3e3'&&points?.length===12)window.__radarGeometry.rings.push(points);return stroke.apply(this,args)}
  const arc=prototype.arc;prototype.arc=function(x,y,r,...args){if(r===2.5)window.__radarGeometry.markers.push(screen(this,x,y));return arc.call(this,x,y,r,...args)}
  const fillText=prototype.fillText;prototype.fillText=function(text,...args){if(this.font==='10px system-ui'&&/^Axis [0-9]+$/.test(String(text)))window.__radarText.push(String(text));return fillText.call(this,text,...args)}
 })
 stage='open';await page.goto(origin+info.openPath);await ready();await page.waitForFunction(()=>[...(window.__sheetsWebCharts?.store.values()??[])].flat().length===1);const initialDraft=await draft()
 await command('chart-descriptions');const chart=await page.evaluate(()=>[...window.__sheetsWebCharts.store.values()].flat()[0]);assert.equal(chart.title,'Radar browser');const path=chart.chartPath;await page.locator(`[data-select-chart="${path}"]`).click();await command('chart-format-pane');await pane().waitFor();assert.equal(await pane().getByLabel('图表元素',{exact:true}).inputValue(),'chart')
 const labels=await page.evaluate(()=>[...document.querySelectorAll('.workbook-grid canvas')].length);assert(labels>0);const texts=await page.evaluate(()=>window.__radarText??[]);assert.deepEqual([...new Set(texts)],Array.from({length:12},(_,index)=>`Axis ${index+1}`))
 const store=await page.evaluate(()=>{const charts=[...window.__sheetsWebCharts.store.values()].flat();return {kind:charts[0]?.kind,series:charts[0]?.series?.map(s=>({valuesRef:s.valuesRef,categoriesRef:s.categoriesRef})),draft:Object.entries(localStorage).filter(([key])=>key.startsWith('native-editor-draft:')).flatMap(([,value])=>JSON.parse(value).operations??[])}})
 assert.equal(store.kind,'radar');assert.equal(store.series?.length,2);assert.match(store.series[0].valuesRef,/\$B\$2:\$B\$14/);assert.match(store.series[1].valuesRef,/\$C\$2:\$C\$16/);assert.match(store.series[0].categoriesRef,/\$A\$2:\$A\$14/)
 const clickTarget=async(target,point)=>{await page.mouse.click(point.x,point.y);await page.waitForFunction(target=>document.querySelector('.workbook-chart-format-pane:not([hidden]) select[aria-label="图表元素"]')?.value===target,target);assert.deepEqual(await draft(),initialDraft);return point}
 const geometry=await page.evaluate(()=>({rings:window.__radarGeometry.rings.slice(-4),markers:window.__radarGeometry.markers.slice(-24),transfers:window.__radarGeometry.transfers.slice(-100),canvases:[...document.querySelectorAll('.workbook-grid canvas')].map(canvas=>({width:canvas.width,height:canvas.height,rect:canvas.getBoundingClientRect().toJSON()}))}))
 await writeFile(join(out,'canvas-geometry-raw.json'),JSON.stringify(geometry,null,2))
 const toScreen=original=>{let point=original;for(let depth=0;depth<6;depth++){const info=point.canvas;if(info.rect.width>0)return {x:info.rect.x+point.x*info.rect.width/info.width,y:info.rect.y+point.y*info.rect.height/info.height};const transfer=[...geometry.transfers].reverse().find(item=>item.source.id===info.id);assert(transfer,`missing canvas transfer ${info.id}`);const a=transfer.args;let sx=0,sy=0,sw=info.width,sh=info.height,dx,dy,dw=sw,dh=sh;if(a.length===8)[sx,sy,sw,sh,dx,dy,dw,dh]=a;else if(a.length===4)[dx,dy,dw,dh]=a;else [dx,dy]=a;const x=dx+(point.x-sx)*dw/sw,y=dy+(point.y-sy)*dh/sh,m=transfer.matrix;point={x:m.a*x+m.c*y+m.e,y:m.b*x+m.d*y+m.f,canvas:transfer.destination}}throw Error('canvas transfer chain exceeds six steps')}
 geometry.rings=geometry.rings.map(ring=>ring.map(toScreen));geometry.markers=geometry.markers.map(toScreen)
 await writeFile(join(out,'canvas-geometry.json'),JSON.stringify(geometry,null,2));assert.equal(geometry.rings.length,4);assert.equal(geometry.markers.length,24)
 const outer=geometry.rings[3],center=outer.reduce((point,vertex)=>({x:point.x+vertex.x/12,y:point.y+vertex.y/12}),{x:0,y:0})
 const inside=(point,polygon)=>{let result=false;for(let i=0,j=polygon.length-1;i<polygon.length;j=i++){const a=polygon[i],b=polygon[j];if((a.y>point.y)!==(b.y>point.y)&&point.x<(b.x-a.x)*(point.y-a.y)/(b.y-a.y)+a.x)result=!result}return result}
 // The fixture's maximum is 32; the pinned Radar maximum is 50.
 const secondary=outer.map((point,index)=>({x:center.x+(point.x-center.x)*(index+1)*2/50,y:center.y+(point.y-center.y)*(index+1)*2/50}))
 const distances=point=>({center:Math.hypot(point.x-center.x,point.y-center.y),marker:Math.min(...geometry.markers.map(marker=>Math.hypot(point.x-marker.x,point.y-marker.y)))})
 const candidates=[];for(let dx=-75;dx<=75;dx++)for(let dy=-75;dy<=75;dy++){const point={x:center.x+dx,y:center.y+dy},distance=distances(point);if(distance.center>20&&distance.marker>10&&inside(point,secondary))candidates.push({point,distance})}
 candidates.sort((a,b)=>b.distance.marker-a.distance.marker);assert(candidates.length>0)
 const polygonSeries=await clickTarget('series:1',candidates[0].point)
 await page.screenshot({path:join(out,'radar-polygon-series-selected.png'),fullPage:true})
 const outerRing=await clickTarget('chart',outer[0]);assert(distances(outerRing).marker>7)
 await page.screenshot({path:join(out,'radar-12-axis-rings.png'),fullPage:true})
 await Promise.all(assetChecks);assert(assetChecks.length>0);assert.deepEqual(errors,[]);assert.deepEqual(consoleErrors,[]);assert.deepEqual(httpErrors,[]);assert.equal(sha(await readFile(join(staticRoot,'.vite/manifest.json'))),manifestSha256);const state=await(await page.request.get(origin+'/__smoke__/state')).json();assert.equal(state.plannerCalls,0);assert.equal(state.savedRevisions,0)
 const evidence={ok:true,browserVersion:browser.version(),scope:'Native XLSX Radar with primary 13 categories and longer secondary 15-category series; visible canvas rings, polygon selection, outer ring chart-area selection, and draft preservation',chartPath:path,seriesRefs:store.series,expectedSeriesLengths:[13,15],canvasCount:labels,renderedCategories:[...new Set(texts)],polygonSeries,polygonDistance:distances(polygonSeries),outerRing,ringGeometry:geometry.rings,initialDraft,finalDraft:store.draft,state,manifestSha256,assetHashes,errors,consoleErrors,httpErrors};await writeFile(join(out,'evidence.json'),JSON.stringify(evidence,null,2));console.log(JSON.stringify({ok:true,directory:out,browserVersion:browser.version(),seriesRefs:store.series,polygonSeries,outerRing,assets:assetChecks.length}))
} catch(error){await writeFile(join(out,'failure.json'),JSON.stringify({stage,error:String(error),stack:error.stack,serverLog,errors,consoleErrors,httpErrors},null,2));await page?.screenshot({path:join(out,'failure.png'),fullPage:true}).catch(()=>{});throw error} finally {await browser?.close();server.kill('SIGTERM');await writeFile(join(out,'server.log'),serverLog)}
