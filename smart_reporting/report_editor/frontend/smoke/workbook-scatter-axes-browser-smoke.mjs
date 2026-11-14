// Real native HTTP routes, writer, one save, download and reopen; no mocked routes.
import assert from 'node:assert/strict'
import {spawn, spawnSync} from 'node:child_process'
import {createHash} from 'node:crypto'
import {once} from 'node:events'
import {copyFile, mkdir, readFile, writeFile} from 'node:fs/promises'
import {join} from 'node:path'
import {fileURLToPath} from 'node:url'
import {setTimeout as delay} from 'node:timers/promises'
import {chromium} from 'playwright'

const toolFrontend=fileURLToPath(new URL('../',import.meta.url))
const repo=process.env.SCATTER_AXES_REPO_DIRECTORY,frontend=process.env.SCATTER_AXES_FRONTEND_DIRECTORY??toolFrontend
const out=process.env.SCATTER_AXES_DIRECTORY,staticRoot=process.env.PDF_SMOKE_STATIC_DIRECTORY
const engineRoot=process.env.AGENT_REPORTING_WORKBOOK_ENGINE_DIR,wrapper=process.env.SCATTER_AXES_SERVER_WRAPPER
const provenanceDirectory=process.env.SCATTER_AXES_SERVER_PROVENANCE_DIRECTORY
const port=Number(process.env.SCATTER_AXES_PORT??4395),origin=`http://127.0.0.1:${port}`
const sha=bytes=>createHash('sha256').update(bytes).digest('hex')
assert.equal(process.env.SCATTER_AXES_RUN_AUTHORIZED,'1','root must freeze and authorize this run')
assert(repo&&out&&staticRoot&&engineRoot&&wrapper&&provenanceDirectory)
await mkdir(out,{recursive:false})
const frozenInputs={}
for(const path of [fileURLToPath(import.meta.url),join(toolFrontend,'smoke/workbook-scatter-axes-browser-fixture.py'),wrapper]){
 const name=path.slice(path.lastIndexOf('/')+1);await copyFile(path,join(out,name));frozenInputs[name]=sha(await readFile(join(out,name)))
}
// The existing server stays beside its sibling helpers; its identity is captured.
const serverPath=join(frontend,'smoke/workbook-ai-charts-server.py')
frozenInputs.server={path:serverPath,sha256:sha(await readFile(serverPath))}
await writeFile(join(out,'tool-inputs.json'),JSON.stringify(frozenInputs,null,2))
const python=join(repo,'.venv/bin/python'),fixturePath=join(out,'workbook-scatter-axes-browser-fixture.py')
const fixture=spawnSync(python,[fixturePath,join(out,'fixture.xlsx')],{cwd:repo,encoding:'utf8'})
await writeFile(join(out,'fixture.stdout.log'),fixture.stdout??'');await writeFile(join(out,'fixture.stderr.log'),fixture.stderr??'')
assert.equal(fixture.status,0,fixture.stderr)
const enginePath=join(engineRoot,'dist/cli.mjs'),runtimeBefore={path:enginePath,sha256:sha(await readFile(enginePath))}
const manifestPath=join(staticRoot,'.vite/manifest.json'),manifestSha256=sha(await readFile(manifestPath))
assert.equal(manifestSha256,process.env.SCATTER_AXES_EXPECTED_MANIFEST_SHA256,'run only the root-frozen UI')
assert.equal(runtimeBefore.sha256,process.env.SCATTER_AXES_EXPECTED_ENGINE_SHA256,'run only the root-frozen engine')
const inspect=async(name,path)=>{
 const request=join(out,name+'-inspect-request.json');await writeFile(request,JSON.stringify({kind:'inspect',input:path},null,2))
 const result=spawnSync(process.execPath,[enginePath,request],{cwd:repo,encoding:'utf8'})
 await writeFile(join(out,name+'-inspect.stdout.json'),result.stdout??'');await writeFile(join(out,name+'-inspect.stderr.log'),result.stderr??'')
 assert.equal(result.status,0,result.stderr);return JSON.parse(result.stdout)
}
const inspectedFixture=await inspect('fixture',join(out,'fixture.xlsx'))
const server=spawn(python,[join(out,wrapper.slice(wrapper.lastIndexOf('/')+1)),serverPath,'--directory',out,'--port',String(port),'--source',join(out,'fixture.xlsx')],{cwd:repo,env:{...process.env,PYTHONPATH:repo,PDF_SMOKE_STATIC_DIRECTORY:staticRoot,SCATTER_VALUE_LABELS_REPO_DIRECTORY:repo,SCATTER_VALUE_LABELS_SERVER_PROVENANCE_DIRECTORY:provenanceDirectory},stdio:'pipe'})
let serverLog='',browser,page,initialState,stage='server'
server.stdout.on('data',bytes=>serverLog+=bytes);server.stderr.on('data',bytes=>serverLog+=bytes)
const errors=[],consoleErrors=[],httpErrors=[],assetErrors=[],assetHashes={},assetChecks=[]
try{
 for(let attempt=0;;attempt++){
  assert.equal(server.exitCode,null,serverLog)
  try{const response=await fetch(origin+'/__smoke__/state',{signal:AbortSignal.timeout(1500)});if(response.ok){initialState=await response.json();break}}catch{}
  assert(attempt<240,serverLog);await delay(250)
 }
 await writeFile(join(out,'initial-state.json'),JSON.stringify(initialState,null,2));assert.equal(initialState.savedRevisions,0)
 const info=JSON.parse(await readFile(join(out,'server-info.json'),'utf8'))
 browser=await chromium.launch({headless:true,executablePath:process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE??'/snap/bin/chromium'})
 page=await browser.newPage({viewport:{width:1700,height:1150}});page.setDefaultTimeout(20000)
 const cdp=await page.context().newCDPSession(page);await cdp.send('Network.enable');await cdp.send('Network.setCacheDisabled',{cacheDisabled:true})
 page.on('pageerror',error=>errors.push(error.message));page.on('console',message=>{if(message.type()==='error')consoleErrors.push(message.text())})
 page.on('response',response=>{const path=new URL(response.url()).pathname;if(response.status()>=400)httpErrors.push({path,status:response.status()});if(path.startsWith('/reports/v1/editor/assets/')&&/\.(?:js|css)$/.test(path))assetChecks.push((async()=>{assert.equal(response.status(),200);const bytes=await response.body();assert.equal(sha(bytes),sha(await readFile(join(staticRoot,decodeURIComponent(path.slice('/reports/v1/editor/assets/'.length))))));assetHashes[path]=sha(bytes)})().catch(error=>assetErrors.push({path,error:String(error)})))})
 await page.addInitScript(()=>{
  window.__scatterAxesFrames={}
  const ids=new WeakMap(),paths=new WeakMap();let next=0,active
  const id=canvas=>{if(!ids.has(canvas))ids.set(canvas,++next);return ids.get(canvas)}
  const matrix=ctx=>{const m=ctx.getTransform();return {a:m.a,b:m.b,c:m.c,d:m.d,e:m.e,f:m.f}}
  const fill=CanvasRenderingContext2D.prototype.fillText
  CanvasRenderingContext2D.prototype.fillText=function(text,x,y,...rest){
   text=String(text)
   if(['Axes standard','Axes standard draft','Axes hidden'].includes(text)){active=text;window.__scatterAxesFrames[active]={texts:[],paths:[]}}
   if(active)window.__scatterAxesFrames[active].texts.push({text,x,y,font:this.font,align:this.textAlign,baseline:this.textBaseline,transform:matrix(this),canvasId:id(this.canvas)})
   return fill.call(this,text,x,y,...rest)
  }
  const begin=CanvasRenderingContext2D.prototype.beginPath
  CanvasRenderingContext2D.prototype.beginPath=function(){paths.set(this,[]);return begin.call(this)}
  for(const method of ['moveTo','lineTo']){const original=CanvasRenderingContext2D.prototype[method];CanvasRenderingContext2D.prototype[method]=function(x,y){const p=paths.get(this)??[];p.push({method,x,y});paths.set(this,p);return original.call(this,x,y)}}
  const stroke=CanvasRenderingContext2D.prototype.stroke
  CanvasRenderingContext2D.prototype.stroke=function(...args){if(active&&!args.length)window.__scatterAxesFrames[active].paths.push({points:paths.get(this)??[],color:String(this.strokeStyle).toLowerCase(),lineWidth:this.lineWidth,transform:matrix(this),canvasId:id(this.canvas)});return stroke.apply(this,args)}
 })
 const ready=()=>page.waitForFunction(()=>document.querySelector('#report-editor')?.getAttribute('aria-busy')==='false',null,{timeout:90000})
 const charts=()=>page.evaluate(()=>[...window.__sheetsWebCharts.store.values()].flat().map(chart=>({title:chart.title,chartPath:chart.chartPath,kind:chart.kind,axes:chart.axes,design:chart.design,dataLabels:chart.dataLabels,series:chart.series.map(s=>({numberFormat:s.numberFormat,marker:s.marker,valuesRef:s.valuesRef,xValuesRef:s.xValuesRef}))})))
 const draft=()=>page.evaluate(()=>Object.entries(localStorage).filter(([key])=>key.startsWith('native-editor-draft:')).flatMap(([,value])=>JSON.parse(value).operations??[]))
 const command=async id=>{await page.locator('[data-ribbon-tab="Chart Design"]').click();await page.locator(`[data-ribbon-command="${id}"]`).click()}
 const pane=()=>page.locator('.workbook-chart-format-pane:not([hidden])')
 const closePane=async()=>{if(await pane().count()){await pane().getByRole('button',{name:'关闭图表格式',exact:true}).click();await pane().waitFor({state:'hidden'})}}
 const select=async path=>{await closePane();await command('chart-descriptions');await page.locator(`[data-select-chart="${path}"]`).click()}
 const waitDraft=async count=>{await page.waitForFunction(count=>Object.entries(localStorage).filter(([key])=>key.startsWith('native-editor-draft:')).flatMap(([,value])=>JSON.parse(value).operations??[]).length>count,count);await page.waitForFunction(()=>!document.querySelector('.workbook-chart-format-pane:not([hidden])')?.hasAttribute('aria-busy'))}
 const design=async(id,label,value)=>{const count=(await draft()).length;await closePane();await command(id);const dialog=page.locator('.workbook-ribbon-format-dialog:visible');await dialog.getByLabel(label,{exact:true}).fill(value);await dialog.getByRole('button',{name:'确定',exact:true}).click();await dialog.waitFor({state:'hidden'});await waitDraft(count)}
 const checkCharts=(rows,edited)=>{
  assert.equal(rows.length,2)
  const standard=rows.find(c=>c.chartPath==='xl/charts/chart1.xml'),hidden=rows.find(c=>c.chartPath==='xl/charts/chart2.xml')
  for(const [chart,ids,fmt] of [[standard,[101,202],'0.000'],[hidden,[303,404],'0.0']]){assert.equal(chart.kind,'scatter');assert.equal(chart.axes.category.id,ids[0]);assert.equal(chart.axes.value.id,ids[1]);assert.equal(chart.dataLabels.showValue,true);assert.equal(chart.series[0].numberFormat,fmt);assert.equal(chart.series[0].marker,'none')}
  assert.equal(standard.axes.category.title,edited?'Elapsed edited':'Elapsed');assert.equal(standard.axes.value.title,edited?'Sales edited':'Sales')
  assert.equal(standard.axes.category.displayUnit,1000);assert.equal(standard.axes.value.displayUnit,1000)
  assert.equal(standard.axes.category.scaling.max,2000);assert.equal(standard.axes.value.scaling.max,edited?15000:10000)
  assert.equal(standard.axes.category.scaling.min,0);assert.equal(standard.axes.value.scaling.min,edited?-5000:0)
  assert.equal(standard.axes.category.majorGridlines,true);assert.equal(standard.axes.value.majorGridlines,edited)
  assert.equal(hidden.axes.category.hidden,true);assert.equal(hidden.axes.value.hidden,true);assert.equal(hidden.axes.category.position,'top');assert.equal(hidden.axes.value.position,'right')
  assert.equal(hidden.axes.category.displayUnit,100);assert.equal(hidden.axes.value.displayUnit,1000000)
 }
 const geometry=async edited=>{
  const name=edited?'Axes standard draft':'Axes standard'
  await page.waitForFunction(({name,title})=>window.__scatterAxesFrames[name]?.texts.some(t=>t.text===title),{name,title:edited?'Sales edited':'Sales'})
  const frames=await page.evaluate(()=>window.__scatterAxesFrames),normal=frames[name],hidden=frames['Axes hidden']
  for(const [frame,xTitle,yTitle,unit,horizontal,vertical,isHidden] of [[normal,edited?'Elapsed edited':'Elapsed',edited?'Sales edited':'Sales','Thousands',edited?5:1,3,false],[hidden,'Hidden X','Hidden Y','Millions',3,0,true]]){
   assert(frame)
   const grids=frame.paths.filter(p=>p.color==='#e3e3e3'&&p.points.length===2)
   const h=grids.filter(p=>p.points[0].y===p.points[1].y),v=grids.filter(p=>p.points[0].x===p.points[1].x)
   assert.equal(h.length,horizontal);assert.equal(v.length,vertical)
   const ticks=frame.texts.filter(t=>t.font==='9px system-ui'&&(t.baseline==='top'||t.align==='right'))
   if(isHidden)assert.equal(ticks.length,0)
   else{assert.deepEqual(ticks.filter(t=>t.align==='center').map(t=>t.text),['0.0','1.0','2.0']);assert.deepEqual(ticks.filter(t=>t.align==='right').map(t=>t.text),edited?['-5.00','0.00','5.00','10.00','15.00']:['0.00','5.00','10.00'])}
   const x=frame.texts.find(t=>t.text===xTitle),y=frame.texts.find(t=>t.text===yTitle),u=frame.texts.find(t=>t.text===unit)
   assert(x&&y&&u);assert.equal(x.align,'center');assert.equal(x.baseline,'middle');assert.equal(x.transform.b,0);assert.equal(x.transform.c,0)
   for(const t of [y,u]){assert.equal(t.x,0);assert.equal(t.y,0);assert(Math.abs(t.transform.a)<1e-8);assert(Math.abs(t.transform.d)<1e-8);assert(t.transform.b<0);assert(t.transform.c>0)}
   const grid=h[0],left=grid.points[0].x,right=grid.points[1].x
   assert(Math.abs(x.x-(left+right)/2)<1e-6);assert(x.y>Math.max(...h.map(p=>p.points[0].y)))
   const base=grid.transform;const screenX=t=>t.transform.e/base.a-base.e/base.a
   assert(screenX(y)<left);assert(screenX(u)>screenX(y));assert(screenX(u)<left)
   assert.equal(frame.texts.some(t=>t.text==='Hundreds'),false)
   assert.equal(frame.texts.some(t=>t.text==='X ONLY UNITS'),false)
   const values=frame.texts.filter(t=>t.font==='9px system-ui'&&t.baseline==='alphabetic'&&t.align==='center')
   assert.deepEqual(values.map(t=>t.text),isHidden?['0.0','5000.0','10000.0']:['0.000','5000.000','10000.000'])
   assert(values[0].x<values[1].x&&values[1].x<values[2].x);assert(values[0].y>values[1].y&&values[1].y>values[2].y)
   if(!isHidden)for(const [index,label] of values.entries()){
    assert.equal(label.x,ticks.find(t=>t.align==='center'&&t.text===['0.0','1.0','2.0'][index]).x)
    assert.equal(label.y+8,ticks.find(t=>t.align==='right'&&t.text===['0.00','5.00','10.00'][index]).y)
   }
   const points=frame.paths.filter(p=>p.color==='#1b7f5a').flatMap(p=>p.points.map(point=>({...point,transform:p.transform})))
   for(const label of values)assert(points.some(point=>point.x===label.x&&point.y===label.y+8&&JSON.stringify(point.transform)===JSON.stringify(label.transform)))
  }
  return frames
 }
 stage='open';await page.goto(origin+info.openPath);await ready();await page.waitForFunction(()=>[...(window.__sheetsWebCharts?.store.values()??[])].flat().length===2)
 const initialCharts=await charts();checkCharts(initialCharts,false);assert.equal((await draft()).length,0)
 const initialGeometry=await geometry(false);await page.screenshot({path:join(out,'initial.png'),fullPage:true})
 stage='manual-chart-draft';await select('xl/charts/chart1.xml');await design('chart-title','图表标题','Axes standard draft')
 const manualDraft=await draft();assert.equal(manualDraft.length,1)
 stage='axis-title-dialogs';await design('chart-axis-cat','分类轴标题','Elapsed edited');await design('chart-axis-val','数值轴标题','Sales edited')
 stage='value-axis-pane';await command('chart-format-pane');await pane().waitFor();assert.equal(await pane().getByLabel('最大值',{exact:true}).inputValue(),'10000')
 let count=(await draft()).length;await pane().getByLabel('最小值',{exact:true}).fill('-5000');await pane().getByLabel('最小值',{exact:true}).press('Enter');await waitDraft(count)
 count=(await draft()).length;await pane().getByLabel('最大值',{exact:true}).fill('15000');await pane().getByLabel('最大值',{exact:true}).press('Enter');await waitDraft(count)
 count=(await draft()).length;await pane().getByLabel('显示主网格线',{exact:true}).check();await waitDraft(count)
 const editedDraft=await draft();assert.deepEqual(editedDraft.slice(0,manualDraft.length),manualDraft)
 assert(editedDraft.every(op=>op.kind==='applyChartEdits'&&op.edits.every(edit=>edit.chartPath==='xl/charts/chart1.xml')))
 const editedCharts=await charts();checkCharts(editedCharts,true);const editedGeometry=await geometry(true)
 await page.screenshot({path:join(out,'edited-pane.png'),fullPage:true});await closePane()
 stage='save';const waiting=page.waitForResponse(response=>response.request().method()==='POST'&&response.url().endsWith('/api/save'));await page.locator('[data-action="save"]').click()
 const response=await waiting,rawSave=await response.body()
 // Persist the actual response before parsing, validating, or attempting a download.
 await writeFile(join(out,'save-response.raw.json'),rawSave)
 await writeFile(join(out,'save-http.json'),JSON.stringify({status:response.status(),headers:response.headers(),request:response.request().postDataJSON()},null,2))
 const saved=JSON.parse(rawSave);assert.equal(response.status(),200,rawSave.toString());assert.equal(saved.revisionRegistered,true);assert.equal(saved.parentRevision,info.context.revision);assert.equal(saved.revision,info.context.revision+1)
 stage='download';const download=await page.request.get(new URL(saved.artifacts.xlsx.downloadUrl,origin).href),bytes=await download.body()
 await writeFile(join(out,'download-http.json'),JSON.stringify({status:download.status(),headers:download.headers(),size:bytes.length,sha256:sha(bytes)},null,2));await writeFile(join(out,'downloaded.xlsx'),bytes)
 assert.equal(download.status(),200);assert.equal(sha(bytes),saved.artifacts.xlsx.sha256);assert.equal(bytes.length,saved.artifacts.xlsx.size)
 const zip=spawnSync(python,[fixturePath,'--verify',join(out,'fixture.xlsx'),join(out,'downloaded.xlsx'),join(out,'zip-readback.json')],{cwd:repo,encoding:'utf8'})
 await writeFile(join(out,'zip-readback.stdout.log'),zip.stdout??'');await writeFile(join(out,'zip-readback.stderr.log'),zip.stderr??'');assert.equal(zip.status,0,zip.stderr)
 const inspectedSaved=await inspect('downloaded',join(out,'downloaded.xlsx'))
 stage='reopen';await page.goto(saved.editor.openUrl);await ready();await page.waitForFunction(()=>[...(window.__sheetsWebCharts?.store.values()??[])].flat().length===2)
 const reopenedCharts=await charts();checkCharts(reopenedCharts,true);const reopenedGeometry=await geometry(true);assert.equal((await draft()).length,0)
 const actual=await page.request.get(page.url()+'/api/file');assert.equal(actual.status(),200);assert.equal(sha(await actual.body()),saved.artifacts.xlsx.sha256)
 await select('xl/charts/chart1.xml');await command('chart-format-pane');await pane().waitFor();assert.equal(await pane().getByLabel('最小值',{exact:true}).inputValue(),'-5000');assert.equal(await pane().getByLabel('最大值',{exact:true}).inputValue(),'15000');assert.equal(await pane().getByLabel('显示主网格线',{exact:true}).isChecked(),true)
 await page.screenshot({path:join(out,'reopened-pane.png'),fullPage:true});await closePane();await page.screenshot({path:join(out,'reopened.png'),fullPage:true})
 const state=await(await page.request.get(origin+'/__smoke__/state')).json();assert.equal(state.savedRevisions,1);assert.equal(state.plannerCalls,0);assert.equal(state.requests.filter(row=>row.method==='POST'&&row.path.endsWith('/api/save')).length,1)
 await Promise.all(assetChecks);assert(assetChecks.length>0);assert.deepEqual(assetErrors,[]);assert.deepEqual(errors,[]);assert.deepEqual(consoleErrors,[]);assert.deepEqual(httpErrors,[])
 assert.equal(sha(await readFile(manifestPath)),manifestSha256);const runtimeAfter={path:enginePath,sha256:sha(await readFile(enginePath))};assert.deepEqual(runtimeAfter,runtimeBefore)
 await writeFile(join(out,'evidence.json'),JSON.stringify({ok:true,initialCharts,editedCharts,reopenedCharts,initialGeometry,editedGeometry,reopenedGeometry,manualDraft,editedDraft,inspectedFixture,inspectedSaved,state,manifestSha256,runtimeBefore,runtimeAfter,frozenInputs,assetHashes,serverPid:server.pid,browserVersion:browser.version(),errors,consoleErrors,httpErrors},null,2))
 console.log(JSON.stringify({ok:true,directory:out,savedRevisions:state.savedRevisions,sha256:sha(bytes),assets:assetChecks.length}))
}catch(error){const state=await fetch(origin+'/__smoke__/state',{signal:AbortSignal.timeout(1500)}).then(response=>response.json()).catch(()=>null);await writeFile(join(out,'failure.json'),JSON.stringify({stage,error:String(error),stack:error.stack,state,initialState,serverPid:server.pid,serverLog,errors,consoleErrors,httpErrors},null,2));await page?.screenshot({path:join(out,'failure.png'),fullPage:true}).catch(()=>{});throw error}
finally{await browser?.close();if(server.exitCode===null){const exited=once(server,'exit');server.kill('SIGTERM');await exited}await writeFile(join(out,'server.log'),serverLog)}
