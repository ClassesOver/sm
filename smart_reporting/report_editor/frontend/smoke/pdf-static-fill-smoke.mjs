// Actual native HTTP/CSRF/revision/download lifecycle. Source mode proxies only Vite assets/HTML;
// frozen mode serves and hashes the exact supplied immutable production asset directory.
import assert from 'node:assert/strict'
import {spawn,spawnSync} from 'node:child_process'
import {createHash} from 'node:crypto'
import {mkdir,readFile,writeFile} from 'node:fs/promises'
import {resolve} from 'node:path'
import {fileURLToPath} from 'node:url'
import {chromium} from 'playwright'
import {createServer} from 'vite'

const frontend=fileURLToPath(new URL('../',import.meta.url)),repo=resolve(frontend,'../../..')
const directory=resolve(process.env.PDF_STATIC_FILL_OUTPUT??'/home/junge/codex-evidence/smart_reporting/office-pdf-static-fill-20261113-recovery/browser')
const staticRoot=process.env.PDF_STATIC_FILL_STATIC_ROOT?resolve(process.env.PDF_STATIC_FILL_STATIC_ROOT):null
const sourceRoot=process.env.PDF_STATIC_FILL_SOURCE_ROOT?resolve(process.env.PDF_STATIC_FILL_SOURCE_ROOT):frontend
const port=Number(process.env.PDF_STATIC_FILL_PORT??4468),origin=`http://127.0.0.1:${port}`
const hash=bytes=>createHash('sha256').update(bytes).digest('hex')
await mkdir(directory,{recursive:true})
const sourceFiles=['src/pdf-main.ts','src/pdf-ribbon.ts','src/pdf-operations.ts','src/pdf-static-fill.ts','src/vendor/genoffice-pdf/renderer/static-form-fill.ts','src/vendor/genoffice-pdf/renderer/form-mark-target.ts']
const sources={};for(const path of sourceFiles)sources[path]=hash(await readFile(resolve(sourceRoot,path)))
const manifest=staticRoot?hash(await readFile(resolve(staticRoot,'.vite/manifest.json'))):null
if(staticRoot)assert.equal(manifest,process.env.PDF_STATIC_FILL_MANIFEST_SHA256)
let vite,server,browser,page,log='',stage='server'
const errors=[],httpErrors=[],requests=[],resources=new Map(),checks=[],saves=[]
try{
 if(!staticRoot){vite=await createServer({root:frontend,configFile:resolve(frontend,'vite.config.ts'),cacheDir:resolve(process.env.PDF_STATIC_FILL_VITE_CACHE??resolve(directory,'../vite-cache')),server:{host:'127.0.0.1',port:port+1,strictPort:true,hmr:false,ws:false,watch:{ignored:['**/*']}}});await vite.listen()}
 server=spawn(resolve(repo,'.venv/bin/python'),[resolve(frontend,'smoke/pdf-static-fill-server.py'),'--directory',directory,'--port',String(port)],{cwd:repo,env:{...process.env,PYTHONPATH:repo,...(staticRoot?{PDF_SMOKE_STATIC_DIRECTORY:staticRoot}:{})},stdio:'pipe'})
 server.stdout.on('data',data=>log+=data);server.stderr.on('data',data=>log+=data)
 for(let attempt=0;;attempt++){assert.equal(server.exitCode,null,log);try{if((await fetch(origin+'/__smoke__/state')).ok)break}catch{}assert.ok(attempt<240,log);await new Promise(resolve=>setTimeout(resolve,250))}
 const info=JSON.parse(await readFile(resolve(directory,'server-info.json'),'utf8'))
 browser=await chromium.launch({headless:true});page=await browser.newPage({viewport:{width:1440,height:900}})
 page.on('pageerror',error=>errors.push(error.message));page.on('console',message=>{if(message.type()==='error')httpErrors.push({console:message.text()})});page.on('request',request=>{if(request.url().includes('/api/'))requests.push({url:request.url(),method:request.method()})});page.on('response',response=>{if(response.status()>=400)httpErrors.push({url:response.url(),status:response.status()})})
 await page.route('**/reports/v1/editor/assets/**',async route=>{
  const url=new URL(route.request().url()),relative=decodeURIComponent(url.pathname.slice('/reports/v1/editor/assets/'.length))
  if(relative.split('/').includes('..'))throw Error('invalid asset path')
  if(!staticRoot&&relative.startsWith('pdfjs/')){
   const body=await readFile(resolve(frontend,'node_modules/pdfjs-dist',relative.slice(6)));return route.fulfill({body,contentType:relative.endsWith('.wasm')?'application/wasm':'application/octet-stream'})
  }
  const response=await route.fetch(!staticRoot?{url:`http://127.0.0.1:${port+1}${url.pathname}${url.search}`}:{})
  const body=await response.body()
  if(staticRoot&&/\.(?:m?js|css)$/.test(url.pathname)){assert.equal(response.status(),200);const sha256=hash(body);assert.equal(sha256,hash(await readFile(resolve(staticRoot,relative))),relative);resources.set(relative,{path:relative,size:body.length,sha256})}
  await route.fulfill({response,body})
 })
 if(!staticRoot)await page.route(/\/reports\/v1\/native\/[^/]+\/\d+$/,async route=>{const response=await route.fetch({url:`http://127.0.0.1:${port+1}/reports/v1/editor/assets/native.html`});const html=(await response.text()).replace(/<script type="module" src="[^"]*\/@vite\/client"><\/script>/g,'');await route.fulfill({response,body:html})})
 const operations=()=>page.evaluate(()=>Object.entries(localStorage).filter(([key])=>key.startsWith('native-editor-draft:')).map(([,value])=>JSON.parse(value).operations).at(-1)??[])
 const waitOps=count=>page.waitForFunction(count=>Object.entries(localStorage).filter(([key])=>key.startsWith('native-editor-draft:')).map(([,value])=>JSON.parse(value).operations).at(-1)?.length===count,count)
 const loaded=()=>page.waitForFunction(()=>document.querySelector('#report-editor')?.getAttribute('aria-busy')==='false'&&document.querySelector('.pdf-page-content canvas'),null,{timeout:90000})
 const action=name=>page.locator(`[data-pdf-static-fill-action="${name}"]`)
 async function fillTab(){await page.locator('[data-pdf-ribbon-tab=fillForm]').click()}
 async function pointOnPage(index,x,y){const content=page.locator('.pdf-page-content').nth(index);await content.scrollIntoViewIfNeeded();await content.locator('canvas').waitFor();const bounds=await content.boundingBox();await page.mouse.click(bounds.x+bounds.width*x/400,bounds.y+bounds.height*(500-y)/500)}
 async function previewSave(filename){
  await page.locator('[data-pdf-ribbon-tab=edit]').click();const count=(await operations()).length
  const [previewResponse]=await Promise.all([page.waitForResponse(r=>r.url().endsWith('/api/preview')&&r.request().postDataJSON()?.operations?.length===count,{timeout:90000}),page.getByRole('button',{name:'校验当前修改',exact:true}).click()])
  assert.equal(previewResponse.status(),200);const preview=await previewResponse.json();assert.deepEqual(preview.skippedOperations,[]);assert.equal(preview.appliedOperationIndices.length,count)
  await page.locator('.pdf-preview-review input[type=checkbox]').check()
  await page.screenshot({path:resolve(directory,filename+'.preview.png'),fullPage:true})
  const [saveResponse]=await Promise.all([page.waitForResponse(r=>r.url().endsWith('/api/save'),{timeout:90000}),page.locator('[data-action=save]').click()])
  const saved=await saveResponse.json();assert.equal(saveResponse.status(),200,JSON.stringify(saved));assert.equal(saved.validation.ok,false);assert.equal(saved.revisionRegistered,true)
  const response=await page.request.get(saved.artifacts.pdf.downloadUrl);assert.equal(response.status(),200);const bytes=await response.body();assert.equal(hash(bytes),saved.artifacts.pdf.sha256);assert.equal(bytes.length,saved.artifacts.pdf.size)
  await writeFile(resolve(directory,filename),bytes);await writeFile(resolve(directory,filename+'.json'),JSON.stringify({preview,saved},null,2));saves.push(saved)
  return saved
 }
 async function reopen(){const link=page.getByRole('link',{name:'打开新修订继续编辑',exact:true});if(staticRoot)await link.click();else{const granted=await page.request.get(await link.getAttribute('href'));assert.equal(granted.status(),200);await page.goto(granted.url())}await loaded();await fillTab()}
 stage='load';const granted=await page.request.get(origin+info.openPath);assert.equal(granted.status(),200);await page.goto(origin+'/reports/v1/native/'+info.context.documentId+'/'+info.context.revision);await loaded();await fillTab();assert.equal(await action('text').isEnabled(),true)
 stage='text-cancel';await action('text').click();let dialog=page.getByRole('dialog',{name:'添加静态填写文字',exact:true});await dialog.getByRole('textbox',{name:'静态填写文字',exact:true}).fill('取消内容');await dialog.getByRole('button',{name:'取消',exact:true}).click();assert.deepEqual(await operations(),[])
 stage='text';await action('text').click();await dialog.getByRole('textbox',{name:'静态填写文字',exact:true}).fill('中文填写\nStatic form');await dialog.getByRole('spinbutton',{name:'静态填写字号',exact:true}).fill('16');await dialog.locator('[data-pdf-static-fill-confirm]').click();await pointOnPage(0,180,250);await waitOps(1);assert.equal((await operations())[0].text,'中文填写\nStatic form');checks.push('CJK multiline bitmap and source-space point')
 stage='check';await action('check').click();await pointOnPage(0,62,357);await waitOps(2);assert.deepEqual((await operations())[1].rect,[55,350,69,364]);checks.push('smallest printed box snap')
 stage='cross-cancel';await action('cross').click();await page.keyboard.press('Escape');assert.equal((await operations()).length,2)
 stage='cross';await action('cross').click();await pointOnPage(1,62,357);await waitOps(3);checks.push('cross on another source page; Escape cancel')
 stage='native-checkbox';await action('check').click();await pointOnPage(0,238,358);await waitOps(4);assert.equal((await operations()).filter(op=>op.kind==='setFormValue'&&op.name==='NativeCheck'&&op.checked).length,1);checks.push('interactive checkbox uses existing native field')
 stage='complete';await action('complete').click();await page.locator('.pdf-editor-message').filter({hasText:'填写完成提示'}).waitFor();assert.equal((await operations()).length,4);checks.push('required soft completion never discards draft')
 await page.screenshot({path:resolve(directory,'desktop.png'),fullPage:true})
 stage='undo-redo';await page.locator('[data-pdf-ribbon-tab=home]').click();await page.locator('[data-source-command-id="genoffice.pdf.home.edit.undo"]').click();await waitOps(3);await page.locator('[data-source-command-id="genoffice.pdf.home.edit.redo"]').click();await waitOps(4);checks.push('real NativeDraft undo redo')
 stage='save-first';await previewSave('downloaded.pdf')
 stage='reopen';await reopen();await action('manage').click();let manage=page.getByRole('dialog',{name:'管理静态填写',exact:true});await manage.getByRole('button',{name:'编辑文字/位置',exact:true}).click();dialog=page.getByRole('dialog',{name:'编辑静态填写',exact:true});assert.equal(await dialog.getByRole('textbox',{name:'静态填写文字',exact:true}).inputValue(),'中文填写\nStatic form');await dialog.getByRole('textbox',{name:'静态填写文字',exact:true}).fill('保存后重新编辑');await dialog.getByRole('button',{name:'更新原位置',exact:true}).click();await waitOps(1);assert.match((await operations())[0].expectedImageSha256,/^[a-f0-9]{64}$/);checks.push('reopen edit binds saved image fingerprint')
 stage='geometry';await action('manage').click();manage=page.getByRole('dialog',{name:'管理静态填写',exact:true});await manage.locator('[data-pdf-static-fill-kind=check]').getByRole('button',{name:'调整位置/大小',exact:true}).click();dialog=page.getByRole('dialog',{name:'静态填写位置与大小',exact:true});for(const [name,value]of [['左边 X','75'],['底边 Y','340'],['宽度','20'],['高度','22']])await dialog.getByRole('spinbutton',{name:'静态填写'+name,exact:true}).fill(value);await dialog.getByRole('button',{name:'暂存位置与大小',exact:true}).click();await waitOps(2)
 stage='delete';await action('manage').click();manage=page.getByRole('dialog',{name:'管理静态填写',exact:true});await manage.locator('[data-pdf-static-fill-kind=cross]').getByRole('button',{name:'删除',exact:true}).click();await waitOps(3);assert.equal((await operations()).filter(op=>op.kind==='removeStaticFill').length,1);checks.push('saved mark position/size and source-bound delete')
 stage='modal-viewports';for(const [width,height]of [[390,844],[1024,480]]){await page.setViewportSize({width,height});await action('text').click();dialog=page.getByRole('dialog',{name:'添加静态填写文字',exact:true});await dialog.getByRole('textbox',{name:'静态填写文字',exact:true}).fill('布局核对');const geometry=await dialog.evaluate(el=>({width:el.clientWidth,scrollWidth:el.scrollWidth,height:el.clientHeight,scrollHeight:el.scrollHeight}));assert.ok(geometry.scrollWidth<=geometry.width+2);await page.screenshot({path:resolve(directory,`dialog-${width}x${height}.png`),fullPage:true});await dialog.getByRole('button',{name:'取消',exact:true}).click()}
 await page.setViewportSize({width:1440,height:900});stage='save-edited';await previewSave('downloaded-edited.pdf');checks.push('second actual saved/downloaded revision after edit, geometry, removal')
 stage='independent-readback';const verification=spawnSync(resolve(repo,'.venv/bin/python'),[resolve(frontend,'smoke/pdf-static-fill-verify.py'),directory],{cwd:repo,env:{...process.env,PYTHONPATH:repo},encoding:'utf8'});await writeFile(resolve(directory,'independent-readback.log'),verification.stdout+verification.stderr);assert.equal(verification.status,0,verification.stderr)
 const state=await(await page.request.get(origin+'/__smoke__/state')).json();assert.equal(state.sourceSha256,info.sourceSha256);assert.equal(state.savedRevisions,2);assert.deepEqual(errors,[]);assert.deepEqual(httpErrors,[])
 if(staticRoot)assert.equal(hash(await readFile(resolve(staticRoot,'.vite/manifest.json'))),manifest)
 for(const path of sourceFiles)assert.equal(hash(await readFile(resolve(sourceRoot,path))),sources[path],path)
 await writeFile(resolve(directory,'evidence.json'),JSON.stringify({ok:true,mode:staticRoot?'frozen-production':'source-vite-native-http',manifest,sources,checks,saves,resources:[...resources.values()],errors,httpErrors,requests,state},null,2))
}catch(error){if(page){await page.screenshot({path:resolve(directory,'failure.png'),fullPage:true}).catch(()=>{});await writeFile(resolve(directory,'failure-dom.txt'),await page.locator('body').innerText().catch(()=>''))}await writeFile(resolve(directory,'failure.json'),JSON.stringify({stage,error:String(error),errors,httpErrors,requests,log},null,2));throw error}
finally{await browser?.close();server?.kill('SIGTERM');await vite?.close();await writeFile(resolve(directory,'server.log'),log)}
