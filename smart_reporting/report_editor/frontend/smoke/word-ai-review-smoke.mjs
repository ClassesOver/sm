import assert from 'node:assert/strict'
import {spawn} from 'node:child_process'
import {createHash} from 'node:crypto'
import {cp,mkdir,readFile,writeFile} from 'node:fs/promises'
import {join} from 'node:path'
import {fileURLToPath} from 'node:url'
import {setTimeout as delay} from 'node:timers/promises'
import {chromium} from 'playwright'

const frontend=fileURLToPath(new URL('../',import.meta.url)),repo=fileURLToPath(new URL('../../../../',import.meta.url))
const directory=process.env.WORD_AI_REVIEW_DIRECTORY??'/tmp/word-ai-review-20261111'
const port=Number(process.env.WORD_AI_REVIEW_PORT??4289),origin='http://127.0.0.1:'+port
const sha=bytes=>createHash('sha256').update(bytes).digest('hex')
await mkdir(directory,{recursive:true})
const staticRoot=process.env.WORD_AI_REVIEW_BUILD??join(directory,'static')
if(!process.env.WORD_AI_REVIEW_BUILD)await cp(join(frontend,'../static'),staticRoot,{recursive:true,errorOnExist:true,force:false})
const manifest=await readFile(join(staticRoot,'.vite/manifest.json'))
await writeFile(join(directory,'build-manifest.json'),manifest)
const server=spawn(join(repo,'.venv/bin/python'),[join(frontend,'smoke/word-ai-review-server.py'),'--directory',directory,'--port',String(port)],{cwd:repo,env:{...process.env,PYTHONPATH:repo,WORD_AI_REVIEW_STATIC_ROOT:staticRoot},stdio:'pipe'})
let serverLog='',browser,page,stage='server'
server.stdout.on('data',data=>{serverLog+=data});server.stderr.on('data',data=>{serverLog+=data})
const errors=[],consoleErrors=[],httpErrors=[],checks=[],assets=new Map(),results=[]
try{
  for(let i=0;;i++){assert.equal(server.exitCode,null,serverLog);try{if((await fetch(origin+'/__smoke__/state')).ok)break}catch{}assert(i<240,serverLog);await delay(250)}
  const info=JSON.parse(await readFile(join(directory,'server-info.json'),'utf8'))
  const comment=info.model.commentThreads.targets.find(target=>target.parentId===null)
  const block=info.model.blocks.find(block=>block.reviewTargets?.length)
  const revision=block.reviewTargets.find(target=>target.type==='insertion')
  browser=await chromium.launch({headless:true})
  const selectedCases=process.env.WORD_AI_REVIEW_CASES?.split(',')??['reply','resolve','revision']
  assert(selectedCases.length&&selectedCases.every(kind=>['reply','resolve','revision'].includes(kind)))
  for(const kind of selectedCases){
    stage=kind+'-open'
    const context=await browser.newContext({viewport:{width:1550,height:1100}})
    page=await context.newPage()
    page.on('pageerror',error=>errors.push(error.message))
    page.on('console',message=>{if(message.type()==='error')consoleErrors.push(message.text())})
    page.on('response',response=>{
      const path=new URL(response.url()).pathname
      if(response.status()>=400)httpErrors.push({path,status:response.status()})
      if(path.startsWith('/reports/v1/editor/assets/')&&/\.(js|css)$/.test(path))checks.push((async()=>{
        assert.equal(response.status(),200);const bytes=await response.body()
        const disk=await readFile(join(staticRoot,path.slice('/reports/v1/editor/assets/'.length)))
        assert.equal(sha(bytes),sha(disk));assets.set(path,sha(bytes))
      })())
    })
    await page.goto(origin+info.openPaths[kind])
    await page.waitForFunction(()=>document.querySelector('#report-editor')?.getAttribute('aria-busy')==='false',null,{timeout:60000})
    await page.getByRole('textbox',{name:'Word 文档编辑区',exact:true}).waitFor()
    const dock=page.getByRole('complementary',{name:'Word AI 助手',exact:true})
    const editPanel=page.getByRole('region',{name:'AI 编辑选区',exact:true,includeHidden:true})
    const readPanel=page.getByRole('region',{name:'Word AI 阅读助手',exact:true,includeHidden:true})
    await page.locator('[data-action=word-read-ai]').waitFor()
    assert.equal(await dock.isVisible(),false);assert.equal(await editPanel.isVisible(),false);assert.equal(await readPanel.isVisible(),false)
    const readEntry=page.locator('[data-action=word-read-ai]'),editEntry=page.locator('[data-action=word-edit-ai]')
    assert.equal(await readEntry.locator('svg').count(),1);assert.equal(await editEntry.locator('svg').count(),1)
    await readEntry.click();await readPanel.waitFor({state:'visible'})
    const desktop=await page.evaluate(()=>{
      const dock=document.querySelector('.office-task-dock'),main=document.querySelector('.docx-navigation-layout')??document.querySelector('#report-editor'),workspace=dock.parentElement
      const d=dock.getBoundingClientRect(),m=main.getBoundingClientRect()
      return {dock:{x:d.x,y:d.y,width:d.width,height:d.height},main:{x:m.x,y:m.y,width:m.width,height:m.height},siblings:main.parentElement===workspace,ribbonOutside:!!document.querySelector('.docx-ribbon')&&!workspace.querySelector('.docx-ribbon')}
    })
    assert(desktop.siblings);assert(desktop.ribbonOutside);assert(Math.abs(desktop.main.x+desktop.main.width-desktop.dock.x)<2)
    const divider=dock.getByRole('separator',{name:'调整 AI 助手宽度',exact:true}),oldWidth=Number(await divider.getAttribute('aria-valuenow'))
    await divider.focus();await page.keyboard.press('ArrowLeft');assert.equal(Number(await divider.getAttribute('aria-valuenow')),oldWidth+20)
    await editEntry.click();await editPanel.waitFor({state:'visible'});assert.equal(await readPanel.isVisible(),false)
    await dock.getByRole('button',{name:'关闭助手',exact:true}).click();await dock.waitFor({state:'hidden'})
    await readEntry.click();await readPanel.waitFor({state:'visible'});await page.keyboard.press('Escape');await dock.waitFor({state:'hidden'})
    await page.setViewportSize({width:760,height:900});await page.locator('.docx-ribbon .office-ai-entry').click();await readPanel.waitFor({state:'visible'})
    const narrow=await dock.evaluate(element=>{const d=element.getBoundingClientRect(),w=element.parentElement.getBoundingClientRect();return {position:getComputedStyle(element).position,x:d.x,width:d.width,right:d.right,workspaceWidth:w.width,viewport:innerWidth}})
    assert.equal(narrow.position,'absolute');assert(narrow.width<=narrow.workspaceWidth*.92+1);assert(narrow.right<=narrow.viewport+1)
    await page.screenshot({path:join(directory,kind+'-dock-narrow.png'),fullPage:true})
    await dock.getByRole('button',{name:'收起 AI 助手',exact:true}).click();await dock.waitFor({state:'hidden'})
    await page.setViewportSize({width:1550,height:1100})
    await page.getByRole('tab',{name:'审阅',exact:true}).click()
    let button
    if(kind==='revision'){
      await page.locator('[data-action=text-revision-list]').click()
      button=page.locator('[data-revision-id="'+revision.revisionId+'"] [data-action=ai-review-revision]')
    }else{
      await page.locator('[data-action=comment-text-list]').click()
      await page.getByLabel('选择已有批注',{exact:true}).selectOption(comment.targetId)
      button=page.locator('[data-comment-ai='+kind+']')
    }
    assert.equal(await button.isEnabled(),true);assert.equal(await button.locator('svg').count(),1)
    const drafts=()=>page.evaluate(()=>Object.keys(localStorage).filter(key=>key.startsWith('native-editor-draft:')).map(key=>JSON.parse(localStorage.getItem(key))))
    const before=await drafts()
    await button.click()
    await dock.waitFor({state:'visible'});assert.equal(await readPanel.isVisible(),false)
    const panel=page.getByRole('region',{name:'AI 编辑选区',exact:true})
    const instruction=kind==='reply'?'请回复当前批注：已核实收入42。':kind==='resolve'?'请重新打开当前批注线程，done设为false。':'请接受当前插入修订。'
    await panel.getByLabel('AI 修改要求',{exact:true}).fill(instruction)
    stage=kind+'-propose'
    await panel.locator('[data-ai=start]').click()
    await panel.locator('[data-ai=accept]').waitFor({state:'visible'})
    await page.waitForFunction(()=>document.querySelector('[aria-label="AI 编辑选区"] [data-ai=accept]')?.disabled===false,null,{timeout:60000})
    assert.deepEqual(await drafts(),before,'候选生成不得提前修改草稿')
    let state=await(await fetch(origin+'/__smoke__/state')).json()
    const job=state.jobs.at(-1),expectedKind={reply:'replyComment',resolve:'resolveComment',revision:'resolveTextRevision'}[kind]
    assert.equal(job.status,'succeeded',JSON.stringify(job));assert.equal(job.proposal.operations.length,1)
    assert.equal(job.proposal.operations[0].kind,expectedKind)
    const startRequest=state.requests.filter(item=>item.path.endsWith('/ai/start')).at(-1)
    assert.deepEqual(startRequest.body.selection,kind==='revision'?[{blockId:block.blockId,revisionId:revision.revisionId}]:[{sourceId:comment.sourceId,targetId:comment.targetId}])
    assert.deepEqual(startRequest.body.operations,[])
    const events=job.events.filter(event=>event.kind==='toolCompleted')
    assert.deepEqual(events.map(event=>[event.toolName,event.toolCallId]),[
      ['get_document_context','review-context'],['read_review_targets','review-read'],['propose_operations','review-propose']])
    await page.waitForFunction(()=>document.querySelector('[aria-label="AI 编辑选区"] [aria-label="AI 执行进度"]')?.textContent?.includes('读取审阅目标'),null,{timeout:10000})
    const progress=await panel.getByLabel('AI 执行进度',{exact:true}).innerText()
    await page.screenshot({path:join(directory,kind+'-candidate.png'),fullPage:true})
    stage=kind+'-accept'
    await panel.locator('[data-ai=accept]').click()
    await page.waitForFunction(()=>document.querySelector('[aria-label="AI 编辑选区"] [role=status]')?.textContent?.startsWith('建议已进入草稿'),null,{timeout:60000})
    const after=await drafts();assert.equal(after.length,1);assert.deepEqual(after[0].operations,job.proposal.operations)
    state=await(await fetch(origin+'/__smoke__/state')).json()
    const accepted=state.jobs.find(item=>item.editId===job.editId)
    assert.equal(state.sourceSha256,info.sourceSha256)
    assert.equal(sha(await readFile(accepted.actualPatchedPath)),accepted.actualPatchedSha256)
    const actual=accepted.actualPatchedModel
    if(kind==='reply'){
      const reply=actual.commentReplies.targets.find(target=>target.text==='AI 审阅回复：已核实收入42。')
      assert(reply);assert.equal(reply.parentId,comment.originalCommentId);assert.equal(reply.author,'AI Assistant')
      assert(accepted.changedParts.includes('word/comments.xml'))
    }else if(kind==='resolve'){
      const root=actual.commentThreads.targets.find(target=>target.parentId===null)
      assert.equal(root.done,false);assert.deepEqual(accepted.changedParts,['word/commentsExtended.xml'])
    }else{
      const remaining=actual.blocks.flatMap(block=>block.reviewTargets??[])
      assert.equal(remaining.length,1);assert.equal(remaining[0].type,'deletion')
      assert.deepEqual(accepted.changedParts,['word/document.xml'])
    }
    assert(!state.requests.some(item=>item.method==='POST'&&/\/(save|export)$/.test(item.path)))
    assert(state.requests.some(item=>item.path.endsWith('/events')))
    await page.screenshot({path:join(directory,kind+'-accepted.png'),fullPage:true})
    results.push({kind,dock:{desktop,narrow,widthKeyboard:{before:oldWidth,after:oldWidth+20},switchReadEdit:true,close:true,reviewAutoOpen:true},proposal:job.proposal,selection:startRequest.body.selection,events,progress,
      sourceSha256:state.sourceSha256,changedParts:accepted.changedParts,actualPatchedPath:accepted.actualPatchedPath,
      actualPatchedSha256:accepted.actualPatchedSha256,draftOperations:after[0].operations})
    await writeFile(join(directory,kind+'-result.json'),JSON.stringify(results.at(-1),null,2))
    await context.close();page=undefined
  }
  await Promise.all(checks);assert(assets.size>0)
  assert.deepEqual(await readFile(join(staticRoot,'.vite/manifest.json')),manifest)
  assert.deepEqual(errors,[]);assert.deepEqual(consoleErrors,[]);assert.deepEqual(httpErrors,[])
  await writeFile(join(directory,'summary.json'),JSON.stringify({ok:true,directory,cases:results.length,
    browserVersion:browser.version(),staticRoot,manifestSha256:sha(manifest),assets:Object.fromEntries(assets),results,
    provider:'ScriptedModel through actual Agno; not real provider',
    http:'real FastAPI routers/grant/cookie/workspace; scoped in-memory revision repository',
    errors,consoleErrors,httpErrors},null,2))
  console.log(JSON.stringify({ok:true,directory,cases:results.length,assets:assets.size}))
}catch(error){
  if(page){await writeFile(join(directory,'failure.html'),await page.content()).catch(()=>{});await page.screenshot({path:join(directory,'failure.png'),fullPage:true}).catch(()=>{})}
  console.error(JSON.stringify({stage,directory}));throw error
}finally{await browser?.close();server.kill();await writeFile(join(directory,'server.log'),serverLog)}
