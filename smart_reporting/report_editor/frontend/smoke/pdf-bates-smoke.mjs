import assert from 'node:assert/strict'
import {spawn,spawnSync} from 'node:child_process'
import {createHash} from 'node:crypto'
import {cp,mkdir,readFile,symlink,writeFile} from 'node:fs/promises'
import {join,resolve,sep} from 'node:path'
import {fileURLToPath} from 'node:url'
import {setTimeout as delay} from 'node:timers/promises'
import {chromium} from 'playwright'
import {createServer} from 'vite'
const frontend=fileURLToPath(new URL('../',import.meta.url)),repo=fileURLToPath(new URL('../../../../',import.meta.url)),sha=bytes=>createHash('sha256').update(bytes).digest('hex')
const output=process.env.PDF_BATES_OUTPUT??'/dev/shm/office-pdf-bates-20261113/browser-source',port=Number(process.env.PDF_BATES_PORT??4412),origin=`http://127.0.0.1:${port}`
await mkdir(output,{recursive:true})
const frozen=Boolean(process.env.PDF_BATES_STATIC),staticRoot=frozen?resolve(process.env.PDF_BATES_STATIC):join(output,'static'),suppliedEngine=process.env.PDF_BATES_ENGINE??process.env.AGENT_REPORTING_PDF_ENGINE_DIR,engineRoot=suppliedEngine?resolve(suppliedEngine):join(output,'engine-source')
let vite
if(!frozen){
 await cp('/tmp/office-four-format-source-entry-20261113/static',staticRoot,{recursive:true,errorOnExist:true,force:false})
 await mkdir(join(staticRoot,'node_modules/pdfjs-dist/legacy/build'),{recursive:true});await cp(join(frontend,'node_modules/pdfjs-dist/legacy/build/pdf.worker.min.mjs'),join(staticRoot,'node_modules/pdfjs-dist/legacy/build/pdf.worker.min.mjs'))
 vite=await createServer({root:frontend,configFile:join(frontend,'vite.config.ts'),server:{host:'127.0.0.1',port:port+1,strictPort:true,cors:true}});await vite.listen()
 await writeFile(join(staticRoot,'native.html'),(await readFile(join(frontend,'native.html'),'utf8')).replace('/src/unified-main.ts',`http://127.0.0.1:${port+1}/reports/v1/editor/assets/src/unified-main.ts`))
}
if(!suppliedEngine){await mkdir(engineRoot);for(const name of ['bridge','src','vendor','node_modules','package.json'])await symlink(join(repo,'smart_reporting/reporting/pdf_engine',name),join(engineRoot,name))}
const sourceModuleHashes={};for(const file of ['pdf-main.ts','pdf-bates.ts','pdf-bates.css','pdf-page-ribbon.ts','pdf-operations.ts'])sourceModuleHashes[file]=sha(await readFile(join(frontend,'src',file)))
const server=spawn(join(repo,'.venv/bin/python'),[join(frontend,'smoke/pdf-bates-server.py'),'--directory',output,'--port',String(port)],{cwd:repo,env:{...process.env,PYTHONPATH:repo,PDF_SMOKE_STATIC_DIRECTORY:staticRoot,AGENT_REPORTING_PDF_ENGINE_DIR:engineRoot},stdio:'pipe'})
let log='',browser,page,stage='server';server.stdout.on('data',b=>{log+=b});server.stderr.on('data',b=>{log+=b})
const errors=[],consoleErrors=[],httpErrors=[],resources=[],resourceTasks=[]
try{
 for(let i=0;;i++){assert.equal(server.exitCode,null,log);try{if((await fetch(origin+'/__smoke__/state')).ok)break}catch{}assert(i<240,log);await delay(250)}
 const info=JSON.parse(await readFile(join(output,'server-info.json'),'utf8'))
 browser=await chromium.launch({headless:true});page=await browser.newPage({viewport:{width:1440,height:900}})
 const cdp=await page.context().newCDPSession(page);await cdp.send('Network.enable');await cdp.send('Network.setCacheDisabled',{cacheDisabled:true})
 page.on('pageerror',e=>errors.push(e.message));page.on('console',e=>{if(e.type()==='error')consoleErrors.push(e.text())});page.on('response',r=>{if(r.status()>=400)httpErrors.push({path:new URL(r.url()).pathname,status:r.status()})})
 if(frozen)page.on('response',r=>{const url=new URL(r.url()),prefix='/reports/v1/editor/assets/';if(url.origin!==origin||!url.pathname.startsWith(prefix)||r.status()!==200)return;resourceTasks.push((async()=>{const path=resolve(staticRoot,decodeURIComponent(url.pathname.slice(prefix.length)));assert(path.startsWith(staticRoot+sep));const actualSha256=sha(await r.body()),fileSha256=sha(await readFile(path));resources.push({path:url.pathname,actualSha256,fileSha256,matches:actualSha256===fileSha256})})().catch(e=>resources.push({path:url.pathname,matches:false,error:String(e)})))})
 const ready=()=>page.waitForFunction(()=>document.querySelector('#report-editor')?.getAttribute('aria-busy')==='false'&&document.querySelector('.pdf-page-content canvas'),null,{timeout:120000})
 const operations=()=>page.evaluate(()=>JSON.parse(Object.entries(localStorage).find(([key])=>key.startsWith('native-editor-draft:'))?.[1]??'{}').operations??[])
 const command=async id=>{await page.locator('[data-pdf-ribbon-tab="page"]').click();await page.locator(`[data-source-command-id="genoffice.pdf.page.${id}"]`).click();await ready()}
 const goTo=async n=>{await page.locator('[data-pdf-ribbon-tab="view"]').click();const input=page.locator('[data-source-command-id="genoffice.pdf.view.pageZoom.goToPage"]');await input.fill(String(n));await input.press('Enter');await ready()}
 await page.goto(origin+info.openPath);await ready()
 stage='before-apply';await command('reverse');await command('insertBlank')
 const before=await operations();await command('bates');assert.deepEqual(await operations(),before)
 const dialog=page.getByRole('dialog',{name:'Bates 编号',exact:true});await dialog.waitFor()
 if(process.env.PDF_BATES_MINIMAL==='1'){await page.getByLabel('Bates 起始页',{exact:true}).fill('20');await page.getByRole('button',{name:'应用 Bates 编号',exact:true}).click();await dialog.waitFor({state:'hidden'});assert.deepEqual(await operations(),before);await command('bates');await dialog.waitFor()}
 await page.getByLabel('Bates 前缀',{exact:true}).fill('CASE-');await page.getByLabel('Bates 起始编号',{exact:true}).fill('41');await page.getByLabel('Bates 编号位数',{exact:true}).fill('6');await page.getByLabel('Bates 字号',{exact:true}).fill('12');await page.getByLabel('Bates 起始页',{exact:true}).fill('2');await page.getByLabel('Bates 结束页',{exact:true}).fill('4');await page.getByLabel('Bates 颜色',{exact:true}).selectOption('2');await page.getByLabel('Bates 位置',{exact:true}).selectOption('top-center')
 await page.screenshot({path:join(output,'bates-dialog-desktop.png'),fullPage:true});await page.setViewportSize({width:390,height:700});await page.screenshot({path:join(output,'bates-dialog-narrow.png'),fullPage:true})
 const dialogLayout=await dialog.evaluate(d=>({width:d.clientWidth,scrollWidth:d.scrollWidth,height:d.clientHeight,scrollHeight:d.scrollHeight}));assert(dialogLayout.scrollWidth<=dialogLayout.width+1)
 await page.getByRole('button',{name:'应用 Bates 编号',exact:true}).scrollIntoViewIfNeeded();await page.screenshot({path:join(output,'bates-dialog-narrow-bottom.png'),fullPage:true});assert(await page.getByLabel('Bates 位置',{exact:true}).isVisible())
 await page.setViewportSize({width:1440,height:900});await page.getByRole('button',{name:'应用 Bates 编号',exact:true}).click();await ready()
 const applied=await operations(),bates=applied.find(o=>o.kind==='addBates');assert.deepEqual(bates.entries.map(e=>e.ordinal),[0,1,2]);assert.equal(bates.config.prefix,'CASE-');assert.equal(bates.entries[0].rotate,90)
 assert.deepEqual(await page.locator('[data-pdf-bates-preview]').allTextContents(),['CASE-000041','CASE-000042','CASE-000043'])
 stage='undo-redo';await page.locator('[data-pdf-ribbon-tab="home"]').click();await page.locator('[data-source-command-id="genoffice.pdf.home.edit.undo"]').click();await ready();assert.deepEqual(await operations(),before);await page.locator('[data-source-command-id="genoffice.pdf.home.edit.redo"]').click();await ready();assert.deepEqual(await operations(),applied)
 stage='later-structure';await goTo(3);await command('delete');await command('reverse');await command('insertBlank');await goTo(2);await command('rotateRight')
 const staged=await operations();assert.deepEqual(staged.find(o=>o.kind==='addBates'),bates)
 await page.screenshot({path:join(output,'bates-draft.png'),fullPage:true})
 stage='restore';await page.reload();await ready();assert.deepEqual(await operations(),staged)
 assert.deepEqual(await page.locator('[data-pdf-bates-preview]').allTextContents(),['CASE-000043','CASE-000041'])
 if(process.env.PDF_BATES_MINIMAL==='1'){
  await Promise.all(resourceTasks);assert(resources.every(r=>r.matches));assert.deepEqual(errors,[]);assert.deepEqual(consoleErrors,[]);assert.deepEqual(httpErrors,[])
  const state=await(await fetch(origin+'/__smoke__/state')).json();assert.equal(state.savedRevisions,0)
  await writeFile(join(output,'minimal-evidence.json'),JSON.stringify({ok:true,mode:frozen?'frozen-static':'source-vite',sourceModuleHashes,resources,sourceSha256:info.sourceSha256,staged,dialogLayout,errors,consoleErrors,httpErrors},null,2));console.log(JSON.stringify({ok:true,output,minimal:true}))
 }else{
  stage='preview';await page.locator('[data-pdf-ribbon-tab="edit"]').click();const previewing=page.waitForResponse(r=>r.url().endsWith('/api/preview')&&r.request().method()==='POST');await page.getByRole('button',{name:'校验当前修改',exact:true}).click();const preview=await(await previewing).json();assert.deepEqual(preview.skippedOperations,[]);assert.deepEqual(preview.appliedOperationIndices,staged.map((_,i)=>i));assert.deepEqual(preview.reviewIssues,[])
  await page.waitForFunction(()=>document.querySelector('[data-pdf-preview="true"]')&&[...document.querySelectorAll('button')].some(b=>b.textContent.includes('返回原稿编辑')&&!b.disabled),null,{timeout:60000})
  await page.getByRole('checkbox',{name:/我已核对实际 PDF 预览/}).check()
  stage='save';const saving=page.waitForResponse(r=>r.url().endsWith('/api/save')&&r.request().method()==='POST');await page.locator('[data-action="save"]').click();const response=await saving,saved=await response.json();assert.equal(response.status(),200,JSON.stringify(saved));assert.equal(saved.revisionRegistered,true);assert.equal(saved.parentRevision,4);assert.equal(saved.revision,5);assert.equal(response.request().postDataJSON().confirmedPreviewDigest,preview.previewDigest);assert.deepEqual(response.request().postDataJSON().operations,staged)
  stage='download';const link=page.locator('.native-delivery a').filter({hasText:'下载 PDF'});await link.waitFor();const downloading=page.waitForEvent('download');await link.click();const download=await downloading;assert.equal(await download.failure(),null);const bytes=await readFile(await download.path());assert.equal(sha(bytes),saved.artifacts.pdf.sha256);assert.equal(bytes.length,saved.artifacts.pdf.size);await writeFile(join(output,'downloaded.pdf'),bytes)
  stage='reopen';await page.goto(saved.editor.openUrl);await ready();const documentText=await page.locator('.textLayer').allTextContents();assert(documentText.some(t=>t.includes('CASE-000041')));assert(documentText.some(t=>t.includes('CASE-000043')));assert(!documentText.some(t=>t.includes('CASE-000042')))
  await page.screenshot({path:join(output,'bates-reopened.png'),fullPage:true});const state=await(await fetch(origin+'/__smoke__/state')).json();assert.equal(state.sourceSha256,info.sourceSha256);assert.equal(state.savedRevisions,1)
  await Promise.all(resourceTasks);assert(resources.every(r=>r.matches));assert.deepEqual(errors,[]);assert.deepEqual(consoleErrors,[]);assert.deepEqual(httpErrors,[])
  await writeFile(join(output,'evidence.json'),JSON.stringify({ok:true,mode:frozen?'frozen-static':'source-vite',sourceModuleHashes,resources,sourceSha256:info.sourceSha256,staged,preview,saved,dialogLayout,errors,consoleErrors,httpErrors,requests:state.requests},null,2))
  const verify=spawnSync(join(repo,'.venv/bin/python'),[join(frontend,'smoke/pdf-bates-verify.py'),output],{encoding:'utf8'});assert.equal(verify.status,0,verify.stderr||verify.stdout);console.log(JSON.stringify({ok:true,output,independent:JSON.parse(verify.stdout)}))
 }
}catch(error){await page?.screenshot({path:join(output,'failure.png'),fullPage:true}).catch(()=>{});await writeFile(join(output,'failure.json'),JSON.stringify({stage,error:String(error),errors,consoleErrors,httpErrors},null,2));throw error}
finally{await browser?.close();server.kill();await vite?.close();await writeFile(join(output,'server.log'),log);if(server.exitCode===null)await Promise.race([new Promise(r=>server.once('exit',r)),delay(5000)]);if(server.exitCode===null)server.kill('SIGKILL')}
