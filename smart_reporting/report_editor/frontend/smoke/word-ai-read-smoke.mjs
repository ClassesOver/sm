import assert from 'node:assert/strict'
import {spawn} from 'node:child_process'
import {createHash} from 'node:crypto'
import {mkdir,readFile,writeFile} from 'node:fs/promises'
import {join} from 'node:path'
import {fileURLToPath} from 'node:url'
import {setTimeout as delay} from 'node:timers/promises'
import {chromium} from 'playwright'

const frontend=fileURLToPath(new URL('../',import.meta.url)),repo=fileURLToPath(new URL('../../../../',import.meta.url))
const checkpoint=process.env.WORD_AI_READ_SMOKE_DIRECTORY??'/tmp/word-ai-read-20261111'
const port=Number(process.env.WORD_AI_READ_SMOKE_PORT??4287),origin='http://127.0.0.1:'+port
const sha=bytes=>createHash('sha256').update(bytes).digest('hex')
await mkdir(checkpoint,{recursive:true})
const manifest=await readFile(join(frontend,'../static/.vite/manifest.json'))
await writeFile(join(checkpoint,'build-manifest.json'),manifest)
const server=spawn(join(repo,'.venv/bin/python'),[join(frontend,'smoke/word-ai-read-server.py'),'--output-dir',checkpoint,'--port',String(port)],{cwd:repo,env:{...process.env,PYTHONPATH:repo},stdio:'pipe'})
let serverLog='',browser,page,stage='server'
server.stdout.on('data',data=>{serverLog+=data});server.stderr.on('data',data=>{serverLog+=data})
const errors=[],consoleErrors=[],httpErrors=[],checks=[],assets=new Map(),results=[]
try {
  for(let i=0;;i++){assert.equal(server.exitCode,null,serverLog);try{if((await fetch(origin+'/__smoke__/state')).ok)break}catch{}assert(i<240,serverLog);await delay(250)}
  const info=JSON.parse(await readFile(join(checkpoint,'server-info.json'),'utf8'))
  browser=await chromium.launch({headless:true});page=await browser.newPage({viewport:{width:1550,height:1100}})
  page.on('pageerror',error=>errors.push(error.message))
  page.on('console',message=>{if(message.type()==='error')consoleErrors.push(message.text())})
  page.on('response',response=>{if(response.status()>=400)httpErrors.push({path:new URL(response.url()).pathname,status:response.status()})})
  page.on('response',response=>{const path=new URL(response.url()).pathname;if(!path.startsWith('/reports/v1/editor/assets/')||!path.endsWith('.js'))return;checks.push((async()=>{assert.equal(response.status(),200);const bytes=await response.body(),disk=await readFile(join(frontend,'../static',path.slice('/reports/v1/editor/assets/'.length)));assert.equal(sha(bytes),sha(disk));assets.set(path,sha(bytes))})())})
  stage='open-real-grant';await page.goto(origin+info.openPath)
  await page.waitForFunction(()=>document.querySelector('#report-editor')?.getAttribute('aria-busy')==='false',null,{timeout:60000})
  await page.getByRole('textbox',{name:'Word 文档编辑区',exact:true}).waitFor()
  const caps=await page.evaluate(async()=>await(await fetch(location.pathname+'/api/context')).json())
  assert.equal(caps.wordReadAIEnabled,true);assert.equal(caps.editingEnabled,false);assert.equal(caps.aiEnabled,false)
  for(const action of ['save','export-word','export-pdf']){const button=page.locator('[data-action="'+action+'"]');if(await button.count())assert.equal(await button.isDisabled(),true)}
  const entry=page.locator('[data-action="word-read-ai"]');assert.equal(await entry.isDisabled(),false);assert.equal(await entry.locator('svg').count(),1)
  const entrySources=await page.evaluate(()=>[...document.scripts].map(script=>new URL(script.src).pathname).filter(path=>path.startsWith('/reports/v1/editor/assets/')))
  const draftState=()=>page.evaluate(()=>Object.fromEntries(Object.keys(localStorage).filter(key=>key.startsWith('native-editor-draft:')).map(key=>[key,localStorage.getItem(key)])))
  const before=await draftState(),panel=page.locator('.native-word-assistant')
  await entry.click();await panel.waitFor({state:'visible'})
  assert.match(await panel.innerText(),/Word AI 阅读助手/);assert.match(await panel.innerText(),/不含页眉、脚注和图片/)
  assert.equal(await panel.getByLabel('Word AI 阅读范围').inputValue(),'document')
  assert.equal(await panel.getByLabel('Word AI 问题或补充要求').isEditable(),true)
  for(const action of ['ask','summarize','keyPoints','start','cancel','close'])assert.equal(await panel.locator('[data-word-ai="'+action+'"] svg').count(),1)
  for(const scope of ['document','selection']) {
    stage=scope+'-summary'
    if(scope==='selection'){
      await panel.locator('[data-word-ai="close"]').click()
      const paragraph=page.getByRole('textbox',{name:'Word 文档编辑区',exact:true}).getByText(info.selectionText,{exact:true})
      await paragraph.click()
      await entry.click();await panel.getByLabel('Word AI 阅读范围').selectOption('selection')
    }
    await panel.locator('[data-word-ai="summarize"]').click()
    await page.waitForFunction(()=>document.querySelector('.native-word-assistant [role="status"]')?.textContent==='阅读完成，文档与草稿未修改。',null,{timeout:60000})
    const state=await(await fetch(origin+'/__smoke__/state')).json(),job=state.jobs.at(-1),result=job.result
    assert.equal(job.status,'completed',JSON.stringify(job));assert.equal(result.coverage.scope,scope);assert.equal(result.coverage.scopeReadComplete,true)
    assert.deepEqual(result.coverage.fullyReadBlockIds,scope==='document'?info.allBlockIds:[info.selectionBlockId])
    assert.equal(result.readingVersion,'source');assert.deepEqual(result.issues,[])
    assert.deepEqual(result.toolEvents.map(event=>event.tool),['get_document_context','read_blocks'])
    assert.match(result.answer,scope==='document'?/收入为42.*净收益为30/:/选中段落.*现金流稳定/)
    const evidence=await panel.locator('.native-ai-evidence').innerText()
    assert.match(evidence,/已核验原件/);assert.match(evidence,/范围已读完/);assert.match(evidence,/读取文档上下文/);assert.match(evidence,/读取文档内容块/)
    assert.match(evidence,new RegExp('实际完整读取：'+(scope==='document'?'3 / 3':'1 / 1')))
    const request=state.requests.filter(item=>item.path.endsWith('/word-read/start')).at(-1)
    assert.equal(request.body.action,'summarize');assert.deepEqual(request.body.operations,[])
    assert.deepEqual(request.body.selection,scope==='document'?[]:[{blockId:info.selectionBlockId}])
    assert.equal(state.sourceSha256,info.sourceSha256)
    assert.deepEqual(state.requests.filter(item=>item.method==='POST'&&!item.path.includes('/ai/word-read/')),[],'只读会话不得发送 preview/save/export 请求')
    await panel.locator('.native-ai-progress').waitFor({state:'visible'})
    await page.waitForFunction(()=>document.querySelector('.native-word-assistant [aria-label="AI 执行进度"]')?.textContent?.includes('读取文档内容块'),null,{timeout:10000})
    const progress=await panel.getByLabel('AI 执行进度').innerText();assert.match(progress,/工具/)
    await page.screenshot({path:join(checkpoint,scope+'-summary.png'),fullPage:true})
    results.push({scope,result,evidence,progress,request});await writeFile(join(checkpoint,scope+'-result.json'),JSON.stringify(results.at(-1),null,2))
  }
  assert.deepEqual(await draftState(),before)
  await Promise.all(checks);assert(assets.size>0,'必须校验实际加载JS资产')
  assert.deepEqual(await readFile(join(frontend,'../static/.vite/manifest.json')),manifest,'验收过程中构建资产不得变化')
  assert.deepEqual(errors,[]);assert.deepEqual(consoleErrors,[]);assert.deepEqual(httpErrors,[])
  const final=await(await fetch(origin+'/__smoke__/state')).json();assert.equal(final.jobs.length,2);assert.equal(final.sourceSha256,info.sourceSha256)
  assert(final.requests.some(item=>item.path.endsWith('/events')),'浏览器须真实请求SSE工具进度')
  const summary={ok:true,checkpoint,browserVersion:browser.version(),manifestSha256:sha(manifest),entryJs:entrySources.map(path=>({path,sha256:assets.get(path)})),assets:Object.fromEntries(assets),provider:'ScriptedModel through actual Agno; not a real provider',http:'uvicorn FastAPI real routers/workspace/grant/cookie; scoped in-memory revision lookup',readOnly:true,editingEnabled:caps.editingEnabled,wordReadAIEnabled:caps.wordReadAIEnabled,sourceSha256:final.sourceSha256,results,errors,consoleErrors,httpErrors}
  await writeFile(join(checkpoint,'summary.json'),JSON.stringify(summary,null,2));console.log(JSON.stringify({ok:true,checkpoint,cases:results.length,assets:assets.size}))
} catch(error) {
  if(page){await writeFile(join(checkpoint,'failure.html'),await page.content()).catch(()=>{});await page.screenshot({path:join(checkpoint,'failure.png'),fullPage:true}).catch(()=>{})}
  console.error(JSON.stringify({stage,checkpoint}));throw error
} finally {
  await browser?.close();server.kill();await writeFile(join(checkpoint,'server.log'),serverLog)
}
