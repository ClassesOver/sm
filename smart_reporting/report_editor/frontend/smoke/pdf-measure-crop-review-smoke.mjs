// Real PDF UI, HTTP/auth, engine preview, save/download and revision reopen.
// Persistence is a scoped in-memory fixture, not a production database.
import assert from 'node:assert/strict'
import {spawn, spawnSync} from 'node:child_process'
import {createHash} from 'node:crypto'
import {mkdir, readFile, writeFile} from 'node:fs/promises'
import {join} from 'node:path'
import {fileURLToPath} from 'node:url'
import {setTimeout as delay} from 'node:timers/promises'
import {chromium} from 'playwright'

const frontend=fileURLToPath(new URL('../',import.meta.url)), repo=fileURLToPath(new URL('../../../../',import.meta.url))
const directory=process.env.PDF_MEASURE_CROP_REVIEW_SMOKE_DIRECTORY??'/tmp/pdf-measure-crop-review-browser-20261112'
const staticDirectory=process.env.PDF_SMOKE_STATIC_DIRECTORY??join(frontend,'../static')
const port=Number(process.env.PDF_MEASURE_CROP_REVIEW_SMOKE_PORT??4351), origin=`http://127.0.0.1:${port}`
const sha=bytes=>createHash('sha256').update(bytes).digest('hex')
// Never overwrite an earlier failure or success checkpoint.
await mkdir(directory,{recursive:false})
const manifest=await readFile(join(staticDirectory,'.vite/manifest.json'))
await writeFile(join(directory,'build-manifest.json'),manifest)
const server=spawn(join(repo,'.venv/bin/python'),[join(frontend,'smoke/pdf-measure-crop-review-server.py'),'--directory',directory,'--port',String(port)],{
 cwd:repo,env:{...process.env,PYTHONPATH:repo,PDF_SMOKE_STATIC_DIRECTORY:staticDirectory},stdio:'pipe',
})
let serverLog='',browser,page,stage='server'
server.stdout.on('data',data=>{serverLog+=data});server.stderr.on('data',data=>{serverLog+=data})
const pageErrors=[],consoleErrors=[],httpErrors=[],assetErrors=[],checks=[],assets=new Map()
let staged,preview,payload,reopened,independent
try{
 for(let attempt=0;;attempt++){
  assert.equal(server.exitCode,null,serverLog)
  try{if((await fetch(origin+'/__smoke__/state',{signal:AbortSignal.timeout(1500)})).ok)break}catch{}
  assert(attempt<240,serverLog);await delay(250)
 }
 const info=JSON.parse(await readFile(join(directory,'server-info.json'),'utf8'))
 browser=await chromium.launch({headless:true,...(process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE?{executablePath:process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE}:{})})
 page=await browser.newPage({viewport:{width:1560,height:1200}})
 page.on('pageerror',error=>pageErrors.push(error.message))
 page.on('console',message=>{if(message.type()==='error')consoleErrors.push(message.text())})
 page.on('response',response=>{
  const path=new URL(response.url()).pathname
  if(response.status()>=400)httpErrors.push({path,status:response.status()})
  if(!path.startsWith('/reports/v1/editor/assets/')||!/\.(?:m?js|css)$/.test(path))return
  checks.push((async()=>{
   assert.equal(response.status(),200)
   const bytes=await response.body(),disk=await readFile(join(staticDirectory,path.slice('/reports/v1/editor/assets/'.length)))
   assert.equal(sha(bytes),sha(disk));assets.set(path,sha(bytes))
  })().catch(error=>{assetErrors.push({path,error:String(error)})}))
 })
 const ready=()=>page.waitForFunction(()=>document.querySelector('#report-editor')?.getAttribute('aria-busy')==='false',null,{timeout:60000})
 const operations=()=>page.evaluate(source=>Object.entries(localStorage).filter(([key])=>key.startsWith('native-editor-draft:')).map(([,value])=>JSON.parse(value)).find(value=>value.identity?.sourceSha256===source)?.operations??[],info.sourceSha256)
 const waitOperations=count=>page.waitForFunction(({source,count})=>(Object.entries(localStorage).filter(([key])=>key.startsWith('native-editor-draft:')).map(([,value])=>JSON.parse(value)).find(value=>value.identity?.sourceSha256===source)?.operations??[]).length===count,{source:info.sourceSha256,count})
 stage='open-original';await page.goto(origin+info.openPath);await ready()
 const original=await page.evaluate(async()=>await(await fetch(location.pathname+'/api/context')).json())
 assert.equal(original.context.revision,4);assert.equal(original.context.sourceFile.sha256,info.sourceSha256)
 assert.deepEqual(await operations(),[])
 await page.locator('.pdf-page .textLayer').filter({hasText:'CONTROL CONTENT'}).first().waitFor()
 stage='calibrated-measure-real-ui'
 await page.locator('[data-pdf-ribbon-tab="annotate"]').click()
 const measure=page.locator('[data-pdf-draw-shape="measure"]');await measure.click()
 await page.waitForFunction(()=>document.querySelector('#report-editor')?.dataset.pdfMode==='draw')
 const content=page.locator('.pdf-page').first().locator('.pdf-page-content');await content.scrollIntoViewIfNeeded()
 const box=await content.boundingBox();assert(box&&box.width>0&&box.height>0)
 await page.mouse.move(box.x+box.width*.8,box.y+box.height*.5);await page.mouse.down()
 await page.mouse.move(box.x+box.width*.95,box.y+box.height*.5,{steps:8});await page.mouse.up()
 const calibration=page.getByRole('dialog',{name:'标定测量比例',exact:true});await calibration.waitFor({state:'visible'})
 await calibration.getByLabel('参考线实际长度',{exact:true}).fill('3')
 await calibration.getByLabel('测量单位',{exact:true}).fill('W'.repeat(12))
 await calibration.getByRole('button',{name:'确定',exact:true}).click();await waitOperations(1)
 staged=await operations();assert.equal(staged[0].kind,'addDrawing');assert.equal(staged[0].shape,'measure')
 assert.equal(staged[0].label,'3.00 '+'W'.repeat(12));assert.equal(staged[0].pageId,'sha256:'+info.sourceSha256+':page:0')
 assert(staged[0].from[0]>330&&staged[0].to[0]>400,'real UI measurement must be near the right crop edge')
 await writeFile(join(directory,'staged.json'),JSON.stringify(staged,null,2))
 await page.screenshot({path:join(directory,'staged.png'),fullPage:true})
 stage='undo-redo-preserves-measurement'
 await page.locator('[data-pdf-ribbon-tab="home"]').click()
 await page.locator('[data-source-command-id="genoffice.pdf.home.edit.undo"]').click();await waitOperations(0)
 await page.locator('[data-source-command-id="genoffice.pdf.home.edit.redo"]').click();await waitOperations(1)
 assert.deepEqual(await operations(),staged)
 stage='actual-preview-warning'
 await page.locator('[data-pdf-ribbon-tab="edit"]').click()
 const previewing=page.waitForResponse(response=>response.url().endsWith('/api/preview')&&response.request().method()==='POST'&&response.request().postDataJSON().operations?.length===1)
 await page.getByRole('button',{name:'校验当前修改',exact:true}).click()
 const previewResponse=await previewing;assert.equal(previewResponse.status(),200);preview=await previewResponse.json()
 await writeFile(join(directory,'preview.json'),JSON.stringify(preview,null,2))
 await writeFile(join(directory,'preview-request.json'),JSON.stringify(previewResponse.request().postDataJSON(),null,2))
 assert.deepEqual(preview.appliedOperationIndices,[0]);assert.deepEqual(preview.skippedOperations,[])
 const warning=preview.reviewIssues.find(issue=>issue.code==='pdf_measure_label_crop_clipping')
 assert(warning);assert.equal(warning.operationIndex,0);assert.match(warning.message,/可能.*裁切/)
 const review=page.locator('.pdf-preview-review');await review.waitFor({state:'visible'})
 const reviewText=await review.innerText();assert.match(reviewText,/测量标签.*裁切/);assert.match(reviewText,/已执行/);assert(!reviewText.includes('未执行'))
 const confirmation=review.locator('input[type="checkbox"]');await confirmation.check()
 await page.screenshot({path:join(directory,'preview-warning.png'),fullPage:true})
 stage='save-applied-file-despite-warning'
 const saving=page.waitForResponse(response=>response.url().endsWith('/api/save')&&response.request().method()==='POST')
 await page.locator('[data-action="save"]').click()
 const savedResponse=await saving;payload=await savedResponse.json();assert.equal(savedResponse.status(),200,JSON.stringify(payload))
 await writeFile(join(directory,'payload.json'),JSON.stringify(payload,null,2))
 await writeFile(join(directory,'save-request.json'),JSON.stringify(savedResponse.request().postDataJSON(),null,2))
 assert.deepEqual(savedResponse.request().postDataJSON().operations,staged)
 // Plain measure has no server confirmation requirement. The UI checkbox
 // is exercised; bind the digest only when the actual API supplies one.
 const saveRequest=savedResponse.request().postDataJSON()
 if(saveRequest.confirmedPreviewDigest!==undefined)assert.equal(saveRequest.confirmedPreviewDigest,preview.previewDigest)
 assert.equal(payload.revisionRegistered,true);assert.equal(payload.parentRevision,4);assert.equal(payload.revision,5)
 assert.equal(payload.validation.ok,false)
 assert(payload.validation.issues.some(issue=>issue.code==='pdf_measure_label_crop_clipping'))
 assert(!payload.validation.issues.some(issue=>issue.code==='native_pdf_text_skipped'))
 const downloadLink=page.locator('.native-delivery a').filter({hasText:'下载 PDF'});await downloadLink.waitFor()
 assert.equal(await downloadLink.getAttribute('href'),payload.artifacts.pdf.downloadUrl)
 stage='actual-download'
 const downloaded=await page.request.get(payload.artifacts.pdf.downloadUrl);assert.equal(downloaded.status(),200)
 const bytes=await downloaded.body();assert.equal(sha(bytes),payload.artifacts.pdf.sha256);assert.equal(bytes.length,payload.artifacts.pdf.size)
 await writeFile(join(directory,'downloaded.pdf'),bytes)
 await page.screenshot({path:join(directory,'saved-warning-download.png'),fullPage:true})
 stage='reopen-new-revision'
 await page.goto(payload.editor.openUrl);await ready()
 reopened=await page.evaluate(async()=>await(await fetch(location.pathname+'/api/context')).json())
 await writeFile(join(directory,'reopened.json'),JSON.stringify(reopened,null,2))
 assert.equal(reopened.context.revision,5);assert.equal(reopened.context.sourceFile.sha256,payload.artifacts.pdf.sha256)
 await page.locator('.pdf-page .textLayer').filter({hasText:'CONTROL CONTENT'}).first().waitFor()
 await page.screenshot({path:join(directory,'reopened.png'),fullPage:true})
 stage='independent-pdf-verification'
 const verified=spawnSync(join(repo,'.venv/bin/python'),[join(frontend,'smoke/pdf-measure-crop-review-verify.py'),directory],{cwd:repo,encoding:'utf8'})
 assert.equal(verified.status,0,verified.stdout+verified.stderr);independent=JSON.parse(verified.stdout)
 await writeFile(join(directory,'independent.json'),JSON.stringify(independent,null,2))
 await page.waitForLoadState('networkidle');await Promise.all(checks)
 assert(assets.size>0);assert([...assets.keys()].some(path=>path.endsWith('.css')),'actual loaded CSS must be hashed')
 assert.deepEqual(pageErrors,[]);assert.deepEqual(consoleErrors,[]);assert.deepEqual(httpErrors,[]);assert.deepEqual(assetErrors,[])
 assert.deepEqual(await readFile(join(staticDirectory,'.vite/manifest.json')),manifest,'frozen production manifest must not change')
 const state=await(await fetch(origin+'/__smoke__/state',{signal:AbortSignal.timeout(1500)})).json()
 assert.equal(state.sourceSha256,info.sourceSha256);assert.equal(state.savedRevisions,1)
 const summary={ok:true,directory,feature:'calibrated measure label crop warning retains applied PDF preview/save/download/reopen',scope:'real production assets/PDF.js/HTTP/grant/cookie/CSRF/Node engine/publication/download/new revision; scoped in-memory save repository, not production DB',browserVersion:browser.version(),manifestSha256:sha(manifest),sourceSha256:info.sourceSha256,staged,preview,payload,reopened,independent,sourceUnchanged:true,assets:Object.fromEntries(assets),pageErrors,consoleErrors,httpErrors,assetErrors,requests:state.requests}
 await writeFile(join(directory,'summary.json'),JSON.stringify(summary,null,2));console.log(JSON.stringify({ok:true,directory,assets:assets.size}))
}catch(error){
 await page?.screenshot({path:join(directory,'failure.png'),fullPage:true}).catch(()=>{})
 if(page)await writeFile(join(directory,'failure.html'),await page.content()).catch(()=>{})
 await writeFile(join(directory,'failure.json'),JSON.stringify({stage,error:String(error),pageErrors,consoleErrors,httpErrors,assetErrors,staged,preview,payload,reopened,independent,assets:Object.fromEntries(assets),manifestSha256:sha(manifest)},null,2))
 throw error
}finally{
 await browser?.close();server.kill();await writeFile(join(directory,'server.log'),serverLog)
 if(server.exitCode===null)await Promise.race([new Promise(resolve=>server.once('exit',resolve)),delay(5000)])
 if(server.exitCode===null)server.kill('SIGKILL')
}
