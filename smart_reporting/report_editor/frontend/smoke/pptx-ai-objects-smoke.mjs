import assert from 'node:assert/strict'
import {spawn} from 'node:child_process'
import {createHash} from 'node:crypto'
import {cp,mkdir,readFile,writeFile} from 'node:fs/promises'
import {join} from 'node:path'
import {fileURLToPath} from 'node:url'
import {setTimeout as delay} from 'node:timers/promises'
import {chromium} from 'playwright'

const frontend=fileURLToPath(new URL('../',import.meta.url)),repo=fileURLToPath(new URL('../../../../',import.meta.url))
const directory=process.env.PPTX_AI_OBJECTS_DIRECTORY??'/tmp/pptx-ai-objects-20261111'
const build=process.env.PPTX_AI_OBJECTS_BUILD??'/tmp/pptx-ai-objects-20261111-build/static'
const port=Number(process.env.PPTX_AI_OBJECTS_PORT??4290),origin='http://127.0.0.1:'+port
const sha=bytes=>createHash('sha256').update(bytes).digest('hex')
await mkdir(directory,{recursive:true})
const staticRoot=join(directory,'static');await cp(build,staticRoot,{recursive:true,errorOnExist:true,force:false})
const manifest=await readFile(join(staticRoot,'.vite/manifest.json'))
await writeFile(join(directory,'build-manifest.json'),manifest)
const server=spawn(join(repo,'.venv/bin/python'),[join(frontend,'smoke/pptx-ai-objects-server.py'),'--directory',directory,'--port',String(port)],{cwd:repo,env:{...process.env,PYTHONPATH:repo,PPTX_AI_OBJECTS_STATIC_ROOT:staticRoot},stdio:'pipe'})
let serverLog='',browser,page,stage='server'
server.stdout.on('data',data=>{serverLog+=data});server.stderr.on('data',data=>{serverLog+=data})
const errors=[],consoleErrors=[],httpErrors=[],checks=[],assets=new Map(),results=[]
try{
  for(let i=0;;i++){assert.equal(server.exitCode,null,serverLog);try{if((await fetch(origin+'/__smoke__/state')).ok)break}catch{}assert(i<240,serverLog);await delay(250)}
  const info=JSON.parse(await readFile(join(directory,'server-info.json'),'utf8'))
  browser=await chromium.launch({headless:true})
  for(const kind of ['table','chart']){
    stage=kind+'-open'
    const context=await browser.newContext({viewport:{width:1600,height:1200}})
    page=await context.newPage()
    page.on('pageerror',error=>errors.push(error.message))
    page.on('console',message=>{if(message.type()==='error')consoleErrors.push(message.text())})
    page.on('response',response=>{
      const path=new URL(response.url()).pathname
      if(response.status()>=400)httpErrors.push({path,status:response.status()})
      if(path.startsWith('/reports/v1/editor/assets/')&&path.endsWith('.js'))checks.push((async()=>{
        assert.equal(response.status(),200);const bytes=await response.body()
        assert.equal(sha(bytes),sha(await readFile(join(staticRoot,path.slice('/reports/v1/editor/assets/'.length)))))
        assets.set(path,sha(bytes))
      })())
    })
    await page.goto(origin+info.openPaths[kind])
    await page.waitForFunction(()=>document.querySelector('#report-editor')?.getAttribute('aria-busy')==='false',null,{timeout:60000})
    const target=info.model.slides[0].elements.find(element=>element.type===kind)
    assert(target);if(kind==='chart')assert.equal(target.chartEditSafe,true)
    await page.getByLabel('可编辑对象',{exact:true}).selectOption(target.id)
    await page.locator('[data-action=office-edit-ai]').click()
    const panel=page.getByRole('region',{name:'PPTX AI 助手',exact:true})
    await page.getByRole('complementary',{name:'PPTX AI 助手侧栏',exact:true}).waitFor({state:'visible'})
    const box=await page.locator('.office-task-dock').boundingBox(),main=await page.locator('.office-task-main').boundingBox();assert(box&&main);assert(box.x>=main.x+main.width-2);assert(main.width>500);assert.equal(await page.locator('.office-task-workspace .slides-ribbon').count(),0)
    const composer=await panel.locator('.office-assistant-composer').boundingBox(),body=await panel.locator('.office-assistant-body').boundingBox();assert(composer&&body);assert(composer.y>=body.y+body.height-2);assert(body.height>100);assert.equal(await panel.locator('.office-assistant-composer textarea').count(),1)
    const resize=page.getByRole('separator',{name:'调整 AI 助手宽度'});await resize.focus();await resize.press('ArrowLeft');assert.equal(await resize.getAttribute('aria-valuenow'),'380');await resize.press('Home');assert.equal(await resize.getAttribute('aria-valuenow'),'280')
    await panel.getByLabel('AI 授权范围',{exact:true}).selectOption('object')
    const input=panel.locator('textarea')
    await input.fill(kind==='table'?'只把当前经营表第2行第2列收入42改为84，保留其它内容。':'只把当前经营图收入改为84，费用保持17。')
    const drafts=()=>page.evaluate(()=>Object.keys(localStorage).filter(key=>key.startsWith('native-editor-draft:')).map(key=>JSON.parse(localStorage.getItem(key))))
    const before=await drafts()
    assert.equal(await panel.locator('[type=submit] svg').count(),1)
    stage=kind+'-propose';await panel.locator('[type=submit]').click()
    await page.waitForFunction(()=>document.querySelector('.slides-native-ai .native-ai-preview')?.hidden===false,null,{timeout:60000})
    assert.deepEqual(await drafts(),before,'候选不得提前进入草稿')
    let state=await(await fetch(origin+'/__smoke__/state')).json(),job=state.jobs.at(-1)
    assert.equal(job.status,'succeeded',JSON.stringify(job))
    const start=state.requests.filter(request=>request.path.endsWith('/slides-ai/start')).at(-1)
    assert.deepEqual(start.body.selection,[{slideIndex:0,elementId:target.id}]);assert.deepEqual(start.body.operations,[])
    const operations=job.proposal.operations
    assert.equal(operations.length,1)
    assert.equal(operations[0][kind==='table'?'tableCells':'chartEdits'][0].elementId,target.id)
    assert(!operations[0][kind==='table'?'chartEdits':'tableCells']?.length)
    const preview=await panel.locator('.native-ai-preview').innerText()
    assert.match(preview,kind==='table'?/第\s*2\s*行\s*(?:第\s*)?2\s*列.*42.*84/:/本期.*42.*84/)
    const events=job.events.filter(event=>event.kind==='toolCompleted')
    assert.deepEqual(events.map(event=>[event.toolName,event.toolCallId]),[
      ['get_presentation_context','objects-context'],['read_slide','objects-read'],['propose_operations','objects-propose']])
    await page.waitForFunction(()=>document.querySelector('.slides-native-ai [aria-label="AI 执行进度"]')?.textContent?.includes('提交候选修改'),null,{timeout:10000})
    await page.screenshot({path:join(directory,kind+'-candidate.png'),fullPage:true})
    stage=kind+'-accept';await panel.locator('.native-ai-accept').click()
    await page.waitForFunction(()=>document.querySelector('.slides-native-ai .native-ai-status')?.textContent?.startsWith('候选已加入草稿'),null,{timeout:60000})
    const after=await drafts();assert.equal(after.length,1)
    assert.deepEqual(after[0].operations,operations)
    state=await(await fetch(origin+'/__smoke__/state')).json()
    const accepted=state.jobs.find(item=>item.editId===job.editId),actual=accepted.independentReadback
    assert.equal(state.sourceSha256,info.sourceSha256)
    assert.equal(sha(await readFile(accepted.actualPatchedPath)),accepted.actualPatchedSha256)
    assert.equal(actual.tables[0][1][1],kind==='table'?'84':'42')
    assert.deepEqual(actual.charts[0].series[0].values,kind==='chart'?[84,17]:[42,17])
    assert(!state.requests.some(request=>request.method==='POST'&&/\/(save|export)$/.test(request.path)))
    assert(state.requests.some(request=>request.path.endsWith('/events')))
    await page.screenshot({path:join(directory,kind+'-accepted.png'),fullPage:true})
    results.push({kind,selection:start.body.selection,operations,events,preview,
      independentReadback:actual,actualPatchedPath:accepted.actualPatchedPath,
      actualPatchedSha256:accepted.actualPatchedSha256,sourceSha256:state.sourceSha256})
    await writeFile(join(directory,kind+'-result.json'),JSON.stringify(results.at(-1),null,2))
    await page.getByRole('button',{name:'收起 AI 助手',exact:true}).click();await panel.waitFor({state:'hidden'});assert.deepEqual(await drafts(),after)
    await page.setViewportSize({width:780,height:1000});await page.locator('[data-action=office-edit-ai]').click();await panel.waitFor({state:'visible'});const narrow=await page.locator('.office-task-dock').boundingBox();assert(narrow&&narrow.width<=780*.92);await page.screenshot({path:join(directory,kind+'-narrow-dock.png'),fullPage:true})
    await context.close();page=undefined
  }
  await Promise.all(checks);assert(assets.size>0)
  assert.deepEqual(await readFile(join(staticRoot,'.vite/manifest.json')),manifest)
  assert.deepEqual(errors,[]);assert.deepEqual(consoleErrors,[]);assert.deepEqual(httpErrors,[])
  await writeFile(join(directory,'summary.json'),JSON.stringify({ok:true,directory,staticRoot,
    browserVersion:browser.version(),manifestSha256:sha(manifest),assets:Object.fromEntries(assets),results,
    provider:'ScriptedModel through actual Agno; not real provider',
    http:'real routers/grant/cookie/workspace; scoped in-memory revision repository',errors,consoleErrors,httpErrors},null,2))
  console.log(JSON.stringify({ok:true,directory,cases:results.length,assets:assets.size}))
}catch(error){
  if(page){await writeFile(join(directory,'failure.html'),await page.content()).catch(()=>{});await page.screenshot({path:join(directory,'failure.png'),fullPage:true}).catch(()=>{})}
  console.error(JSON.stringify({stage,directory}));throw error
}finally{await browser?.close();server.kill();await writeFile(join(directory,'server.log'),serverLog)}
