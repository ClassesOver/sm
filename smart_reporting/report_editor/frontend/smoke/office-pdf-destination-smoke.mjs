// 真实构建、PDF.js、授权和来源接口；明确派生 PDF/内存仓储，不创建保存修订。
import assert from 'node:assert/strict'
import {spawn} from 'node:child_process'
import {createHash} from 'node:crypto'
import {mkdir,readFile,writeFile} from 'node:fs/promises'
import {join} from 'node:path'
import {fileURLToPath} from 'node:url'
import {setTimeout as delay} from 'node:timers/promises'
import {chromium} from 'playwright'
const frontend=fileURLToPath(new URL('../',import.meta.url)),repo=fileURLToPath(new URL('../../../../',import.meta.url))
const directory=process.env.PDF_DESTINATION_OUTPUT,staticRoot=process.env.PDF_SMOKE_STATIC_DIRECTORY,port=Number(process.env.PDF_DESTINATION_PORT??4395),origin=`http://127.0.0.1:${port}`
assert.ok(directory&&staticRoot&&process.env.PDF_DESTINATION_SOURCE);await mkdir(directory)
const sha=b=>createHash('sha256').update(b).digest('hex'),manifest=await readFile(join(staticRoot,'.vite/manifest.json')),input=await readFile(process.env.PDF_DESTINATION_SOURCE)
assert.equal(sha(manifest),process.env.PDF_EXPECTED_MANIFEST_SHA256);await writeFile(join(directory,'build-manifest.json'),manifest)
const server=spawn(join(repo,'.venv/bin/python'),[join(frontend,'smoke/office-pdf-destination-server.py'),'--directory',directory,'--port',String(port)],{cwd:repo,env:{...process.env,PYTHONPATH:repo},stdio:'pipe'})
let serverLog='',browser,page,stage='server';server.stdout.on('data',b=>{serverLog+=b});server.stderr.on('data',b=>{serverLog+=b})
const errors=[],checks=[],resources=new Map(),cases=[]
try{
 for(let i=0;;i++){assert.equal(server.exitCode,null,serverLog);try{if((await fetch(origin+'/__smoke__/state',{signal:AbortSignal.timeout(1500)})).ok)break}catch{}assert.ok(i<240,serverLog);await delay(250)}
 const info=JSON.parse(await readFile(join(directory,'server-info.json'),'utf8')),reference=JSON.parse(await readFile(join(directory,'reference-destinations.json'),'utf8'))
 assert.equal(reference.inputSha256,sha(input));assert.equal(reference.sourceSha256,info.sourceSha256)
 browser=await chromium.launch({headless:true,...(process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE?{executablePath:process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE}:{})});page=await browser.newPage({viewport:{width:1440,height:900}})
 page.on('pageerror',e=>errors.push(e.message));page.on('console',m=>{if(m.type()==='error')errors.push(m.text())});page.on('crash',()=>errors.push('renderer crashed'))
 page.on('response',r=>{const path=new URL(r.url()).pathname;if(r.status()>=400)errors.push(`${r.status()} ${path}`);if(r.status()===200&&path.startsWith('/reports/v1/editor/assets/')&&/\.(?:m?js|css|wasm)$/.test(path))checks.push(r.body().then(async b=>{assert.equal(sha(b),sha(await readFile(join(staticRoot,path.slice('/reports/v1/editor/assets/'.length)))));resources.set(path,{sha256:sha(b),size:b.length})}).catch(e=>errors.push(String(e))))})
 const ready=()=>page.waitForFunction(()=>document.querySelector('#report-editor')?.getAttribute('aria-busy')==='false',null,{timeout:60000})
 const operations=()=>page.evaluate(()=>Object.entries(localStorage).filter(([k])=>k.startsWith('native-editor-draft:')).flatMap(([,v])=>JSON.parse(v).operations))
 const card=index=>page.locator(`.pdf-page[data-page-id$=":page:${index}"]`)
 const zoom=async value=>{await page.locator('[data-pdf-ribbon-tab="home"]').click();await page.getByLabel('页面缩放',{exact:true}).selectOption(String(value));await ready();await page.waitForFunction(value=>Math.abs(Number(document.querySelector('.pdf-zoom').value)-value)<1e-8,value)}
 const metrics=target=>{
  const viewport=document.querySelector('.pdf-document-pages'),card=document.querySelector(`.pdf-page[data-page-id$=":page:${target}"]`),content=card.querySelector('.pdf-page-content'),source=document.querySelector('.pdf-page[data-page-id$=":page:0"] .pdf-page-content'),style=getComputedStyle(viewport),cs=getComputedStyle(card),box=viewport.getBoundingClientRect(),c=card.getBoundingClientRect(),p=content.getBoundingClientRect(),s=source.getBoundingClientRect(),px=v=>parseFloat(v)||0
  const scale=Number(document.querySelector('.pdf-zoom').value),sx=Math.max(0,Math.min(s.width,box.left+viewport.clientLeft-s.left)),sy=Math.max(0,Math.min(s.height,box.top+viewport.clientTop-s.top))
  return {scale,width:viewport.clientWidth-px(style.paddingLeft)-px(style.paddingRight)-px(cs.paddingLeft)-px(cs.paddingRight)-px(cs.borderLeftWidth)-px(cs.borderRightWidth),height:viewport.clientHeight-px(style.paddingTop)-px(style.paddingBottom)-(p.top-c.top)-px(cs.paddingBottom)-px(cs.borderBottomWidth),retained:[sx/scale,400-sy/scale]}
 }
 await page.goto(origin+info.openPath);await ready()
 for(const [width,height]of [[1440,900],[768,720],[320,640],[640,360],[390,320]]){
  await page.setViewportSize({width,height});await page.evaluate(()=>document.fonts.ready)
  for(const test of reference.cases){
   stage=`${test.name}-${width}x${height}`;await zoom(test.name==='xyz-null-preserve-zoom'?1.5:1)
   await card(0).locator('.pdf-page-label').click();const link=card(0).locator(`.pdf-saved-links a[data-element-id="${test.id}"]`);await link.waitFor();await link.focus()
   const before=await operations(),initial=await page.evaluate(metrics,test.page)
   if(test.name==='invalid'){
    await page.keyboard.press('Enter');await page.waitForFunction(()=>document.querySelector('.pdf-editor-message').textContent.includes('链接目标参数无效'))
    assert.equal(await card(0).evaluate(n=>n.classList.contains('is-active')),true);assert.equal(Number(await page.locator('.pdf-zoom').inputValue()),1);assert.deepEqual(await operations(),before);cases.push({name:stage,invalid:true});continue
   }
   let expectedScale=test.kind==='XYZ'?(test.parameters[2]||initial.scale):test.kind==='Fit'||test.kind==='FitB'?Math.min(initial.width/test.pageSize[0],initial.height/test.pageSize[1]):test.kind==='FitH'||test.kind==='FitBH'?initial.width/test.pageSize[0]:test.kind==='FitV'||test.kind==='FitBV'?initial.height/test.pageSize[1]:Math.min(initial.width/test.unitRectSize[0],initial.height/test.unitRectSize[1]);expectedScale=Math.max(.1,Math.min(8,expectedScale))
   const unitPoint=test.unitPoint??[initial.retained[0],test.kind==='FitV'||test.kind==='FitBV'?0:400-initial.retained[1]],point=unitPoint.map(n=>n*expectedScale)
   await page.keyboard.press('Enter')
   try{await page.waitForFunction(({index,scale})=>document.querySelector('.pdf-document-pages')===document.activeElement&&document.querySelector('.pdf-page.is-active')?.getAttribute('data-page-id')?.endsWith(`:page:${index}`)&&Math.abs(Number(document.querySelector('.pdf-zoom').value)-scale)<1e-7,{index:test.page,scale:expectedScale},{timeout:8000})}catch(error){const state=await page.evaluate(()=>({zoom:document.querySelector('.pdf-zoom')?.value,active:document.querySelector('.pdf-page.is-active')?.getAttribute('data-page-id'),focused:document.activeElement?.className,viewport:document.querySelector('.pdf-document-pages')?.className,status:document.querySelector('.pdf-editor-message')?.textContent}));throw new Error(`${error}; expected=${JSON.stringify({index:test.page,scale:expectedScale})}; state=${JSON.stringify(state)}`)}
   const actual=await page.evaluate(({index,point})=>{
    const v=document.querySelector('.pdf-document-pages'),card=document.querySelector(`.pdf-page[data-page-id$=":page:${index}"]`),content=card.querySelector('.pdf-page-content'),r=content.getBoundingClientRect(),b=v.getBoundingClientRect(),left=r.left-b.left-v.clientLeft+point[0],top=r.top-b.top-v.clientTop+point[1]
    return {scale:Number(document.querySelector('.pdf-zoom').value),scroll:[v.scrollLeft,v.scrollTop],scrollSize:[v.scrollWidth,v.scrollHeight,v.clientWidth,v.clientHeight],targetBounds:[r.left,r.top,r.right,r.bottom],pointOnScreen:[r.left+point[0],r.top+point[1]],scrollport:[b.left+v.clientLeft,b.top+v.clientTop],viewport:[b.left,b.top,b.right,b.bottom],status:document.querySelector('.pdf-editor-message').textContent,focused:v===document.activeElement}
   },{index:test.page,point})
   assert.ok(Math.abs(actual.scale-expectedScale)<1e-7,`${stage}: scale`);assert.ok(actual.pointOnScreen[0]>=actual.scrollport[0]-1&&actual.pointOnScreen[0]<=actual.viewport[2]+1&&actual.pointOnScreen[1]>=actual.scrollport[1]-1&&actual.pointOnScreen[1]<=actual.viewport[3]+1,`${stage}: destination remains visible ${JSON.stringify(actual)}`);assert.ok(actual.status.includes(`第 ${test.page+1} 页`));assert.deepEqual(await operations(),before)
   const file=`${stage}.png`;await page.screenshot({path:join(directory,file)});cases.push({name:stage,test,initial,expectedScale,point,actual,file});await writeFile(join(directory,'cases.json'),JSON.stringify(cases,null,2));console.log(JSON.stringify({name:stage,scale:actual.scale}))
  }
 }
 await page.reload();await ready();assert.deepEqual(await operations(),[]);await Promise.all(checks);assert.deepEqual(errors,[])
 const state=await(await fetch(origin+'/__smoke__/state')).json();assert.equal(state.savedRevisions,0);assert.ok(!state.requests.some(n=>n.path.endsWith('/api/save')))
 const original=await page.request.get(origin+await page.locator('.pdf-original-download').getAttribute('href'));assert.equal(original.status(),200);assert.equal(sha(await original.body()),reference.sourceSha256);assert.deepEqual(await readFile(process.env.PDF_DESTINATION_SOURCE),input);assert.deepEqual(await readFile(join(staticRoot,'.vite/manifest.json')),manifest)
 await writeFile(join(directory,'evidence.json'),JSON.stringify({ok:true,manifest:sha(manifest),cases,resources:Object.fromEntries(resources),state,errors,saveCount:0,inputSha256:sha(input)},null,2));console.log(JSON.stringify({ok:true,cases:cases.length,resources:resources.size,saveCount:0,directory}))
}catch(error){await page?.screenshot({path:join(directory,'failure.png'),fullPage:true}).catch(()=>{});await writeFile(join(directory,'failure.json'),JSON.stringify({stage,error:String(error),stack:error.stack,errors},null,2));throw error}
finally{await browser?.close();server.kill();await writeFile(join(directory,'server.log'),serverLog);if(server.exitCode===null)await Promise.race([new Promise(done=>server.once('exit',done)),delay(5000)]);if(server.exitCode===null)server.kill('SIGKILL')}
