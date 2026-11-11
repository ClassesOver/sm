import assert from 'node:assert/strict'
import {spawn} from 'node:child_process'
import {createHash} from 'node:crypto'
import {cp,mkdir,readFile,writeFile} from 'node:fs/promises'
import {join} from 'node:path'
import {fileURLToPath} from 'node:url'
import {setTimeout as delay} from 'node:timers/promises'
import {chromium} from 'playwright'

const frontend=fileURLToPath(new URL('../',import.meta.url)),repo=fileURLToPath(new URL('../../../../',import.meta.url))
const directory=process.env.PDF_AI_FORMS_DIRECTORY??'/tmp/pdf-ai-forms-20261111',build=process.env.PDF_AI_FORMS_BUILD??'/tmp/pdf-ai-forms-20261111-build/static'
const port=Number(process.env.PDF_AI_FORMS_PORT??4302),origin='http://127.0.0.1:'+port,staticRoot=join(directory,'static')
const sha=bytes=>createHash('sha256').update(bytes).digest('hex')
await mkdir(directory,{recursive:true});await cp(build,staticRoot,{recursive:true,errorOnExist:true,force:false})
const manifest=await readFile(join(staticRoot,'.vite/manifest.json'));await writeFile(join(directory,'build-manifest.json'),manifest)
const server=spawn(join(repo,'.venv/bin/python'),[join(frontend,'smoke/pdf-ai-forms-server.py'),'--directory',directory,'--port',String(port)],{cwd:repo,env:{...process.env,PYTHONPATH:repo,PDF_AI_FORMS_STATIC_ROOT:staticRoot},stdio:'pipe'})
let serverLog='',browser,page,stage='startup';server.stdout.on('data',data=>serverLog+=data);server.stderr.on('data',data=>serverLog+=data)
const errors=[],consoleErrors=[],httpErrors=[],assets=new Map(),checks=[],results=[]
const state=async()=>await(await fetch(origin+'/__smoke__/state')).json()
try{
 for(let i=0;;i++){assert.equal(server.exitCode,null,serverLog);try{if((await fetch(origin+'/__smoke__/state')).ok)break}catch{}assert(i<200,serverLog);await delay(250)}
 const info=JSON.parse(await readFile(join(directory,'server-info.json'),'utf8'))
 browser=await chromium.launch({headless:true});page=await browser.newPage({viewport:{width:1600,height:1200}})
 page.on('pageerror',error=>errors.push(error.message));page.on('console',message=>{if(message.type()==='error')consoleErrors.push(message.text())})
 page.on('response',response=>{
  const path=new URL(response.url()).pathname;if(response.status()>=400)httpErrors.push({path,status:response.status()})
  if(!path.startsWith('/reports/v1/editor/assets/')||!path.endsWith('.js'))return
  const check=(async()=>{assert.equal(response.status(),200);const bytes=await response.body(),disk=await readFile(join(staticRoot,path.slice('/reports/v1/editor/assets/'.length)));assert.equal(sha(bytes),sha(disk));assets.set(path,sha(bytes))})();check.catch(()=>{});checks.push(check)
 })
 const ready=()=>page.waitForFunction(()=>document.querySelector('#report-editor')?.getAttribute('aria-busy')==='false',null,{timeout:60000})
 await page.goto(origin+info.openPath);await ready()
 const draft=()=>page.evaluate(()=>Object.keys(localStorage).filter(k=>k.startsWith('native-editor-draft:')).map(k=>JSON.parse(localStorage.getItem(k))))
 async function open(){await page.locator('[data-pdf-ribbon-tab="fillForm"]').click();const entry=page.locator('[data-pdf-form-ai-entry]');assert.equal(await entry.isDisabled(),false);assert.equal(await entry.locator('svg').count(),1);await entry.click();return page.getByRole('region',{name:'AI 填写 PDF 表单',exact:true})}
 stage='normal';let panel=await open()
 await page.getByRole('complementary',{name:'PDF AI 助手侧栏',exact:true}).waitFor({state:'visible'})
 const dockBox=await page.locator('.pdf-ai-dock').boundingBox(),canvasBox=await page.locator('.pdf-layout').boundingBox();assert(dockBox&&canvasBox);assert(dockBox.x>=canvasBox.x+canvasBox.width-2);assert(canvasBox.width>500)
 const selects=panel.locator('[data-pdf-form-ai-field]');assert.equal(await selects.count(),5);assert.equal(await selects.evaluateAll(inputs=>inputs.filter(input=>input.checked).length),0)
 const targetNames=['contact.name','consent','region','plan'],targetIds=info.model.formFields.filter(f=>targetNames.includes(f.name)).map(f=>f.fieldId)
 for(const id of targetIds)await panel.locator(`[data-pdf-form-ai-field="${id}"]`).check()
 await panel.getByLabel('AI 表单填写要求').fill('只填写勾选的四个字段：姓名Lin、同意勾选、地区south、套餐pro；其他字段保留。')
 const before=await draft();await panel.locator('[data-pdf-form-ai="start"]').click()
 await panel.getByRole('status').filter({hasText:'填写建议已核验'}).waitFor({timeout:90000})
 assert.deepEqual(await draft(),before)
 let current=await state(),job=current.jobs.at(-1);assert.equal(job.status,'succeeded',JSON.stringify(job))
 const start=current.requests.filter(r=>r.path.endsWith('/ai/forms/start')).at(-1)
 assert.deepEqual(start.body.selection.map(f=>f.fieldId).sort(),targetIds.sort());assert.deepEqual(start.body.operations,[])
 const proposal=job.result.proposal;assert.equal(proposal.changes.length,4);assert.equal(proposal.operations.length,4)
 const visible=await panel.innerText();assert.match(visible,/Original.*Lin/);assert.match(visible,/未勾选.*已勾选/);assert.match(visible,/north.*south/);assert.match(visible,/basic.*pro/)
 await page.waitForFunction(()=>document.querySelector('.native-pdf-form-ai [aria-label="AI 执行进度"]')?.textContent?.includes('读取表单字段'),null,{timeout:10000})
 assert(!JSON.stringify(current.readPayloads).includes('UNSELECTED_SECRET_729463'))
 assert.deepEqual(job.events.filter(e=>e.kind==='toolCompleted').map(e=>[e.toolName,e.toolCallId,e.outcome]),[['list_form_fields','forms-read','success'],['apply_ops','forms-propose','success']])
 const layout=await panel.evaluate(element=>{
  const bounds=node=>{const rect=node.getBoundingClientRect();return{top:rect.top,bottom:rect.bottom,height:rect.height}}
  const body=element.querySelector('.office-assistant-body'),composer=element.querySelector('.office-assistant-composer')
  return{panel:bounds(element),header:bounds(element.querySelector('.office-assistant-header')),body:bounds(body),composer:bounds(composer),overflow:getComputedStyle(body).overflowY,inputInsideComposer:composer.contains(element.querySelector('textarea')),resultInsideBody:body.contains(element.querySelector('.native-ai-evidence'))}
 })
 assert(layout.header.bottom<=layout.body.top+1);assert(layout.body.bottom<=layout.composer.top+1)
 assert(layout.body.height>100);assert(layout.composer.bottom<=layout.panel.bottom+1&&layout.composer.bottom>=layout.panel.bottom-24)
 assert.equal(layout.overflow,'auto');assert.equal(layout.inputInsideComposer,true);assert.equal(layout.resultInsideBody,true)
 results.push({kind:'genoffice-layout',...layout})
 stage='floating';const dock=page.locator('.pdf-ai-dock'),instruction=await panel.getByLabel('AI 表单填写要求').inputValue()
 await dock.getByRole('button',{name:'浮动 AI 助手',exact:true}).click()
 assert.equal(await dock.evaluate(element=>element.classList.contains('is-office-assistant-floating')),true)
 const floating=await dock.boundingBox(),header=await dock.locator(':scope > .office-assistant-window-header').boundingBox();assert(floating&&header)
 await page.mouse.move(header.x+120,header.y+20);await page.mouse.down();await page.mouse.move(480,210,{steps:8});await page.mouse.up()
 const moved=await dock.boundingBox();assert(moved);assert(Math.abs(moved.x-floating.x)>20)
 assert.equal(await panel.getByLabel('AI 表单填写要求').inputValue(),instruction);assert.deepEqual(await draft(),before)
 await page.screenshot({path:join(directory,'form-floating-desktop.png'),fullPage:true})
 await page.setViewportSize({width:390,height:740})
 const floatingNarrow=await dock.boundingBox();assert(floatingNarrow)
 assert(floatingNarrow.x>=0&&floatingNarrow.y>=0&&floatingNarrow.x+floatingNarrow.width<=391&&floatingNarrow.y+floatingNarrow.height<=741,JSON.stringify(floatingNarrow))
 await page.screenshot({path:join(directory,'form-floating-narrow.png'),fullPage:true})
 await dock.getByRole('button',{name:'停靠 AI 助手',exact:true}).click()
 assert.equal(await dock.evaluate(element=>element.classList.contains('is-office-assistant-floating')),false)
 await page.setViewportSize({width:1600,height:1200})
 const restored=await dock.boundingBox(),restoredCanvas=await page.locator('.pdf-layout').boundingBox();assert(restored&&restoredCanvas);assert(restored.x>=restoredCanvas.x+restoredCanvas.width-2)
 assert.equal(await panel.getByLabel('AI 表单填写要求').inputValue(),instruction);assert.deepEqual(await draft(),before)
 results.push({kind:'floating',floating,moved,narrow:floatingNarrow,restored,preservedInput:true,preservedDraft:true})
 stage='normal'
 await page.screenshot({path:join(directory,'form-candidate.png'),fullPage:true})
 stage='accept';await panel.locator('[data-pdf-form-ai="accept"]').click();await panel.getByRole('status').filter({hasText:'填写建议已进入草稿'}).waitFor({timeout:90000})
 const after=await draft();assert.equal(after.length,1);assert.deepEqual(after[0].operations,proposal.operations)
 assert.equal(await page.getByLabel('contact.name',{exact:true}).inputValue(),'Lin');assert.equal(await page.getByLabel('consent',{exact:true}).isChecked(),true)
 current=await state();job=current.jobs.at(-1);const back=job.independentReadback
 assert.equal(back['contact.name'].value,'Lin');assert.equal(back.consent.value,'/Yes');assert.equal(back.region.value,'south');assert.equal(back.plan.value,'/pro');assert.equal(back.secret.value,'UNSELECTED_SECRET_729463')
 assert.equal(sha(await readFile(job.actualPatchedPath)),job.actualPatchedSha256);assert.equal(current.sourceSha256,info.sourceSha256)
 assert(!current.requests.some(r=>r.method==='POST'&&/\/(save|export)$/.test(r.path)));assert(current.requests.some(r=>r.path.endsWith('/events')))
 await page.screenshot({path:join(directory,'form-accepted.png'),fullPage:true});results.push({kind:'fill',selection:start.body.selection,proposal,actualPatchedPath:job.actualPatchedPath,actualPatchedSha256:job.actualPatchedSha256,independentReadback:back,sourceSha256:current.sourceSha256})
 stage='cancel';await fetch(origin+'/__smoke__/mode/cancel',{method:'POST'});panel=await open();await panel.locator('[data-pdf-form-ai="start"]').click()
 for(let i=0;!(await state()).blockedEntered;i++){assert(i<200);await delay(100)}
 await panel.locator('[data-pdf-form-ai="cancel"]').click()
 for(let i=0;;i++){current=await state();job=current.jobs.at(-1);if(job.status==='cancelled'){assert.equal(current.blockedCancelled,true);assert(!job.result);break}assert(i<200);await delay(100)}
 assert.deepEqual(await draft(),after);results.push({kind:'cancel',status:job.status,swallowedCancellationCannotRevive:true})
 stage='dock-switch';await page.locator('[data-pdf-ai-mode=read]').click();await page.getByRole('region',{name:'PDF AI 助手',exact:true}).waitFor({state:'visible'});assert.equal(await panel.isVisible(),false)
 await page.locator('[data-pdf-ai-mode=forms]').click();await panel.waitFor({state:'visible'});await panel.getByRole('button',{name:'关闭助手',exact:true}).click();await page.getByRole('complementary',{name:'PDF AI 助手侧栏',exact:true}).waitFor({state:'hidden'});assert.deepEqual(await draft(),after)
 await page.setViewportSize({width:780,height:1000});panel=await open();const narrow=await page.locator('.pdf-ai-dock').boundingBox();assert(narrow&&narrow.width<=780*.92);await page.screenshot({path:join(directory,'form-narrow-dock.png'),fullPage:true});results.push({kind:'dock',desktopAdjacent:true,narrowWidth:narrow.width,closeHidesDock:true})
 await Promise.all(checks);assert(assets.size>0);assert.deepEqual(await readFile(join(staticRoot,'.vite/manifest.json')),manifest);assert.deepEqual(errors,[]);assert.deepEqual(consoleErrors,[]);assert.deepEqual(httpErrors,[])
 await writeFile(join(directory,'summary.json'),JSON.stringify({ok:true,directory,staticRoot,manifestSha256:sha(manifest),assets:Object.fromEntries(assets),browserVersion:browser.version(),results,errors,consoleErrors,httpErrors,provider:'ScriptedModel through actual Agno; real provider separately verified'},null,2))
 console.log(JSON.stringify({ok:true,cases:results.length,assets:assets.size,directory}))
}catch(error){if(page){await writeFile(join(directory,'failure.html'),await page.content()).catch(()=>{});await page.screenshot({path:join(directory,'failure.png'),fullPage:true}).catch(()=>{})}console.error(JSON.stringify({stage,directory}));throw error}
finally{await browser?.close();server.kill();await writeFile(join(directory,'server.log'),serverLog)}
