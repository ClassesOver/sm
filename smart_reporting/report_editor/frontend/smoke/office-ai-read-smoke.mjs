import assert from 'node:assert/strict'
import {spawn} from 'node:child_process'
import {createHash} from 'node:crypto'
import {mkdir,readFile,writeFile} from 'node:fs/promises'
import {join} from 'node:path'
import {fileURLToPath} from 'node:url'
import {setTimeout as delay} from 'node:timers/promises'
import {chromium} from 'playwright'

const frontend=fileURLToPath(new URL('../',import.meta.url)),repo=fileURLToPath(new URL('../../../../',import.meta.url))
const checkpoint=process.env.OFFICE_AI_READ_SMOKE_DIRECTORY??'/tmp/office-ai-read-20261111'
const port=Number(process.env.OFFICE_AI_READ_SMOKE_PORT??4288),origin='http://127.0.0.1:'+port
const sha=bytes=>createHash('sha256').update(bytes).digest('hex')
// 已存在的验收目录必须显式换名，避免覆盖旧证据。
await mkdir(checkpoint,{recursive:false})
const manifest=await readFile(join(frontend,'../static/.vite/manifest.json'))
await writeFile(join(checkpoint,'build-manifest.json'),manifest)
const server=spawn(join(repo,'.venv/bin/python'),[join(frontend,'smoke/office-ai-read-server.py'),'--output-dir',checkpoint,'--port',String(port)],{cwd:repo,env:{...process.env,PYTHONPATH:repo},stdio:'pipe'})
let serverLog='',browser,page,stage='server'
server.stdout.on('data',data=>{serverLog+=data});server.stderr.on('data',data=>{serverLog+=data})
const errors=[],consoleErrors=[],httpErrors=[],checks=[],assets=new Map(),results=[]
try {
  for(let i=0;;i++){assert.equal(server.exitCode,null,serverLog);try{if((await fetch(origin+'/__smoke__/state')).ok)break}catch{}assert(i<240,serverLog);await delay(250)}
  const info=JSON.parse(await readFile(join(checkpoint,'server-info.json'),'utf8'))
  browser=await chromium.launch({headless:true})
  for(const format of ['xlsx','pptx']) {
    stage=format+'-open-real-grant'
    page=await browser.newPage({viewport:{width:1550,height:1100}})
    page.on('pageerror',error=>errors.push({format,message:error.message}))
    page.on('console',message=>{if(message.type()==='error')consoleErrors.push({format,message:message.text()})})
    page.on('response',response=>{if(response.status()>=400)httpErrors.push({format,path:new URL(response.url()).pathname,status:response.status()})})
    page.on('response',response=>{const path=new URL(response.url()).pathname;if(!path.startsWith('/reports/v1/editor/assets/')||!path.endsWith('.js'))return;checks.push((async()=>{assert.equal(response.status(),200);const bytes=await response.body(),disk=await readFile(join(frontend,'../static',path.slice('/reports/v1/editor/assets/'.length)));assert.equal(sha(bytes),sha(disk));assets.set(path,sha(bytes))})())})
    const document=info.documents[format]
    await page.goto(origin+document.openPath)
    await page.waitForFunction(()=>document.querySelector('#report-editor')?.getAttribute('aria-busy')==='false',null,{timeout:60000})
    const caps=await page.evaluate(async()=>await(await fetch(location.pathname+'/api/context')).json())
    assert.equal(caps.officeReadAIEnabled,true);assert.equal(caps.editingEnabled,false);assert.equal(caps.aiEnabled,false)
    assert.equal(await page.locator('.workbook-grid,.slides-workspace').count(),0,'关闭编辑时不伪造编辑画布')
    assert.equal(await page.locator('[data-action="save"]').isDisabled(),true)
    const download=page.getByRole('link',{name:'下载原件',exact:true});assert.equal(await download.count(),1)
    const entry=page.locator('[data-action="office-read-ai"]');assert.equal(await entry.isDisabled(),false);assert.equal(await entry.locator('svg').count(),1)
    assert.equal(await entry.innerText(),'AI 助手')
    const draftState=()=>page.evaluate(()=>Object.fromEntries(Object.keys(localStorage).filter(key=>key.startsWith('native-editor-draft:')).map(key=>[key,localStorage.getItem(key)])))
    const before=await draftState(),panel=page.locator('.native-office-assistant')
    await entry.click();await panel.waitFor({state:'visible'})
    assert.equal(await panel.getAttribute('aria-label'),format==='xlsx'?'Excel AI 阅读助手':'PPT AI 阅读助手')
    assert.equal(await panel.getByLabel('Office AI 阅读范围').inputValue(),'document')
    assert.equal(await panel.getByLabel('Office AI 问题或补充要求').isEditable(),true)
    for(const action of ['ask','summarize','keyPoints','start','cancel','close'])assert.equal(await panel.locator('[data-office-ai="'+action+'"] svg').count(),1)
    stage=format+'-document-summary'
    await panel.locator('[data-office-ai="summarize"]').click()
    await page.waitForFunction(()=>document.querySelector('.native-office-assistant [role="status"]')?.textContent==='阅读完成，文档与草稿未修改。',null,{timeout:60000})
    const state=await(await fetch(origin+'/__smoke__/state')).json(),job=state.jobs.at(-1),result=job.result
    assert.equal(job.status,'completed',JSON.stringify(job));assert.equal(result.coverage.scope,'document');assert.equal(result.coverage.scopeReadComplete,true)
    assert.equal(result.coverage.totalBlocks,format==='xlsx'?2:1)
    assert.deepEqual(result.coverage.fullyReadBlockIds,format==='xlsx'?['经营!A1','经营!B1']:['0'])
    assert.equal(result.readingVersion,'source');assert.deepEqual(result.issues,[])
    assert.equal(result.sourceSha256,document.sourceSha256);assert.equal(result.effectiveSha256,document.sourceSha256)
    assert.deepEqual(result.toolEvents.map(event=>event.tool),format==='xlsx'?['get_workbook_context','read_cells']:['get_presentation_context','read_slide'])
    assert.match(result.answer,/收入42.*费用12/)
    if(format==='pptx') {
      assert.match(result.answer,/演讲者备注.*下季度目标59/)
      assert.equal(result.citations[0].speakerNotes,true)
      assert.match(result.citations[0].label,/演讲者备注/)
    }
    const evidence=await panel.locator('.native-ai-evidence').innerText()
    const textLayout=await panel.locator('.native-ai-evidence > p').first().evaluate(el=>({height:el.getBoundingClientRect().height,fontFamily:getComputedStyle(el).fontFamily,hostFontFamily:getComputedStyle(document.querySelector('.office-task-workspace')).fontFamily}))
    assert(textLayout.height>0,'引用与阅读覆盖文字必须实际可见')
    assert.equal(textLayout.fontFamily,textLayout.hostFontFamily,'侧栏沿用可读宿主字体')
    assert.match(evidence,/已核验原件/);assert.match(evidence,/范围已读完/)
    assert.match(evidence,new RegExp('实际完整读取：'+(format==='xlsx'?'2 / 2':'1 / 1')))
    if(format==='pptx') {
      assert(result.limitations?.length,'服务端必须返回PPTX真实阅读边界')
      await panel.locator('summary',{hasText:'阅读范围与限制'}).click()
      const panelText=await panel.innerText()
      assert.match(panelText,/整稿包含演讲者备注/);assert.match(panelText,/当前对象选区不包含备注/);assert.match(panelText,/引用：.*演讲者备注/);assert.match(panelText,/图片/);assert.match(panelText,/表格/)
      assert.match(panelText,/不代表.*PPTX.*全部内容|不代表.*全部.*PPTX|仅为引擎/)
    }
    const request=state.requests.filter(item=>item.path.includes('/'+document.context.documentId+'/')&&item.path.endsWith('/office-read/start')).at(-1)
    assert.equal(request.body.action,'summarize');assert.deepEqual(request.body.operations,[]);assert.equal(request.body.selection,null)
    assert.equal(state.identities[format].sourceSha256,document.sourceSha256)
    assert.deepEqual(state.requests.filter(item=>item.method==='POST'&&!item.path.includes('/ai/office-read/')),[],'只读会话不得发送 preview/save/export 请求')
    await panel.locator('.native-ai-progress').waitFor({state:'visible'})
    const toolLabel=format==='xlsx'?'读取单元格':'读取幻灯片'
    await page.waitForFunction(label=>document.querySelector('.native-office-assistant [aria-label="AI 执行进度"]')?.textContent?.includes(label),toolLabel,{timeout:10000})
    const progress=await panel.getByLabel('AI 执行进度').innerText();assert.match(progress,/工具/)
    assert(state.requests.some(item=>item.path.includes('/'+document.context.documentId+'/')&&item.path.endsWith('/events')),'浏览器须真实请求SSE工具进度')
    assert.deepEqual(await draftState(),before)
    await page.screenshot({path:join(checkpoint,format+'-document-summary.png'),fullPage:true})
    results.push({format,result,evidence,textLayout,progress,request,sourceUnchanged:true,draftUnchanged:true})
    await writeFile(join(checkpoint,format+'-result.json'),JSON.stringify(results.at(-1),null,2))
    await page.close();page=undefined
  }
  await Promise.all(checks);assert(assets.size>0,'必须校验实际加载JS资产')
  assert.deepEqual(await readFile(join(frontend,'../static/.vite/manifest.json')),manifest,'验收过程中构建资产不得变化')
  assert.deepEqual(errors,[]);assert.deepEqual(consoleErrors,[]);assert.deepEqual(httpErrors,[])
  const final=await(await fetch(origin+'/__smoke__/state')).json();assert.equal(final.jobs.length,2)
  const summary={ok:true,checkpoint,browserVersion:browser.version(),manifestSha256:sha(manifest),assets:Object.fromEntries(assets),provider:'ScriptedModel through actual Agno; not a real provider',http:'uvicorn FastAPI real routers/workspace/grant/cookie; scoped in-memory revision lookup',readOnly:true,editingEnabled:false,officeReadAIEnabled:true,identities:final.identities,results,errors,consoleErrors,httpErrors}
  await writeFile(join(checkpoint,'summary.json'),JSON.stringify(summary,null,2));console.log(JSON.stringify({ok:true,checkpoint,cases:results.length,assets:assets.size}))
} catch(error) {
  if(page){await writeFile(join(checkpoint,'failure-layout.json'),JSON.stringify(await page.evaluate(()=>[...document.querySelectorAll('.office-task-dock,.office-assistant-header,.office-assistant-body,.native-ai-evidence,.native-ai-evidence p')].map(el=>{const css=getComputedStyle(el),box=el.getBoundingClientRect();return {className:el.className,text:el.textContent?.slice(0,120),innerText:el.innerText,display:css.display,visibility:css.visibility,color:css.color,fontSize:css.fontSize,fontFamily:css.fontFamily,contentVisibility:css.contentVisibility,height:box.height,width:box.width}})),null,2)).catch(()=>{});await writeFile(join(checkpoint,'failure.html'),await page.content()).catch(()=>{});await page.screenshot({path:join(checkpoint,'failure.png'),fullPage:true}).catch(()=>{})}
  console.error(JSON.stringify({stage,checkpoint}));throw error
} finally {
  await browser?.close();server.kill();await writeFile(join(checkpoint,'server.log'),serverLog)
}
