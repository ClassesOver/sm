// 产品签名 UI → 实际授权/CSRF/保存/发布/HTTP下载；仅修订仓储使用内存夹具。
import assert from 'node:assert/strict'
import {spawn} from 'node:child_process'
import {createHash} from 'node:crypto'
import {mkdir,readFile,writeFile} from 'node:fs/promises'
import {join} from 'node:path'
import {fileURLToPath} from 'node:url'
import {setTimeout as delay} from 'node:timers/promises'
import {chromium} from 'playwright'
const frontend=fileURLToPath(new URL('../',import.meta.url)),repo=fileURLToPath(new URL('../../../../',import.meta.url))
const directory=process.env.PDF_SIGNATURE_OUTPUT,port=Number(process.env.PDF_SIGNATURE_PORT??4493),vitePort=Number(process.env.PDF_SIGNATURE_VITE_PORT??4494),origin='http://127.0.0.1:'+port
const dev=process.env.PDF_SIGNATURE_DEV==='1',staticRoot=process.env.PDF_SMOKE_STATIC_DIRECTORY??join(frontend,'../static')
assert.ok(directory,'PDF_SIGNATURE_OUTPUT required');await mkdir(directory)
const sha=bytes=>createHash('sha256').update(bytes).digest('hex'),logs=[],children=[]
function start(cmd,args,cwd,env=process.env){const child=spawn(cmd,args,{cwd,env,stdio:'pipe'});children.push(child);child.stdout.on('data',b=>logs.push(String(b)));child.stderr.on('data',b=>logs.push(String(b)));return child}
async function wait(url,child){for(let n=0;;n++){assert.equal(child.exitCode,null,logs.join(''));try{if((await fetch(url,{signal:AbortSignal.timeout(1500)})).ok)return}catch{}assert(n<240,logs.join(''));await delay(250)}}
let browser,page,stage='server';const errors=[],infrastructureWarnings=[],layout=[],resources=new Map()
try{
 if(dev){const vite=start('./node_modules/.bin/vite',['--host','127.0.0.1','--port',String(vitePort),'--strictPort'],frontend);await wait(`http://127.0.0.1:${vitePort}/reports/v1/editor/assets/native.html`,vite)}
 const server=start(join(repo,'.venv/bin/python'),[join(frontend,'smoke/office-pdf-link-server.py'),'--directory',directory,'--port',String(port)],repo,{...process.env,PYTHONPATH:repo,PDF_SMOKE_STATIC_DIRECTORY:staticRoot});await wait(origin+'/__smoke__/state',server)
 const info=JSON.parse(await readFile(join(directory,'server-info.json'),'utf8'))
 browser=await chromium.launch({headless:true,...(process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE?{executablePath:process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE}:{})});page=await browser.newPage({viewport:{width:1440,height:900}})
 page.on('pageerror',e=>errors.push(e.message));page.on('crash',()=>errors.push('renderer crashed'));page.on('console',m=>{if(m.type()==='error')(dev&&/WebSocket|websocket|\[vite\]/.test(m.text())?infrastructureWarnings:errors).push(m.text())});page.on('requestfailed',r=>errors.push(r.url()+' '+r.failure()?.errorText))
 if(dev){
  await page.route('**/reports/v1/native/*/*',async route=>{const u=new URL(route.request().url());if(/\/reports\/v1\/native\/[^/]+\/\d+$/.test(u.pathname)){const r=await fetch(`http://127.0.0.1:${vitePort}/reports/v1/editor/assets/native.html`);return route.fulfill({contentType:'text/html',body:await r.text()})}return route.continue()})
  await page.route('**/reports/v1/editor/assets/**',async route=>{const u=new URL(route.request().url());if(u.pathname.includes('/assets/pdfjs/'))return route.continue();const r=await fetch(`http://127.0.0.1:${vitePort}`+u.pathname+u.search);const body=Buffer.from(await r.arrayBuffer());resources.set(u.pathname,{sha256:sha(body),size:body.length});return route.fulfill({status:r.status,contentType:r.headers.get('content-type')??'application/octet-stream',body})})
 }
 const ready=()=>page.waitForFunction(()=>document.querySelector('#report-editor')?.getAttribute('aria-busy')==='false',null,{timeout:90000})
 const ops=()=>page.evaluate(()=>Object.entries(localStorage).filter(([k])=>k.startsWith('native-editor-draft:')).flatMap(([,v])=>JSON.parse(v).operations))
 const waitOps=count=>page.waitForFunction(count=>Object.entries(localStorage).filter(([k])=>k.startsWith('native-editor-draft:')).flatMap(([,v])=>JSON.parse(v).operations).length===count,count)
 const command=async(tab,id)=>{await page.locator(`[data-pdf-ribbon-tab="${tab}"]`).click();await page.locator(`[data-source-command-id="genoffice.pdf.${id}"]`).click()}
 const dialog=page.locator('dialog.pdf-signature-source-dialog'),open=()=>command('annotate','annotate.signature.sign')
 const place=async(row)=>{const holder=page.locator('.pdf-page-content').first();await holder.scrollIntoViewIfNeeded();const r=await holder.boundingBox();assert.ok(r);await page.mouse.move(r.x+r.width*.15,r.y+r.height*(.25+row*.16));await page.mouse.down();await page.mouse.move(r.x+r.width*.65,r.y+r.height*(.34+row*.16),{steps:8});await page.mouse.up()}
 const navigateOpen=async url=>{const granted=await page.request.get(url);assert.equal(granted.status(),200);await page.goto(granted.url())}
 await navigateOpen(origin+info.openPath);await ready();await open();await dialog.waitFor()
 stage='layout-and-cancel'
 for(const [width,height] of [[1440,900],[640,360],[390,320]]){
  await page.setViewportSize({width,height})
  for(const tab of ['手绘','输入','图片']){
   await dialog.getByRole('button',{name:tab,exact:true}).click()
   const geometry=await dialog.evaluate(n=>{const r=n.getBoundingClientRect();return {x:r.x,y:r.y,right:r.right,bottom:r.bottom,overflow:n.scrollWidth>n.clientWidth+1,background:getComputedStyle(n).backgroundColor}})
   assert.ok(geometry.background!=='rgba(0, 0, 0, 0)'&&geometry.background!=='transparent','模态窗口须有不透明背景')
   assert.ok(geometry.x>=0&&geometry.y>=0&&geometry.right<=width+1&&geometry.bottom<=height+1&&!geometry.overflow,JSON.stringify({tab,width,height,geometry}))
   const cancel=dialog.getByRole('button',{name:'取消',exact:true});await cancel.focus();await cancel.scrollIntoViewIfNeeded()
   assert.ok(await cancel.evaluate(n=>{const r=n.getBoundingClientRect();return n===document.activeElement&&n.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2))}))
   await page.screenshot({path:join(directory,`signature-${tab}-${width}x${height}.png`)});assert.deepEqual(await ops(),[]);layout.push({width,height,tab,geometry})
  }
 }
 await dialog.getByRole('button',{name:'取消',exact:true}).click();assert.deepEqual(await ops(),[])
 await page.setViewportSize({width:1440,height:900});await open();await dialog.getByRole('button',{name:'输入',exact:true}).click();await dialog.locator('.pdf-modal-input').fill('Cancel Name');await page.keyboard.press('Escape');await dialog.waitFor({state:'detached'});assert.deepEqual(await ops(),[])
 assert.ok(await page.locator('[data-source-command-id="genoffice.pdf.annotate.signature.sign"]').evaluate(n=>n===document.activeElement))
 stage='draw';await open();const pad=dialog.locator('canvas');await pad.waitFor();const p=await pad.boundingBox();await page.mouse.move(p.x+30,p.y+65);await page.mouse.down();await page.mouse.move(p.x+80,p.y+35,{steps:5});await page.mouse.move(p.x+140,p.y+85,{steps:5});await page.mouse.move(p.x+210,p.y+45,{steps:5});await page.mouse.up();await dialog.locator('.primary').click();await dialog.waitFor({state:'detached'});assert.deepEqual(await ops(),[]);await place(0);await waitOps(1)
 stage='type';await open();await dialog.getByRole('button',{name:'输入',exact:true}).click();await dialog.locator('.pdf-modal-input').fill('Ada Lovelace');assert.equal(await dialog.locator('.pdf-sign-fontcard').count(),4);await dialog.locator('.pdf-sign-fontcard').nth(3).click();await dialog.locator('.primary').click();await place(1);await waitOps(2)
 stage='image';await open();await dialog.getByRole('button',{name:'图片',exact:true}).click()
 const png=await page.evaluate(()=>{const c=document.createElement('canvas');c.width=240;c.height=70;const x=c.getContext('2d');x.fillStyle='white';x.fillRect(0,0,240,70);x.fillStyle='black';x.font='italic 34px serif';x.fillText('Image Sign',8,47);return c.toDataURL('image/png').split(',')[1]})
 await dialog.locator('input[type=file]').setInputFiles({name:'signature.png',mimeType:'image/png',buffer:Buffer.from(png,'base64')});await dialog.locator('.pdf-sign-img').waitFor();await dialog.getByLabel('黑白（背景透明）',{exact:true}).check();await dialog.locator('.primary').click();await place(2);await waitOps(3)
 const applied=await ops();assert.equal(applied[0].shape,'ink');assert.equal(applied[1].shape,'image');assert.equal(applied[2].shape,'image');await writeFile(join(directory,'staged.json'),JSON.stringify(applied,null,2))
 stage='history-and-reload';await command('home','home.edit.undo');await waitOps(2);await command('home','home.edit.redo');await waitOps(3);assert.deepEqual(await ops(),applied)
 await page.reload();await ready();assert.deepEqual(await ops(),applied);await open();await dialog.locator('.pdf-sign-saved-pick').first().waitFor();assert.equal(await dialog.locator('.pdf-sign-saved-pick').count(),3);await dialog.getByRole('button',{name:'取消',exact:true}).click()
 stage='save';const saving=page.waitForResponse(r=>r.url().endsWith('/api/save')&&r.request().method()==='POST');await page.locator('[data-action=save]').click();const response=await saving,result=await response.json();await writeFile(join(directory,'save.json'),JSON.stringify({request:response.request().postDataJSON(),result},null,2));assert.equal(response.status(),200,JSON.stringify(result));assert.equal(result.revisionRegistered,true);assert.deepEqual(response.request().postDataJSON().operations,applied)
 stage='download';const link=page.locator('.native-delivery a').filter({hasText:'下载 PDF'});await link.waitFor();const download=await page.request.get(new URL(await link.getAttribute('href'),origin).href);assert.equal(download.status(),200);assert.match(download.headers()['content-disposition'],/attachment/);const bytes=await download.body();await writeFile(join(directory,'downloaded.pdf'),bytes);assert.equal(sha(bytes),result.artifacts.pdf.sha256);assert.equal(bytes.length,result.artifacts.pdf.size);assert.equal(result.validation.ok,false);assert.ok(result.validation.issues.length)
 stage='reopen';await navigateOpen(result.editor.openUrl);await ready();assert.deepEqual(await ops(),[]);const reopened=await page.request.get(origin+await page.locator('.pdf-original-download').getAttribute('href'));assert.equal(sha(await reopened.body()),sha(bytes));await page.locator('.pdf-page-content').first().locator('canvas').waitFor();await page.screenshot({path:join(directory,'reopened.png'),fullPage:true});assert.deepEqual(errors,[])
 await writeFile(join(directory,'evidence.json'),JSON.stringify({ok:true,mode:dev?'source-vite-runtime':'built-runtime',scope:'product UI, actual grants/CSRF/PDF writer/publication/authenticated HTTP attachment download/reopen; memory revision repository; browser download manager not covered',layout,applied,result,resources:Object.fromEntries(resources),errors,infrastructureWarnings},null,2));console.log(JSON.stringify({ok:true,directory,layoutCases:layout.length,validation:result.validation}))
}catch(error){await page?.screenshot({path:join(directory,'failure.png'),fullPage:true}).catch(()=>{});if(page)await writeFile(join(directory,'failure.html'),await page.content());await writeFile(join(directory,'failure.json'),JSON.stringify({stage,error:String(error),stack:error.stack,errors,resources:[...resources.keys()]},null,2));throw error}
finally{await browser?.close();for(const child of children)child.kill();await writeFile(join(directory,'server.log'),logs.join(''));await delay(500);for(const child of children)if(child.exitCode===null)child.kill('SIGKILL')}
