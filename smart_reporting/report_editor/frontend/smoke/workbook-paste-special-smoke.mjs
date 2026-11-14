import assert from 'node:assert/strict'
import { spawn, spawnSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import { mkdir, readFile, writeFile } from 'node:fs/promises'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { setTimeout as delay } from 'node:timers/promises'
import { once } from 'node:events'
import { chromium } from 'playwright'
const frontend=fileURLToPath(new URL('../',import.meta.url)),repo=fileURLToPath(new URL('../../../../',import.meta.url))
const out=process.env.PASTE_SPECIAL_OUT;assert(out);await mkdir(out,{recursive:false})
const sourceFrontend=process.env.PASTE_SPECIAL_FRONTEND??frontend
const dev=process.env.PASTE_SPECIAL_DEV==='1',port=Number(process.env.PASTE_SPECIAL_PORT??4493),vitePort=port+1
const api=`http://127.0.0.1:${port}`,origin=dev?`http://127.0.0.1:${vitePort}`:api
const sha=b=>createHash('sha256').update(b).digest('hex')
const fixture=spawnSync(join(repo,'.venv/bin/python'),[join(frontend,'smoke/workbook-paste-special-verify.py'),out,'--fixture'],{cwd:repo,encoding:'utf8'});assert.equal(fixture.status,0,fixture.stderr)
const files=['smart_reporting/report_editor/native_office.py','smart_reporting/report_editor/native_api.py','smart_reporting/reporting/workbook_engine/packages/xlsx-engine/src/style-read.ts']
const before=await Promise.all(files.map(async path=>({path,sha256:sha(await readFile(join(repo,path)))})))
await writeFile(join(out,'runtime-wrapper-before.json'),JSON.stringify(before,null,2))
const manifestPath=process.env.PDF_SMOKE_STATIC_DIRECTORY?join(process.env.PDF_SMOKE_STATIC_DIRECTORY,'.vite/manifest.json'):null,manifestBefore=manifestPath?sha(await readFile(manifestPath)):null
const enginePath=join(process.env.AGENT_REPORTING_WORKBOOK_ENGINE_DIR,'dist/cli.mjs'),engineBefore=sha(await readFile(enginePath))
await writeFile(join(out,'runtime-engine-before.json'),JSON.stringify({path:enginePath,sha256:engineBefore},null,2))
const server=spawn(join(repo,'.venv/bin/python'),[join(frontend,'smoke/workbook-ai-charts-server.py'),'--directory',out,'--port',String(port),'--source',join(out,'fixture.xlsx')],{cwd:repo,env:{...process.env,PYTHONPATH:repo},stdio:'pipe'})
let log='',viteLog='',vite,browser,page,stage='server';const errors=[],consoleErrors=[],assets=new Map(),assetFailures=[],pending=[],checks=[]
server.stdout.on('data',b=>{log+=b});server.stderr.on('data',b=>{log+=b})
try{
 for(let n=0;;n++){assert.equal(server.exitCode,null,log);try{if((await fetch(api+'/__smoke__/state')).ok)break}catch{}assert(n<240,log);await delay(250)}
 const info=JSON.parse(await readFile(join(out,'server-info.json'),'utf8'))
 if(dev){
  const code=`import {createServer} from 'vite';const s=await createServer({root:${JSON.stringify(sourceFrontend)},cacheDir:${JSON.stringify(join(out,'vite-cache'))},server:{host:'127.0.0.1',port:${vitePort},strictPort:true,proxy:{'^/reports/v1/(?!editor/assets/)':{target:${JSON.stringify(api)},changeOrigin:true,configure(p){p.on('proxyReq',r=>{r.setHeader('origin',${JSON.stringify(api)})})}}}}});await s.listen()`
  vite=spawn(process.execPath,['--input-type=module','-e',code],{cwd:sourceFrontend});vite.stdout.on('data',b=>{viteLog+=b});vite.stderr.on('data',b=>{viteLog+=b})
  for(let n=0;;n++){assert.equal(vite.exitCode,null,viteLog);try{if((await fetch(origin+'/reports/v1/editor/assets/native.html')).ok)break}catch{}assert(n<240,viteLog);await delay(250)}
 }
 browser=await chromium.launch({headless:true});page=await browser.newPage({viewport:{width:1440,height:900},acceptDownloads:true,permissions:['clipboard-read','clipboard-write']})
 page.setDefaultTimeout(15000);page.setDefaultNavigationTimeout(60000)
 page.on('pageerror',error=>errors.push(error.message));page.on('console',message=>{if(message.type()==='error')consoleErrors.push(message.text())})
 if(!dev)await page.route('**/reports/v1/editor/assets/**',async route=>{
  const path=new URL(route.request().url()).pathname
  try{
   const response=await route.fetch(),actual=await response.body(),disk=await readFile(join(process.env.PDF_SMOKE_STATIC_DIRECTORY,decodeURIComponent(path.slice('/reports/v1/editor/assets/'.length))))
   assert.equal(response.status(),200);assert.equal(sha(actual),sha(disk));assets.set(path,sha(actual))
   await route.fulfill({response,body:actual})
  }catch(error){assetFailures.push({path,error:String(error)});await route.abort()}
 })
 let nativePath=info.openPath
 if(dev){const grant=await page.request.get(origin+info.openPath,{maxRedirects:0});assert.equal(grant.status(),303);nativePath=grant.headers()['location'];await page.route('**/reports/v1/native/**',async route=>{if(!route.request().isNavigationRequest()||new URL(route.request().url()).pathname.includes('/native/artifacts/'))return route.continue();const response=await page.request.get(origin+'/reports/v1/editor/assets/native.html');await route.fulfill({response,body:await response.body()})})}
 const ready=()=>page.waitForFunction(()=>document.querySelector('#report-editor')?.getAttribute('aria-busy')==='false',null,{timeout:90000})
 const draft=()=>page.evaluate(()=>Object.entries(localStorage).filter(([key])=>key.startsWith('native-editor-draft:')).flatMap(([,v])=>JSON.parse(v).operations??[]))
 const select=async text=>{const box=page.locator('[data-u-comp="defined-name"] input');await box.fill(text);await box.press('Enter')}
 const home=()=>page.locator('[data-ribbon-tab=Home]').click()
 const open=async()=>{await home();await page.locator('[data-ribbon-menu=paste-special]').selectOption('paste-special-open');await page.getByRole('dialog',{name:'选择性粘贴',exact:true}).waitFor()}
 const dialog=()=>page.getByRole('dialog',{name:'选择性粘贴',exact:true})
 const copy=async range=>{await select(range);await home();await page.locator('[data-ribbon-command=copy]').click();await delay(150)}
 const apply=async()=>{await dialog().getByRole('button',{name:'确定',exact:true}).click();await page.waitForFunction(()=>document.querySelector('.workbook-paste-special-overlay')?.hasAttribute('hidden'),null,{timeout:15000});await delay(200)}
 const type=value=>dialog().locator('input[name=paste-special-type][value='+value+']').check()
 stage='open';await page.goto(origin+nativePath);await ready()
 if(process.env.PASTE_SPECIAL_CONTROLS_ONLY==='1'){
 stage='controls';await copy('A1:B2');await select('P1');await page.keyboard.press('Escape');await page.keyboard.press('Control+Alt+v');await dialog().waitFor();await dialog().getByRole('button',{name:'取消',exact:true}).click()
 const canvas=page.locator('#workbook-grid canvas[id^=univer-sheet-main-canvas]').first();await canvas.click({position:{x:130,y:90},button:'right'});await page.getByText('选择性粘贴…',{exact:true}).last().click();await dialog().waitFor();await page.screenshot({path:join(out,'context-menu-opened.png')});await dialog().getByRole('button',{name:'取消',exact:true}).click();assert.deepEqual(await draft(),[])
 const state=await(await fetch(api+'/__smoke__/state')).json();assert.equal(state.savedRevisions,0);assert.equal(state.plannerCalls,0);await writeFile(join(out,'controls-evidence.json'),JSON.stringify({ok:true,sourceSha256:info.sourceSha256,state,ctrlAltV:true,nativeContextMenu:true},null,2));console.log(JSON.stringify({ok:true,controlsOnly:true}))
 }else{
 stage='viewport';await copy('A1:B2');const baseline=await draft()
 for(const [width,height]of [[1440,900],[1024,480],[390,844]]){
 await page.setViewportSize({width,height});await select('P1');await open();assert.equal(await dialog().locator('input[name=paste-special-type]').count(),12);assert.equal(await dialog().locator('input[name=paste-special-operation]').count(),5);assert(await dialog().locator('input[value=comments]').isDisabled());assert(await dialog().locator('input[value=validation]').isDisabled())
 if(width===1024){const body=dialog().locator('.workbook-paste-special-body');await body.hover();await page.mouse.wheel(0,450);await delay(120);assert(await body.evaluate(node=>node.scrollTop>0),'low-height dialog must actually scroll')}
 const hit=await dialog().getByRole('button',{name:'确定',exact:true}).evaluate(node=>{const r=node.getBoundingClientRect();return r.x>=0&&r.y>=0&&r.right<=innerWidth&&r.bottom<=innerHeight&&node.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2))});assert(hit);checks.push({width,height,actualActionHit:hit});await page.screenshot({path:join(out,'dialog-'+width+'x'+height+'.png')});await dialog().getByRole('button',{name:'取消',exact:true}).click();assert.deepEqual(await draft(),baseline)
 }
 stage='shortcut-context';await page.setViewportSize({width:1440,height:900});await select('P1');await page.keyboard.press('Escape');await page.keyboard.press('Control+Alt+v');await dialog().waitFor();await dialog().getByRole('button',{name:'取消',exact:true}).click();await page.locator('#workbook-grid canvas[id^=univer-sheet-main-canvas]').first().click({position:{x:130,y:90},button:'right'});await page.getByText('选择性粘贴…',{exact:true}).last().click();await dialog().waitFor();await dialog().getByRole('button',{name:'取消',exact:true}).click();assert.deepEqual(await draft(),baseline)
 stage='operation';await page.setViewportSize({width:1440,height:900});await select('D4:E5');await open();await type('values');await dialog().locator('input[value=add]').check();await apply();const added=await draft();assert.notDeepEqual(added,baseline)
 await page.locator('[data-ribbon-tab=File]').click();await page.locator('[data-ribbon-command=undo]').click();await delay(200);assert.deepEqual(await draft(),baseline);await page.locator('[data-ribbon-command=redo]').click();await delay(200);assert.deepEqual(await draft(),added)
 stage='transpose';await copy('A1:B2');await select('G1');await open();await type('values');await dialog().getByLabel('转置',{exact:true}).check();await apply()
 stage='number-format';await copy('A1');await select('J1');await open();await type('values-numfmt');await dialog().getByLabel('跳过空单元',{exact:true}).check();await apply()
 stage='link';await select('L1');await open();await dialog().getByRole('button',{name:'粘贴链接',exact:true}).click();await page.waitForFunction(()=>document.querySelector('.workbook-paste-special-overlay')?.hasAttribute('hidden'),null,{timeout:15000});await delay(200)
 stage='official-paste-values';await copy('A1');await select('P1');await open();await type('values');await apply()
 const adopted=await draft();assert(adopted.length>0);stage='draft-reload';await page.reload();await ready();assert.deepEqual(await draft(),adopted)
 stage='save';const waiting=page.waitForResponse(r=>r.url().endsWith('/api/save')&&r.request().method()==='POST');await page.locator('[data-action=save]').click();const response=await waiting,saved=await response.json();assert.equal(response.status(),200,JSON.stringify(saved));assert.equal(saved.revisionRegistered,true);assert.equal(saved.revision,info.context.revision+1)
 await writeFile(join(out,'save-request.json'),JSON.stringify(response.request().postDataJSON(),null,2));await writeFile(join(out,'save-response.json'),JSON.stringify(saved,null,2))
 const [download]=await Promise.all([page.waitForEvent('download'),page.locator('[data-action=xlsx-download]').click()]);await download.saveAs(join(out,'paste-special.xlsx'));assert.equal(sha(await readFile(join(out,'paste-special.xlsx'))),saved.artifacts.xlsx.sha256)
 const verify=spawnSync(join(repo,'.venv/bin/python'),[join(frontend,'smoke/workbook-paste-special-verify.py'),out],{cwd:repo,encoding:'utf8'});assert.equal(verify.status,0,verify.stderr||verify.stdout)
 stage='reopen';if(dev){const grant=await page.request.get(saved.editor.openUrl.replace(api,origin),{maxRedirects:0});assert.equal(grant.status(),303);await page.goto(origin+grant.headers()['location'])}else await page.goto(saved.editor.openUrl);await ready();const reopened=await page.request.get(page.url()+'/api/file');assert.equal(sha(await reopened.body()),saved.artifacts.xlsx.sha256);await select('D4:E5');await copy('A1');await select('P1');await open();await page.screenshot({path:join(out,'reopened.png')});await dialog().getByRole('button',{name:'取消',exact:true}).click()
 const state=await(await fetch(api+'/__smoke__/state')).json();assert.equal(state.sourceSha256,info.sourceSha256);assert.equal(state.savedRevisions,1);assert.equal(state.plannerCalls,0);await Promise.all(pending);assert.deepEqual(assetFailures,[]);assert.deepEqual(errors,[]);if(manifestPath)assert.equal(sha(await readFile(manifestPath)),manifestBefore);const after=await Promise.all(files.map(async path=>({path,sha256:sha(await readFile(join(repo,path)))})));assert.deepEqual(after,before);assert.equal(sha(await readFile(enginePath)),engineBefore)
 await writeFile(join(out,'evidence.json'),JSON.stringify({ok:true,dev,checks,adopted,state,manifestSha256:manifestBefore,runtimeWrapperBefore:before,runtimeWrapperAfter:after,sourceSha256:info.sourceSha256,savedSha256:saved.artifacts.xlsx.sha256,reopenedUrl:page.url(),independentReadback:JSON.parse(verify.stdout),actualStaticAssets:[...assets],browserErrors:errors,consoleErrors},null,2));console.log(JSON.stringify({ok:true,dev,checks:checks.length,downloadSha256:saved.artifacts.xlsx.sha256}))
 }
}catch(error){await page?.screenshot({path:join(out,'failure.png')}).catch(()=>{});await writeFile(join(out,'failure.json'),JSON.stringify({stage,error:String(error),stack:error.stack,errors,assetFailures,actualStaticAssets:[...assets],consoleErrors,feedback:await page?.locator('.workbook-feedback').innerText().catch(()=>null),dialog:await page?.locator('.workbook-paste-special-overlay').innerText().catch(()=>null)},null,2));throw error}
finally{await writeFile(join(out,'runtime-wrapper-after.json'),JSON.stringify(await Promise.all(files.map(async path=>({path,sha256:sha(await readFile(join(repo,path)))}))),null,2));await writeFile(join(out,'runtime-engine-after.json'),JSON.stringify({path:enginePath,sha256:sha(await readFile(enginePath)),unchanged:engineBefore===sha(await readFile(enginePath))},null,2));await writeFile(join(out,'server.log'),log);await writeFile(join(out,'vite.log'),viteLog);await browser?.close();await Promise.all([server,vite].filter(Boolean).map(async child=>{if(child.exitCode!==null)return;const done=once(child,'exit');child.kill('SIGTERM');await done}))}
