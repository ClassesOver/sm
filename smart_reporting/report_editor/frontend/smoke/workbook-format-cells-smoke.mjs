import assert from 'node:assert/strict'
import { spawn, spawnSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import { copyFile, mkdir, readFile, writeFile } from 'node:fs/promises'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { setTimeout as delay } from 'node:timers/promises'
import { once } from 'node:events'
import { chromium } from 'playwright'
const frontend=fileURLToPath(new URL('../',import.meta.url)),repo=fileURLToPath(new URL('../../../../',import.meta.url))
const out=process.env.FORMAT_CELLS_OUT;assert(out);await mkdir(out,{recursive:false})
const sourceFrontend=process.env.FORMAT_CELLS_FRONTEND??frontend
const dev=process.env.FORMAT_CELLS_DEV==='1',port=Number(process.env.FORMAT_CELLS_PORT??4493),vitePort=port+1
const api=`http://127.0.0.1:${port}`,origin=dev?`http://127.0.0.1:${vitePort}`:api
const sha=b=>createHash('sha256').update(b).digest('hex')
const fixture=spawnSync(join(repo,'.venv/bin/python'),[join(frontend,'smoke/workbook-format-cells-verify.py'),out,'--fixture'],{cwd:repo,encoding:'utf8'});assert.equal(fixture.status,0,fixture.stderr)
if(process.env.FORMAT_CELLS_REOPEN_FILE)await copyFile(process.env.FORMAT_CELLS_REOPEN_FILE,join(out,'fixture.xlsx'))
const files=['smart_reporting/report_editor/native_office.py','smart_reporting/report_editor/native_api.py','smart_reporting/reporting/workbook_engine/packages/xlsx-engine/src/style-read.ts']
const before=await Promise.all(files.map(async path=>({path,sha256:sha(await readFile(join(repo,path)))})))
await writeFile(join(out,'runtime-wrapper-before.json'),JSON.stringify(before,null,2))
const enginePath=join(process.env.AGENT_REPORTING_WORKBOOK_ENGINE_DIR,'dist/cli.mjs'),engineBefore=sha(await readFile(enginePath))
await writeFile(join(out,'runtime-engine-before.json'),JSON.stringify({path:enginePath,sha256:engineBefore},null,2))
const server=spawn(join(repo,'.venv/bin/python'),[join(frontend,'smoke/workbook-ai-charts-server.py'),'--directory',out,'--port',String(port),'--source',join(out,'fixture.xlsx')],{cwd:repo,env:{...process.env,PYTHONPATH:repo},stdio:'pipe'})
let log='',viteLog='',vite,browser,page,continuationSaved,stage='server';const errors=[],consoleErrors=[],assets=new Map(),assetFailures=[],pending=[],checks=[]
server.stdout.on('data',b=>{log+=b});server.stderr.on('data',b=>{log+=b})
try{
 for(let n=0;;n++){assert.equal(server.exitCode,null,log);try{if((await fetch(api+'/__smoke__/state')).ok)break}catch{}assert(n<240,log);await delay(250)}
 const info=JSON.parse(await readFile(join(out,'server-info.json'),'utf8'))
 if(dev){
  const code=`import {createServer} from 'vite';const s=await createServer({root:${JSON.stringify(sourceFrontend)},cacheDir:${JSON.stringify(join(out,'vite-cache'))},server:{host:'127.0.0.1',port:${vitePort},strictPort:true,proxy:{'^/reports/v1/(?!editor/assets/)':{target:${JSON.stringify(api)},changeOrigin:true,configure(p){p.on('proxyReq',r=>{r.setHeader('origin',${JSON.stringify(api)})})}}}}});await s.listen()`
  vite=spawn(process.execPath,['--input-type=module','-e',code],{cwd:sourceFrontend});vite.stdout.on('data',b=>{viteLog+=b});vite.stderr.on('data',b=>{viteLog+=b})
  for(let n=0;;n++){assert.equal(vite.exitCode,null,viteLog);try{if((await fetch(origin+'/reports/v1/editor/assets/native.html')).ok)break}catch{}assert(n<240,viteLog);await delay(250)}
 }
 browser=await chromium.launch({headless:true});page=await browser.newPage({viewport:{width:1440,height:900},acceptDownloads:true})
 page.on('pageerror',error=>errors.push(error.message));page.on('console',message=>{if(message.type()==='error')consoleErrors.push(message.text())})
 if(!dev)await page.route('**/reports/v1/editor/assets/**',async route=>{
  const path=new URL(route.request().url()).pathname
  try{
   const response=await route.fetch(),actual=await response.body(),disk=await readFile(join(process.env.PDF_SMOKE_STATIC_DIRECTORY,decodeURIComponent(path.slice('/reports/v1/editor/assets/'.length))))
   assert.equal(response.status(),200);assert.equal(sha(actual),sha(disk));assets.set(path,sha(actual))
   await route.fulfill({response,body:actual})
  }catch(error){assetFailures.push({path,error:String(error)});await route.abort()}
 })
 if(dev){const grant=await page.request.get(origin+info.openPath,{maxRedirects:0});assert.equal(grant.status(),303);const path=grant.headers()['location'];await page.addInitScript(path=>{if(location.pathname.includes('/editor/assets/'))history.replaceState(null,'',path)},path)}
 const ready=()=>page.waitForFunction(()=>document.querySelector('#report-editor')?.getAttribute('aria-busy')==='false',null,{timeout:90000})
 const draft=()=>page.evaluate(()=>Object.entries(localStorage).filter(([key])=>key.startsWith('native-editor-draft:')).flatMap(([,v])=>JSON.parse(v).operations??[]))
 const select=async text=>{const box=page.locator('[data-u-comp="defined-name"] input');await box.fill(text);await box.press('Enter')}
 const open=async()=>{await page.locator('[data-ribbon-tab="Home"]').click();const b=page.locator('[data-ribbon-command="format-cells"]');await b.scrollIntoViewIfNeeded();await b.click();await page.getByRole('tab',{name:'保护',exact:true}).waitFor()}
 const tab=label=>page.getByRole('tab',{name:label,exact:true}).click()
 const pick=async(label,value)=>{
  const dialog=page.getByRole('dialog',{name:'设置单元格格式',exact:true}),trigger=dialog.getByRole('button',{name:label,exact:true})
  await trigger.click();await dialog.getByRole('option',{name:value,exact:true}).click()
  const expanded=await trigger.getAttribute('aria-expanded')
  if(expanded!=='false')await writeFile(join(out,'dropdown-click-trace.json'),JSON.stringify({label,value,expanded,events:await page.evaluate(()=>window.__formatClickTrace)},null,2))
  assert.equal(expanded,'false',`${label} option pick must close its menu`)
 }
 stage='open';await page.goto(origin+(dev?'/reports/v1/editor/assets/native.html':info.openPath));await ready()
 if(process.env.FORMAT_CELLS_SAVE_REQUEST){
  stage='save-continuation'
  const endpoint=page.url().replace(/\/$/,'')+'/api'
  const context=await(await page.request.get(endpoint+'/context')).json()
  const response=await page.request.post(endpoint+'/save',{data:JSON.parse(await readFile(process.env.FORMAT_CELLS_SAVE_REQUEST,'utf8')),headers:{Origin:api,'X-CSRF-Token':context.csrfToken}})
  const saved=await response.json();assert.equal(response.status(),200,JSON.stringify(saved))
  continuationSaved=saved
  await writeFile(join(out,'save-continuation-response.json'),JSON.stringify(saved,null,2))
  await page.goto(saved.editor.openUrl);await ready()
 }
 if(process.env.FORMAT_CELLS_REOPEN_FILE){
  await select('A1:A2');await open()
  for(const label of ['数字','对齐','字体','边框','填充','保护'])await tab(label)
  assert.match(await page.getByRole('button',{name:'锁定',exact:true}).innerText(),/关/)
  assert.match(await page.getByRole('button',{name:'隐藏（公式）',exact:true}).innerText(),/开/)
  await page.screenshot({path:join(out,'reopened.png')});await page.getByRole('button',{name:'取消',exact:true}).click()
  await Promise.all(pending);assert.deepEqual(assetFailures,[]);assert.deepEqual(errors,[])
  await writeFile(join(out,'reopen-evidence.json'),JSON.stringify({ok:true,sourceSha256:info.sourceSha256,sourceFile:process.env.FORMAT_CELLS_REOPEN_FILE,actualStaticAssets:[...assets],browserErrors:errors,consoleErrors,saveCount:continuationSaved?1:0,savedRevision:continuationSaved?.revision,savedSha256:continuationSaved?.artifacts.xlsx.sha256},null,2))
  console.log(JSON.stringify({ok:true,reopenedSavedRevision:Boolean(continuationSaved),reopenedActualDownload:!continuationSaved,saveCount:continuationSaved?1:0}));
 }else{
 // Frozen source value/format mixture is preserved by opening and cancelling every tab.
 await page.evaluate(()=>{window.__formatClickTrace=[];document.addEventListener('click',event=>{if(event.target instanceof Element&&event.target.closest('.workbook-format-cells-overlay'))window.__formatClickTrace.push({tag:event.target.tagName,role:event.target.getAttribute('role'),name:event.target.getAttribute('aria-label'),className:event.target.className,defaultPrevented:event.defaultPrevented})},true)})
 const noedit=await draft()
 for(const [width,height] of (process.env.FORMAT_CELLS_SKIP_VIEWPORTS==='1'?[]:[[1440,900],[320,640],[640,360],[390,320]])){
  await page.setViewportSize({width,height});await select('A1:A2');await open()
  for(const label of ['数字','对齐','字体','边框','填充','保护']){
   await tab(label)
   const action=page.getByRole('button',{name:'确定',exact:true});await action.scrollIntoViewIfNeeded()
   const hit=await action.evaluate(node=>{const r=node.getBoundingClientRect();return r.x>=0&&r.y>=0&&r.right<=innerWidth&&r.bottom<=innerHeight&&node.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2))});assert(hit,`${width}x${height} ${label}`)
   checks.push({width,height,tab:label,actualActionHit:hit})
   if(label==='字体')await page.screenshot({path:join(out,`font-${width}x${height}.png`),animations:'disabled'})
  }
  await page.getByRole('button',{name:'取消',exact:true}).click();assert.deepEqual(await draft(),noedit)
 }
 stage='apply';await page.setViewportSize({width:1440,height:900});await select('A1:A2');await open()
 await page.getByRole('option',{name:'自定义',exact:true}).click();await page.getByLabel('自定义代码',{exact:true}).fill('0.000')
 await tab('对齐');await pick('水平对齐','分散对齐');await pick('垂直对齐','垂直居中');await pick('自动换行','开');await pick('方向','顺时针角度（−45°）');await page.getByLabel('缩进',{exact:true}).fill('2')
 await tab('字体');await pick('字体','Arial');await pick('字号','16');await pick('加粗','关');await pick('倾斜','开');await pick('下划线','开');await pick('删除线','开')
 // Actual palette clicks; Escape first closes only the nested palette.
 await page.getByRole('button',{name:'颜色',exact:true}).click();await page.keyboard.press('Escape');assert(await page.getByRole('tab',{name:'字体',exact:true}).isVisible());await page.getByRole('button',{name:'颜色',exact:true}).click();await page.getByRole('gridcell',{name:'Dark Red',exact:true}).click()
 await tab('边框');await pick('预置','外侧框线');await pick('线型','双线');await page.getByRole('button',{name:'颜色',exact:true}).click();await page.locator('.gcp-standard-row').getByRole('gridcell',{name:'Blue',exact:true}).click()
 await tab('填充');await page.getByLabel('无填充',{exact:true}).check()
 await tab('保护');await pick('锁定','关');await pick('隐藏（公式）','开')
 await page.getByRole('button',{name:'确定',exact:true}).click();await page.waitForFunction(()=>document.querySelector('.workbook-format-cells-overlay')?.hasAttribute('hidden'));await ready()
 const adopted=await draft();assert.equal(adopted.filter(op=>op.kind==='applyCellEdits'&&op.edits.some(e=>e.style?.protectionHidden)).length,1)
 stage='undo-redo';await page.locator('[data-ribbon-tab="File"]').click();await page.locator('[data-ribbon-command="undo"]').click();await ready();assert.deepEqual(await draft(),noedit)
 await page.locator('[data-ribbon-command="redo"]').click();await ready();assert.deepEqual(await draft(),adopted)
 if(dev)await page.goto(origin+'/reports/v1/editor/assets/native.html');else await page.reload();await ready();assert.deepEqual(await draft(),adopted)
 // The actual saved flags must echo again, without an accidental extra command.
 await select('A1:A2');await open();await tab('保护');assert.match(await page.getByRole('button',{name:'锁定',exact:true}).innerText(),/关/);assert.match(await page.getByRole('button',{name:'隐藏（公式）',exact:true}).innerText(),/开/);await page.getByRole('button',{name:'确定',exact:true}).click();assert.deepEqual(await draft(),adopted)
 stage='save';const waiting=page.waitForResponse(r=>r.url().endsWith('/api/save')&&r.request().method()==='POST');await page.locator('[data-action="save"]').click();const response=await waiting,saved=await response.json();assert.equal(response.status(),200,JSON.stringify(saved));assert.equal(saved.revisionRegistered,true);assert.equal(saved.revision,info.context.revision+1)
 await writeFile(join(out,'save-request.json'),JSON.stringify(response.request().postDataJSON(),null,2));await writeFile(join(out,'save-response.json'),JSON.stringify(saved,null,2))
 const [download]=await Promise.all([page.waitForEvent('download'),page.locator('[data-action="xlsx-download"]').click()]);await download.saveAs(join(out,'format-cells.xlsx'));assert.equal(sha(await readFile(join(out,'format-cells.xlsx'))),saved.artifacts.xlsx.sha256)
 const verify=spawnSync(join(repo,'.venv/bin/python'),[join(frontend,'smoke/workbook-format-cells-verify.py'),out],{cwd:repo,encoding:'utf8'});assert.equal(verify.status,0,verify.stderr||verify.stdout)
 if(!dev){await page.goto(saved.editor.openUrl);await ready();await select('A1:A2');await open();await tab('保护');assert.match(await page.getByRole('button',{name:'锁定',exact:true}).innerText(),/关/);await page.screenshot({path:join(out,'reopened.png')})}
 await Promise.all(pending);assert.deepEqual(assetFailures,[]);assert.deepEqual(errors,[])
 const after=await Promise.all(files.map(async path=>({path,sha256:sha(await readFile(join(repo,path)))})))
 await writeFile(join(out,'evidence.json'),JSON.stringify({ok:true,dev,checks,adopted,sourceSha256:info.sourceSha256,savedSha256:saved.artifacts.xlsx.sha256,independentReadback:JSON.parse(verify.stdout),actualStaticAssets:[...assets],pythonSourceBefore:before,pythonSourceAfter:after,browserErrors:errors,consoleErrors,sourceProxy:dev?'Vite reverse proxy fixes Origin to backend fixture; final static route must verify direct origin separately':null},null,2));console.log(JSON.stringify({ok:true,checks:checks.length,downloadSha256:saved.artifacts.xlsx.sha256,dev}))
 }
}catch(error){await page?.screenshot({path:join(out,'failure.png')}).catch(()=>{});await writeFile(join(out,'failure.json'),JSON.stringify({stage,error:String(error),stack:error.stack,errors,assetFailures,actualStaticAssets:[...assets],consoleErrors,feedback:await page?.locator('.workbook-feedback').innerText().catch(()=>null)},null,2));throw error}
finally{await writeFile(join(out,'runtime-wrapper-after.json'),JSON.stringify(await Promise.all(files.map(async path=>({path,sha256:sha(await readFile(join(repo,path)))}))),null,2));await writeFile(join(out,'runtime-engine-after.json'),JSON.stringify({path:enginePath,sha256:sha(await readFile(enginePath)),unchanged:engineBefore===sha(await readFile(enginePath))},null,2));await writeFile(join(out,'server.log'),log);await writeFile(join(out,'vite.log'),viteLog);await browser?.close();await Promise.all([server,vite].filter(Boolean).map(async child=>{if(child.exitCode!==null)return;const done=once(child,'exit');child.kill('SIGTERM');await done}))}
