import assert from 'node:assert/strict'
import {spawn} from 'node:child_process'
import {createHash} from 'node:crypto'
import {cp,mkdir,readFile,writeFile} from 'node:fs/promises'
import {join} from 'node:path'
import {fileURLToPath} from 'node:url'
import {setTimeout as delay} from 'node:timers/promises'
import {chromium} from 'playwright'
const frontend=fileURLToPath(new URL('../',import.meta.url)),repo=fileURLToPath(new URL('../../../../',import.meta.url))
const directory=process.env.PPTX_AI_NOTES_DIRECTORY??'/tmp/office-ai-notes-browser-20261111',build=process.env.PPTX_AI_NOTES_BUILD??'/tmp/office-ai-notes-final-20261111/static'
const port=Number(process.env.PPTX_AI_NOTES_PORT??4318),origin='http://127.0.0.1:'+port,staticRoot=process.env.PPTX_AI_NOTES_REUSE_STATIC==='1'?build:join(directory,'static'),sha=value=>createHash('sha256').update(value).digest('hex')
await mkdir(directory,{recursive:true});if(staticRoot!==build)await cp(build,staticRoot,{recursive:true,errorOnExist:true,force:false});const manifest=await readFile(join(staticRoot,'.vite/manifest.json'))
const server=spawn(join(repo,'.venv/bin/python'),[join(frontend,'smoke/pptx-ai-objects-server.py'),'--directory',directory,'--port',String(port)],{cwd:repo,env:{...process.env,PYTHONPATH:repo,PPTX_AI_OBJECTS_STATIC_ROOT:staticRoot,PPTX_AI_NOTES_SMOKE:'1'},stdio:'pipe'})
let log='',browser,page;server.stdout.on('data',data=>log+=data);server.stderr.on('data',data=>log+=data)
const errors=[],consoleErrors=[],httpErrors=[],assets=new Map(),checks=[]
try{
 for(let i=0;;i++){assert.equal(server.exitCode,null,log);try{if((await fetch(origin+'/__smoke__/state')).ok)break}catch{}assert(i<240,log);await delay(250)}
 const info=JSON.parse(await readFile(join(directory,'server-info.json')));assert.equal(info.model.slides[0].notesEditable,true)
 browser=await chromium.launch({headless:true});page=await browser.newPage({viewport:{width:1600,height:1200}})
 page.on('pageerror',e=>errors.push(e.message));page.on('console',m=>{if(m.type()==='error')consoleErrors.push(m.text())});page.on('response',r=>{const path=new URL(r.url()).pathname;if(r.status()>=400)httpErrors.push({path,status:r.status()});if(path.startsWith('/reports/v1/editor/assets/')&&path.endsWith('.js'))checks.push((async()=>{assert.equal(r.status(),200);const content=await r.body();assert.equal(sha(content),sha(await readFile(join(staticRoot,path.slice('/reports/v1/editor/assets/'.length)))));assets.set(path,sha(content))})())})
 await page.goto(origin+info.openPaths.notes);await page.waitForFunction(()=>document.querySelector('#report-editor')?.getAttribute('aria-busy')==='false',null,{timeout:60000})
 const styleOverlay=process.env.PPTX_AI_NOTES_STYLE_OVERLAY?await readFile(process.env.PPTX_AI_NOTES_STYLE_OVERLAY,'utf8'):undefined
 if(styleOverlay)await page.addStyleTag({content:styleOverlay})
 if(process.env.PPTX_AI_NOTES_LAYOUT_ONLY==='1'){
  await page.locator('[data-action=office-edit-ai]').click();const panel=page.getByRole('region',{name:'PPTX AI 助手',exact:true})
  await page.getByRole('button',{name:'浮动 AI 助手',exact:true}).click()
  async function geometry(){const outer=await panel.boundingBox(),composer=await panel.locator('.office-assistant-composer').boundingBox();assert(outer&&composer);assert(composer.width>=outer.width-40,JSON.stringify({outer,composer}));return{outer,composer}}
  const desktop=await geometry();await page.screenshot({path:join(directory,'layout-desktop.png'),fullPage:true})
  await page.setViewportSize({width:390,height:740});const narrow=await geometry();await page.screenshot({path:join(directory,'layout-narrow.png'),fullPage:true})
  await Promise.all(checks);assert.deepEqual(errors,[]);assert.deepEqual(consoleErrors,[]);assert.deepEqual(httpErrors,[])
  await writeFile(join(directory,'summary.json'),JSON.stringify({ok:true,layoutOnly:true,styleOverlaySha256:styleOverlay?sha(styleOverlay):null,desktop,narrow,manifestSha256:sha(manifest),staticRoot,assets:Object.fromEntries(assets),errors,consoleErrors,httpErrors},null,2));console.log(JSON.stringify({ok:true,directory,layoutOnly:true}))
 }else{
 // 先写人工备注草稿，AI必须以当前草稿为基础，未接受前不改变它。
 const manual='人工备注草稿：收入42，费用17；保留事实。'
 const notes=page.getByRole('textbox',{name:'演讲者备注',exact:true});await notes.fill(manual);await notes.blur()
 const drafts=()=>page.evaluate(()=>Object.keys(localStorage).filter(k=>k.startsWith('native-editor-draft:')).map(k=>JSON.parse(localStorage.getItem(k))))
 await page.locator('[data-action=office-edit-ai]').click();const panel=page.getByRole('region',{name:'PPTX AI 助手',exact:true})
 await panel.getByLabel('AI 授权范围',{exact:true}).selectOption('notes');await panel.locator('textarea').fill('润色本页演讲者备注，收入42、费用17保持不变。')
 const before=await drafts();assert.equal(before.length,1);assert.deepEqual(before[0].operations[0].notesEdits,[{slideIndex:0,text:manual}])
 await panel.locator('[type=submit]').click();await page.waitForFunction(()=>document.querySelector('.slides-native-ai .native-ai-preview')?.hidden===false,null,{timeout:60000});assert.deepEqual(await drafts(),before)
 const preview=await panel.locator('.native-ai-preview').innerText();assert(preview.includes(manual));assert(preview.includes('演讲稿候选'))
 let state=await(await fetch(origin+'/__smoke__/state')).json(),job=state.jobs.at(-1);assert.equal(job.status,'succeeded',JSON.stringify(job));const start=state.requests.filter(r=>r.path.endsWith('/slides-ai/start')).at(-1);assert.equal(start.body.scope,'notes');assert.deepEqual(start.body.selection,[{slideIndex:0}]);assert.deepEqual(start.body.operations,before[0].operations)
 assert(!job.proposal.operations[0].edits?.length);assert(!job.proposal.operations[0].tableCells?.length);assert(!job.proposal.operations[0].chartEdits?.length)
 const events=job.events.filter(e=>e.kind==='toolCompleted');assert.deepEqual(events.map(e=>e.toolName),['get_presentation_context','read_slide','propose_operations'])
 await page.getByRole('button',{name:'浮动 AI 助手',exact:true}).click();await page.screenshot({path:join(directory,'notes-floating-candidate.png'),fullPage:true});assert.deepEqual(await drafts(),before)
 await panel.locator('.native-ai-accept').click();await page.waitForFunction(()=>document.querySelector('.slides-native-ai .native-ai-status')?.textContent?.startsWith('候选已加入草稿'),null,{timeout:60000})
 const after=await drafts();assert.equal(after[0].operations[0].notesEdits[0].text,'演讲稿候选：本期收入42，费用17；请重点说明收入与费用结构。')
 state=await(await fetch(origin+'/__smoke__/state')).json();job=state.jobs.find(j=>j.editId===job.editId);const actual=job.independentReadback;assert.equal(actual.notes[0],after[0].operations[0].notesEdits[0].text);assert.equal(actual.notes[1],'未授权备注秘密：不可读取或修改');assert.equal(actual.texts[0][0],'经营数据：收入42，费用17。');assert.equal(actual.tables[0][1][1],'42');assert.deepEqual(actual.charts[0].series[0].values,[42,17]);assert.equal(state.sourceSha256,info.sourceSha256);assert.equal(sha(await readFile(job.actualPatchedPath)),job.actualPatchedSha256)
 assert(!state.requests.some(r=>r.method==='POST'&&/\/(save|export)$/.test(r.path)));await page.screenshot({path:join(directory,'notes-accepted.png'),fullPage:true});await Promise.all(checks);assert(assets.size>0);assert.deepEqual(errors,[]);assert.deepEqual(consoleErrors,[]);assert.deepEqual(httpErrors,[])
 await writeFile(join(directory,'summary.json'),JSON.stringify({ok:true,manifestSha256:sha(manifest),staticRoot,assets:Object.fromEntries(assets),preview,events,selection:start.body.selection,before,after,actualPatchedPath:job.actualPatchedPath,actualPatchedSha256:job.actualPatchedSha256,independentReadback:actual,sourceSha256:state.sourceSha256,errors,consoleErrors,httpErrors,provider:'Actual Agno with ScriptedModel; not real provider'},null,2));console.log(JSON.stringify({ok:true,directory,assets:assets.size}))
 }
}catch(error){if(page){await writeFile(join(directory,'failure.html'),await page.content()).catch(()=>{});await page.screenshot({path:join(directory,'failure.png'),fullPage:true}).catch(()=>{})}throw error}finally{await browser?.close();server.kill();await writeFile(join(directory,'server.log'),log)}
