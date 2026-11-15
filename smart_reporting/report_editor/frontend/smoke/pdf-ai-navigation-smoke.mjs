// Real native HTTP/grants, Agno and PDF viewport; provider uses ScriptedModel.
import assert from 'node:assert/strict'
import {spawn} from 'node:child_process'
import {createHash} from 'node:crypto'
import {readFile,writeFile,mkdtemp} from 'node:fs/promises'
import {join,delimiter} from 'node:path'
import {tmpdir} from 'node:os'
import {fileURLToPath} from 'node:url'
import {setTimeout as delay} from 'node:timers/promises'
import {chromium} from 'playwright'
const frontend=fileURLToPath(new URL('../',import.meta.url)),repo=fileURLToPath(new URL('../../../../',import.meta.url))
const directory=process.env.PDF_AI_NAVIGATION_DIRECTORY??await mkdtemp(join(tmpdir(),'pdf-ai-navigation-'))
const port=Number(process.env.PDF_AI_NAVIGATION_PORT??4369),origin=`http://127.0.0.1:${port}`
const server=spawn(process.env.PDF_AI_NAVIGATION_PYTHON??join(repo,'.venv/bin/python'),
 [join(frontend,'smoke/pdf-ai-read-server.py'),'--directory',directory,'--port',String(port)],
 {cwd:repo,env:{...process.env,PDF_AI_NAVIGATION_SMOKE:'1',PYTHONPATH:[repo,process.env.PYTHONPATH].filter(Boolean).join(delimiter)},stdio:'pipe'})
