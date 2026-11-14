// Zero-save follow-up: reopen a real downloaded PDF and exercise low-height wheel scrolling.
import assert from 'node:assert/strict'
import {spawn} from 'node:child_process'
import {createHash} from 'node:crypto'
import {mkdir,readFile,writeFile} from 'node:fs/promises'
import {resolve} from 'node:path'
import {fileURLToPath} from 'node:url'
import {chromium} from 'playwright'
import {createServer} from 'vite'
const frontend=fileURLToPath(new URL('../',import.meta.url)),repo=resolve(frontend,'../../..')
const output=resolve(process.env.PDF_STATIC_FILL_OUTPUT),source=resolve(process.env.PDF_STATIC_FILL_SOURCE_PDF)
const staticRoot=process.env.PDF_STATIC_FILL_STATIC_ROOT?resolve(process.env.PDF_STATIC_FILL_STATIC_ROOT):null
const sha=b=>createHash('sha256').update(b).digest('hex'),port=Number(process.env.PDF_STATIC_FILL_PORT??4478),origin=`http://127.0.0.1:${port}`
const expected=process.env.PDF_STATIC_FILL_MANIFEST_SHA256,resources=new Map(),errors=[],consoleErrors=[],httpErrors=[],checks=[]
await mkdir(output,{recursive:true});let server,vite,browser,page,log=''
const manifest=staticRoot?sha(await readFile(resolve(staticRoot,'.vite/manifest.json'))):null
if(staticRoot)assert.equal(manifest,expected)
try{
 if(!staticRoot){vite=await createServer({root:frontend,configFile:resolve(frontend,'vite.config.ts'),cacheDir:resolve(output,'vite-cache'),server:{host:'127.0.0.1',port:port+1,strictPort:true,hmr:false,watch:{ignored:['**/*']}}});await vite.listen()}
 server=spawn(resolve(repo,'.venv/bin/python'),[resolve(frontend,'smoke/pdf-static-fill-server.py'),'--directory',output,'--port',String(port),'--source',source],{cwd:repo,env:{...process.env,PYTHONPATH:repo,...(staticRoot?{PDF_SMOKE_STATIC_DIRECTORY:staticRoot}:{})},stdio:'pipe'})
 server.stdout.on('data',b=>log+=b);server.stderr.on('data',b=>log+=b)
 for(let n=0;;n++){assert.equal(server.exitCode,null,log);try{if((await fetch(origin+'/__smoke__/state')).ok)break}catch{}assert.ok(n<240,log);await new Promise(r=>setTimeout(r,250))}
 const info=JSON.parse(await readFile(resolve(output,'server-info.json'),'utf8'));assert.equal(info.sourceSha256,sha(await readFile(source)))
 browser=await chromium.launch({headless:true});page=await browser.newPage({viewport:{width:1024,height:480}})
 page.on('pageerror',e=>errors.push(e.message));page.on('console',m=>{if(m.type()==='error')consoleErrors.push(m.text())});page.on('response',r=>{if(r.status()>=400)httpErrors.push({url:r.url(),status:r.status()})})
 await page.route('**/reports/v1/editor/assets/**',async route=>{
  const url=new URL(route.request().url()),path=url.pathname,relative=decodeURIComponent(path.slice('/reports/v1/editor/assets/'.length));assert.ok(!relative.split('/').includes('..'))
  if(!staticRoot&&relative.startsWith('pdfjs/'))return route.fulfill({body:await readFile(resolve(frontend,'node_modules/pdfjs-dist',relative.slice(6))),contentType:relative.endsWith('.wasm')?'application/wasm':'application/octet-stream'})
  const response=await route.fetch(staticRoot?{}:{url:`http://127.0.0.1:${port+1}${path}${url.search}`}),body=await response.body()
  if(staticRoot&&/\.(?:m?js|css)$/.test(path)){assert.equal(response.status(),200);assert.equal(sha(body),sha(await readFile(resolve(staticRoot,relative))));resources.set(relative,{path:relative,size:body.length,sha256:sha(body)})}
  await route.fulfill({response,body})
 })
 if(!staticRoot)await page.route(/\/reports\/v1\/native\/[^/]+\/\d+$/,async route=>{const response=await route.fetch({url:`http://127.0.0.1:${port+1}/reports/v1/editor/assets/native.html`});await route.fulfill({response,body:await response.body()})})
 const granted=await page.request.get(origin+info.openPath);assert.equal(granted.status(),200);await page.goto(origin+'/reports/v1/native/'+info.context.documentId+'/'+info.context.revision)
 await page.waitForFunction(()=>document.querySelector('#report-editor')?.getAttribute('aria-busy')==='false'&&document.querySelector('.pdf-page-content canvas'),null,{timeout:90000})
 await page.locator('[data-pdf-ribbon-tab=fillForm]').click();await page.locator('[data-pdf-static-fill-action=manage]').click()
 let dialog=page.getByRole('dialog',{name:'管理静态填写',exact:true});assert.equal(await dialog.locator('[data-pdf-static-fill-id]').count(),2)
 await dialog.locator('[data-pdf-static-fill-kind=text]').getByRole('button',{name:'编辑文字/位置',exact:true}).click()
 dialog=page.getByRole('dialog',{name:'编辑静态填写',exact:true});assert.equal(await dialog.getByRole('textbox',{name:'静态填写文字',exact:true}).inputValue(),'保存后重新编辑')
 const before=await dialog.evaluate(el=>({height:el.clientHeight,scrollHeight:el.scrollHeight,scrollTop:el.scrollTop,overflowY:getComputedStyle(el).overflowY}));assert.equal(before.overflowY,'auto');assert.ok(before.scrollHeight>before.height)
 const bounds=await dialog.boundingBox();await page.mouse.move(bounds.x+bounds.width-30,bounds.y+bounds.height-70);await page.mouse.wheel(0,900)
 await page.waitForFunction(()=>document.querySelector('.pdf-static-fill-dialog')?.scrollTop>0)
 const confirm=dialog.getByRole('button',{name:'更新原位置',exact:true}),cancel=dialog.getByRole('button',{name:'取消',exact:true})
 for(const button of [confirm,cancel]){const b=await button.boundingBox();assert.ok(b.y>=0&&b.y+b.height<=480);const hit=await button.evaluate(el=>{const b=el.getBoundingClientRect();return el.contains(document.elementFromPoint(b.x+b.width/2,b.y+b.height/2))});assert.equal(hit,true)}
 await page.screenshot({path:resolve(output,'1024x480-wheel-bottom.png'),fullPage:true});await cancel.click();assert.equal(await page.locator('dialog[open]').count(),0);checks.push({name:'1024x480 actual wheel scroll exposes saved-fill confirm and cancel',before})
 await page.setViewportSize({width:390,height:844});await page.locator('[data-pdf-static-fill-action=text]').click();dialog=page.getByRole('dialog',{name:'添加静态填写文字',exact:true});assert.ok((await dialog.evaluate(el=>el.scrollWidth-el.clientWidth))<=2);await page.screenshot({path:resolve(output,'390x844-dialog.png'),fullPage:true});await dialog.getByRole('button',{name:'取消',exact:true}).click()
 const state=await(await page.request.get(origin+'/__smoke__/state')).json();assert.equal(state.savedRevisions,0);assert.equal(state.sourceSha256,info.sourceSha256);assert.deepEqual(errors,[]);if(staticRoot){assert.deepEqual(consoleErrors,[]);assert.deepEqual(httpErrors,[]);assert.equal(sha(await readFile(resolve(staticRoot,'.vite/manifest.json'))),manifest)}
 await writeFile(resolve(output,'evidence.json'),JSON.stringify({ok:true,mode:staticRoot?'frozen-production':'source-vite',manifest,sourceSha256:info.sourceSha256,savedRevisions:0,checks,resources:[...resources.values()],errors,consoleErrors,httpErrors,state},null,2))
}catch(error){if(page){await page.screenshot({path:resolve(output,'failure.png'),fullPage:true}).catch(()=>{});await writeFile(resolve(output,'failure-dom.txt'),await page.locator('body').innerText().catch(()=>''))}await writeFile(resolve(output,'failure.json'),JSON.stringify({error:String(error),errors,consoleErrors,httpErrors,log},null,2));throw error}
finally{await browser?.close();server?.kill('SIGTERM');await vite?.close();await writeFile(resolve(output,'server.log'),log)}
