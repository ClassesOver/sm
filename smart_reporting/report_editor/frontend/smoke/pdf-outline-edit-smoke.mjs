import assert from 'node:assert/strict'
import {spawn,spawnSync} from 'node:child_process'
import {createHash} from 'node:crypto'
import {cp,mkdir,readFile,symlink,writeFile} from 'node:fs/promises'
import {join,resolve,sep} from 'node:path'
import {fileURLToPath} from 'node:url'
import {setTimeout as delay} from 'node:timers/promises'
import {chromium} from 'playwright'
import {createServer} from 'vite'

const frontend=fileURLToPath(new URL('../',import.meta.url)),repo=fileURLToPath(new URL('../../../../',import.meta.url))
const output=process.env.PDF_OUTLINE_EDIT_OUTPUT??'/tmp/office-pdf-outline-edit-20261113/browser-source'
const port=Number(process.env.PDF_OUTLINE_EDIT_PORT??4396),origin=`http://127.0.0.1:${port}`,sha=bytes=>createHash('sha256').update(bytes).digest('hex')
await mkdir(output,{recursive:true})
const frozen=Boolean(process.env.PDF_OUTLINE_EDIT_STATIC),staticRoot=frozen?resolve(process.env.PDF_OUTLINE_EDIT_STATIC):join(output,'static')
const suppliedEngine=process.env.PDF_OUTLINE_EDIT_ENGINE??process.env.AGENT_REPORTING_PDF_ENGINE_DIR
const engineRoot=suppliedEngine?resolve(suppliedEngine):join(output,'engine-source'),engine=join(repo,'smart_reporting/reporting/pdf_engine')
const worker='node_modules/pdfjs-dist/legacy/build/pdf.worker.min.mjs'
let vite
if(!frozen){
 await cp('/tmp/office-four-format-source-increment-20261113/static',staticRoot,{recursive:true,errorOnExist:true,force:false})
 await mkdir(join(staticRoot,'node_modules/pdfjs-dist/legacy/build'),{recursive:true})
 await cp(join(frontend,worker),join(staticRoot,worker))
 vite=await createServer({root:frontend,configFile:join(frontend,'vite.config.ts'),server:{host:'127.0.0.1',port:port+1,strictPort:true,cors:true}})
 await vite.listen()
 const html=(await readFile(join(frontend,'native.html'),'utf8')).replace('/src/unified-main.ts',`http://127.0.0.1:${port+1}/reports/v1/editor/assets/src/unified-main.ts`)
 await writeFile(join(staticRoot,'native.html'),html)
}
if(!suppliedEngine){await mkdir(engineRoot);for(const name of ['bridge','src','vendor','node_modules','package.json'])await symlink(join(engine,name),join(engineRoot,name))}
const sourceModuleHashes={}
for(const file of ['pdf-main.ts','pdf-outline-edit.ts','pdf-outline-edit.css','pdf-operations.ts'])sourceModuleHashes[file]=sha(await readFile(join(frontend,'src',file)))
sourceModuleHashes[worker]=sha(await readFile(join(frontend,worker)))
const server=spawn(join(repo,'.venv/bin/python'),[join(frontend,'smoke/pdf-outline-edit-server.py'),'--directory',output,'--port',String(port)],{cwd:repo,env:{...process.env,PYTHONPATH:repo,PDF_SMOKE_STATIC_DIRECTORY:staticRoot,AGENT_REPORTING_PDF_ENGINE_DIR:engineRoot},stdio:'pipe'})
let log='',browser,page,stage='server';server.stdout.on('data',bytes=>{log+=bytes});server.stderr.on('data',bytes=>{log+=bytes})
const errors=[],consoleErrors=[],httpErrors=[],resourceChecks=[],resourceTasks=[]
const resourceEvidence=async()=>{
 await Promise.all(resourceTasks)
 if(frozen){assert(resourceChecks.some(item=>item.path.endsWith('.js')),'未加载冻结 JavaScript 资源');assert(resourceChecks.every(item=>item.matches),JSON.stringify(resourceChecks))}
 return {mode:frozen?'frozen-static':'source-vite',staticRoot,engineRoot,resources:resourceChecks}
}
try{
 for(let i=0;;i++){assert.equal(server.exitCode,null,log);try{if((await fetch(origin+'/__smoke__/state')).ok)break}catch{}assert(i<240,log);await delay(250)}
 const info=JSON.parse(await readFile(join(output,'server-info.json'),'utf8'))
 browser=await chromium.launch({headless:true});page=await browser.newPage({viewport:{width:1440,height:900}})
 if(frozen){const cdp=await page.context().newCDPSession(page);await cdp.send('Network.enable');await cdp.send('Network.setCacheDisabled',{cacheDisabled:true})}
 page.on('pageerror',error=>errors.push(error.message));page.on('console',entry=>{if(entry.type()==='error')consoleErrors.push(entry.text())});page.on('response',response=>{if(response.status()>=400)httpErrors.push({path:new URL(response.url()).pathname,status:response.status()})})
 if(frozen)page.on('response',response=>{
  const url=new URL(response.url()),prefix='/reports/v1/editor/assets/'
  if(url.origin!==origin||!url.pathname.startsWith(prefix)||response.status()!==200)return
  resourceTasks.push((async()=>{
   const relative=decodeURIComponent(url.pathname.slice(prefix.length)),path=resolve(staticRoot,relative)
   assert(path.startsWith(staticRoot+sep),'静态资源路径越界')
   const actualSha256=sha(await response.body()),fileSha256=sha(await readFile(path))
   resourceChecks.push({path:url.pathname,actualSha256,fileSha256,matches:actualSha256===fileSha256})
  })().catch(error=>{resourceChecks.push({path:url.pathname,matches:false,error:String(error)})}))
 })
 const ready=()=>page.waitForFunction(()=>document.querySelector('#report-editor')?.getAttribute('aria-busy')==='false',null,{timeout:120000})
 const operations=()=>page.evaluate(()=>JSON.parse(Object.entries(localStorage).find(([key])=>key.startsWith('native-editor-draft:'))?.[1]??'{}').operations??[])
 const settle=()=>page.waitForFunction(()=>document.querySelector('#report-editor')?.getAttribute('aria-busy')==='false'&&document.querySelector('.pdf-page-content canvas'),null,{timeout:60000})
 const rename=async(path,value)=>{await page.locator(`[data-outline-rename="${path}"]`).click();await page.getByRole('textbox',{name:'书签名称',exact:true}).fill(value);await page.getByRole('textbox',{name:'书签名称',exact:true}).press('Enter');await settle()}
 const goTo=async number=>{await page.locator('[data-pdf-ribbon-tab="view"]').click();await page.locator('[data-source-command-id="genoffice.pdf.view.pageZoom.goToPage"]').fill(String(number));await page.locator('[data-source-command-id="genoffice.pdf.view.pageZoom.goToPage"]').press('Enter')}
 const command=async id=>{await page.locator('[data-pdf-ribbon-tab="page"]').click();await page.locator(`[data-source-command-id="genoffice.pdf.page.${id}"]`).click();await settle()}
 await page.goto(origin+info.openPath);await ready();await settle()
 stage='outline';await page.locator('[data-pdf-ribbon-tab="view"]').click();await page.locator('[data-source-command-id="genoffice.pdf.view.navigation.outline"]').click()
 await page.getByRole('button',{name:'编辑书签',exact:true}).click();assert.deepEqual(await operations(),[])
 stage='rename-delete';await rename('0','修订书签');await page.locator('[data-outline-delete="0.0"]').click();await settle()
 stage='add';await goTo(2);await page.locator('[data-outline-add]').click();await settle();await rename('2','Second renewed')
 const renamed=await operations();assert.equal(renamed[0].tree[0].children.length,0)
 stage='undo-redo';await page.locator('[data-pdf-ribbon-tab="home"]').click();await page.locator('[data-source-command-id="genoffice.pdf.home.edit.undo"]').click();await settle();assert.equal((await operations())[0].tree[2].title,'新书签')
 await page.locator('[data-source-command-id="genoffice.pdf.home.edit.redo"]').click();await settle();assert.deepEqual(await operations(),renamed)
 stage='page-composition';await command('reverse');await command('insertBlank');await page.locator('[data-outline-add]').click();await settle();await rename('3','Blank')
 await page.locator('[data-outline-page]').filter({hasText:'Last'}).click();await command('delete')
 const staged=await operations();assert(staged.some(op=>op.kind==='setOutline'));assert(staged.some(op=>op.kind==='insertBlankPage'));assert(staged.some(op=>op.kind==='deletePage'));assert(staged.some(op=>op.kind==='reorderPages'))
 stage='desktop';await page.screenshot({path:join(output,'outline-desktop.png'),fullPage:true})
 stage='narrow';await page.setViewportSize({width:390,height:700});await page.screenshot({path:join(output,'outline-narrow.png'),fullPage:true})
 const layout=await page.locator('.pdf-outline').evaluate(panel=>({clientWidth:panel.clientWidth,scrollWidth:panel.scrollWidth,buttons:[...panel.querySelectorAll('button')].filter(button=>!button.hidden).map(button=>({text:button.textContent,width:button.getBoundingClientRect().width}))}))
 assert(layout.scrollWidth<=layout.clientWidth+1,JSON.stringify(layout))
 await page.setViewportSize({width:1440,height:900})
 if(process.env.PDF_OUTLINE_EDIT_MINIMAL==='1'){
  assert.deepEqual(errors,[]);assert.deepEqual(consoleErrors,[]);assert.deepEqual(httpErrors,[])
  const state=await(await fetch(origin+'/__smoke__/state')).json();assert.equal(state.savedRevisions,0)
  const assets=await resourceEvidence()
  await writeFile(join(output,'minimal-evidence.json'),JSON.stringify({ok:true,layer:`minimal real native HTTP ${assets.mode} entry + edit controls/UndoRedo/page composition + desktop/narrow visual checks; no save/download rerun`,assets,sourceModuleHashes,sourceSha256:info.sourceSha256,staged,layout,errors,consoleErrors,httpErrors},null,2))
  console.log(JSON.stringify({ok:true,output,minimal:true}))
 }else{
 stage='restore';await page.reload();await ready();await settle();assert.deepEqual(await operations(),staged)
 await page.locator('[data-pdf-ribbon-tab="view"]').click();await page.locator('[data-source-command-id="genoffice.pdf.view.navigation.outline"]').click()
 assert.deepEqual(await page.locator('[data-outline-page]').allTextContents(),['修订书签','Second renewed','Blank'])
 stage='preview';await page.locator('[data-pdf-ribbon-tab="edit"]').click();const previewing=page.waitForResponse(response=>response.url().endsWith('/api/preview')&&response.request().method()==='POST'&&response.request().postDataJSON().operations.length>0)
 await page.getByRole('button',{name:'校验当前修改',exact:true}).click();const preview=await(await previewing).json()
 assert.deepEqual(preview.skippedOperations,[]);assert.deepEqual(preview.appliedOperationIndices,staged.map((_,i)=>i));assert.deepEqual(preview.reviewIssues,[])
 await page.waitForFunction(()=>document.querySelector('[data-pdf-preview="true"]')&&[...document.querySelectorAll('button')].some(button=>button.textContent.includes('返回原稿编辑')&&!button.disabled),null,{timeout:60000})
 await page.getByRole('button',{name:'返回原稿编辑',exact:true}).click()
 await page.waitForFunction(()=>document.querySelector('[data-pdf-preview="false"]')&&[...document.querySelectorAll('button')].some(button=>button.textContent.includes('校验当前修改')&&!button.disabled),null,{timeout:60000})
 stage='save';const saving=page.waitForResponse(response=>response.url().endsWith('/api/save')&&response.request().method()==='POST');await page.locator('[data-action="save"]').click()
 const savedResponse=await saving,saved=await savedResponse.json();assert.equal(savedResponse.status(),200,JSON.stringify(saved));assert.equal(saved.revisionRegistered,true);assert.equal(saved.revision,5);assert.equal(saved.parentRevision,4);assert.deepEqual(savedResponse.request().postDataJSON().operations,staged)
 stage='download';const link=page.locator('.native-delivery a').filter({hasText:'下载 PDF'});await link.waitFor();assert.equal(await link.getAttribute('href'),saved.artifacts.pdf.downloadUrl)
 const downloading=page.waitForEvent('download');await link.click();const download=await downloading;assert.equal(await download.failure(),null);const bytes=await readFile(await download.path());assert.equal(sha(bytes),saved.artifacts.pdf.sha256);assert.equal(bytes.length,saved.artifacts.pdf.size);await writeFile(join(output,'downloaded.pdf'),bytes)
 stage='revision-reopen';await page.goto(saved.editor.openUrl);await ready();await settle();await page.locator('[data-pdf-ribbon-tab="view"]').click();await page.locator('[data-source-command-id="genoffice.pdf.view.navigation.outline"]').click()
 assert.deepEqual(await page.locator('.pdf-outline-link').allTextContents(),['修订书签','Second renewed','Blank'])
 await page.locator('.pdf-outline-link').filter({hasText:'修订书签'}).click();assert.match(await page.locator('.pdf-page.is-active .pdf-page-label').innerText(),/^第 3 页/)
 const state=await(await fetch(origin+'/__smoke__/state')).json();assert.equal(state.sourceSha256,info.sourceSha256);assert.equal(state.savedRevisions,1)
 assert.deepEqual(errors,[]);assert.deepEqual(consoleErrors,[]);assert.deepEqual(httpErrors,[])
 await page.screenshot({path:join(output,'outline-reopened.png'),fullPage:true})
 const assets=await resourceEvidence()
 await writeFile(join(output,'evidence.json'),JSON.stringify({ok:true,layer:`real native HTTP + ${assets.mode} + isolated engine`,assets,sourceModuleHashes,sourceSha256:info.sourceSha256,staged,preview,saved,layout,errors,consoleErrors,httpErrors,requests:state.requests},null,2))
 const independent=spawnSync(join(repo,'.venv/bin/python'),[join(frontend,'smoke/pdf-outline-edit-verify.py'),output],{encoding:'utf8'});assert.equal(independent.status,0,independent.stderr||independent.stdout)
 console.log(JSON.stringify({ok:true,output,independent:JSON.parse(independent.stdout)}))
 }
}catch(error){await page?.screenshot({path:join(output,'failure.png'),fullPage:true}).catch(()=>{});await writeFile(join(output,'failure.json'),JSON.stringify({stage,error:String(error),errors,consoleErrors,httpErrors},null,2));throw error}
finally{await browser?.close();server.kill();await vite?.close();await writeFile(join(output,'server.log'),log);if(server.exitCode===null)await Promise.race([new Promise(resolve=>server.once('exit',resolve)),delay(5000)]);if(server.exitCode===null)server.kill('SIGKILL')}
