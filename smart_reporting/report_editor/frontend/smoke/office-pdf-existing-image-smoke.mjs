// 真实授权、预览、打包引擎、发布和下载；复用隔离内存仓储的已有图像夹具。
import assert from 'node:assert/strict'
import {createHash} from 'node:crypto'
import {spawn} from 'node:child_process'
import {setTimeout as delay} from 'node:timers/promises'
import {mkdir,readFile,writeFile,access} from 'node:fs/promises'
import {join} from 'node:path'
import {fileURLToPath} from 'node:url'
import {chromium} from 'playwright'
import {inspectExistingImageLayout} from './office-pdf-existing-image-layout.mjs'
const frontend=fileURLToPath(new URL('../',import.meta.url)),repo=fileURLToPath(new URL('../../../../',import.meta.url)),staticRoot=join(frontend,'../static')
const directory=process.env.PDF_EXISTING_IMAGE_OUTPUT,port=Number(process.env.PDF_EXISTING_IMAGE_PORT??4391),origin='http://127.0.0.1:'+port
assert.ok(directory,'PDF_EXISTING_IMAGE_OUTPUT must name a fresh evidence directory');await mkdir(directory,{recursive:true})
let priorSave=false;try{await access(join(directory,'save.json'));priorSave=true}catch{}assert.equal(priorSave,false,'use a fresh directory; never repeat a successful save')
const sha=b=>createHash('sha256').update(b).digest('hex'),manifest=await readFile(join(staticRoot,'.vite/manifest.json'))
assert.equal(sha(manifest),process.env.PDF_EXPECTED_MANIFEST_SHA256);await writeFile(join(directory,'build-manifest.json'),manifest)
const server=spawn(join(repo,'.venv/bin/python'),[join(frontend,'smoke/pdf-existing-image-server.py'),'--directory',directory,'--port',String(port)],{cwd:repo,env:{...process.env,PYTHONPATH:repo},stdio:'pipe'})
let serverLog='',browser,page,stage='server';server.stdout.on('data',b=>{serverLog+=b});server.stderr.on('data',b=>{serverLog+=b})
const errors=[],checks=[],assets=new Map(),layout={cases:[],failures:[]}
try{
 for(let i=0;;i++){assert.equal(server.exitCode,null,serverLog);try{if((await fetch(origin+'/__smoke__/state',{signal:AbortSignal.timeout(1500)})).ok)break}catch{}assert(i<240,serverLog);await delay(250)}
 const info=JSON.parse(await readFile(join(directory,'server-info.json'),'utf8'))
 browser=await chromium.launch({headless:true,...(process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE?{executablePath:process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE}:{})});page=await browser.newPage({viewport:{width:1440,height:900}})
 page.on('pageerror',e=>errors.push(e.message));page.on('console',m=>{if(m.type()==='error')errors.push(m.text())});page.on('crash',()=>errors.push('renderer crashed'))
 page.on('response',r=>{const path=new URL(r.url()).pathname;if(r.status()>=400)errors.push(r.status()+' '+path);if(r.status()===200&&path.startsWith('/reports/v1/editor/assets/')&&/\.(?:m?js|css)$/.test(path))checks.push(r.body().then(async b=>{const disk=await readFile(join(staticRoot,path.slice('/reports/v1/editor/assets/'.length)));assert.equal(sha(b),sha(disk));assets.set(path,{sha256:sha(b),size:b.length})}).catch(e=>errors.push(String(e))))})
 const ready=()=>page.waitForFunction(()=>document.querySelector('#report-editor')?.getAttribute('aria-busy')==='false',null,{timeout:60000})
 const draft=()=>page.evaluate(()=>Object.entries(localStorage).filter(([k])=>k.startsWith('native-editor-draft:')).map(([k,v])=>[k,JSON.parse(v).operations]))
 const operations=async()=>(await draft()).flatMap(([,ops])=>ops)
 const waitOps=count=>page.waitForFunction(count=>Object.entries(localStorage).filter(([k])=>k.startsWith('native-editor-draft:')).flatMap(([,v])=>JSON.parse(v).operations).length===count,count)
 const command=async(tab,id)=>{await page.locator(`[data-pdf-ribbon-tab="${tab}"]`).click();await page.locator(`[data-source-command-id="genoffice.pdf.${id}"]`).click()}
 const dialog=page.getByRole('dialog',{name:'编辑已有图像',exact:true}),entry=page.locator('[data-source-command-id="genoffice.pdf.edit.objects.editImage"]')
 const open=async()=>{await command('edit','edit.objects.editImage');await dialog.waitFor()}
 const geometry=async()=>Object.fromEntries(await Promise.all(['X','Y','宽度','高度'].map(async label=>[label,await dialog.getByLabel('已有图像'+label,{exact:true}).inputValue()])))
 await page.goto(origin+info.openPath);await ready();await open();stage='initial-layout'
 await inspectExistingImageLayout(page,{directory,phase:'initial',layout,draft})
 if(process.env.PDF_EXISTING_IMAGE_BASELINE==='1'){
  const state=await(await fetch(origin+'/__smoke__/state')).json();assert.equal(state.savedRevisions,0);await Promise.all(checks);assert.deepEqual(errors,[])
  await writeFile(join(directory,'baseline.json'),JSON.stringify({baseline:true,manifest:sha(manifest),layout,state,errors},null,2));console.log(JSON.stringify({baseline:true,cases:layout.cases.length,failures:layout.failures.length}))
 }else{
 assert.deepEqual(layout.failures,[])
 await dialog.getByRole('button',{name:'取消',exact:true}).click();assert.equal(await entry.evaluate(n=>n===document.activeElement),true);assert.deepEqual(await operations(),[])
 await open();assert.equal(await dialog.getByLabel('已有图像选择',{exact:true}).evaluate(n=>n===document.activeElement),true)
 stage='error';await dialog.getByLabel('已有图像宽度',{exact:true}).fill('');await dialog.locator('[data-pdf-existing-image-confirm]').click();assert.match(await dialog.locator('[role=alert]').innerText(),/有限数值/)
 await inspectExistingImageLayout(page,{directory,phase:'error',layout,draft});assert.deepEqual(layout.failures,[]);assert.deepEqual(await operations(),[])
 await dialog.getByLabel('选择替换图像',{exact:true}).setInputFiles({name:'invalid.gif',mimeType:'image/gif',buffer:Buffer.from('GIF89a')});await page.waitForFunction(()=>document.querySelector('.pdf-existing-image-dialog [role=alert]')?.textContent?.includes('PNG 或 JPEG'))
 const replacement=Buffer.from(await page.evaluate(()=>{const c=document.createElement('canvas');c.width=40;c.height=30;const x=c.getContext('2d');x.fillStyle='#1f4fd8';x.fillRect(0,0,40,30);x.fillStyle='#ffd400';x.fillRect(10,8,20,14);return c.toDataURL('image/png').split(',')[1]}),'base64')
 await writeFile(join(directory,'replacement.png'),replacement)
 const name='已有图像替换 & <保真> 😀 '.repeat(12)+'.png',pick=()=>dialog.getByLabel('选择替换图像',{exact:true}).setInputFiles({name,mimeType:'image/png',buffer:replacement})
 await pick();await page.waitForFunction(()=>document.querySelector('.pdf-existing-image-replace-info')?.textContent?.includes('40×30'))
 stage='replacement-layout';await inspectExistingImageLayout(page,{directory,phase:'replacement',layout,draft});assert.deepEqual(layout.failures,[])
 await dialog.getByRole('button',{name:'不替换',exact:true}).click();assert.equal(await dialog.locator('.pdf-existing-image-replace-info').textContent(),'不替换像素');assert.deepEqual(await operations(),[])
 await pick();await page.waitForFunction(()=>document.querySelector('.pdf-existing-image-replace-info')?.textContent?.includes('40×30'))
 await dialog.getByRole('button',{name:'关闭编辑已有图像',exact:true}).click();assert.equal(await entry.evaluate(n=>n===document.activeElement),true);assert.deepEqual(await operations(),[])
 await open();assert.equal(await dialog.locator('.pdf-existing-image-replace-info').textContent(),'不替换像素');assert.deepEqual(await geometry(),{X:'60',Y:'90','宽度':'100','高度':'80'});await dialog.getByLabel('已有图像X',{exact:true}).press('Escape');await dialog.waitFor({state:'hidden'});assert.equal(await entry.evaluate(n=>n===document.activeElement),true)
 stage='apply';await open();for(const [label,value] of [['X','80'],['Y','110'],['宽度','150'],['高度','100']])await dialog.getByLabel('已有图像'+label,{exact:true}).fill(value)
 await pick();await page.waitForFunction(()=>document.querySelector('.pdf-existing-image-replace-info')?.textContent?.includes('40×30'));await dialog.locator('[data-pdf-existing-image-confirm]').click();await waitOps(1)
 const applied=await operations();assert.equal(applied[0].kind,'transformExistingImage');assert.deepEqual(applied[0].rect,[80,110,230,210]);assert.match(applied[0].image,/^iVBORw0KGgo/);await writeFile(join(directory,'staged.json'),JSON.stringify(applied,null,2))
 await command('home','home.edit.undo');await waitOps(0);await command('home','home.edit.redo');await waitOps(1);assert.deepEqual(await operations(),applied);await page.reload();await ready();assert.deepEqual(await operations(),applied)
 stage='preview';await page.locator('[data-pdf-ribbon-tab="edit"]').click();const previewing=page.waitForResponse(r=>r.url().endsWith('/api/preview')&&r.request().method()==='POST'&&r.request().postDataJSON().operations?.length===1);await page.getByRole('button',{name:'校验当前修改',exact:true}).click();const preview=await(await previewing).json();assert.deepEqual(preview.appliedOperationIndices,[0]);assert.deepEqual(preview.skippedOperations,[])
 await page.locator('.pdf-preview-review input[type=checkbox]').check();await page.waitForFunction(()=>document.querySelector('#report-editor')?.dataset.pdfPreview==='true');await page.screenshot({path:join(directory,'preview.png'),fullPage:true})
 stage='save';const saving=page.waitForResponse(r=>r.url().endsWith('/api/save')&&r.request().method()==='POST');await page.locator('[data-action=save]').click();const response=await saving,result=await response.json();await writeFile(join(directory,'save.json'),JSON.stringify({request:response.request().postDataJSON(),result},null,2));assert.equal(response.status(),200,JSON.stringify(result));assert.equal(result.revisionRegistered,true);assert.deepEqual(response.request().postDataJSON().operations,applied);assert.equal(response.request().postDataJSON().confirmedPreviewDigest,preview.previewDigest)
 stage='download';const link=page.locator('.native-delivery a').filter({hasText:'下载 PDF'});await link.waitFor();const downloading=page.waitForEvent('download');await link.click();const download=await downloading;assert.equal(await download.failure(),null);await download.saveAs(join(directory,'downloaded.pdf'));const bytes=await readFile(join(directory,'downloaded.pdf'));assert.equal(sha(bytes),result.artifacts.pdf.sha256);assert.equal(bytes.length,result.artifacts.pdf.size)
 assert.equal(result.validation.ok,false);assert.ok(result.validation.issues.length);assert.match(await page.locator('.native-delivery').innerText(),/核验|复核|验证|验收/)
 stage='reopen';await page.goto(result.editor.openUrl);await ready();await open();const reopenedGeometry=await geometry();for(const [label,value] of [['X',80],['Y',110],['宽度',150],['高度',100]])assert.ok(Math.abs(Number(reopenedGeometry[label])-value)<.05)
 assert.equal(await dialog.locator('.pdf-existing-image-replace-info').textContent(),'不替换像素');await inspectExistingImageLayout(page,{directory,phase:'reopened',layout,draft});assert.deepEqual(layout.failures,[]);await dialog.getByRole('button',{name:'取消',exact:true}).click();await page.screenshot({path:join(directory,'reopened.png'),fullPage:true})
 await Promise.all(checks);assert.deepEqual(errors,[]);assert.deepEqual(await readFile(join(staticRoot,'.vite/manifest.json')),manifest)
 const state=await(await fetch(origin+'/__smoke__/state')).json();assert.equal(state.savedRevisions,1);assert.equal(state.sourceSha256,info.sourceSha256)
 await writeFile(join(directory,'evidence.json'),JSON.stringify({ok:true,manifest:sha(manifest),scope:'real grants/CSRF/preview/packed engine/publication/download; isolated memory repository',sourceSha256:info.sourceSha256,layout,applied,preview,result,state,resources:Object.fromEntries(assets),errors},null,2));console.log(JSON.stringify({ok:true,cases:layout.cases.length,resources:assets.size,directory}))
 }
}catch(error){await page?.screenshot({path:join(directory,'failure.png'),fullPage:true}).catch(()=>{});await writeFile(join(directory,'failure.json'),JSON.stringify({stage,error:String(error),stack:error.stack,errors},null,2));throw error}
finally{await browser?.close();server.kill();await writeFile(join(directory,'server.log'),serverLog);if(server.exitCode===null)await Promise.race([new Promise(done=>server.once('exit',done)),delay(5000)]);if(server.exitCode===null)server.kill('SIGKILL')}
