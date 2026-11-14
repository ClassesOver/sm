import assert from 'node:assert/strict'
import {spawn} from 'node:child_process'
import {createHash} from 'node:crypto'
import {mkdir,readFile,writeFile} from 'node:fs/promises'
import {resolve} from 'node:path'
import {fileURLToPath} from 'node:url'
import {chromium} from 'playwright'
import {build} from 'vite'

const frontend=fileURLToPath(new URL('../',import.meta.url)),repo=resolve(frontend,'../../..')
const output=resolve(process.env.PDF_STATIC_TEXT_THUMBNAIL_OUTPUT??'/tmp/pdf-static-text-thumbnail-20261113')
const port=Number(process.env.PDF_STATIC_TEXT_THUMBNAIL_PORT??4298),origin=`http://127.0.0.1:${port}`
const sha=bytes=>createHash('sha256').update(bytes).digest('hex'),resources=new Map(),requests=[],apiBodies=[],pageErrors=[],consoleErrors=[],httpErrors=[]
await mkdir(output,{recursive:true})
let server,browser,page,serverLog=''
try{
 const staticRoot=resolve(process.env.PDF_STATIC_TEXT_THUMBNAIL_STATIC_ROOT??resolve(output,'static'))
 if(!process.env.PDF_STATIC_TEXT_THUMBNAIL_STATIC_ROOT)await build({root:frontend,configFile:resolve(frontend,'vite.config.ts'),cacheDir:resolve(output,'vite-cache'),build:{outDir:staticRoot,emptyOutDir:true}})
 server=spawn(resolve(repo,'.venv/bin/python'),[resolve(frontend,'smoke/pdf-static-text-thumbnail-server.py'),'--directory',output,'--port',String(port)],{cwd:repo,env:{...process.env,PYTHONPATH:repo,PDF_SMOKE_STATIC_DIRECTORY:staticRoot},stdio:'pipe'})
 server.stdout.on('data',data=>serverLog+=data);server.stderr.on('data',data=>serverLog+=data)
 for(let n=0;;n++){assert.equal(server.exitCode,null,serverLog);try{if((await fetch(origin+'/__smoke__/state')).ok)break}catch{}assert.ok(n<240,serverLog);await new Promise(r=>setTimeout(r,250))}
 const info=JSON.parse(await readFile(resolve(output,'server-info.json'),'utf8'))
 assert.deepEqual(info.sourcePages.map(item=>item.rotation),[90,270]);assert.ok(info.sourcePages.every(item=>item.cropBox[0]!==0&&item.cropBox[1]!==0))
 browser=await chromium.launch({headless:true,...(process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE?{executablePath:process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE}:{})})
 page=await browser.newPage({viewport:{width:1440,height:1100},deviceScaleFactor:1})
 page.on('pageerror',error=>pageErrors.push(error.message));page.on('console',message=>{if(message.type()==='error')consoleErrors.push(message.text())});page.on('response',async response=>{if(response.status()>=400)httpErrors.push({url:response.url(),status:response.status(),body:await response.text().catch(()=> '')});if(response.url().endsWith('/api/preview'))apiBodies.push({status:response.status(),body:await response.text().catch(()=> '')})})
 await page.route('**/*',async route=>{
  const url=new URL(route.request().url()),path=url.pathname
  if(url.origin!==origin){await route.continue();return}
  if(path.startsWith('/reports/v1/native/open/')){await route.continue();return}
  if(path.startsWith('/reports/v1/editor/assets/')){
   const relative=decodeURIComponent(path.slice('/reports/v1/editor/assets/'.length));assert.ok(!relative.split('/').includes('..'))
   const response=await route.fetch(),body=await response.body()
   assert.equal(response.status(),200);assert.equal(sha(body),sha(await readFile(resolve(staticRoot,relative))))
   resources.set(path,{path,size:body.length,sha256:sha(body)});await route.fulfill({response,body});return
  }
  const response=await route.continue();requests.push({path,status:response?.status()})
 })
 const granted=await page.request.get(origin+info.openPath);assert.equal(granted.status(),200)
 await page.goto(origin+info.openPath)
 await page.waitForFunction(()=>document.querySelector('#report-editor')?.getAttribute('aria-busy')==='false'&&document.querySelectorAll('.pdf-page-content canvas').length===2,null,{timeout:90000})
 const pages=await page.locator('.pdf-page').evaluateAll(nodes=>nodes.map(node=>({pageId:node.dataset.pageId,label:node.getAttribute('aria-label')})))
 assert.deepEqual(pages.map(item=>item.pageId),[0,1].map(index=>`sha256:${info.sourceSha256}:page:${index}`))
 const geometry=await page.evaluate(()=>[...document.querySelectorAll('.pdf-page')].map(node=>({pageId:node.dataset.pageId,canvas:node.querySelector('canvas')?.getBoundingClientRect().toJSON()})))
 const staged=[];let previewState,preview,duplicateOverlayCount
 for(const index of [0,1]){
  await page.locator('[data-source-command-id="genoffice.pdf.home.edit.insertText"]').click()
  const dialog=page.getByRole('dialog',{name:'插入文字',exact:true});await dialog.waitFor({state:'visible'})
  await dialog.getByLabel('插入文字内容',{exact:true}).fill(`${index===0?90:270}`)
  await dialog.locator('[data-pdf-static-text-confirm]').click()
  const holder=page.locator(`.pdf-page[data-page-id="sha256:${info.sourceSha256}:page:${index}"] .pdf-page-content`)
  await holder.locator('canvas').waitFor();const bounds=await holder.boundingBox();assert.ok(bounds)
  await holder.click({position:{x:bounds.width*.52,y:bounds.height*.48}})
  await page.waitForFunction(()=>JSON.parse(Object.entries(localStorage).find(([key])=>key.startsWith('native-editor-draft:'))?.[1]??'{"operations":[]}').operations.length===1)
  const operation=await page.evaluate(()=>JSON.parse(Object.entries(localStorage).find(([key])=>key.startsWith('native-editor-draft:'))[1]).operations[0])
  assert.equal(operation.kind,'insertText');assert.equal(operation.sourceSha256,info.sourceSha256);assert.equal(operation.pageId,`sha256:${info.sourceSha256}:page:${index}`)
  const thumb=page.locator(`.pdf-thumbnail[data-page-id="${operation.pageId}"]`),overlay=thumb.locator('[data-pdf-static-text-thumb]')
  await overlay.waitFor();assert.equal(await overlay.textContent(),operation.text);assert.equal(await overlay.evaluate(el=>el.style.pointerEvents),'none')
  const metrics=await overlay.evaluate(el=>({left:el.style.left,top:el.style.top,fontSize:el.style.fontSize,transform:el.style.transform,box:el.getBoundingClientRect().toJSON()}))
  assert.ok(metrics.box.width>0&&metrics.box.height>0);assert.ok(metrics.fontSize.endsWith('cqw'))
  staged.push({operation,thumbnail:metrics})
  await page.screenshot({path:resolve(output,`pending-${index===0?90:270}.png`),fullPage:true})
  if(index===0)await page.locator('[data-source-command-id="genoffice.pdf.home.edit.undo"]').click()
  else{
   await page.locator('[data-pdf-ribbon-tab="edit"]').click()
   await page.getByRole('button',{name:'校验当前修改',exact:true}).click()
   await new Promise(resolve=>setTimeout(resolve,4000))
   previewState=await page.locator('#report-editor').getAttribute('data-pdf-preview')
   preview=JSON.parse(apiBodies.filter(item=>item.status===200).at(-1).body);assert.deepEqual(preview.appliedOperationIndices,[0])
   duplicateOverlayCount=await page.locator('[data-pdf-static-text-thumb]').count();assert.equal(duplicateOverlayCount,0)
   await page.screenshot({path:resolve(output,'actual-preview-270.png'),fullPage:true})
  }
 }
 assert.deepEqual(pageErrors,[]);assert.deepEqual(consoleErrors,[]);assert.deepEqual(httpErrors,[])
 await writeFile(resolve(output,'evidence.json'),JSON.stringify({ok:true,mode:'isolated Vite build and PDF.js sidecars under /tmp + real PDF.js + real HTTP editor grant/API + real preview engine',browserVersion:browser.version(),sourceSha256:info.sourceSha256,sourcePages:info.sourcePages,geometry,staged,previewState,preview,apiBodies,previewDuplicateOverlayCount:duplicateOverlayCount,resources:[...resources.values()],requests,pageErrors,consoleErrors,httpErrors},null,2))
 console.log(JSON.stringify({ok:true,output,sourceSha256:info.sourceSha256,assets:resources.size}))
}catch(error){
 await page?.screenshot({path:resolve(output,'failure.png'),fullPage:true}).catch(()=>{})
 await writeFile(resolve(output,'failure.json'),JSON.stringify({error:String(error),serverLog,pageErrors,consoleErrors,httpErrors,apiBodies,requests},null,2));throw error
}finally{
 await browser?.close();server?.kill('SIGTERM');await writeFile(resolve(output,'server.log'),serverLog)
 if(server?.exitCode===null)await Promise.race([new Promise(resolve=>server.once('exit',resolve)),new Promise(resolve=>setTimeout(resolve,5000))])
 if(server?.exitCode===null)server.kill('SIGKILL')
}
