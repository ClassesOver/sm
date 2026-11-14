// 真实授权/CSRF/预览/PDF引擎/发布/下载；隔离内存修订仓储。
import assert from 'node:assert/strict'
import {spawn} from 'node:child_process'
import {createHash} from 'node:crypto'
import {mkdir,readFile,writeFile} from 'node:fs/promises'
import {join} from 'node:path'
import {fileURLToPath} from 'node:url'
import {setTimeout as delay} from 'node:timers/promises'
import {chromium} from 'playwright'
import {inspectStampLayout} from './office-pdf-stamp-layout.mjs'
const frontend=fileURLToPath(new URL('../',import.meta.url)),repo=fileURLToPath(new URL('../../../../',import.meta.url)),staticRoot=join(frontend,'../static')
const directory=process.env.PDF_STAMP_OUTPUT,port=Number(process.env.PDF_STAMP_PORT??4387),origin='http://127.0.0.1:'+port
assert.ok(directory,'PDF_STAMP_OUTPUT must name a fresh evidence directory');await mkdir(directory,{recursive:true})
const sha=b=>createHash('sha256').update(b).digest('hex'),manifest=await readFile(join(staticRoot,'.vite/manifest.json'))
assert.equal(sha(manifest),process.env.PDF_EXPECTED_MANIFEST_SHA256)
await writeFile(join(directory,'build-manifest.json'),manifest)
const server=spawn(join(repo,'.venv/bin/python'),[join(frontend,'smoke/pdf-static-text-server.py'),'--directory',directory,'--port',String(port)],{cwd:repo,env:{...process.env,PYTHONPATH:repo},stdio:'pipe'})
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
 const operations=async()=> (await draft()).flatMap(([,ops])=>ops)
 const waitOps=count=>page.waitForFunction(count=>Object.entries(localStorage).filter(([k])=>k.startsWith('native-editor-draft:')).flatMap(([,v])=>JSON.parse(v).operations).length===count,count)
 const command=async(tab,id)=>{await page.locator(`[data-pdf-ribbon-tab="${tab}"]`).click();await page.locator(`[data-source-command-id="genoffice.pdf.${id}"]`).click()}
 const dialog=page.getByRole('dialog',{name:'水印与页眉页脚',exact:true})
 const open=async()=>{await command('edit','edit.objects.watermark');await dialog.waitFor()}
 const range=async(label,value)=>{const input=dialog.getByLabel(label,{exact:true});await input.focus();await input.press('Home');for(let n=Number(await input.getAttribute('min'));n<value;n++)await input.press('ArrowRight');assert.equal(await input.inputValue(),String(value))}
 await page.goto(origin+info.openPath);await ready();await open();stage='initial-layout';assert.equal(await dialog.getByLabel('水印文字',{exact:true}).evaluate(n=>n===document.activeElement),true)
 await inspectStampLayout(page,{directory,phase:'initial',layout,draft})
 if(process.env.PDF_STAMP_BASELINE==='1'){
  const state=await(await fetch(origin+'/__smoke__/state')).json();assert.equal(state.savedRevisions,0);await Promise.all(checks);assert.deepEqual(errors,[])
  await writeFile(join(directory,'baseline.json'),JSON.stringify({baseline:true,manifest:sha(manifest),layout,state,errors},null,2));console.log(JSON.stringify({baseline:true,cases:layout.cases.length,failures:layout.failures.length}));
 }else{
 assert.deepEqual(layout.failures,[])
 stage='invalid';await dialog.getByLabel('页脚居中显示页码（第 n / 共 N 页）',{exact:true}).uncheck();await dialog.getByRole('button',{name:'确定',exact:true}).click();assert.match(await dialog.locator('[role=alert]').innerText(),/请填写/)
 await inspectStampLayout(page,{directory,phase:'error',layout,draft});assert.deepEqual(layout.failures,[]);assert.deepEqual(await operations(),[])
 await dialog.getByLabel('水印文字',{exact:true}).fill('长水印文字 '.repeat(25));await dialog.getByLabel('页眉左',{exact:true}).fill('年度经营报告 '.repeat(20));await range('角度（°）',-30);await range('不透明度（%）',45);await range('字号（页宽 %）',12)
 await inspectStampLayout(page,{directory,phase:'long-input',layout,draft});assert.deepEqual(layout.failures,[])
 await dialog.getByRole('button',{name:'关闭水印与页眉页脚',exact:true}).click();assert.equal(await page.locator('[data-source-command-id="genoffice.pdf.edit.objects.watermark"]').evaluate(n=>n===document.activeElement),true);assert.deepEqual(await operations(),[])
 await open();assert.equal(await dialog.getByLabel('水印文字',{exact:true}).inputValue(),'');await dialog.getByLabel('水印文字',{exact:true}).press('Escape');await dialog.waitFor({state:'hidden'});assert.equal(await page.locator('[data-source-command-id="genoffice.pdf.edit.objects.watermark"]').evaluate(n=>n===document.activeElement),true)
 stage='apply';await command('page','page.rotateRight');await waitOps(1);const base=await operations();await open()
 const fill=async()=>{await dialog.getByLabel('水印文字',{exact:true}).fill('机密 Confidential');await dialog.getByLabel('页眉左',{exact:true}).fill('年度经营报告');await dialog.getByLabel('页脚右',{exact:true}).fill('{page}/{total}');await dialog.getByLabel('起始页码',{exact:true}).fill('3');await range('角度（°）',-30);await range('不透明度（%）',45);await range('字号（页宽 %）',12)}
 await fill();await dialog.getByRole('button',{name:'确定',exact:true}).click();await waitOps(2);const applied=await operations();assert.deepEqual(applied[0],base[0]);assert.equal(applied[1].kind,'setStamps');assert.equal(applied[1].watermark.opacity,.45);assert.equal(applied[1].watermark.angle,-30);assert.equal(applied[1].watermark.sizeRatio,.12)
 await command('home','home.edit.undo');await waitOps(1);assert.deepEqual(await operations(),base);await command('home','home.edit.redo');await waitOps(2);assert.deepEqual(await operations(),applied)
 await page.reload();await ready();assert.deepEqual(await operations(),applied);await open();assert.equal(await dialog.getByLabel('水印文字',{exact:true}).inputValue(),'机密 Confidential');assert.equal(await dialog.getByLabel('起始页码',{exact:true}).inputValue(),'3')
 await inspectStampLayout(page,{directory,phase:'recovered',layout,draft});assert.deepEqual(layout.failures,[])
 await dialog.getByRole('button',{name:'清除水印与页眉页脚',exact:true}).click();await waitOps(1);assert.deepEqual(await operations(),base);await command('home','home.edit.undo');await waitOps(2);assert.deepEqual(await operations(),applied)
 stage='preview';await page.locator('[data-pdf-ribbon-tab="edit"]').click();const previewing=page.waitForResponse(r=>r.url().endsWith('/api/preview')&&r.request().method()==='POST'&&r.request().postDataJSON().operations?.length===2);await page.getByRole('button',{name:'校验当前修改',exact:true}).click();const preview=await(await previewing).json();assert.deepEqual(preview.appliedOperationIndices,[0,1]);assert.deepEqual(preview.skippedOperations,[])
 await page.waitForFunction(()=>document.querySelector('#report-editor')?.dataset.pdfPreview==='true');assert.equal(await page.locator('.pdf-preview-review').evaluate(n=>n.hidden),true);await page.screenshot({path:join(directory,'preview.png'),fullPage:true})
 stage='save';const saving=page.waitForResponse(r=>r.url().endsWith('/api/save')&&r.request().method()==='POST');await page.locator('[data-action=save]').click();const response=await saving,result=await response.json();await writeFile(join(directory,'save.json'),JSON.stringify({request:response.request().postDataJSON(),result},null,2));assert.equal(response.status(),200,JSON.stringify(result));assert.equal(result.revisionRegistered,true);assert.deepEqual(response.request().postDataJSON().operations,applied);assert.equal(response.request().postDataJSON().confirmedPreviewDigest,undefined)
 stage='download';const link=page.locator('.native-delivery a').filter({hasText:'下载 PDF'});await link.waitFor();const downloading=page.waitForEvent('download');await link.click();const download=await downloading;assert.equal(await download.failure(),null);await download.saveAs(join(directory,'downloaded.pdf'));const bytes=await readFile(join(directory,'downloaded.pdf'));assert.equal(sha(bytes),result.artifacts.pdf.sha256);assert.equal(bytes.length,result.artifacts.pdf.size)
 stage='reopen';await page.goto(result.editor.openUrl);await ready();await page.screenshot({path:join(directory,'reopened.png'),fullPage:true});await open();assert.equal(await dialog.getByLabel('水印文字',{exact:true}).inputValue(),'');await dialog.getByRole('button',{name:'取消',exact:true}).click()
 await page.waitForLoadState('networkidle');await Promise.all(checks);assert.deepEqual(errors,[]);assert.deepEqual(await readFile(join(staticRoot,'.vite/manifest.json')),manifest)
 const state=await(await fetch(origin+'/__smoke__/state')).json();assert.equal(state.savedRevisions,1);assert.equal(state.sourceSha256,info.sourceSha256)
 await writeFile(join(directory,'evidence.json'),JSON.stringify({ok:true,manifest:sha(manifest),scope:'real grants/CSRF/preview/packed engine/publication/download; isolated memory repository',sourceSha256:info.sourceSha256,layout,base,applied,preview,result,state,resources:Object.fromEntries(assets),errors},null,2));console.log(JSON.stringify({ok:true,cases:layout.cases.length,resources:assets.size,directory}))
 }
}catch(error){await page?.screenshot({path:join(directory,'failure.png'),fullPage:true}).catch(()=>{});await writeFile(join(directory,'failure.json'),JSON.stringify({stage,error:String(error),stack:error.stack,errors},null,2));throw error}
finally{await browser?.close();server.kill();await writeFile(join(directory,'server.log'),serverLog);if(server.exitCode===null)await Promise.race([new Promise(done=>server.once('exit',done)),delay(5000)]);if(server.exitCode===null)server.kill('SIGKILL')}
