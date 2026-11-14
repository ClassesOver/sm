// 本地授权/仓储fixture，真实HTTP导入、原生PPTX bridge、保存/下载/新修订重开。
import assert from 'node:assert/strict'
import {spawn} from 'node:child_process'
import {createHash} from 'node:crypto'
import {mkdir,readFile,writeFile} from 'node:fs/promises'
import {join} from 'node:path'
import {fileURLToPath} from 'node:url'
import {setTimeout as delay} from 'node:timers/promises'
import {chromium} from 'playwright'

const frontend=fileURLToPath(new URL('../',import.meta.url)),repo=fileURLToPath(new URL('../../../../',import.meta.url))
const assets=process.env.NATIVE_EDITOR_ASSET_ROOT,engine=process.env.PPTX_VIEW_ENGINE_ROOT,output=process.env.PPTX_SAVE_DIRECTORY,port=Number(process.env.PPTX_SAVE_PORT??4595),origin=`http://127.0.0.1:${port}`,sha=bytes=>createHash('sha256').update(bytes).digest('hex')
assert(assets&&engine&&output,'须指定冻结资源、引擎和新输出目录');await mkdir(output)
const manifest=await readFile(join(assets,'.vite/manifest.json')),html=await readFile(join(assets,'native.html'))
const server=spawn(join(repo,'.venv/bin/python'),[join(frontend,'smoke/pptx-outline-reading-server.py'),'--directory',output,'--port',String(port)],{cwd:repo,env:{...process.env,PYTHONPATH:repo,NATIVE_EDITOR_ASSET_ROOT:assets,AGENT_REPORTING_SLIDES_ENGINE_DIR:engine},stdio:'pipe'})
let log='',browser,page,stage='server';server.stdout.on('data',bytes=>log+=bytes);server.stderr.on('data',bytes=>log+=bytes)
const pageErrors=[],consoleErrors=[],httpErrors=[],resourceTasks=[],resources=new Map(),notes='快捷键保存：未失焦备注 😀'
try{
 for(let n=0;;n++){assert.equal(server.exitCode,null,log);try{if((await fetch(origin+'/__smoke__/state')).ok)break}catch{}assert(n<240,log);await delay(250)}
 browser=await chromium.launch({headless:true,...(process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE?{executablePath:process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE}:{})})
 const context=await browser.newContext({viewport:{width:1600,height:1100},serviceWorkers:'block'});page=await context.newPage()
 page.on('pageerror',error=>pageErrors.push(error.message));page.on('console',message=>{if(message.type()==='error')consoleErrors.push(message.text())})
 page.on('response',response=>{const url=new URL(response.url()),prefix='/reports/v1/editor/assets/';if(response.status()>=400)httpErrors.push({path:url.pathname,status:response.status()});if(response.ok()&&url.origin===origin&&url.pathname.startsWith(prefix))resourceTasks.push((async()=>{const bytes=await response.body(),file=decodeURIComponent(url.pathname.slice(prefix.length)),disk=await readFile(join(assets,file));assert.equal(sha(bytes),sha(disk),file);resources.set(file,{sha256:sha(bytes),size:bytes.length})})())})
 stage='import';const info=JSON.parse(await readFile(join(output,'server-info.json'),'utf8')),source=await readFile(join(output,'source.pptx'))
 const imported=await context.request.post(origin+'/reports/v1/native/import',{headers:{'X-Workspace-Thread':info.thread,'X-Workspace-Capability':info.capability},multipart:{requestId:'save-shortcut-runtime',file:{name:'save-shortcut.pptx',mimeType:'application/vnd.openxmlformats-officedocument.presentationml.presentation',buffer:source}}});assert.equal(imported.status(),200,await imported.text())
 const registration=await imported.json(),opened=await page.goto(origin+registration.editor.url);assert.equal(sha(await opened.body()),sha(html))
 await page.waitForFunction(()=>document.querySelector('#report-editor')?.getAttribute('aria-busy')==='false',null,{timeout:120000})
 const input=page.locator('[data-notes-text]');await input.waitFor();const sourceNotes=await input.inputValue();await input.fill(notes);await input.focus()
 assert.equal(await input.evaluate(node=>node===document.activeElement),true)
 stage='keyboard-save';await page.screenshot({path:join(output,'before-keyboard-save.png'),fullPage:true})
 const responsePromise=page.waitForResponse(response=>response.url().endsWith('/api/save')&&response.request().method()==='POST',{timeout:120000})
 await page.keyboard.press('Control+s');const response=await responsePromise;assert.equal(response.status(),200,await response.text());const result=await response.json(),payload=response.request().postDataJSON()
 await writeFile(join(output,'save-response.json'),JSON.stringify(result,null,2));await writeFile(join(output,'save-request.json'),JSON.stringify(payload,null,2))
 assert.equal(payload.expectedSha256,sha(source));assert.deepEqual(payload.operations[0].notesEdits,[{slideIndex:0,text:notes}]);assert.equal(result.revisionRegistered,true)
 const url=result.artifacts?.pptx?.downloadUrl;assert(url,'已生成PPTX应有下载链接')
 const download=await context.request.get(new URL(url,origin).href);assert.equal(download.status(),200);const bytes=await download.body();await writeFile(join(output,'downloaded.pptx'),bytes)
 if(result.artifacts.pptx.sha256)assert.equal(sha(bytes),result.artifacts.pptx.sha256)
 stage='reopen';assert(result.editor?.openUrl);await page.goto(new URL(result.editor.openUrl,origin).href)
 await page.waitForFunction(()=>document.querySelector('#report-editor')?.getAttribute('aria-busy')==='false',null,{timeout:120000});await page.locator('[data-notes-text]').waitFor();assert.equal(await page.locator('[data-notes-text]').inputValue(),notes)
 await page.screenshot({path:join(output,'saved-revision-reopened.png'),fullPage:true});await Promise.all(resourceTasks)
 const state=await(await fetch(origin+'/__smoke__/state')).json();const saves=state.requests.filter(item=>item.path.endsWith('/api/save'));assert.equal(saves.length,1);assert.equal(state.completedRevisions,1);assert.deepEqual(pageErrors,[]);assert.deepEqual(consoleErrors,[]);assert.deepEqual(httpErrors,[])
 const summary={ok:true,authorizationFixture:true,manifestSha256:sha(manifest),sourceSha256:sha(source),downloadSha256:sha(bytes),downloadSize:bytes.length,sourceNotes,savedNotes:notes,revision:result.revision,validation:result.validation,saveCount:saves.length,reopened:true,resources:Object.fromEntries(resources),pageErrors,consoleErrors,httpErrors}
 await writeFile(join(output,'summary.json'),JSON.stringify(summary,null,2));console.log(JSON.stringify({ok:true,output,saveCount:saves.length,resources:resources.size}))
}catch(error){await page?.screenshot({path:join(output,'failure.png'),fullPage:true}).catch(()=>{});await writeFile(join(output,'failure.json'),JSON.stringify({stage,error:String(error),pageErrors,consoleErrors,httpErrors,status:await page?.locator('.status-message').allTextContents().catch(()=>[])},null,2));throw error}
finally{await browser?.close();server.kill();await writeFile(join(output,'server.log'),log)}
