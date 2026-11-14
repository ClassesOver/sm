// 冻结分包的真实缩放定位运行检查；不代替保存/下载/重开验收。
import assert from 'node:assert/strict'
import {spawn} from 'node:child_process'
import {createHash} from 'node:crypto'
import {mkdir,readFile,writeFile} from 'node:fs/promises'
import {join} from 'node:path'
import {fileURLToPath} from 'node:url'
import {setTimeout as delay} from 'node:timers/promises'
import {chromium} from 'playwright'

const frontend=fileURLToPath(new URL('../',import.meta.url)),repo=fileURLToPath(new URL('../../../../',import.meta.url))
const assets=process.env.NATIVE_EDITOR_ASSET_ROOT,engine=process.env.PPTX_VIEW_ENGINE_ROOT,output=process.env.PPTX_ZOOM_DIRECTORY,port=Number(process.env.PPTX_ZOOM_PORT??4594),origin=`http://127.0.0.1:${port}`,sha=bytes=>createHash('sha256').update(bytes).digest('hex')
assert(assets&&engine&&output,'须指定冻结资源、现有引擎和新输出目录')
await mkdir(output)
const manifest=await readFile(join(assets,'.vite/manifest.json')),html=await readFile(join(assets,'native.html'))
const engineIdentities={};for(const name of ['edit-pptx.mjs','render-pptx.mjs'])engineIdentities[name]=sha(await readFile(join(engine,'dist',name)))
const server=spawn(join(repo,'.venv/bin/python'),[join(frontend,'smoke/pptx-outline-reading-server.py'),'--directory',output,'--port',String(port)],{cwd:repo,env:{...process.env,PYTHONPATH:repo,NATIVE_EDITOR_ASSET_ROOT:assets,AGENT_REPORTING_SLIDES_ENGINE_DIR:engine},stdio:'pipe'})
let log='',browser,page,stage='server';server.stdout.on('data',bytes=>log+=bytes);server.stderr.on('data',bytes=>log+=bytes)
const pageErrors=[],consoleErrors=[],httpErrors=[],resourceTasks=[],resources=new Map()
try{
 for(let n=0;;n++){assert.equal(server.exitCode,null,log);try{if((await fetch(origin+'/__smoke__/state')).ok)break}catch{}assert(n<240,log);await delay(250)}
 browser=await chromium.launch({headless:true,...(process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE?{executablePath:process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE}:{})})
 const context=await browser.newContext({viewport:{width:1600,height:1100},serviceWorkers:'block'});page=await context.newPage()
 page.on('pageerror',error=>pageErrors.push(error.message));page.on('console',message=>{if(message.type()==='error')consoleErrors.push(message.text())})
 page.on('response',response=>{const url=new URL(response.url()),prefix='/reports/v1/editor/assets/';if(response.status()>=400)httpErrors.push({path:url.pathname,status:response.status()});if(response.ok()&&url.origin===origin&&url.pathname.startsWith(prefix))resourceTasks.push((async()=>{const bytes=await response.body(),file=decodeURIComponent(url.pathname.slice(prefix.length)),disk=await readFile(join(assets,file));assert.equal(sha(bytes),sha(disk),file);resources.set(file,{sha256:sha(bytes),size:bytes.length})})())})
 stage='real-import'
 const info=JSON.parse(await readFile(join(output,'server-info.json'),'utf8')),source=await readFile(join(output,'source.pptx'))
 const imported=await context.request.post(origin+'/reports/v1/native/import',{headers:{'X-Workspace-Thread':info.thread,'X-Workspace-Capability':info.capability},multipart:{requestId:'zoom-chunks-runtime',file:{name:'zoom-source.pptx',mimeType:'application/vnd.openxmlformats-officedocument.presentationml.presentation',buffer:source}}});assert.equal(imported.status(),200,await imported.text())
 const registration=await imported.json(),opened=await page.goto(origin+registration.editor.url);assert.equal(sha(await opened.body()),sha(html))
 await page.waitForFunction(()=>document.querySelector('#report-editor')?.getAttribute('aria-busy')==='false',null,{timeout:120000});await page.locator('.slides-canvas canvas').first().waitFor()
 const operations=()=>page.evaluate(()=>{const key=Object.keys(localStorage).find(key=>key.startsWith('native-editor-draft:'));return key?JSON.parse(localStorage.getItem(key)).operations:[]})
 assert.deepEqual(await operations(),[])
 stage='zoom-grid-cancel'
 await page.locator('[data-ribbon-tab=insert]').click();await page.locator('[data-command=slideZoom]').click()
 const dialog=page.getByRole('dialog',{name:'幻灯片缩放定位',exact:true})
 await dialog.waitFor();await dialog.locator('.zoom-items button canvas').first().waitFor();assert.equal(await dialog.locator('.zoom-items button').count(),2)
 await page.screenshot({path:join(output,'zoom-grid.png'),fullPage:true});await dialog.getByRole('button',{name:'取消',exact:true}).click();await dialog.waitFor({state:'detached'});assert.deepEqual(await operations(),[])
 stage='zoom-insert-snapshot'
 await page.locator('[data-command=slideZoom]').click();await dialog.waitFor();await dialog.locator('.zoom-items button').first().click()
 const previewResponse=page.waitForResponse(response=>{if(!response.url().endsWith('/api/render-tree')||response.request().method()!=='POST')return false;try{return response.request().postDataJSON().operations?.some(item=>item.zoomInsertions?.length===1)}catch{return false}})
 await dialog.getByRole('button',{name:'插入',exact:true}).click()
 await page.waitForFunction(()=>{const key=Object.keys(localStorage).find(key=>key.startsWith('native-editor-draft:'));return key&&JSON.parse(localStorage.getItem(key)).operations.some(item=>item.zoomInsertions?.length===1)},null,{timeout:60000})
 await dialog.waitFor({state:'detached'})
 const pending=await operations(),insertion=pending.flatMap(item=>item.zoomInsertions??[])[0],png=Buffer.from(insertion.bytesBase64,'base64')
 assert.equal(insertion.mode,'slide');assert.match(insertion.slideIdentity,/^[a-f0-9]{64}$/);assert.match(insertion.targetSlideIdentity,/^[a-f0-9]{64}$/);assert.notEqual(insertion.slideIdentity,insertion.targetSlideIdentity);assert.equal(png.subarray(0,8).toString('hex'),'89504e470d0a1a0a')
 await writeFile(join(output,'zoom-snapshot.png'),png)
 const pixels=await page.evaluate(async base64=>{const img=new Image();img.src=`data:image/png;base64,${base64}`;await img.decode();const canvas=document.createElement('canvas');canvas.width=img.naturalWidth;canvas.height=img.naturalHeight;const ctx=canvas.getContext('2d');ctx.drawImage(img,0,0);const values=ctx.getImageData(0,0,canvas.width,canvas.height).data;let ink=0;for(let i=0;i<values.length;i+=4)if(values[i+3]>0&&Math.min(values[i],values[i+1],values[i+2])<200)ink++;return{width:canvas.width,height:canvas.height,ink}},insertion.bytesBase64)
 assert(pixels.ink>500,'快照须实际绘出内容，不能仅验证PNG头')
 const preview=await(await previewResponse).json();await writeFile(join(output,'zoom-render-tree.json'),JSON.stringify(preview,null,2))
 assert(preview.slides.some(slide=>slide.nodes?.some(node=>node.dataUrl===`data:image/png;base64,${insertion.bytesBase64}`)),'实际预览须包含插入快照')
 await page.waitForFunction(()=>document.querySelector('.canvas-status')?.textContent==='点击对象选择，拖动调整位置，拖动角点缩放',null,{timeout:60000});await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))))
 await page.screenshot({path:join(output,'zoom-inserted.png'),fullPage:true})
 stage='undo-redo'
 await page.locator('[data-source-action=onUndo]').click();assert.deepEqual(await operations(),[]);await page.locator('[data-source-action=onRedo]').click();assert.deepEqual(await operations(),pending)
 await page.waitForFunction(()=>document.querySelector('.canvas-status')?.textContent==='点击对象选择，拖动调整位置，拖动角点缩放',null,{timeout:60000})
 await Promise.all(resourceTasks);assert([...resources.keys()].some(file=>file.includes('native-pptx-zoom-controls')));assert([...resources.keys()].some(file=>file.includes('slides-print-render')))
 const state=await(await fetch(origin+'/__smoke__/state')).json();assert.equal(state.completedRevisions,0);assert.equal(state.requests.filter(item=>item.path.endsWith('/save')).length,0);assert.deepEqual(pageErrors,[]);assert.deepEqual(consoleErrors,[]);assert.deepEqual(httpErrors,[])
 const summary={ok:true,runtimeOnly:true,manifestSha256:sha(manifest),sourceSha256:sha(source),engineIdentities,pixels,pngSha256:sha(png),zoom:{...insertion,bytesBase64:undefined},cancelPreservesDraft:true,undoRedo:true,saveCount:0,resources:Object.fromEntries(resources),pageErrors,consoleErrors,httpErrors}
 await writeFile(join(output,'summary.json'),JSON.stringify(summary,null,2));console.log(JSON.stringify({ok:true,output,pixels,resources:resources.size}))
}catch(error){await page?.screenshot({path:join(output,'failure.png'),fullPage:true}).catch(()=>{});await writeFile(join(output,'failure.json'),JSON.stringify({stage,error:String(error),pageErrors,consoleErrors,httpErrors,status:await page?.locator('.status-message').allTextContents().catch(()=>[])},null,2));throw error}
finally{await browser?.close();server.kill();await writeFile(join(output,'server.log'),log)}