let log='',browser,page,posted
server.stdout.on('data',data=>{log+=data});server.stderr.on('data',data=>{log+=data})
const errors=[],checks=[],assetErrors=[],assets=new Map(),sha=bytes=>createHash('sha256').update(bytes).digest('hex')
try {
 for(let i=0;;i++){
  assert.equal(server.exitCode,null,log)
  try{if((await fetch(origin+'/__smoke__/state',{signal:AbortSignal.timeout(1000)})).ok)break}catch{}
  assert(i<240,log);await delay(250)
 }
 const info=JSON.parse(await readFile(join(directory,'server-info.json'),'utf8'))
 browser=await chromium.launch({headless:true,...(process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE?{executablePath:process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE}:{}),args:['--disable-dev-shm-usage']})
 page=await browser.newPage({viewport:{width:1550,height:1050}})
 page.on('pageerror',error=>errors.push(String(error)))
 page.on('response',response=>{
  const path=new URL(response.url()).pathname,prefix='/reports/v1/editor/assets/'
  if(path.startsWith(prefix)&&/\.(js|css)$/.test(path))checks.push((async()=>{
   assert.equal(response.status(),200);const bytes=await response.body(),disk=await readFile(join(frontend,'../static',path.slice(prefix.length)))
   assert.equal(sha(bytes),sha(disk));assets.set(path,sha(bytes))
  })().catch(error=>assetErrors.push(String(error))))
 })
 page.on('request',request=>{if(request.url().endsWith('/ai/read/start'))posted=request.postDataJSON()})
 await page.goto(origin+info.openPath)
 await page.waitForFunction(()=>document.querySelector('#report-editor')?.getAttribute('aria-busy')==='false',null,{timeout:90000})
 const draft=()=>page.evaluate(()=>Object.fromEntries(Object.entries(localStorage).filter(([key])=>key.startsWith('native-editor-draft:'))))
 const before=await draft()
 const openAssistant=async()=>{
  const compact=page.locator('[data-action="assistant"]')
  if(await compact.count())await compact.click()
  else {await page.locator('[data-pdf-ribbon-tab="home"]').click();await page.locator('[data-source-command-id="genoffice.pdf.home.ai.openAssistant"]').click()}
 }
 await openAssistant()
 if(await page.locator('.office-workspace-native').count()){assert.equal(await page.locator('.app-bar').isVisible(),false);assert.equal(await page.locator('.pdf-ribbon').isVisible(),true)}
 const panel=page.locator('.native-pdf-assistant')
 assert.equal(await panel.locator('.office-assistant-composer select,.office-assistant-composer [role=combobox]').count(),0)
 const input=panel.getByLabel('PDF AI 问题或补充要求')
 await input.fill('多行输入尺寸核验\n'.repeat(30))
 assert.equal(await input.evaluate(node=>node.style.height),'168px')
 await input.fill('');assert.equal(await input.evaluate(node=>node.style.height),'')
 await panel.getByLabel('PDF AI 问题或补充要求').fill('请跳转到第2页，并说明费用金额。')
 await panel.locator('[data-pdf-ai="start"]').click()
 await page.waitForFunction(()=>document.querySelector('.native-pdf-assistant [role="status"]')?.textContent?.includes('已定位到第 2 页'),null,{timeout:60000})
 assert.equal(typeof posted.viewPageId,'string');assert.deepEqual(posted.operations,[]);assert.deepEqual(posted.selection,[])
 const state=await(await fetch(origin+'/__smoke__/state')).json(),result=state.jobs.at(-1).result
 assert.deepEqual(result.navigation,{page:2,pageId:result.citations.find(c=>c.pageNumber===2).pageId})
 assert(result.toolEvents.some(e=>e.tool==='goto_page'))
 assert.deepEqual(result.coverage.fullyReadPages,[1,2]);assert.equal(result.coverage.annotationsReadComplete,true)
 await page.waitForFunction(id=>{
  const node=[...document.querySelectorAll('.pdf-page')].find(n=>n.dataset.pageId===id),viewport=document.querySelector('.pdf-document-pages')
  if(!node?.classList.contains('is-active') || !viewport)return false
  const box=node.getBoundingClientRect(),view=viewport.getBoundingClientRect()
  return box.top<view.bottom&&box.bottom>view.top&&[...document.querySelectorAll('.pdf-view-page-input')].every(input=>input.value==='2')
 },result.navigation.pageId)
 await page.waitForFunction(id=>[...document.querySelectorAll('.pdf-page')].find(n=>n.dataset.pageId===id)?.textContent?.includes('expenses are 12'),result.navigation.pageId,{timeout:20000})
 assert.equal(state.sourceSha256,info.sourceSha256);assert.deepEqual(await draft(),before)
 assert(!state.requests.some(r=>r.method==='POST'&&!r.path.includes('/ai/read/')))
 assert.equal(state.editingEnabled,false);assert.equal(state.pdfTextEnabled,false)
 await Promise.all(checks);assert.deepEqual(assetErrors,[]);assert.deepEqual(errors,[])
 assert([...assets.keys()].some(path=>path.includes('pdf-ai-navigation')))
 await page.screenshot({path:join(directory,'navigated.png'),fullPage:true})
 const secondRequest=page.waitForRequest(request=>request.url().endsWith('/ai/read/start'))
 await panel.getByLabel('PDF AI 问题或补充要求').fill('继续说明第二页的费用。')
 await panel.locator('[data-pdf-ai="start"]').click();await secondRequest
 await panel.locator('.office-assistant-close').click()
 await page.waitForFunction(()=>document.querySelectorAll('.native-pdf-assistant .native-ai-answer').length===2,null,{timeout:60000})
 assert.equal(await panel.isVisible(),false)
 await openAssistant()
 await page.waitForFunction(()=>{
  const body=document.querySelector('.native-pdf-assistant .office-assistant-body')
  return body && body.clientHeight>0 && body.scrollHeight-body.scrollTop-body.clientHeight<2
 },null,{timeout:20000})
 await page.screenshot({path:join(directory,'reopened.png'),fullPage:true})
 const finalState=await(await fetch(origin+'/__smoke__/state')).json()
 assert.equal(finalState.sourceSha256,info.sourceSha256);assert.deepEqual(await draft(),before)
 assert(!finalState.requests.some(r=>r.method==='POST'&&!r.path.includes('/ai/read/')))
 await Promise.all(checks);assert.deepEqual(errors,[]);assert.deepEqual(assetErrors,[])
 const requests=finalState.requests.map(r=>({...r,path:r.path.replace(/\/open\/.+$/,'/open/<fixture-grant>')}))
 await writeFile(join(directory,'evidence.json'),JSON.stringify({status:'passed',posted,result,composerSizingVerified:true,reopenFollowVerified:true,sourceSha256:state.sourceSha256,requests,errors,assets:Object.fromEntries(assets)},null,2))
 console.log('PDF navigation browser passed: '+directory)
} catch(error) {
 if(page){await page.screenshot({path:join(directory,'failed.png'),fullPage:true}).catch(()=>{});await writeFile(join(directory,'failed.json'),JSON.stringify({error:String(error),errors,text:await page.locator('body').innerText().catch(()=>''),log},null,2))}
 throw error
} finally {await browser?.close();server.kill('SIGTERM')}
