// Frozen production assets and real form-source server. Resume verified saves from checkpoint.json.
import assert from 'node:assert/strict'
import {spawn,spawnSync} from 'node:child_process'
import {createHash} from 'node:crypto'
import {openSync} from 'node:fs'
import {mkdir,readFile,writeFile} from 'node:fs/promises'
import {join} from 'node:path'
import {fileURLToPath} from 'node:url'
import {setTimeout as delay} from 'node:timers/promises'
import {chromium} from 'playwright'
const frontend=fileURLToPath(new URL('../',import.meta.url)),repo=fileURLToPath(new URL('../../../../',import.meta.url))
const directory=process.env.PDF_FORM_CANVAS_SMOKE_DIRECTORY??'/tmp/pdf-form-canvas-browser-20261111',port=Number(process.env.PDF_FORM_CANVAS_SMOKE_PORT??4350),origin='http://127.0.0.1:'+port
const staticDirectory=process.env.PDF_SMOKE_STATIC_DIRECTORY;assert.ok(staticDirectory,'PDF_SMOKE_STATIC_DIRECTORY is required')
const sha=b=>createHash('sha256').update(b).digest('hex')
await mkdir(directory,{recursive:true})
const manifest=await readFile(join(staticDirectory,'.vite/manifest.json')),manifestSha256=sha(manifest)
let checkpoint={manifestSha256,staticDirectory,saves:{},assets:{}},browser,page,stage='server',serverPid
try{checkpoint=JSON.parse(await readFile(join(directory,'checkpoint.json'),'utf8'));assert.equal(checkpoint.manifestSha256,manifestSha256);assert.equal(checkpoint.staticDirectory,staticDirectory)}catch(error){if(error.code!=='ENOENT')throw error}
let checkpointWrite=Promise.resolve()
const persistCheckpoint=()=>{const data=JSON.stringify(checkpoint,null,2);checkpointWrite=checkpointWrite.then(()=>writeFile(join(directory,'checkpoint.json'),data));return checkpointWrite}
const pageErrors=[],consoleErrors=[],httpErrors=[],assetErrors=[],assetChecks=[]
try{
 let running=false;try{running=(await fetch(origin+'/__smoke__/state')).ok}catch{}
 if(!running){assert.equal(Object.keys(checkpoint.saves).length,0,'Saved checkpoint requires its still-running source server; do not silently replay completed UI saves')
  const log=openSync(join(directory,'server.log'),'a'),server=spawn(join(repo,'.venv/bin/python'),[join(frontend,'smoke/pdf-form-create-server.py'),'--directory',directory,'--port',String(port)],{cwd:repo,env:{...process.env,PYTHONPATH:repo},detached:true,stdio:['ignore',log,log]});serverPid=server.pid;server.unref();checkpoint.serverPid=serverPid;await persistCheckpoint()
  for(let i=0;;i++){try{if((await fetch(origin+'/__smoke__/state')).ok)break}catch{}assert.ok(i<480,'source server startup timeout');await delay(250)}
 }else serverPid=checkpoint.serverPid
 const info=JSON.parse(await readFile(join(directory,'server-info.json'),'utf8'));if(checkpoint.sourceSha256)assert.equal(checkpoint.sourceSha256,info.sourceSha256);checkpoint.sourceSha256=info.sourceSha256
 const state=await(await fetch(origin+'/__smoke__/state')).json();assert.equal(state.sourceSha256,info.sourceSha256)
 assert.equal(state.savedRevisions,Object.keys(checkpoint.saves).length,'server checkpoint/save count drift')
 for(const [path,digest]of Object.entries(checkpoint.assets))assert.equal(sha(await readFile(join(staticDirectory,path.slice('/reports/v1/editor/assets/'.length)))),digest)
 for(const [label,saved]of Object.entries(checkpoint.saves)){if(!saved.downloadVerified)continue;const bytes=await readFile(join(directory,label+'-downloaded.pdf'));assert.equal(sha(bytes),saved.payload.artifacts.pdf.sha256);assert.equal(bytes.length,saved.payload.artifacts.pdf.size)}
 browser=await chromium.launch({headless:true,...(process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE?{executablePath:process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE}:{})});page=await browser.newPage({viewport:{width:1500,height:1100}})
 page.on('pageerror',e=>pageErrors.push(e.message));page.on('console',m=>{if(m.type()==='error')consoleErrors.push(m.text())})
 page.on('response',response=>{const path=new URL(response.url()).pathname,status=response.status();if(status>=400)httpErrors.push({path,status});if(status!==200||!path.startsWith('/reports/v1/editor/assets/')||!(/\.m?js$/).test(path))return;assetChecks.push((async()=>{const bytes=await response.body(),disk=await readFile(join(staticDirectory,path.slice('/reports/v1/editor/assets/'.length)));assert.equal(sha(bytes),sha(disk));checkpoint.assets[path]=sha(bytes);await persistCheckpoint()})().catch(error=>assetErrors.push({path,error:String(error)})))})
 const ready=()=>page.waitForFunction(()=>document.querySelector('#report-editor')?.getAttribute('aria-busy')==='false',null,{timeout:60000})
 const operations=()=>page.evaluate(()=>JSON.parse(Object.entries(localStorage).find(([k])=>k.startsWith('native-editor-draft:'))?.[1]??'{}').operations??[])
 const waitOperations=()=>page.waitForFunction(()=>JSON.parse(Object.entries(localStorage).find(([k])=>k.startsWith('native-editor-draft:'))?.[1]??'{}').operations?.length===1)
 const command=id=>page.locator('[data-source-command-id="genoffice.pdf.formDesign.'+id+'"]'),panel=page.locator('.pdf-form-create-panel')
 async function openDesign(id){await page.locator('[data-pdf-ribbon-tab="formDesign"]').click();assert.equal(await command(id).isDisabled(),false);await command(id).click();await panel.waitFor({state:'visible'})}
 const savedValues=Object.values(checkpoint.saves),latest=savedValues.at(-1)
 await page.goto(latest?.payload.editor.openUrl??origin+info.openPath);await ready();if(latest){const context=await page.evaluate(async()=>(await fetch(location.pathname+'/api/context')).json());assert.equal(context.context.revision,latest.payload.revision);assert.equal(context.context.sourceFile.sha256,latest.payload.artifacts.pdf.sha256)}
 async function save(label,kind,requiresPreview=true){
  if(await panel.isVisible())await panel.getByRole('button',{name:'关闭字段设置',exact:true}).click()
  let preview=null
  if(requiresPreview){stage=label+'-preview';await page.locator('[data-pdf-ribbon-tab="edit"]').click();const previewing=page.waitForResponse(r=>r.url().endsWith('/api/preview')&&r.request().method()==='POST');await page.getByRole('button',{name:'校验当前修改',exact:true}).click();const response=await previewing;preview=await response.json();await writeFile(join(directory,label+'-preview.json'),JSON.stringify(preview,null,2));assert.equal(response.status(),200,JSON.stringify(preview));assert.deepEqual(preview.appliedOperationIndices,[0]);assert.deepEqual(preview.skippedOperations,[]);const confirm=page.locator('.pdf-preview-review input[type="checkbox"]');await confirm.waitFor({state:'visible'});await confirm.check()}
  const staged=await operations();assert.equal(staged.length,1);assert.equal(staged[0].kind,kind);await page.screenshot({path:join(directory,label+'-before-save.png'),fullPage:true})
  const parentRevision=4+Object.keys(checkpoint.saves).length;stage=label+'-save';const saving=page.waitForResponse(r=>r.url().endsWith('/api/save')&&r.request().method()==='POST');await page.locator('[data-action="save"]').click();const saved=await saving,payload=await saved.json();await writeFile(join(directory,label+'-save.json'),JSON.stringify(payload,null,2));assert.equal(saved.status(),200,JSON.stringify(payload));assert.equal(payload.revisionRegistered,true);assert.equal(payload.parentRevision,parentRevision);assert.equal(payload.revision,parentRevision+1);assert.deepEqual(saved.request().postDataJSON().operations,staged);if(preview)assert.equal(saved.request().postDataJSON().confirmedPreviewDigest,preview.previewDigest)
  checkpoint.saves[label]={staged,payload,preview,downloadVerified:false};await persistCheckpoint()
  stage=label+'-download';const downloaded=await page.request.get(payload.artifacts.pdf.downloadUrl);assert.equal(downloaded.status(),200);const bytes=await downloaded.body();assert.equal(sha(bytes),payload.artifacts.pdf.sha256);assert.equal(bytes.length,payload.artifacts.pdf.size);await writeFile(join(directory,label+'-downloaded.pdf'),bytes);checkpoint.saves[label].downloadVerified=true;await persistCheckpoint()
  stage=label+'-reopen';await page.goto(payload.editor.openUrl);await ready();const reopened=await page.evaluate(async()=>(await fetch(location.pathname+'/api/context')).json());assert.equal(reopened.context.revision,parentRevision+1);assert.equal(reopened.context.sourceFile.sha256,payload.artifacts.pdf.sha256);checkpoint.saves[label].reopened=true;await persistCheckpoint()
 }
 for(const [label,saved]of Object.entries(checkpoint.saves))if(!saved.downloadVerified){const response=await page.request.get(saved.payload.artifacts.pdf.downloadUrl);assert.equal(response.status(),200);const bytes=await response.body();assert.equal(sha(bytes),saved.payload.artifacts.pdf.sha256);assert.equal(bytes.length,saved.payload.artifacts.pdf.size);await writeFile(join(directory,label+'-downloaded.pdf'),bytes);saved.downloadVerified=true;await persistCheckpoint()}
 for(const [label,index,x,y,width,height]of [['text',0,30,180,80,24],['check',1,60,180,20,20]]){
  if(checkpoint.saves[label])continue;stage=label+'-input';await page.locator('.pdf-page-label').nth(index).click();await openDesign(label==='text'?'addTextField':'addCheckBox');await panel.getByRole('textbox',{name:'字段名称',exact:true}).fill(label);if(label==='text')await panel.getByRole('textbox',{name:'初始值',exact:true}).fill('Canvas Alpha');else await panel.getByRole('checkbox',{name:'初始勾选',exact:true}).check();for(const[name,value]of [['左下角 X',x],['左下角 Y',y],['宽度',width],['高度',height]])await panel.getByRole('spinbutton',{name,exact:true}).fill(String(value));await panel.locator('[data-pdf-form-create-apply]').click();await waitOperations();assert.equal((await operations())[0].pageId.endsWith(':page:'+index),true);await save(label,'createFormField')
 }
 async function nudge(label,index,original,first,final){
  if(checkpoint.saves[label])return;stage=label+'-select';await page.locator('.pdf-page-label').nth(index).click();await page.locator('[data-pdf-ribbon-tab="formDesign"]').click();const rect=page.locator('.pdf-page').nth(index).locator('[data-pdf-form-canvas-widget]');assert.equal(await rect.count(),1);await rect.click();assert.equal(await rect.getAttribute('aria-pressed'),'true');const before=await rect.boundingBox();assert.ok(before)
  const measure=()=>rect.evaluate(element=>{const client=element.getBoundingClientRect(),svg=element.closest('svg'),page=svg.getBoundingClientRect();return {client:{x:client.x,y:client.y,width:client.width,height:client.height},pageRelative:{x:client.x-page.x,y:client.y-page.y,width:client.width,height:client.height},svgGeometry:{x:Number(element.getAttribute('x')),y:Number(element.getAttribute('y')),width:Number(element.getAttribute('width')),height:Number(element.getAttribute('height'))},svgClient:{x:page.x,y:page.y,width:page.width,height:page.height},stroke:getComputedStyle(element).strokeWidth}})
  const beforeMeasurement=await measure(),width=index===0?80:20,scale=beforeMeasurement.svgGeometry.width/width
  checkpoint[label+'Gesture']={original,first,final,before,beforeMeasurement,scale,measurement:'stroke-free SVG geometry / page-relative DOM coordinates',continuedWithoutReselection:false};await persistCheckpoint()
  await page.keyboard.press('ArrowRight');await waitOperations();assert.deepEqual((await operations())[0].rect,first);await page.waitForFunction(index=>document.querySelectorAll('.pdf-page')[index]?.querySelector('[data-pdf-form-canvas-widget]')?.getAttribute('aria-pressed')==='true',index)
  // Do not reselect/focus after refresh: the second key must use the retained source-bound selection.
  await page.keyboard.press('Shift+ArrowUp');await page.waitForFunction(expected=>{const op=JSON.parse(Object.entries(localStorage).find(([k])=>k.startsWith('native-editor-draft:'))?.[1]??'{}').operations?.[0];return JSON.stringify(op?.rect)===JSON.stringify(expected)},final)
  assert.deepEqual((await operations())[0].rect,final);assert.equal((await operations()).length,1);await rect.waitFor({state:'visible'});const after=await rect.boundingBox(),afterMeasurement=await measure();assert.ok(after)
  Object.assign(checkpoint[label+'Gesture'],{after,afterMeasurement,continuedWithoutReselection:true});await persistCheckpoint()
  const a=beforeMeasurement.pageRelative,b=afterMeasurement.pageRelative
  assert.ok(Math.abs(b.x-a.x-scale)<.75,'page-relative screen right must be one point at current zoom');assert.ok(Math.abs(b.y-a.y+10*scale)<.75,'page-relative screen up must be ten points at current zoom');await page.screenshot({path:join(directory,label+'-canvas.png'),fullPage:true})
  const staged=await operations();await page.locator('[data-pdf-ribbon-tab="home"]').click();await page.locator('[data-source-command-id="genoffice.pdf.home.edit.undo"]').click();assert.deepEqual((await operations())[0].rect,first);await page.locator('[data-source-command-id="genoffice.pdf.home.edit.redo"]').click();assert.deepEqual(await operations(),staged);await save(label,'editFormWidget')
 }
 await nudge('nudge0',0,[30,180,110,204],[31,180,111,204],[31,190,111,214])
 if(!checkpoint.saves.rotated){stage='rotate-page';await page.locator('.pdf-page-label').nth(1).click();await page.locator('[data-pdf-ribbon-tab="page"]').click();await page.locator('[data-source-command-id="genoffice.pdf.page.rotateRight"]').click();await waitOperations();assert.equal((await operations())[0].kind,'rotatePage');await save('rotated','rotatePage',false)}
 await nudge('nudge90',1,[60,180,80,200],[60,181,80,201],[50,181,70,201])
 stage='independent-pypdf';const verified=spawnSync(join(repo,'.venv/bin/python'),[join(frontend,'smoke/pdf-form-canvas-verify.py'),directory],{cwd:repo,encoding:'utf8'});assert.equal(verified.status,0,verified.stderr);const independent=JSON.parse(verified.stdout);await writeFile(join(directory,'independent.json'),JSON.stringify(independent,null,2))
 await Promise.all(assetChecks);await checkpointWrite;assert.ok(Object.keys(checkpoint.assets).length>0);assert.deepEqual(assetErrors,[]);assert.deepEqual(pageErrors,[]);assert.deepEqual(consoleErrors,[]);assert.deepEqual(httpErrors,[]);assert.equal(sha(await readFile(join(staticDirectory,'.vite/manifest.json'))),manifestSha256)
 const finalState=await(await fetch(origin+'/__smoke__/state')).json();assert.equal(finalState.sourceSha256,info.sourceSha256);assert.equal(finalState.savedRevisions,5);await writeFile(join(directory,'summary.json'),JSON.stringify({ok:true,directory,staticDirectory,manifestSha256,browserVersion:browser.version(),sourceSha256:info.sourceSha256,sourceUnchanged:true,independent,checkpoint,pageErrors,consoleErrors,httpErrors,assetErrors,requests:finalState.requests},null,2));console.log(JSON.stringify({ok:true,directory}));if(serverPid)process.kill(serverPid,'SIGTERM')
}catch(error){await persistCheckpoint().catch(()=>{});await page?.screenshot({path:join(directory,'failure.png'),fullPage:true}).catch(()=>{});if(page)await page.content().then(html=>writeFile(join(directory,'failure.html'),html)).catch(()=>{});await writeFile(join(directory,'failure.json'),JSON.stringify({stage,error:String(error),serverPid,resume:'Rerun with the same directory/port/frozen assets; source server intentionally retained',pageErrors,consoleErrors,httpErrors,assetErrors},null,2));throw error}
finally{await browser?.close()}
