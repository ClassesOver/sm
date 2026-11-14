// 实际构建/授权/CSRF/PDF引擎/发布/HTTP下载，修订仓储为明确的内存夹具。
import assert from 'node:assert/strict'
import {spawn} from 'node:child_process'
import {createHash} from 'node:crypto'
import {mkdir,readFile,writeFile} from 'node:fs/promises'
import {join} from 'node:path'
import {fileURLToPath} from 'node:url'
import {setTimeout as delay} from 'node:timers/promises'
import {chromium} from 'playwright'
import {inspectLinkLayout} from './office-pdf-link-layout.mjs'
const frontend=fileURLToPath(new URL('../',import.meta.url)),repo=fileURLToPath(new URL('../../../../',import.meta.url))
const staticRoot=process.env.PDF_SMOKE_STATIC_DIRECTORY,directory=process.env.PDF_LINK_OUTPUT,port=Number(process.env.PDF_LINK_PORT??4393),origin='http://127.0.0.1:'+port
assert.ok(directory&&staticRoot,'PDF_LINK_OUTPUT / PDF_SMOKE_STATIC_DIRECTORY are required')
// 在任何服务、浏览器或保存之前拒绝复用证据目录。
await mkdir(directory)
const sha=b=>createHash('sha256').update(b).digest('hex'),manifest=await readFile(join(staticRoot,'.vite/manifest.json'))
assert.equal(sha(manifest),process.env.PDF_EXPECTED_MANIFEST_SHA256)
await writeFile(join(directory,'build-manifest.json'),manifest)
const server=spawn(join(repo,'.venv/bin/python'),[join(frontend,'smoke/office-pdf-link-server.py'),'--directory',directory,'--port',String(port)],{cwd:repo,env:{...process.env,PYTHONPATH:repo},stdio:'pipe'})
let serverLog='',browser,page,stage='server';server.stdout.on('data',b=>{serverLog+=b});server.stderr.on('data',b=>{serverLog+=b})
const errors=[],checks=[],assets=new Map(),layout={cases:[],failures:[]}
try{
 for(let i=0;;i++){assert.equal(server.exitCode,null,serverLog);try{if((await fetch(origin+'/__smoke__/state',{signal:AbortSignal.timeout(1500)})).ok)break}catch{}assert(i<240,serverLog);await delay(250)}
 const info=JSON.parse(await readFile(join(directory,'server-info.json'),'utf8'))
 browser=await chromium.launch({headless:true,...(process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE?{executablePath:process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE}:{})});page=await browser.newPage({viewport:{width:1440,height:900}})
 page.on('pageerror',e=>errors.push(e.message));page.on('console',m=>{if(m.type()==='error')errors.push(m.text())});page.on('crash',()=>errors.push('renderer crashed'))
 page.on('response',r=>{const path=new URL(r.url()).pathname;if(r.status()>=400)errors.push(r.status()+' '+path);if(r.status()===200&&path.startsWith('/reports/v1/editor/assets/')&&/\.(?:m?js|css|wasm)$/.test(path))checks.push(r.body().then(async b=>{assert.equal(sha(b),sha(await readFile(join(staticRoot,path.slice('/reports/v1/editor/assets/'.length)))));assets.set(path,{sha256:sha(b),size:b.length})}).catch(e=>errors.push(String(e))))})
 const ready=()=>page.waitForFunction(()=>document.querySelector('#report-editor')?.getAttribute('aria-busy')==='false',null,{timeout:60000})
 const draft=()=>page.evaluate(()=>Object.entries(localStorage).filter(([k])=>k.startsWith('native-editor-draft:')).map(([k,v])=>[k,JSON.parse(v).operations]))
 const operations=async()=> (await draft()).flatMap(([,ops])=>ops)
 const waitOps=count=>page.waitForFunction(count=>Object.entries(localStorage).filter(([k])=>k.startsWith('native-editor-draft:')).flatMap(([,v])=>JSON.parse(v).operations).length===count,count)
 const command=async(tab,id)=>{await page.locator(`[data-pdf-ribbon-tab="${tab}"]`).click();await page.locator(`[data-source-command-id="genoffice.pdf.${id}"]`).click()}
 const dialog=page.getByRole('dialog',{name:'添加链接',exact:true}),entry=page.locator('[data-source-command-id="genoffice.pdf.edit.objects.editLink"]')
 const open=async(row=0)=>{
  await page.locator('[data-pdf-ribbon-tab="edit"]').click()
  if(await entry.getAttribute('aria-pressed')!=='true')await entry.click()
  const holder=page.locator('.pdf-page-content').first();await holder.locator('canvas').waitFor();await holder.scrollIntoViewIfNeeded()
  const r=await holder.boundingBox();assert.ok(r)
  await page.mouse.move(r.x+r.width*.1,r.y+r.height*(.22+row*.13));await page.mouse.down();await page.mouse.move(r.x+r.width*.6,r.y+r.height*(.29+row*.13),{steps:5});await page.mouse.up();await dialog.waitFor()
  assert.equal(await dialog.getByLabel('链接网址',{exact:true}).evaluate(n=>n===document.activeElement),true)
 }
 const inspect=phase=>inspectLinkLayout(page,{directory,phase,layout,draft})
 const close=async action=>{
  if(action==='escape')await dialog.getByLabel('链接网址',{exact:true}).press('Escape')
  else await dialog.getByRole('button',{name:action==='title'?'关闭添加链接':'取消',exact:true}).click()
  await dialog.waitFor({state:'hidden'});assert.equal(await entry.evaluate(n=>n===document.activeElement),true)
 }
 await page.goto(origin+info.openPath);await ready();await open();stage='initial-layout';await inspect('initial')
 if(process.env.PDF_LINK_BASELINE==='1'){
  const state=await(await fetch(origin+'/__smoke__/state')).json();assert.equal(state.savedRevisions,0);await Promise.all(checks);assert.deepEqual(errors,[])
  await writeFile(join(directory,'baseline.json'),JSON.stringify({baseline:true,manifest:sha(manifest),layout,state,errors},null,2));console.log(JSON.stringify({baseline:true,cases:layout.cases.length,failures:layout.failures.length}))
 }else{
 assert.deepEqual(layout.failures,[])
 for(const action of ['title','cancel','escape']){if(action!=='title')await open();await dialog.getByLabel('链接网址',{exact:true}).fill('https://cancel.invalid');await close(action);assert.deepEqual(await operations(),[])}
 await open();assert.equal(await dialog.getByLabel('链接网址',{exact:true}).inputValue(),'')
 stage='invalid-url';await dialog.getByLabel('链接网址',{exact:true}).fill('javascript:alert(1)');await dialog.getByRole('button',{name:'确定',exact:true}).click();assert.match(await dialog.locator('[role=alert]').innerText(),/http\/https\/mailto/)
 assert.equal(await dialog.locator('[role=alert]').evaluate(n=>n===document.activeElement),true);assert.deepEqual(await operations(),[]);await inspect('invalid-url')
 stage='long-url';await dialog.getByLabel('链接网址',{exact:true}).fill('https://example.com/'+ 'a'.repeat(2100));await dialog.getByRole('button',{name:'确定',exact:true}).click();assert.deepEqual(await operations(),[]);await inspect('long-url')
 stage='invalid-page';await dialog.getByLabel('链接页码',{exact:true}).fill('4');assert.equal(await dialog.getByLabel('链接网址',{exact:true}).inputValue(),'');await dialog.getByRole('button',{name:'确定',exact:true}).click();assert.match(await dialog.locator('[role=alert]').innerText(),/1–3/);await inspect('invalid-page');assert.deepEqual(layout.failures,[])
 stage='apply';await dialog.getByLabel('链接网址',{exact:true}).fill('www.example.com/report?year=2026&kind=office');assert.equal(await dialog.getByLabel('链接页码',{exact:true}).inputValue(),'');await dialog.getByRole('button',{name:'确定',exact:true}).click();await waitOps(1)
 await open(1);await dialog.getByLabel('链接网址',{exact:true}).fill('mailto:review@example.com?subject=Report');await dialog.getByRole('button',{name:'确定',exact:true}).click();await waitOps(2)
 await open(2);await dialog.getByLabel('链接页码',{exact:true}).fill('3');await dialog.getByRole('button',{name:'确定',exact:true}).click();await waitOps(3)
 const applied=await operations();assert.equal(applied[0].url,'https://www.example.com/report?year=2026&kind=office');assert.equal(applied[1].url,'mailto:review@example.com?subject=Report');assert.equal(applied[2].destPage,3);await writeFile(join(directory,'staged.json'),JSON.stringify(applied,null,2))
 await command('home','home.edit.undo');await waitOps(2);assert.deepEqual(await operations(),applied.slice(0,2));await command('home','home.edit.redo');await waitOps(3);assert.deepEqual(await operations(),applied)
 await page.reload();await ready();assert.deepEqual(await operations(),applied)
 stage='preview';await page.locator('[data-pdf-ribbon-tab="edit"]').click();const previewing=page.waitForResponse(r=>r.url().endsWith('/api/preview')&&r.request().method()==='POST'&&r.request().postDataJSON().operations?.length===3);await page.getByRole('button',{name:'校验当前修改',exact:true}).click();const preview=await(await previewing).json();assert.deepEqual(preview.appliedOperationIndices,[0,1,2]);assert.deepEqual(preview.skippedOperations,[])
 await page.waitForFunction(()=>document.querySelector('#report-editor')?.dataset.pdfPreview==='true');assert.equal(await page.locator('.pdf-preview-review').isVisible(),false);await page.screenshot({path:join(directory,'preview.png'),fullPage:true})
 stage='save';const saving=page.waitForResponse(r=>r.url().endsWith('/api/save')&&r.request().method()==='POST');await page.locator('[data-action=save]').click();const response=await saving,result=await response.json();await writeFile(join(directory,'save.json'),JSON.stringify({request:response.request().postDataJSON(),result},null,2));assert.equal(response.status(),200,JSON.stringify(result));assert.equal(result.revisionRegistered,true);assert.deepEqual(response.request().postDataJSON().operations,applied);assert.equal(response.request().postDataJSON().confirmedPreviewDigest,undefined)
 stage='download';const link=page.locator('.native-delivery a').filter({hasText:'下载 PDF'});await link.waitFor();const downloading=page.waitForEvent('download');await link.click();const download=await downloading;assert.equal(await download.failure(),null);await download.saveAs(join(directory,'downloaded.pdf'));const bytes=await readFile(join(directory,'downloaded.pdf'));assert.equal(sha(bytes),result.artifacts.pdf.sha256);assert.equal(bytes.length,result.artifacts.pdf.size)
 assert.equal(result.validation.ok,false);assert.ok(result.validation.issues.length);assert.match(await page.locator('.native-delivery').innerText(),/核验|复核|验证|验收/)
 stage='reopen';await page.goto(result.editor.openUrl);await ready();assert.deepEqual(await operations(),[])
 // 重开读取的是实际保存字节；链接目标由独立 PDF 读取器校验，当前宿主没有已保存链接点击层。
 const reopened=await page.request.get(origin+await page.locator('.pdf-original-download').getAttribute('href'));assert.equal(reopened.status(),200);assert.equal(sha(await reopened.body()),sha(bytes))
 await page.locator('.pdf-page-content').first().locator('canvas').waitFor();await page.screenshot({path:join(directory,'reopened.png'),fullPage:true})
 await open();await inspect('reopened');assert.deepEqual(layout.failures,[]);await close('title')
 await Promise.all(checks);assert.deepEqual(errors,[]);assert.deepEqual(await readFile(join(staticRoot,'.vite/manifest.json')),manifest)
 const state=await(await fetch(origin+'/__smoke__/state')).json();assert.equal(state.savedRevisions,1);assert.equal(state.sourceSha256,info.sourceSha256)
 await writeFile(join(directory,'evidence.json'),JSON.stringify({ok:true,manifest:sha(manifest),scope:'actual build/grants/CSRF/preview/PDF bridge/publication/HTTP download; memory revision repository',sourceSha256:info.sourceSha256,layout,applied,preview,result,state,resources:Object.fromEntries(assets),errors},null,2));console.log(JSON.stringify({ok:true,cases:layout.cases.length,resources:assets.size,directory}))
 }
}catch(error){await page?.screenshot({path:join(directory,'failure.png'),fullPage:true}).catch(()=>{});await writeFile(join(directory,'failure.json'),JSON.stringify({stage,error:String(error),stack:error.stack,errors},null,2));throw error}
finally{await browser?.close();server.kill();await writeFile(join(directory,'server.log'),serverLog);if(server.exitCode===null)await Promise.race([new Promise(done=>server.once('exit',done)),delay(5000)]);if(server.exitCode===null)server.kill('SIGKILL')}
