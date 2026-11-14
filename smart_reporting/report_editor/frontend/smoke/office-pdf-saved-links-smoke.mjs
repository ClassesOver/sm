// 实际构建/授权/源文件/PDF.js；复用前批下载派生夹具，不创建新保存修订。
import assert from 'node:assert/strict'
import {spawn} from 'node:child_process'
import {createHash} from 'node:crypto'
import {mkdir,readFile,writeFile} from 'node:fs/promises'
import {join} from 'node:path'
import {fileURLToPath} from 'node:url'
import {setTimeout as delay} from 'node:timers/promises'
import {chromium} from 'playwright'
const frontend=fileURLToPath(new URL('../',import.meta.url)),repo=fileURLToPath(new URL('../../../../',import.meta.url))
const directory=process.env.PDF_SAVED_LINKS_OUTPUT,staticRoot=process.env.PDF_SMOKE_STATIC_DIRECTORY,port=Number(process.env.PDF_SAVED_LINKS_PORT??4394),origin=`http://127.0.0.1:${port}`,baseline=process.env.PDF_SAVED_LINKS_BASELINE==='1'
assert.ok(directory&&staticRoot&&process.env.PDF_SAVED_LINKS_SOURCE,'evidence/build/source paths are required');await mkdir(directory)
const sha=b=>createHash('sha256').update(b).digest('hex'),manifest=await readFile(join(staticRoot,'.vite/manifest.json')),input=await readFile(process.env.PDF_SAVED_LINKS_SOURCE)
assert.equal(sha(manifest),process.env.PDF_EXPECTED_MANIFEST_SHA256);await writeFile(join(directory,'build-manifest.json'),manifest)
const server=spawn(join(repo,'.venv/bin/python'),[join(frontend,'smoke/office-pdf-saved-links-server.py'),'--directory',directory,'--port',String(port)],{cwd:repo,env:{...process.env,PYTHONPATH:repo},stdio:'pipe'})
let serverLog='',browser,page,stage='server';server.stdout.on('data',b=>{serverLog+=b});server.stderr.on('data',b=>{serverLog+=b})
const errors=[],checks=[],resources=new Map(),layout={cases:[],failures:[]},interactions=[]
try{
 for(let i=0;;i++){assert.equal(server.exitCode,null,serverLog);try{if((await fetch(origin+'/__smoke__/state',{signal:AbortSignal.timeout(1500)})).ok)break}catch{}assert.ok(i<240,serverLog);await delay(250)}
 const info=JSON.parse(await readFile(join(directory,'server-info.json'),'utf8')),reference=JSON.parse(await readFile(join(directory,'reference-geometry.json'),'utf8'))
 assert.equal(reference.inputSha256,sha(input));assert.equal(reference.sourceSha256,info.sourceSha256)
 assert.deepEqual([reference.pages[2].width,reference.pages[2].height],[700,520]);assert.deepEqual(reference.pages[2].links[0].rect,[460,80,520,320])
 browser=await chromium.launch({headless:true,...(process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE?{executablePath:process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE}:{})});const context=await browser.newContext({viewport:{width:1440,height:900}});page=await context.newPage()
 page.on('pageerror',e=>errors.push(e.message));page.on('console',m=>{if(m.type()==='error')errors.push(m.text())});page.on('crash',()=>errors.push('renderer crashed'))
 page.on('response',r=>{const path=new URL(r.url()).pathname;if(r.status()>=400)errors.push(`${r.status()} ${path}`);if(r.status()===200&&path.startsWith('/reports/v1/editor/assets/')&&/\.(?:m?js|css|wasm)$/.test(path))checks.push(r.body().then(async b=>{assert.equal(sha(b),sha(await readFile(join(staticRoot,path.slice('/reports/v1/editor/assets/'.length)))));resources.set(path,{sha256:sha(b),size:b.length})}).catch(e=>errors.push(String(e))))})
 const ready=()=>page.waitForFunction(()=>document.querySelector('#report-editor')?.getAttribute('aria-busy')==='false',null,{timeout:60000})
 const operations=()=>page.evaluate(()=>Object.entries(localStorage).filter(([k])=>k.startsWith('native-editor-draft:')).flatMap(([,v])=>JSON.parse(v).operations))
 const waitOps=count=>page.waitForFunction(count=>Object.entries(localStorage).filter(([k])=>k.startsWith('native-editor-draft:')).flatMap(([,v])=>JSON.parse(v).operations).length===count,count)
 const command=async(tab,id)=>{await page.locator(`[data-pdf-ribbon-tab="${tab}"]`).click();await page.locator(`[data-source-command-id="genoffice.pdf.${id}"]`).click()}
 const card=index=>page.locator(`.pdf-page[data-page-id$=":page:${index}"]`),holder=index=>card(index).locator('.pdf-page-content')
 const show=async index=>{await card(index).locator('.pdf-page-label').click();await holder(index).locator('canvas').waitFor()}
 const measure=node=>{
  const r=node.getBoundingClientRect(),host=node.closest('.pdf-page-content').getBoundingClientRect(),s=getComputedStyle(node),clipping=[]
  let clipLeft=0,clipTop=0,clipRight=innerWidth,clipBottom=innerHeight
  for(let parent=node.parentElement;parent;parent=parent.parentElement){
   const style=getComputedStyle(parent),box=parent.getBoundingClientRect()
   // PDF.js 的批注层会旋转；clientWidth/Height 是局部坐标，不能直接当屏幕尺寸。
   const matrix=new DOMMatrixReadOnly(style.transform==='none'?undefined:style.transform)
   const bounds=(left,top,right,bottom)=>{const points=[[left,top],[right,top],[right,bottom],[left,bottom]].map(([x,y])=>[matrix.a*x+matrix.c*y,matrix.b*x+matrix.d*y]);return [Math.min(...points.map(p=>p[0])),Math.min(...points.map(p=>p[1])),Math.max(...points.map(p=>p[0])),Math.max(...points.map(p=>p[1]))]}
   const outer=bounds(0,0,parent.offsetWidth,parent.offsetHeight),inner=bounds(parent.clientLeft,parent.clientTop,parent.clientLeft+parent.clientWidth,parent.clientTop+parent.clientHeight)
   const sx=box.width/(outer[2]-outer[0]||1),sy=box.height/(outer[3]-outer[1]||1),swapped=Math.abs(matrix.b)>Math.abs(matrix.a)
   if((swapped?style.overflowY:style.overflowX)!=='visible'){clipLeft=Math.max(clipLeft,box.left+(inner[0]-outer[0])*sx);clipRight=Math.min(clipRight,box.left+(inner[2]-outer[0])*sx)}
   if((swapped?style.overflowX:style.overflowY)!=='visible'){clipTop=Math.max(clipTop,box.top+(inner[1]-outer[1])*sy);clipBottom=Math.min(clipBottom,box.top+(inner[3]-outer[1])*sy)}
   if(parent.scrollWidth>parent.clientWidth||parent.scrollHeight>parent.clientHeight)clipping.push({className:parent.className,scrollLeft:parent.scrollLeft,scrollTop:parent.scrollTop,clientWidth:parent.clientWidth,clientHeight:parent.clientHeight})
  }
  const left=Math.max(r.left,clipLeft),top=Math.max(r.top,clipTop),right=Math.min(r.right,clipRight),bottom=Math.min(r.bottom,clipBottom)
  const visible=right>left&&bottom>top,d=visible?Math.min(4,(right-left)/4,(bottom-top)/4):0
  const points=visible?[[left+(right-left)/2,top+(bottom-top)/2],[left+d,top+d],[right-d,top+d],[left+d,bottom-d],[right-d,bottom-d]]:[]
  const hits=points.map(([x,y])=>{const hit=document.elementFromPoint(x,y);return {inside:!!hit&&node.contains(hit),tag:hit?.tagName,className:hit?.className}})
  const fits=(r.width>clipRight-clipLeft+1||r.left>=clipLeft-1&&r.right<=clipRight+1)&&(r.height>clipBottom-clipTop+1||r.top>=clipTop-1&&r.bottom<=clipBottom+1)
  return {rect:[r.left-host.left,r.top-host.top,r.right-host.left,r.bottom-host.top],screen:[r.left,r.top,r.right,r.bottom],visibleRect:[left,top,right,bottom],clipRect:[clipLeft,clipTop,clipRight,clipBottom],fits,clipping,href:node.getAttribute('href'),target:node.target,rel:node.rel,label:node.getAttribute('aria-label'),focused:node===document.activeElement,ring:s.outlineStyle!=='none'&&parseFloat(s.outlineWidth)>=2,points,hits,hit:visible&&hits.every(n=>n.inside)}
 }
 const inspect=async(name,index,expected,zoom=1)=>{
  await show(index)
  if(!baseline)await page.waitForFunction(({index,count,width})=>{const n=document.querySelector(`.pdf-page[data-page-id$=":page:${index}"] .pdf-page-content`);return n&&n.querySelectorAll('.pdf-saved-links a').length===count&&Math.abs(n.getBoundingClientRect().width-width)<1},{index,count:expected.links.length,width:expected.width*zoom})
  const before=await operations(),items=[],check=(ok,reason)=>{if(!ok)layout.failures.push(`${name}: ${reason}`)}
  const count=await holder(index).locator('.pdf-saved-links a').count();check(count===expected.links.length,'链接数量')
  for(const link of expected.links){
   const anchor=holder(index).locator(`.pdf-saved-links a[data-element-id="${link.id}"]`)
   if(!await anchor.count()){check(false,`${link.id}缺少链接`);continue}
   await anchor.scrollIntoViewIfNeeded();await anchor.focus();const initial=await anchor.evaluate(measure)
   await page.keyboard.press('Tab');const afterTab=await anchor.evaluate(measure)
   await page.keyboard.press('Shift+Tab');const actual=await anchor.evaluate(measure)
   check(actual.rect.every((value,i)=>Math.abs(value-link.rect[i]*zoom)<1),`${link.id}PDF坐标映射`);check(actual.hit&&actual.focused&&actual.ring,`${link.id}键盘焦点和五点命中`)
   check(actual.fits,`${link.id}可容纳的焦点区域应完整可见`)
   check(!!actual.label,`${link.id}可访问名称`)
   if(link.url){check(actual.href===link.url&&actual.target==='_blank'&&actual.rel.includes('noopener')&&actual.rel.includes('noreferrer'),`${link.id}外部目标`)}
   const segments=[actual],oversized=[0,1].map(axis=>actual.screen[axis+2]-actual.screen[axis]>actual.clipRect[axis+2]-actual.clipRect[axis]+1)
   if(oversized.some(Boolean)){
    for(const edge of ['start','end']){await anchor.evaluate((n,edge)=>n.scrollIntoView({block:edge,inline:edge}),edge);const segment=await anchor.evaluate(measure);segments.push(segment);check(segment.hit&&segment.focused&&segment.ring,`${link.id}${edge}分段命中`)}
    for(const axis of [0,1])if(oversized[axis]){
     const ranges=segments.map(n=>[n.visibleRect[axis]-n.screen[axis],n.visibleRect[axis+2]-n.screen[axis]]).sort((a,b)=>a[0]-b[0]);let covered=0
     for(const [start,end]of ranges){check(start<=covered+1,`${link.id}分段覆盖连续`);covered=Math.max(covered,end)}
     check(covered>=actual.screen[axis+2]-actual.screen[axis]-1,`${link.id}分段覆盖完整`)
    }
   }
   items.push({expected:link,initial,afterTab,actual,segments})
  }
  assert.deepEqual(await operations(),before)
  const file=`${name}.png`;await page.screenshot({path:join(directory,file)});layout.cases.push({name,index,zoom,width:(await page.viewportSize()).width,height:(await page.viewportSize()).height,items,file})
  await writeFile(join(directory,'layout.json'),JSON.stringify(layout,null,2));console.log(JSON.stringify({name,index,links:items.length,failures:layout.failures.length}))
 }
 const zoom=async value=>{await page.locator('[data-pdf-ribbon-tab="home"]').click();await page.getByLabel('页面缩放',{exact:true}).selectOption(String(value));await ready()}
 await page.goto(origin+info.openPath);await ready();stage='viewports'
 for(const [width,height] of [[1440,900],[768,720],[320,640],[640,360],[390,320]]){
  await page.setViewportSize({width,height});await page.evaluate(()=>document.fonts.ready)
  for(let index=0;index<3;index++)await inspect(`source-${index}-${width}x${height}`,index,reference.pages[index])
 }
 if(!baseline){
  assert.deepEqual(layout.failures,[]);await page.setViewportSize({width:1440,height:900});stage='external'
  await context.route('https://www.example.com/**',route=>route.fulfill({status:200,contentType:'text/html',body:'<!doctype html><title>External navigation fixture</title><p id="loaded">Link opened</p>'}))
  await show(0);const web=holder(0).locator(`a[data-element-id="${reference.pages[0].links.find(n=>n.url?.startsWith('https://www.')).id}"]`)
  const opened=context.waitForEvent('page');await web.focus();await page.keyboard.press('Enter');const popup=await opened;await popup.waitForLoadState('domcontentloaded');assert.equal(popup.url(),reference.pages[0].links[0].url);assert.equal(await popup.evaluate(()=>window.opener===null),true);await popup.close();interactions.push('external Enter/new window/no opener')
  stage='internal';for(const link of reference.pages[0].links.filter(n=>n.targetPage===2)){
   await show(0);const anchor=holder(0).locator(`a[data-element-id="${link.id}"]`);await anchor.focus();await page.keyboard.press('Enter');await page.waitForFunction(()=>document.querySelector('.pdf-page.is-active')?.getAttribute('data-page-id')?.endsWith(':page:2'));assert.equal(await card(2).locator('.pdf-page-label').evaluate(n=>n===document.activeElement),true)
  }interactions.push('explicit and named destinations/Enter/page focus')
  stage='mode';await show(0);await command('edit','edit.objects.editLink');await page.waitForFunction(()=>[...document.querySelectorAll('.pdf-saved-links')].every(n=>n.inert&&[...n.querySelectorAll('a')].every(a=>a.tabIndex===-1)))
  await page.locator('[data-pdf-ribbon-tab="annotate"]').click();await page.getByRole('button',{name:'选择文字',exact:true}).click();await page.waitForFunction(()=>[...document.querySelectorAll('.pdf-saved-links')].every(n=>!n.inert));assert.deepEqual(await operations(),[]);interactions.push('drawing/select mode avoids link interception')
  stage='geometry';for(const cropped of [false,true]){
   if(cropped){
    await show(0);await command('page','page.crop');const dialog=page.getByRole('dialog',{name:'裁切当前页面',exact:true});await dialog.waitFor()
    for(const [label,value] of [['左侧裁去 (%)',100/30],['顶部裁去 (%)',2.5],['右侧裁去 (%)',100/30],['底部裁去 (%)',5]])await dialog.getByLabel(label,{exact:true}).fill(String(value))
    await dialog.getByRole('button',{name:'应用裁切',exact:true}).click();await dialog.waitFor({state:'hidden'});await waitOps(1);assert.equal((await operations())[0].kind,'cropPage')
   }
   for(let turn=0;turn<4;turn++){
    const referenceCase=reference.scenarios.find(n=>n.rotation===turn*90&&!!n.crop===cropped)
    if(turn){await show(0);await command('page','page.rotateRight');await waitOps((cropped?1:0)+turn)}
    for(const value of [.5,1,1.5]){await zoom(value);await inspect(`${referenceCase.name}-zoom-${value}`,0,referenceCase,value)}
   }
   for(let count=(cropped?1:0)+3;count>0;count--){await command('home','home.edit.undo');await waitOps(count-1)}
  }
  await zoom(1);assert.deepEqual(await operations(),[]);await page.reload();await ready();await inspect('reloaded-clean',0,reference.pages[0]);assert.deepEqual(layout.failures,[])
 }
 await Promise.all(checks);assert.deepEqual(errors,[]);assert.deepEqual(await readFile(join(staticRoot,'.vite/manifest.json')),manifest);assert.deepEqual(await readFile(process.env.PDF_SAVED_LINKS_SOURCE),input)
 const state=await(await fetch(origin+'/__smoke__/state')).json();assert.equal(state.savedRevisions,0);assert.equal(state.sourceSha256,info.sourceSha256);assert.ok(!state.requests.some(n=>n.path.endsWith('/api/save')))
 const original=await page.request.get(origin+await page.locator('.pdf-original-download').getAttribute('href'));assert.equal(original.status(),200);assert.equal(sha(await original.body()),reference.sourceSha256)
 await writeFile(join(directory,'evidence.json'),JSON.stringify({ok:!layout.failures.length,baseline,manifest:sha(manifest),scope:'actual build/grants/source bytes/PDF.js; explicit derived fixture/memory revision repository; external page response fixture',layout,interactions,state,resources:Object.fromEntries(resources),errors,referenceInputSha256:sha(input),saveCount:0},null,2));console.log(JSON.stringify({ok:!layout.failures.length,baseline,cases:layout.cases.length,resources:resources.size,saveCount:0,directory}))
}catch(error){await page?.screenshot({path:join(directory,'failure.png'),fullPage:true}).catch(()=>{});await writeFile(join(directory,'failure.json'),JSON.stringify({stage,error:String(error),stack:error.stack,errors},null,2));throw error}
finally{await browser?.close();server.kill();await writeFile(join(directory,'server.log'),serverLog);if(server.exitCode===null)await Promise.race([new Promise(done=>server.once('exit',done)),delay(5000)]);if(server.exitCode===null)server.kill('SIGKILL')}
