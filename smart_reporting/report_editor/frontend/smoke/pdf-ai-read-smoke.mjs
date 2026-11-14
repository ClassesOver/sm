import assert from 'node:assert/strict'
import {spawn} from 'node:child_process'
import {createHash} from 'node:crypto'
import {mkdir, readFile, writeFile} from 'node:fs/promises'
import {join} from 'node:path'
import {fileURLToPath} from 'node:url'
import {setTimeout as delay} from 'node:timers/promises'
import {chromium} from 'playwright'

const frontend=fileURLToPath(new URL('../',import.meta.url)), repo=fileURLToPath(new URL('../../../../',import.meta.url))
const checkpoint=process.env.PDF_AI_READ_SMOKE_DIRECTORY??'/tmp/pdf-ai-read-built-20261111-final-01'
const port=Number(process.env.PDF_AI_READ_SMOKE_PORT??4285), origin='http://127.0.0.1:'+port
const sha=bytes=>createHash('sha256').update(bytes).digest('hex')
await mkdir(checkpoint,{recursive:true})
const manifest=await readFile(join(frontend,'../static/.vite/manifest.json'))
try {assert.deepEqual(await readFile(join(checkpoint,'build-manifest.json')),manifest)} catch(error) {if(error.code!=='ENOENT')throw error;await writeFile(join(checkpoint,'build-manifest.json'),manifest)}
const server=spawn(join(repo,'.venv/bin/python'),[join(frontend,'smoke/pdf-ai-read-server.py'),'--directory',checkpoint,'--port',String(port)],{cwd:repo,env:{...process.env,PYTHONPATH:repo},stdio:'pipe'})
let serverLog='', browser, page, stage='server'
server.stdout.on('data',data=>{serverLog+=data});server.stderr.on('data',data=>{serverLog+=data})
const errors=[], consoleErrors=[], httpErrors=[], checks=[], assets=new Map(), results=[]
try {
  for(let i=0;;i++){assert.equal(server.exitCode,null,serverLog);try{if((await fetch(origin+'/__smoke__/state')).ok)break}catch{}assert(i<240,serverLog);await delay(250)}
  const info=JSON.parse(await readFile(join(checkpoint,'server-info.json'),'utf8'))
  browser=await chromium.launch({headless:true});page=await browser.newPage({viewport:{width:1550,height:1100}})
  page.on('pageerror',error=>errors.push(error.message))
  page.on('console',message=>{if(message.type()==='error')consoleErrors.push(message.text())})
  page.on('response',response=>{if(response.status()>=400)httpErrors.push({path:new URL(response.url()).pathname,status:response.status()})})
  page.on('response',response=>{const path=new URL(response.url()).pathname;if(!path.startsWith('/reports/v1/editor/assets/')||!path.endsWith('.js'))return;checks.push((async()=>{assert.equal(response.status(),200);const bytes=await response.body();const disk=await readFile(join(frontend,'../static',path.slice('/reports/v1/editor/assets/'.length)));assert.equal(sha(bytes),sha(disk));assets.set(path,sha(bytes))})())})
  stage='open-real-grant';await page.goto(origin+info.openPath)
  await page.waitForFunction(()=>document.querySelector('#report-editor')?.getAttribute('aria-busy')==='false',null,{timeout:60000})
  const caps=await page.evaluate(async()=>await(await fetch(location.pathname+'/api/context')).json())
  assert.equal(caps.editingEnabled,false);assert.equal(caps.pdfTextEnabled,false);assert.equal(caps.pdfReadAIEnabled,true)
  assert.equal(await page.locator('[data-action="save"]').isDisabled(),true)
  const entrySources=await page.evaluate(()=>[...document.scripts].map(script=>new URL(script.src).pathname).filter(path=>path.startsWith('/reports/v1/editor/assets/')))
  const initial=await(await fetch(origin+'/__smoke__/state')).json()
  const writes=state=>state.requests.filter(req=>req.method==='POST'&&!req.path.includes('/ai/read/'))
  const baselineWrites=writes(initial)
  await writeFile(join(checkpoint,'read-only-initialization.json'),JSON.stringify({baselineWrites,consoleErrors,httpErrors},null,2))
  assert.deepEqual(baselineWrites,[],'只读会话初始化不得请求编辑 preview/save')
  assert.deepEqual(consoleErrors,[],'只读初始化不得有 console error')
  assert.deepEqual(httpErrors,[],'只读初始化不得有 HTTP 错误')
  const actualPanel=page.locator('.native-pdf-assistant')
  const before=await page.evaluate(()=>Object.fromEntries(Object.keys(localStorage).filter(key=>key.startsWith('native-editor-draft:')).map(key=>[key,localStorage.getItem(key)])))
  for(const item of [{action:'ask',tab:'home',id:'home.ai.openAssistant'},{action:'summarize',tab:'home',id:'home.ai.summarize'},{action:'keyPoints',tab:'home',id:'home.ai.keyPoints'},{action:'reviewSummary',tab:'annotate',id:'annotate.aiReview.summary'}]) {
    stage=item.action;await page.locator('[data-pdf-ribbon-tab="'+item.tab+'"]').click()
    const button=page.locator('[data-source-command-id="genoffice.pdf.'+item.id+'"]');assert.equal(await button.isDisabled(),false);assert.equal(await button.locator('svg').count(),1)
    const headings=await page.locator('[data-pdf-ribbon-panel="'+item.tab+'"] .pdf-ribbon-group h2').allTextContents();assert.equal(headings.some(text=>/AI Review|Draw Tools|Edit|Markup/.test(text)),false,JSON.stringify(headings))
    await button.click()
    await actualPanel.waitFor({state:'visible'})
    await actualPanel.getByLabel('PDF AI 问题或补充要求').scrollIntoViewIfNeeded();assert.equal(await actualPanel.getByLabel('PDF AI 问题或补充要求').isEditable(),true)
    const dimensions=await actualPanel.evaluate(panel=>{const input=panel.querySelector('textarea'),rect=input.getBoundingClientRect(),style=getComputedStyle(panel);return{width:rect.width,height:rect.height,maxHeight:parseFloat(style.maxHeight),overflowY:style.overflowY,viewport:innerHeight}})
    assert(dimensions.width>=250&&dimensions.height>=50,JSON.stringify(dimensions));assert(dimensions.maxHeight<=dimensions.viewport*.46);assert.equal(dimensions.overflowY,'auto')
    if(item.action==='ask'){await actualPanel.getByLabel('PDF AI 问题或补充要求').fill('收入和费用各是多少？请读取全文及批注。');await actualPanel.locator('[data-pdf-ai="start"]').click()}
    await page.waitForFunction(()=>document.querySelector('.native-pdf-assistant [role="status"]')?.textContent==='阅读完成，文档与草稿未修改。',null,{timeout:60000})
    assert.match(await actualPanel.locator('.native-ai-answer').innerText(),/收入为42/)
    const evidence=await actualPanel.locator('.native-ai-evidence').innerText();assert.match(evidence,/实际读取页码：1、2/);assert.match(evidence,/read_pages/);assert.match(evidence,/read_annotations/);assert.match(evidence,/get_outline/)
    assert.equal(await actualPanel.getByRole('button',{name:'转到第 1 页',exact:true}).count(),1)
    assert.equal(await actualPanel.getByRole('button',{name:'转到第 2 页',exact:true}).count(),1)
    const state=await(await fetch(origin+'/__smoke__/state')).json(), job=state.jobs.at(-1), result=job.result
    assert.equal(job.status,'completed');assert.deepEqual(result.coverage.fullyReadPages,[1,2]);assert.equal(result.coverage.fullDocumentRead,true);assert.equal(result.coverage.annotationsReadComplete,true);assert.equal(result.coverage.ocrPerformed,false);assert.deepEqual(result.issues,[])
    assert.deepEqual(new Set(result.toolEvents.map(event=>event.tool)),new Set(['read_pages','read_annotations','get_outline']))
    assert.equal(state.sourceSha256,info.sourceSha256);assert.deepEqual(writes(state),baselineWrites)
    const navigation=[]
    for(const number of [1,2]){const citation=result.citations.find(item=>item.pageNumber===number);await actualPanel.getByRole('button',{name:'转到第 '+number+' 页',exact:true}).click();await page.waitForFunction(({id,number})=>{const card=[...document.querySelectorAll('.pdf-page')].find(node=>node.getAttribute('data-page-id')===id),viewport=document.querySelector('.pdf-document-pages'),inputs=[...document.querySelectorAll('.pdf-view-page-input')];if(!card||!card.classList.contains('is-active')||!viewport||!inputs.length||!inputs.every(input=>input.value===String(number)))return false;const rect=card.getBoundingClientRect(),visible=viewport.getBoundingClientRect();return rect.top>=visible.top-10&&rect.top<visible.bottom},{id:citation.pageId,number});navigation.push({pageNumber:number,pageId:citation.pageId,visible:true,active:true,pageInputsMatch:true})}
    await page.screenshot({path:join(checkpoint,item.action+'.png'),fullPage:true});results.push({action:item.action,result,evidence,navigation,dimensions,headings})
    await writeFile(join(checkpoint,item.action+'-result.json'),JSON.stringify(results.at(-1),null,2))
  }
  assert.deepEqual(await page.evaluate(()=>Object.fromEntries(Object.keys(localStorage).filter(key=>key.startsWith('native-editor-draft:')).map(key=>[key,localStorage.getItem(key)]))),before)
  stage='pagehide-cancel';await page.request.post(origin+'/__smoke__/block-next')
  await page.locator('[data-pdf-ribbon-tab="home"]').click();await page.locator('[data-source-command-id="genoffice.pdf.home.ai.openAssistant"]').click()
  await actualPanel.getByLabel('PDF AI 问题或补充要求').fill('取消探针：等待服务端确认后离开页面。');await actualPanel.locator('[data-pdf-ai="start"]').click()
  for(let i=0;;i++){const state=await(await fetch(origin+'/__smoke__/state')).json();if(state.blockedEntered)break;assert(i<100,'取消探针任务未进入');await delay(100)}
  await page.goto('about:blank')
  let cancelEvidence
  for(let i=0;;i++){const state=await(await fetch(origin+'/__smoke__/state')).json();if(state.blockedCancelled&&state.jobs.at(-1)?.status==='cancelled'){cancelEvidence={pagehide:true,cancelled:true,lastJob:state.jobs.at(-1)};break}assert(i<100,'pagehide后真实后端任务未取消');await delay(100)}
  await checks.reduce(async(previous,check)=>{await previous;await check},Promise.resolve());assert.deepEqual(errors,[])
  assert.deepEqual(await readFile(join(frontend,'../static/.vite/manifest.json')),manifest)
  const state=await(await fetch(origin+'/__smoke__/state')).json();assert.equal(state.jobs.length,5);assert.equal(state.jobs.filter(job=>job.status==='completed').length,4);assert.equal(state.sourceSha256,info.sourceSha256)
  assert.deepEqual(writes(state).filter(req=>req.path.startsWith('/reports/v1/native/')),[])
  assert.deepEqual(consoleErrors,[]);assert.deepEqual(httpErrors,[])
  const summary={ok:true,checkpoint,browserVersion:browser.version(),manifestSha256:sha(manifest),entryJs:entrySources.map(path=>({path,sha256:assets.get(path)})),provider:'ScriptedModel through actual Agno; not a real provider',http:'uvicorn FastAPI real routers/workspace/grant/cookie; scoped in-memory revision lookup',readOnly:true,initialPreviewAttempts:baselineWrites,cancelEvidence,sourceSha256:state.sourceSha256,results,assets:Object.fromEntries(assets),errors,consoleErrors,httpErrors}
  await writeFile(join(checkpoint,'summary.json'),JSON.stringify(summary,null,2));console.log(JSON.stringify({ok:true,checkpoint,cases:results.length,assets:assets.size}))
} catch(error) {
  if(page){await writeFile(join(checkpoint,'failure.html'),await page.content()).catch(()=>{});await page.screenshot({path:join(checkpoint,'failure.png'),fullPage:true}).catch(()=>{})}
  console.error(JSON.stringify({stage,checkpoint}));throw error
} finally {
  await browser?.close();server.kill();await writeFile(join(checkpoint,'server.log'),serverLog)
}
