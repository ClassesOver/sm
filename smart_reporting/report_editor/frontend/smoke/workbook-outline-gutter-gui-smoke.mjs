import assert from 'node:assert/strict'
import {createHash} from 'node:crypto'
import {spawn,spawnSync} from 'node:child_process'
import {setTimeout as delay} from 'node:timers/promises'
import {chromium} from 'playwright'
const frontend=process.cwd(),repo=new URL('../../../',`file://${frontend}/`).pathname,base='http://127.0.0.1:4196',media='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
function python(payload){
 const r=spawnSync(`${repo}/.venv/bin/python`,['-c',`
import base64,json,sys
from io import BytesIO
from openpyxl import Workbook,load_workbook
p=json.load(sys.stdin)
if p['mode']=='create':
 b=Workbook();s=b.active;s.title='Outline'
 for i in range(1,101):s.append([i,'Item '+str(i),i*2,i*3,i*4,i*5])
 s.row_dimensions.group(2,8,outline_level=1,hidden=False);s.row_dimensions.group(3,4,outline_level=2,hidden=False);s.row_dimensions.group(20,22,outline_level=1,hidden=False)
 if p.get('perf'):s.row_dimensions.group(200,10199,outline_level=1,hidden=False)
 s.column_dimensions.group('B','D',outline_level=1,hidden=False);s.column_dimensions.group('C','C',outline_level=2,hidden=False)
 b.create_sheet('Plain')['A1']='Plain cell'
 stream=BytesIO();b.save(stream);print(base64.b64encode(stream.getvalue()).decode())
elif p['mode']=='patch':
 from smart_reporting.report_editor.native_office import patch_office
 print(base64.b64encode(patch_office('xlsx',base64.b64decode(p['bytes']),p['operations'])).decode())
else:
 s=load_workbook(BytesIO(base64.b64decode(p['bytes']))).active
 print(json.dumps({'rows':{str(i):{'level':d.outlineLevel,'hidden':d.hidden,'collapsed':d.collapsed} for i,d in s.row_dimensions.items()},'cols':{i:{'level':d.outlineLevel,'hidden':d.hidden,'collapsed':d.collapsed} for i,d in s.column_dimensions.items()},'freeze':s.freeze_panes,'zoom':s.sheet_view.zoomScale,'value':s['A1'].value}))
`],{cwd:repo,env:{...process.env,PYTHONPATH:repo},input:JSON.stringify(payload),encoding:'utf8',maxBuffer:20*1024*1024})
 if(r.status)throw Error(r.stderr);return r.stdout.trim()
}
const source=Buffer.from(python({mode:'create',perf:process.env.OUTLINE_GUI_PERF==='1'}),'base64')
const ctx=bytes=>({documentId:'outline-gutter',format:'xlsx',revision:1,parentRevision:null,scope:{database:'f',companyId:'f',userId:'f',threadId:'f'},sourceFile:{path:'outline.xlsx',size:bytes.length,sha256:createHash('sha256').update(bytes).digest('hex'),mediaType:media},origin:'upload'})
const preview=process.env.NATIVE_GUI_PREVIEW==='1'
const server=spawn('./node_modules/.bin/vite',[...(preview?['preview']:[]),'--host','127.0.0.1','--port','4196','--strictPort'],{cwd:frontend,stdio:'ignore'})
let browser,saved,payload,activePage
try{
 for(let i=0;i<120;i++){try{if((await fetch(`${base}/reports/v1/editor/assets/native.html`)).ok)break}catch{}await delay(250)}
 browser=await chromium.launch({headless:true,args:['--disable-features=LocalNetworkAccessChecks']})
 const context=await browser.newContext({viewport:{width:1440,height:1100}}),page=await context.newPage(),errors=[]
 activePage=page
 page.on('pageerror',e=>errors.push(e.message))
 page.on('console',m=>{if(m.type()==='warning'&&m.text().includes('outline-gutter'))console.log('GUTTER_WARNING',m.text())})
 if(process.env.OUTLINE_GUI_PERF!=='1')await page.addInitScript(()=>{
  window.__outlineGlyphs={};const fill=CanvasRenderingContext2D.prototype.fillText,clear=CanvasRenderingContext2D.prototype.clearRect
  CanvasRenderingContext2D.prototype.clearRect=function(...a){if(String(this.canvas.className).includes('outline-gutter'))window.__outlineGlyphs[this.canvas.className]=[];return clear.apply(this,a)}
  CanvasRenderingContext2D.prototype.fillText=function(text,x,y,...rest){
   if(String(this.canvas.className).includes('outline-gutter')){const m=this.getTransform(),r=this.canvas.getBoundingClientRect(),ratio=this.canvas.width/r.width;const records=window.__outlineGlyphs[this.canvas.className]??=[];records.push({text:String(text),x:r.x+(m.a*x+m.c*y+m.e)/ratio,y:r.y+(m.b*x+m.d*y+m.f)/ratio})}
   return fill.call(this,text,x,y,...rest)
  }
 })
 if(process.env.OUTLINE_GUI_PERF==='1')await page.route('**/src/workbook-outline-gutter.ts*',async route=>{
  const response=await route.fetch();let body=await response.text()
  body=body.replace('outlineCache = readWorkbookOutline(worksheet);', 'window.__outlineMetadataReads=(window.__outlineMetadataReads??0)+1; outlineCache = readWorkbookOutline(worksheet);')
  body=body.replace('if (groupCache?.key !== cacheKey) {', 'if (groupCache?.key !== cacheKey) {window.__outlineGroupRebuilds??=[];window.__outlineGroupRebuilds.push([skeleton.rowTotalHeight,skeleton.columnTotalWidth]);')
  if(process.env.OUTLINE_GUI_TRACE==='1'){
   for(const marker of ['const outline = outlineCache;', 'const gridBounds = gridCanvas.getBoundingClientRect();', 'const rowBounds = rowCanvas.getBoundingClientRect();', 'const next = [', 'const cacheKey =', 'const colors = palette();', 'hits = nextHits;']){
    body=body.replace(marker,`window.__outlineTimings??=[];window.__outlineTimings.push([${JSON.stringify(marker)},performance.now()]);${marker}`)
   }
  }
  body=body.replace('export function installOutlineGutter(deps)', 'function installOutlineGutterOriginal(deps)')
  body+='\nexport function installOutlineGutter(deps){deps.runtime.univerAPI.onCommandExecuted(c=>{const counts=window.__outlineCommandCounts??={};counts[c.id]=(counts[c.id]??0)+1});const handle=installOutlineGutterOriginal(deps);window.__outlineGutterHandle=handle;return handle}\n'
  await route.fulfill({response,body})
 })
 await page.route('**/reports/v1/native/outline-gutter/1/api/context',r=>r.fulfill({json:{context:ctx(source),csrfToken:'csrf',capabilities:{xlsx_editor:true},editingEnabled:true}}))
 await page.route('**/reports/v1/native/outline-gutter/1/api/file',r=>r.fulfill({body:source,contentType:media}))
 await page.route('**/reports/v1/native/outline-gutter/1/api/save',async r=>{payload=r.request().postDataJSON();console.log(JSON.stringify({phase:'save-request',operations:payload.operations}));saved=Buffer.from(python({mode:'patch',bytes:source.toString('base64'),operations:payload.operations}),'base64');await r.fulfill({json:{documentId:'outline-gutter',revision:2,parentRevision:1,revisionRegistered:true,artifacts:{xlsx:{downloadUrl:'/gutter-download.xlsx'}},editor:{openUrl:'/reports/v1/native/outline-gutter/2'},validation:{issues:[]}}})})
 await page.route(/\/reports\/v1\/native\/outline-gutter\/[12]$/,async r=>r.fulfill({response:await r.fetch({url:`${base}/reports/v1/editor/assets/native.html`})}))
 await page.addInitScript(()=>history.replaceState(null,'','/reports/v1/native/outline-gutter/1'))
 await page.goto(`${base}/reports/v1/editor/assets/native.html`)
 const ready=async()=>{await page.waitForFunction(()=>document.querySelector('#report-editor')?.getAttribute('aria-busy')==='false');await page.locator('.outline-gutter-rows').waitFor({timeout:60000});if(process.env.OUTLINE_GUI_PERF!=='1')await page.waitForFunction(()=>Object.values(window.__outlineGlyphs).flat().some(g=>g.text==='−'))}
 const glyphs=axis=>page.evaluate(axis=>Object.entries(window.__outlineGlyphs).filter(([key])=>key.endsWith(axis)).flatMap(([,v])=>v),axis)
 const clickGlyph=async(axis,text,pick=list=>list[0])=>{await delay(100);const list=(await glyphs(axis)).filter(g=>g.text===text);assert(list.length,`${axis} ${text} must paint`);const target=pick(list);await page.mouse.click(target.x,target.y);return target}
 const ops=()=>page.evaluate(()=>Object.keys(localStorage).filter(k=>k.startsWith('native-editor-draft:')).flatMap(k=>JSON.parse(localStorage.getItem(k)).operations))
 const waitHidden=async(axis,index,hidden)=>page.waitForFunction(({axis,index,hidden})=>Object.keys(localStorage).filter(k=>k.startsWith('native-editor-draft:')).some(k=>{
  let value=false
  for(const op of JSON.parse(localStorage.getItem(k)).operations)if(op.kind==='applySheetOutline')for(const e of op[axis]??[])if(e.index===index&&e.hidden!==undefined)value=e.hidden
  return value===hidden
 }),{axis,index,hidden})
 const goto=async(reference)=>{await page.locator('[data-ribbon-tab="Home"]').click();await page.locator('[data-ribbon-command="goto-open"]').click();await page.locator('[data-goto-reference]').fill(reference);await page.locator('.workbook-ribbon-goto-dialog button[type="submit"]').click()}
 await ready();
 if(process.env.OUTLINE_GUI_PERF==='1'){
  await delay(1200)
  const measure=async()=>{
   await page.evaluate(()=>{window.__gutterPerf={frames:[],longTasks:[]};window.__outlineCommandCounts={};window.__outlineMetadataReads=0;window.__outlineTimings=[];window.__outlineGroupRebuilds=[];if(!window.__gutterWrapped){window.__gutterWrapped=true;const request=window.requestAnimationFrame;window.requestAnimationFrame=callback=>request.call(window,time=>{const start=performance.now();callback(time);window.__gutterPerf.frames.push(performance.now()-start)})}window.__gutterObserver?.disconnect();window.__gutterObserver=new PerformanceObserver(list=>window.__gutterPerf.longTasks.push(...list.getEntries().map(e=>e.duration)));window.__gutterObserver.observe({entryTypes:['longtask']})})
   for(let i=0;i<10;i++){await page.locator('.workbook-grid').hover();await page.mouse.wheel(0,90);await delay(80)}
   await delay(300)
   return page.evaluate(()=>{const all=window.__gutterPerf.frames;return {groupRebuilds:window.__outlineGroupRebuilds,timings:window.__outlineTimings,commands:window.__outlineCommandCounts,metadataReads:window.__outlineMetadataReads,count:all.length,maxMs:Math.max(...all),meanMs:all.reduce((a,b)=>a+b,0)/all.length,longTasks:window.__gutterPerf.longTasks}})
  }
  const enabled=await measure()
  await goto('A1');await delay(300)
  await page.evaluate(()=>{if(!window.__outlineGutterHandle)throw Error('missing test-only captured gutter handle');window.__outlineGutterHandle.dispose()})
  await delay(500)
  const disabled=await measure()
  console.log(JSON.stringify({phase:'10000-group-rows-controlled-browser',enabled,disabled,viewport:await page.viewportSize()}))
  assert.equal(enabled.metadataReads,0,'pure scrolling must reuse cached outline metadata')
  assert(enabled.count>0&&disabled.count>0);await browser.close();browser=null;server.kill();process.exit(0)
 }
 console.log(JSON.stringify({phase:'initial-glyphs',rows:await glyphs('rows'),cols:await glyphs('cols')}))
 // Inner group: its bracket column is farther right than the outer group's.
 await clickGlyph('rows','−',list=>list.sort((a,b)=>b.x-a.x)[0]);await waitHidden('rows',2,true)
 // Exact outer group button, even while native selection has moved to the inner summary.
 await clickGlyph('rows','−',list=>list.sort((a,b)=>a.y-b.y)[0]);await waitHidden('rows',1,true)
 await clickGlyph('rows','+',list=>list.sort((a,b)=>b.y-a.y)[0]);await waitHidden('rows',1,false)
 assert((await ops()).some(op=>op.kind==='applySheetOutline'&&op.rows.some(e=>e.index===2&&e.hidden===true)),'outer expand retains explicitly folded inner group')
 await clickGlyph('cols','1');await waitHidden('columns',1,true)
 await clickGlyph('cols','3');await waitHidden('columns',1,false)
 // Level 2 leaves nested level 2 hidden and reveals level 1 detail.
 await clickGlyph('rows','2');await waitHidden('rows',2,true)
 await goto('B3');await page.locator('[data-ribbon-tab="View"]').click();await page.locator('[data-ribbon-command="freeze-panes"]').click();await page.locator('[data-ribbon-command="zoom-in"]').click();await delay(300)
 await page.locator('.workbook-grid').hover();await page.mouse.wheel(260,360);await delay(300)
 assert((await glyphs('rows')).some(g=>g.text==='1'),'level buttons survive scrolling and frozen panes')
 await clickGlyph('rows','−',list=>list.sort((a,b)=>b.y-a.y)[0]);await waitHidden('rows',19,true)
 await goto('A1');await delay(300);await page.screenshot({path:'/tmp/outline-gutter-geometry.png'})
 await page.reload();await ready();await clickGlyph('cols','1');await waitHidden('columns',1,true)
 console.log(JSON.stringify({phase:'before-save',feedback:await page.locator('.workbook-feedback').innerText(),draft:await ops()}));await page.locator('[data-action="save"]').click();await page.waitForFunction(()=>document.querySelector('.save-state-label')?.textContent==='已保存修订 2',null,{timeout:60000})
 const actual=JSON.parse(python({mode:'inspect',bytes:saved.toString('base64')}));assert.equal(actual.rows['3'].hidden,true);assert.equal(actual.rows['3'].level,2);assert.equal(actual.cols.B.hidden,true);assert.equal(actual.value,1)
 await page.route('**/reports/v1/native/outline-gutter/2/api/context',r=>r.fulfill({json:{context:{...ctx(saved),revision:2,parentRevision:1},csrfToken:'csrf',capabilities:{xlsx_editor:true},editingEnabled:true}}))
 await page.route('**/reports/v1/native/outline-gutter/2/api/file',r=>r.fulfill({body:saved,contentType:media}))
 await page.addInitScript(()=>history.replaceState(null,'','/reports/v1/native/outline-gutter/2'))
 await page.goto(`${base}/reports/v1/native/outline-gutter/2`);await ready();assert((await glyphs('cols')).some(g=>g.text==='+'))
 await page.getByText('Plain',{exact:true}).last().click();await page.waitForFunction(()=>!document.querySelector('.outline-gutter'))
 await goto('A2:A4');await page.locator('[data-ribbon-tab="Data"]').click();await page.locator('[data-ribbon-command="outline-group:rows"]').click();await page.locator('.outline-gutter-rows').waitFor()
 await goto('A1');await page.locator('[data-ribbon-tab="Data"]').click();await page.locator('[data-ribbon-command="outline-clear"]').click();await page.waitForFunction(()=>!document.querySelector('.outline-gutter'))
 await page.getByText('Outline',{exact:true}).last().click();await page.locator('.outline-gutter-cols').waitFor()
 assert.deepEqual(errors,[])
 console.log(JSON.stringify({ok:true,preview,case:'outline-gutter',browser:browser.version(),actual,exactGroup:true,levelButtons:true,scrollZoomFreeze:true,draftAndRevisionReopen:true,operations:payload.operations,pageErrors:errors}))
}catch(error){if(activePage){console.log(JSON.stringify({phase:'failure',feedback:await activePage.locator('.workbook-feedback').innerText(),saveLabel:await activePage.locator('.save-state-label').innerText(),glyphs:await activePage.evaluate(()=>window.__outlineGlyphs)}));await activePage.screenshot({path:'/tmp/outline-gutter-failure.png'})}throw error}finally{await browser?.close();server.kill()}
