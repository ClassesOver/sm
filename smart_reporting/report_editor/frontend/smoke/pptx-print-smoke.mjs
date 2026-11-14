import assert from 'node:assert/strict'
import { spawn, spawnSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import { cp, mkdir, readFile, writeFile } from 'node:fs/promises'
import { join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { setTimeout as delay } from 'node:timers/promises'
import { chromium } from 'playwright'

const frontend=fileURLToPath(new URL('../',import.meta.url)),repo=fileURLToPath(new URL('../../../../',import.meta.url))
const assetRoot=process.env.PPTX_VIEW_ASSET_ROOT??process.env.ASSET_ROOT??process.env.NATIVE_EDITOR_ASSET_ROOT
const source=!assetRoot,reopenFile=process.env.PPTX_PRINT_SOURCE_FILE
const output=process.env.PPTX_PRINT_DIRECTORY??'/tmp/office-slides-print-20261113/browser-01'
const port=Number(process.env.PPTX_PRINT_PORT??4581),origin=`http://127.0.0.1:${port}`,python=join(repo,'.venv/bin/python'),sha=bytes=>createHash('sha256').update(bytes).digest('hex')
await mkdir(resolve(output,'..'),{recursive:true});await mkdir(output)
let engine=process.env.PPTX_VIEW_ENGINE_ROOT??process.env.ENGINE_ROOT??process.env.AGENT_REPORTING_SLIDES_ENGINE_DIR
assert(source||engine,'冻结验收须指定 ENGINE_ROOT，不能重新构建引擎')
if(!engine){
 engine=join(output,'engine');await mkdir(join(engine,'dist'),{recursive:true})
 const root=join(repo,'smart_reporting/reporting/slides_engine')
 const result=spawnSync(join(root,'node_modules/.bin/esbuild'),['bridge/edit-pptx.ts','bridge/render-pptx.ts','--bundle','--platform=node','--format=esm','--loader:.md=text',`--outdir=${join(engine,'dist')}`,'--out-extension:.js=.mjs','--log-level=warning','--banner:js=import { createRequire } from "node:module"; const require = createRequire(import.meta.url);'],{cwd:root,encoding:'utf8'});assert.equal(result.status,0,result.stderr)
}
const bridgeIdentities={};for(const file of ['edit-pptx.mjs','render-pptx.mjs'])bridgeIdentities[file]=sha(await readFile(join(engine,'dist',file)))
let vite,staticRoot=assetRoot,manifest,nativeHtml
if(source){
 staticRoot=join(output,'source-assets');await mkdir(staticRoot);const {createServer}=await import('vite')
 vite=await createServer({root:frontend,configFile:join(frontend,'vite.config.ts'),server:{host:'127.0.0.1',port:port+1,strictPort:true,cors:true}});await vite.listen()
 await writeFile(join(staticRoot,'native.html'),(await readFile(join(frontend,'native.html'),'utf8')).replace('/src/unified-main.ts',`http://127.0.0.1:${port+1}/reports/v1/editor/assets/src/unified-main.ts`))
 for(const file of ['favicon.svg','favicon-32.png','apple-touch-icon.png'])await cp(join(frontend,'public',file),join(staticRoot,file))
}else{assert(staticRoot,'冻结验收须设置 ASSET_ROOT');manifest=await readFile(join(staticRoot,'.vite/manifest.json'));nativeHtml=await readFile(join(staticRoot,'native.html'));if((process.env.PPTX_VIEW_EXPECTED_MANIFEST_SHA256??process.env.PPTX_EXPECTED_MANIFEST_SHA256))assert.equal(sha(manifest),(process.env.PPTX_VIEW_EXPECTED_MANIFEST_SHA256??process.env.PPTX_EXPECTED_MANIFEST_SHA256))}
const server=spawn(python,[join(frontend,'smoke/pptx-outline-reading-server.py'),'--directory',output,'--port',String(port)],{cwd:repo,env:{...process.env,PYTHONPATH:repo,NATIVE_EDITOR_ASSET_ROOT:staticRoot,AGENT_REPORTING_SLIDES_ENGINE_DIR:engine},stdio:'pipe'})
let log='',browser,page,stage='server';server.stdout.on('data',data=>{log+=data});server.stderr.on('data',data=>{log+=data})
const errors=[],consoleErrors=[],httpErrors=[],assetReadWarnings=[],assetChecks=[],assets=new Map(),checkpoints=[]
try {
 for(let n=0;;n++){assert.equal(server.exitCode,null,log);try{if((await fetch(origin+'/__smoke__/state')).ok)break}catch{}assert(n<240,log);await delay(250)}
 const info=JSON.parse(await readFile(join(output,'server-info.json'),'utf8')),sourceBytes=await readFile(reopenFile??join(output,'source.pptx'))
 browser=await chromium.launch({headless:true,...(process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE?{executablePath:process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE}:{})});const context=await browser.newContext({viewport:{width:1600,height:1100},acceptDownloads:true,serviceWorkers:'block'});page=await context.newPage();const cdp=await context.newCDPSession(page);await cdp.send('Network.enable');await cdp.send('Network.setCacheDisabled',{cacheDisabled:true})
 page.on('pageerror',e=>errors.push(e.message));page.on('console',m=>{if(m.type()==='error')consoleErrors.push(m.text())})
 page.on('response',response=>{const url=new URL(response.url()),path=url.pathname,prefix='/reports/v1/editor/assets/';if(response.status()>=400)httpErrors.push({path,status:response.status()});const frozenAsset=!source&&url.origin===origin&&path.startsWith(prefix);if(response.ok()&&(frozenAsset||/\.(js|ts|tsx)$/.test(path)))assetChecks.push((async()=>{const bytes=await response.body(),actualSha256=sha(bytes);let diskSha256;if(frozenAsset){diskSha256=sha(await readFile(join(staticRoot,decodeURIComponent(path.slice(prefix.length)))));assert.equal(actualSha256,diskSha256,`冻结资源身份不一致: ${path}`)}assets.set(response.url(),{sha256:actualSha256,size:bytes.length,...(frozenAsset?{diskSha256,verifiedAgainstFrozenFile:true}:{})})})().catch(error=>{if(!source)throw error;assetReadWarnings.push({url:response.url(),error:String(error)})}))})
 stage='real-import';const imported=await context.request.post(origin+'/reports/v1/native/import',{headers:{'X-Workspace-Thread':info.thread,'X-Workspace-Capability':info.capability},multipart:{requestId:'print-browser-import',file:{name:'outline-reading-source.pptx',mimeType:'application/vnd.openxmlformats-officedocument.presentationml.presentation',buffer:sourceBytes}}});assert.equal(imported.status(),200,await imported.text());const registration=await imported.json();await writeFile(join(output,'import-receipt.json'),JSON.stringify(registration,null,2));const opened=await page.goto(origin+registration.editor.url);if(!source)assert.equal(sha(await opened.body()),sha(nativeHtml),'实际native入口HTML身份不一致')

 const ready=async()=>{await page.waitForFunction(()=>document.querySelector('#report-editor')?.getAttribute('aria-busy')==='false',null,{timeout:120000});await page.locator('.slides-canvas canvas').first().waitFor({timeout:90000})};await ready()
 const operations=()=>page.evaluate(()=>{const key=Object.keys(localStorage).find(key=>key.startsWith('native-editor-draft:'));return key?JSON.parse(localStorage.getItem(key)).operations:[]})
 const initial=await operations();assert.deepEqual(initial,[])
 stage='native-print-open';await page.locator('[data-ribbon-tab=file]').click();const entry=page.locator('[data-command=print]');assert.equal(await entry.isEnabled(),true);await entry.click()
 const dialog=page.locator('.slides-print-dialog');await dialog.waitFor();await page.waitForFunction(()=>document.querySelector('.slides-print-dialog [role=status]')?.textContent?.includes('2 张'),null,{timeout:120000})
 const preview=page.frameLocator('.slides-print-body>iframe');await preview.locator('.page img').first().waitFor();assert.equal(await preview.locator('.page img').count(),2)
 await preview.locator('.page img').first().evaluate(async img=>{if(!img.complete)await new Promise((resolve,reject)=>{img.onload=resolve;img.onerror=reject});if(!img.naturalWidth)throw Error('no raster')})
 const srcs=await preview.locator('.page img').evaluateAll(images=>images.map(img=>img.src));for(let i=0;i<srcs.length;i++)await writeFile(join(output,`slide-${i}.png`),Buffer.from(srcs[i].split(',')[1],'base64'))
 await page.waitForFunction(()=>Number(document.querySelector('.slides-print-body>iframe').contentDocument.body.style.zoom)>0);assert(await preview.locator('.page').first().evaluate(el=>el.getBoundingClientRect().width<window.innerWidth));await page.screenshot({path:join(output,'print-full.png'),fullPage:true})
 stage='range-layout-notes';await dialog.getByLabel('打印隐藏幻灯片',{exact:true}).check();await page.waitForFunction(()=>document.querySelector('.slides-print-dialog [role=status]')?.textContent?.includes('3 张'))
 await dialog.getByLabel('打印布局',{exact:true}).selectOption('handout3');await preview.locator('.page.handout.h3').waitFor();assert.equal(await preview.locator('.rules').count(),3)
 await dialog.getByLabel('纸张方向',{exact:true}).selectOption('landscape');assert((await page.locator('.slides-print-body>iframe').getAttribute('srcdoc')).includes('size: 11.69in 8.27in'))
 await page.screenshot({path:join(output,'print-handout.png'),fullPage:true})
 for(const [layout,selector,pages]of [['handout2','.page.handout.h2',2],['handout6','.page.handout.h6',1]]){
  await dialog.getByLabel('打印布局',{exact:true}).selectOption(layout);await preview.locator(selector).first().waitFor();assert.equal(await preview.locator(selector).count(),pages);assert.equal(await preview.locator('.page img').count(),3)
  await page.screenshot({path:join(output,`print-${layout}.png`),fullPage:true})
 }
 await dialog.getByLabel('打印范围',{exact:true}).selectOption('custom');await dialog.getByLabel('打印页码',{exact:true}).fill('3-1');assert.equal(await dialog.locator('[data-slides-print-confirm]').isEnabled(),false);assert.match(await dialog.locator('[role=alert]').textContent(),/页码/)
 await dialog.getByLabel('打印页码',{exact:true}).fill('3');await dialog.getByLabel('打印布局',{exact:true}).selectOption('notes');await preview.locator('.page.notes').waitFor();assert.equal(await preview.locator('.note').textContent(),'空白页讲稿')
 await page.screenshot({path:join(output,'print-notes.png'),fullPage:true})
 stage='system-print-iframe';await context.addInitScript(()=>{window.print=function(){document.documentElement.dataset.printCalled='true'}})
 await dialog.locator('[data-slides-print-confirm]').click();const job=page.frameLocator('[data-slides-print-job]');await job.locator('html[data-print-called=true]').waitFor({timeout:30000});assert.equal(await job.locator('.page.notes').count(),1)
 assert.equal(await job.locator('.note').textContent(),'空白页讲稿');assert(!(await page.locator('[data-slides-print-job]').getAttribute('srcdoc')).includes('counter-reset: pg'))
 const printableHtml=await page.locator('[data-slides-print-job]').getAttribute('srcdoc');await writeFile(join(output,'printed.html'),printableHtml);const pdfPage=await context.newPage();await pdfPage.setContent(printableHtml,{waitUntil:'load'});await pdfPage.pdf({path:join(output,'printed.pdf'),preferCSSPageSize:true,printBackground:true});await pdfPage.close()
 stage='mobile-layout';await page.setViewportSize({width:390,height:844});await page.waitForFunction(()=>{const f=document.querySelector('.slides-print-body>iframe'),p=f.contentDocument.querySelector('.page');return p&&p.getBoundingClientRect().width<f.clientWidth});await page.screenshot({path:join(output,'print-mobile.png'),fullPage:true});assert.equal(await dialog.evaluate(el=>el.scrollWidth<=el.clientWidth),true)
 await dialog.getByRole('button',{name:'取消',exact:true}).click();assert.equal(await dialog.count(),0);assert.deepEqual(await operations(),initial)
 stage='keyboard-print';for(const shortcut of ['Control+p','Meta+p']){
  await entry.focus();await page.keyboard.press(shortcut);await dialog.waitFor();await page.waitForFunction(()=>document.querySelector('.slides-print-dialog [role=status]')?.textContent?.includes('2 张'),null,{timeout:120000})
  assert.equal(await preview.locator('.page img').count(),2);await dialog.getByRole('button',{name:'取消',exact:true}).click();assert.equal(await dialog.count(),0)
 }
 assert.deepEqual(await operations(),initial)
 stage='unsaved-draft-notes';await page.setViewportSize({width:1600,height:1100});const notes=page.locator('[data-notes-text]'),originalNotes=await notes.inputValue(),pendingNote='尚未保存的打印备注'
 await notes.fill(pendingNote);const pending=await operations();assert(pending.length>0);assert(JSON.stringify(pending).includes(pendingNote));await notes.focus();await page.keyboard.press('Control+p');await dialog.waitFor();await page.waitForFunction(()=>document.querySelector('.slides-print-dialog [role=status]')?.textContent?.includes('2 张'),null,{timeout:120000})
 await dialog.getByLabel('打印范围',{exact:true}).selectOption('current');await dialog.getByLabel('打印布局',{exact:true}).selectOption('notes');await preview.locator('.page.notes').waitFor();assert.equal(await preview.locator('.note').textContent(),pendingNote);await page.screenshot({path:join(output,'print-draft-notes.png'),fullPage:true})
 await dialog.getByRole('button',{name:'取消',exact:true}).click();assert.deepEqual(await operations(),pending);await page.locator('[data-source-action=onUndo]').click();assert.deepEqual(await operations(),initial);assert.equal(await notes.inputValue(),originalNotes)
 const state=await(await fetch(origin+'/__smoke__/state')).json();assert.equal(state.completedRevisions,0);assert.equal(state.requests.filter(r=>r.path.endsWith('/save')).length,0);await Promise.all(assetChecks);assert.deepEqual(errors,[]);assert.deepEqual(consoleErrors,[]);assert.deepEqual(httpErrors,[])
 await writeFile(join(output,'summary.json'),JSON.stringify({ok:true,source,bridgeIdentities,inputSha256:sha(sourceBytes),snapshotIsReadOnly:true,unsavedDraftNotes:true,layouts:['full','handout2','handout3','handout6','notes'],rangeAndHidden:true,keyboardShortcuts:['Control+p','Meta+p'],systemPrintStubbed:true,actualRaster:true,assetReadWarnings,assets:Object.fromEntries(assets),errors,consoleErrors,httpErrors},null,2));console.log(JSON.stringify({ok:true,output,source,assets:assets.size}))
}catch(error){await page?.screenshot({path:join(output,'failure.png'),fullPage:true}).catch(()=>{});if(page)await writeFile(join(output,'failure.html'),await page.content()).catch(()=>{});await writeFile(join(output,'failure.json'),JSON.stringify({stage,error:String(error),stack:error.stack,errors,consoleErrors,httpErrors},null,2));throw error}
finally{await browser?.close();server.kill();await vite?.close();await writeFile(join(output,'server.log'),log)}
