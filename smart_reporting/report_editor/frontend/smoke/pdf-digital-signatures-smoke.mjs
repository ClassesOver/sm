// 真实原生签名读取与只读源面板；仓储夹具复用已有授权/CSRF/下载路由。
import assert from 'node:assert/strict'
import {spawn} from 'node:child_process'
import {createHash} from 'node:crypto'
import {mkdir,readFile,writeFile} from 'node:fs/promises'
import {join} from 'node:path'
import {fileURLToPath} from 'node:url'
import {setTimeout as delay} from 'node:timers/promises'
import {chromium} from 'playwright'
const frontend=fileURLToPath(new URL('../',import.meta.url)),repo=fileURLToPath(new URL('../../../../',import.meta.url))
const directory=process.env.PDF_SIGNATURES_OUTPUT,port=Number(process.env.PDF_SIGNATURES_PORT??4591),vitePort=Number(process.env.PDF_SIGNATURES_VITE_PORT??4592),origin='http://127.0.0.1:'+port
assert.ok(directory);assert.ok(process.env.PDF_FORM_DESIGN_SOURCE);await mkdir(directory,{recursive:true})
const dev=process.env.PDF_SIGNATURES_DEV!=='0',children=[],logs=[],errors=[],resourceReads=[],resources=new Map(),sha=b=>createHash('sha256').update(b).digest('hex')
function start(cmd,args,cwd,env=process.env){const child=spawn(cmd,args,{cwd,env,stdio:'pipe'});children.push(child);for(const stream of [child.stdout,child.stderr])stream.on('data',b=>logs.push(String(b)));return child}
async function wait(url,child){for(let i=0;i<240;i++){assert.equal(child.exitCode,null,logs.join(''));try{if((await fetch(url,{signal:AbortSignal.timeout(1500)})).ok)return}catch{}await delay(250)}throw Error(logs.join(''))}
let browser,page,stage='startup'
try{
 if(dev){const vite=start('./node_modules/.bin/vite',['--host','127.0.0.1','--port',String(vitePort),'--strictPort'],frontend);await wait(`http://127.0.0.1:${vitePort}/reports/v1/editor/assets/native.html`,vite)}
 const server=start(join(repo,'.venv/bin/python'),[join(frontend,'smoke/pdf-form-design-server.py'),'--directory',directory,'--port',String(port)],repo,{...process.env,PYTHONPATH:repo});await wait(origin+'/__smoke__/state',server)
 const info=JSON.parse(await readFile(join(directory,'server-info.json'),'utf8')),before=await(await fetch(origin+'/__smoke__/state')).json()
 await mkdir(join(directory,'browser-downloads'),{recursive:true})
 browser=await chromium.launch({headless:true,downloadsPath:join(directory,'browser-downloads'),executablePath:process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE??'/snap/bin/chromium'});page=await browser.newPage({viewport:{width:1440,height:900},acceptDownloads:true})
 page.on('pageerror',e=>errors.push(e.message));page.on('console',m=>{if(m.type()==='error'&&!/WebSocket|websocket|\[vite\]/.test(m.text()))errors.push(m.text())});page.on('requestfailed',r=>{if(!/WebSocket|websocket/.test(r.url()))errors.push(r.url()+' '+r.failure()?.errorText)})
 page.on('response',response=>{if(response.status()===200&&/\/api\/(preview|read-model)$/.test(response.url()))resourceReads.push(response.json().then(result=>writeFile(join(directory,'native-preview.json'),JSON.stringify(result,null,2))))
  if(response.status()===200&&response.url().includes('/reports/v1/editor/assets/'))resourceReads.push((async()=>{const bytes=Buffer.from(await response.body()),path=new URL(response.url()).pathname;resources.set(path,{sha256:sha(bytes),size:bytes.length,status:response.status()})})().catch(error=>errors.push(String(error))))})
 if(dev){await page.route('**/reports/v1/native/*/*',async route=>{if(/\/reports\/v1\/native\/[^/]+\/\d+$/.test(new URL(route.request().url()).pathname)){const response=await fetch(`http://127.0.0.1:${vitePort}/reports/v1/editor/assets/native.html`);return route.fulfill({contentType:'text/html',body:await response.text()})}return route.continue()});await page.route('**/reports/v1/editor/assets/**',async route=>{const u=new URL(route.request().url());if(u.pathname.includes('/assets/pdfjs/'))return route.continue();const response=await fetch(`http://127.0.0.1:${vitePort}`+u.pathname+u.search);return route.fulfill({status:response.status,contentType:response.headers.get('content-type')??'application/octet-stream',body:Buffer.from(await response.arrayBuffer())})})}
 const granted=await page.request.get(origin+info.openPath);assert.equal(granted.status(),200);await page.goto(granted.url());await page.waitForFunction(()=>document.querySelector('#report-editor')?.getAttribute('aria-busy')==='false',null,{timeout:90000})
 await page.locator('[data-pdf-ribbon-tab="annotate"]').click();const entry=page.locator('[data-source-command-id="genoffice.pdf.annotate.signature.signaturePanel"]'),dialog=page.locator('dialog.pdf-digital-signatures-dialog')
 const draft=()=>page.evaluate(()=>Object.entries(localStorage).filter(([key])=>key.startsWith('native-editor-draft:'))),draftBefore=await draft(),viewports=[]
 for(const[width,height]of [[1440,900],[640,360],[390,320],[320,640]]){
  stage=`layout-${width}x${height}`;await page.setViewportSize({width,height});await entry.scrollIntoViewIfNeeded();await entry.focus();await entry.click();await dialog.locator('.pdf-sig-card').waitFor()
  assert.match(await dialog.innerText(),/完整，信任未建立/);assert.match(await dialog.innerText(),/未检查证书吊销/);assert.match(await dialog.innerText(),/Signature Fixture/);assert.match(await dialog.innerText(),/SHA256/);assert.match(await dialog.innerText(),new RegExp(info.sourceSha256))
  const box=await dialog.boundingBox();assert.ok(box&&box.x>=0&&box.y>=0&&box.x+box.width<=width+1&&box.y+box.height<=height+1)
  assert.equal(await dialog.evaluate(el=>el.scrollWidth<=el.clientWidth+1),true)
  await dialog.locator('summary').click();const fingerprint=dialog.getByText('SHA-256 指纹',{exact:true});await fingerprint.scrollIntoViewIfNeeded();const fingerprintBox=await fingerprint.boundingBox();assert.ok(fingerprintBox&&fingerprintBox.y>=0&&fingerprintBox.y+fingerprintBox.height<=height)
  await page.screenshot({path:join(directory,`certificate-${width}x${height}.png`)});await dialog.getByRole('button',{name:'关闭',exact:true}).scrollIntoViewIfNeeded();await page.screenshot({path:join(directory,`signatures-${width}x${height}.png`)})
  await page.keyboard.press('Escape');await dialog.waitFor({state:'detached'});assert.equal(await entry.evaluate(el=>el===document.activeElement),true);viewports.push({width,height,box})
 }
 stage='navigation';await page.setViewportSize({width:1440,height:900});await entry.click();await dialog.getByRole('button',{name:/跳转到该页/}).click();await dialog.waitFor({state:'detached'});assert.deepEqual(await draft(),draftBefore)
 stage='native-browser-download';const downloaded=page.waitForEvent('download');await page.getByRole('link',{name:'下载原件',exact:true}).click();const download=await downloaded;await download.saveAs(join(directory,'downloaded-source.pdf'));assert.equal(await download.failure(),null);assert.equal(sha(await readFile(join(directory,'downloaded-source.pdf'))),info.sourceSha256)
 await Promise.all(resourceReads);const preview=JSON.parse(await readFile(join(directory,'native-preview.json'),'utf8'));assert.equal(preview.model.sourceSha256,info.sourceSha256);assert.equal(preview.model.digitalSignatures.length,1);assert.equal(preview.model.digitalSignatures[0].status,'untrusted');assert.equal(preview.model.signatureVerification.scope,'basic-integrity-only')
 const after=await(await fetch(origin+'/__smoke__/state')).json();assert.equal(after.sourceSha256,before.sourceSha256);assert.equal(after.savedRevisions,0);assert.equal(after.requests.filter(r=>r.method==='POST'&&/\/(save|export)$/.test(r.path)).length,0);assert.deepEqual(errors,[])
 if(process.env.PDF_FORM_DESIGN_READ_ONLY==='1'){assert.equal(after.requests.filter(r=>r.path.endsWith('/api/read-model')).length,1);assert.equal(after.requests.filter(r=>r.path.endsWith('/api/preview')).length,0)}
 const result={ok:true,mode:dev?'source-vite':'built-static',readOnly:process.env.PDF_FORM_DESIGN_READ_ONLY==='1',scope:'real grants/CSRF/native inspect/source browser download; memory repository; read-only basic cryptographic integrity, no PKI/revocation/timestamp/sign creation',sourceSha256:info.sourceSha256,viewports,resources:Object.fromEntries(resources),errors,sourceUnchanged:true,saves:after.savedRevisions}
 await writeFile(join(directory,'evidence.json'),JSON.stringify(result,null,2));console.log(JSON.stringify({ok:true,directory,resources:resources.size,viewports:viewports.length}))
}catch(error){await page?.screenshot({path:join(directory,'failure.png'),fullPage:true}).catch(()=>{});await writeFile(join(directory,'failure.json'),JSON.stringify({stage,error:String(error),stack:error.stack,errors},null,2));throw error}
finally{await browser?.close();for(const child of children)child.kill();await writeFile(join(directory,'server.log'),logs.join(''));await delay(300);for(const child of children)if(child.exitCode===null)child.kill('SIGKILL')}
