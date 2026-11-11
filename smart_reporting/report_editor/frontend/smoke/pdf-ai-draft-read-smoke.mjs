import assert from 'node:assert/strict'
import {spawn} from 'node:child_process'
import {createHash} from 'node:crypto'
import {mkdir,readFile,writeFile} from 'node:fs/promises'
import {join} from 'node:path'
import {fileURLToPath} from 'node:url'
import {setTimeout as delay} from 'node:timers/promises'
import {chromium} from 'playwright'

const frontend=fileURLToPath(new URL('../',import.meta.url)),repo=fileURLToPath(new URL('../../../../',import.meta.url))
const checkpoint=process.env.PDF_AI_DRAFT_SMOKE_DIRECTORY??'/tmp/pdf-ai-draft-read-built-20261111-final-01'
const port=Number(process.env.PDF_AI_DRAFT_SMOKE_PORT??4286),origin='http://127.0.0.1:'+port
const entryOnly=process.env.PDF_AI_DRAFT_SMOKE_ENTRY_ONLY==='1'
const cases=entryOnly?[]:process.env.PDF_AI_DRAFT_SMOKE_SINGLE_SUMMARY==='1'?['text']:['text','reorder','partial','blank']
const sha=bytes=>createHash('sha256').update(bytes).digest('hex')
const canonical=value=>Array.isArray(value)?value.map(canonical):value&&typeof value==='object'?Object.fromEntries(Object.keys(value).sort().map(key=>[key,canonical(value[key])])):value
await mkdir(checkpoint,{recursive:true})
const manifest=await readFile(join(frontend,'../static/.vite/manifest.json'))
try{assert.deepEqual(await readFile(join(checkpoint,'build-manifest.json')),manifest)}catch(error){if(error.code!=='ENOENT')throw error;await writeFile(join(checkpoint,'build-manifest.json'),manifest)}
const server=spawn(join(repo,'.venv/bin/python'),[join(frontend,'smoke/pdf-ai-read-server.py'),'--draft','--directory',checkpoint,'--port',String(port)],{cwd:repo,env:{...process.env,PYTHONPATH:repo},stdio:'pipe'})
let serverLog='',browser,page,stage='server'
server.stdout.on('data',data=>{serverLog+=data});server.stderr.on('data',data=>{serverLog+=data})
const pageErrors=[],consoleErrors=[],httpErrors=[],checks=[],assets=new Map(),results=[]
try{
  for(let i=0;;i++){assert.equal(server.exitCode,null,serverLog);try{if((await fetch(origin+'/__smoke__/state')).ok)break}catch{}assert(i<240,serverLog);await delay(250)}
  const info=JSON.parse(await readFile(join(checkpoint,'server-info.json'),'utf8'))
  browser=await chromium.launch({headless:true});page=await browser.newPage({viewport:{width:1550,height:1100}})
  page.on('pageerror',error=>pageErrors.push(error.message))
  page.on('console',message=>{if(message.type()==='error')consoleErrors.push(message.text())})
  page.on('response',response=>{if(response.status()>=400)httpErrors.push({path:new URL(response.url()).pathname,status:response.status()})})
  page.on('response',response=>{const path=new URL(response.url()).pathname;if(!path.startsWith('/reports/v1/editor/assets/')||!path.endsWith('.js'))return;checks.push((async()=>{assert.equal(response.status(),200);const bytes=await response.body(),disk=await readFile(join(frontend,'../static',path.slice('/reports/v1/editor/assets/'.length)));assert.equal(sha(bytes),sha(disk));assets.set(path,sha(bytes))})())})
  await page.goto(origin+info.openPath)
  const ready=()=>page.waitForFunction(()=>document.querySelector('#report-editor')?.getAttribute('aria-busy')==='false',null,{timeout:60000})
  await ready()
  const context=info.context,identity={documentId:context.documentId,revision:context.revision,sourceSha256:info.sourceSha256,scope:context.scope}
  const key='native-editor-draft:v1:'+JSON.stringify([context.scope.database,context.scope.companyId,context.scope.userId,context.scope.threadId,context.documentId,context.revision,info.sourceSha256])
  const panel=page.locator('.native-pdf-assistant')
  const entryControls=[]
  if(entryOnly){
    stage='entry-controls'
    for(const item of [{tab:'home',id:'home.ai.openAssistant'},{tab:'home',id:'home.ai.summarize'},{tab:'home',id:'home.ai.keyPoints'},{tab:'annotate',id:'annotate.aiReview.summary'}]){
      await page.locator('[data-pdf-ribbon-tab="'+item.tab+'"]').click()
      const button=page.locator('[data-source-command-id="genoffice.pdf.'+item.id+'"]')
      assert.equal(await button.isVisible(),true);assert.equal(await button.isDisabled(),false);assert.equal(await button.locator('svg').count(),1)
      const label=(await button.innerText()).trim();assert.match(label,/[\u4e00-\u9fff]/)
      entryControls.push({...item,label,visible:true,svg:true})
    }
    await page.locator('[data-pdf-ribbon-tab="home"]').click()
    await page.locator('[data-source-command-id="genoffice.pdf.home.ai.openAssistant"]').click()
    await panel.waitFor({state:'visible'})
    assert.equal(await panel.getByLabel('PDF AI 问题或补充要求').isEditable(),true)
    assert.equal(await panel.locator('[data-pdf-ai="start"]').isDisabled(),true)
    await page.screenshot({path:join(checkpoint,'entry.png'),fullPage:true})
  }
  for(const name of cases){
    stage=name
    const operations=info.draftFixtures[name],stored=JSON.stringify({version:1,identity,operations})
    await page.evaluate(({key,stored})=>localStorage.setItem(key,stored),{key,stored});await page.reload();await ready()
    assert.equal(await page.evaluate(key=>localStorage.getItem(key),key),stored)
    await page.locator('[data-pdf-ribbon-tab="home"]').click()
    await page.locator('[data-source-command-id="genoffice.pdf.home.ai.summarize"]').click()
    await panel.waitFor({state:'visible'})
    await page.waitForFunction(()=>document.querySelector('.native-pdf-assistant [role="status"]')?.textContent==='阅读完成，文档与草稿未修改。',null,{timeout:60000})
    const state=await(await fetch(origin+'/__smoke__/state')).json(),job=state.jobs.at(-1),result=job.result
    assert.equal(job.status,'completed',JSON.stringify(job));assert.equal(state.draftMode,true)
    assert.equal(state.sourceSha256,info.sourceSha256);assert.equal(result.sourceSha256,info.sourceSha256)
    const projection=result.projection;assert.equal(projection.originalSourceSha256,info.sourceSha256)
    assert.equal(projection.previewDigest.length,64);assert.equal(projection.draftSnapshotSha256.length,64)
    assert.equal(projection.draftSnapshotSha256,sha(JSON.stringify(canonical(operations))))
    assert.notEqual(projection.effectiveSha256,info.sourceSha256)
    assert.equal(result.coverage.fullDocumentRead,true);assert.equal(result.coverage.ocrPerformed,false)
    assert.equal(result.coverage.pageCount,name==='blank'?3:2)
    assert.deepEqual(result.coverage.fullyReadPages,name==='blank'?[1,2,3]:[1,2])
    const preview=await page.evaluate(async({operations,originalSha256,previewDigest})=>{const context=await(await fetch(location.pathname+'/api/context')).json();const response=await fetch(location.pathname+'/api/preview.pdf',{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':context.csrfToken},body:JSON.stringify({expectedSha256:originalSha256,operations,expectedPreviewDigest:previewDigest})});return{status:response.status,digest:response.headers.get('X-Native-Preview-Digest'),bytes:[...new Uint8Array(await response.arrayBuffer())]}},{operations,originalSha256:info.sourceSha256,previewDigest:projection.previewDigest})
    assert.equal(preview.status,200);assert.equal(preview.digest,projection.previewDigest)
    assert.equal(sha(Buffer.from(preview.bytes)),projection.effectiveSha256);assert.equal(preview.bytes.length,projection.effectiveSize)
    await writeFile(join(checkpoint,name+'-effective.pdf'),Buffer.from(preview.bytes))
    assert.deepEqual(projection.appliedOperationIndices,name==='partial'?[1]:name==='text'?[0]:[0,1])
    assert.equal(projection.skippedOperations.length,name==='partial'?1:0)
    const answer=await panel.locator('.native-ai-answer').innerText(),evidence=await panel.locator('.native-ai-evidence').innerText()
    assert.match(answer,name==='text'||name==='reorder'?/收入为72/:/收入为42/)
    assert.match(evidence,/阅读版本：未保存草稿/);assert.match(evidence,/实际读取草稿页码/)
    if(name==='partial'){assert.match(evidence,/跳过 1 项/);assert.match(evidence,new RegExp(projection.skippedOperations[0].reason));assert(result.issues.some(issue=>issue.code==='native_pdf_ai_draft_operations_skipped'))}
    if(name==='reorder')assert.deepEqual(projection.pageMapping.map(page=>page.originalPageNumber),[2,1])
    const navigation=[]
    for(const citation of result.citations){
      if(citation.pageId===null){const button=panel.getByRole('button',{name:'草稿新增第 '+citation.effectivePageNumber+' 页（无原始页面）',exact:true});assert.equal(await button.isDisabled(),true);assert.equal(citation.pageNumber,null);navigation.push({originalPage:null,effectivePage:citation.effectivePageNumber,disabled:true});continue}
      assert.equal(citation.sourceSha256,info.sourceSha256);assert.equal(citation.effectiveSha256,projection.effectiveSha256)
      await panel.getByRole('button',{name:'转到原始第 '+citation.pageNumber+' 页（草稿第 '+citation.effectivePageNumber+' 页）',exact:true}).click()
      await page.waitForFunction(id=>{const card=[...document.querySelectorAll('.pdf-page')].find(node=>node.getAttribute('data-page-id')===id),viewport=document.querySelector('.pdf-document-pages');if(!card?.classList.contains('is-active')||!viewport)return false;const rect=card.getBoundingClientRect(),visible=viewport.getBoundingClientRect();return rect.top>=visible.top-10&&rect.top<visible.bottom},citation.pageId)
      navigation.push({originalPage:citation.pageNumber,effectivePage:citation.effectivePageNumber,pageId:citation.pageId,active:true,visible:true})
    }
    assert.equal(await page.evaluate(key=>localStorage.getItem(key),key),stored)
    assert.equal(state.requests.some(request=>request.method==='POST'&&/\/(save|export)$/.test(request.path)),false)
    await page.screenshot({path:join(checkpoint,name+'.png'),fullPage:true})
    results.push({name,result,evidence,navigation,operations,storedDraftUnchanged:true,effectiveBytesVerified:true})
    await writeFile(join(checkpoint,name+'-result.json'),JSON.stringify(results.at(-1),null,2))
  }
  await Promise.all(checks);assert.deepEqual(pageErrors,[]);assert.deepEqual(consoleErrors,[]);assert.deepEqual(httpErrors,[])
  assert.deepEqual(await readFile(join(frontend,'../static/.vite/manifest.json')),manifest)
  const state=await(await fetch(origin+'/__smoke__/state')).json();assert.equal(state.jobs.length,cases.length)
  assert.equal(sha(await readFile(join(checkpoint,'source.pdf'))),state.sourceSha256)
  const summary={ok:true,validationMode:entryOnly?'entry-only':cases.length===1?'entry-and-single-summary':'draft-four-cases',checkpoint,browserVersion:browser.version(),manifestSha256:sha(manifest),sourceSha256:state.sourceSha256,provider:entryOnly?'No AI/provider task invoked':'ScriptedModel through real Agno; not a real provider',http:'uvicorn FastAPI real routers/workspace/grant/cookie; scoped in-memory revision lookup',entryControls,results,assets:Object.fromEntries(assets),pageErrors,consoleErrors,httpErrors}
  await writeFile(join(checkpoint,'summary.json'),JSON.stringify(summary,null,2));console.log(JSON.stringify({ok:true,checkpoint,cases:results.length,assets:assets.size}))
}catch(error){if(page){await writeFile(join(checkpoint,'failure.html'),await page.content()).catch(()=>{});await page.screenshot({path:join(checkpoint,'failure.png'),fullPage:true}).catch(()=>{})}console.error(JSON.stringify({stage,checkpoint}));throw error}
finally{await browser?.close();server.kill();await writeFile(join(checkpoint,'server.log'),serverLog)}
