// 实际原生宿主与Python保存；授权、CSRF、修订登记为显式HTTP路由夹具。
import assert from 'node:assert/strict'
import {createHash} from 'node:crypto'
import {spawn,spawnSync} from 'node:child_process'
import {setTimeout as delay} from 'node:timers/promises'
import {mkdir,readFile,writeFile,access} from 'node:fs/promises'
import {join,resolve} from 'node:path'
import {fileURLToPath} from 'node:url'
import {isDeepStrictEqual} from 'node:util'
import {createServer} from 'node:http'
import {chromium} from 'playwright'
import {inspectSymbolLayout} from './office-xlsx-symbol-layout.mjs'
const frontend=fileURLToPath(new URL('../',import.meta.url)),repo=resolve(frontend,'../../..'),staticRoot=resolve(process.env.PDF_SMOKE_STATIC_DIRECTORY??resolve(frontend,'../static'))
const directory=process.env.WORKBOOK_SYMBOL_OUTPUT,port=Number(process.env.WORKBOOK_SYMBOL_PORT??4393),base='http://127.0.0.1:'+port
assert.ok(directory,'WORKBOOK_SYMBOL_OUTPUT must name a fresh evidence directory');await mkdir(directory,{recursive:true})
let prior=false;try{await access(join(directory,'save.json'));prior=true}catch{}assert.equal(prior,false,'never repeat a successful save in this directory')
const sha=b=>createHash('sha256').update(b).digest('hex'),manifest=await readFile(join(staticRoot,'.vite/manifest.json'))
assert.equal(sha(manifest),process.env.WORKBOOK_EXPECTED_MANIFEST_SHA256);await writeFile(join(directory,'build-manifest.json'),manifest)
function python(mode,extra={}){const r=spawnSync(join(repo,'.venv/bin/python'),[join(frontend,'smoke/office-xlsx-symbol-fixture.py')],{cwd:repo,env:{...process.env,PYTHONPATH:repo},input:JSON.stringify({mode,directory,...extra}),encoding:'utf8',timeout:120000,maxBuffer:20*1024*1024});assert.equal(r.status,0,r.stderr);return JSON.parse(r.stdout)}
python('create');const source=await readFile(join(directory,'source.xlsx')),revisions={1:source},errors=[],checks=[],resources=new Map(),requests=[],layout={cases:[],failures:[]}
const media='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
let browser,page,server,downloadServer,downloadUrl,stage='preview',saved=false
try{
 downloadServer=createServer((request,response)=>{const bytes=revisions[2];requests.push({method:request.method,path:'download-http'});if(!bytes){response.writeHead(404);response.end();return}response.writeHead(200,{'Content-Type':media,'Content-Disposition':'attachment; filename=symbol-pc.xlsx','Content-Length':bytes.length});response.end(bytes)})
 await new Promise((done,reject)=>{downloadServer.once('error',reject);downloadServer.listen(0,'127.0.0.1',done)});downloadUrl='http://127.0.0.1:'+downloadServer.address().port+'/symbol-pc-download.xlsx'
 server=spawn('./node_modules/.bin/vite',['preview','--outDir',staticRoot,'--host','127.0.0.1','--port',String(port),'--strictPort'],{cwd:frontend,stdio:'ignore'})
 for(let i=0;;i++){assert.equal(server.exitCode,null);try{if((await fetch(base+'/reports/v1/editor/assets/native.html',{signal:AbortSignal.timeout(1500)})).ok)break}catch{}assert.ok(i<120,'preview not ready');await delay(250)}
 browser=await chromium.launch({headless:true,...(process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE?{executablePath:process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE}:{})});const context=await browser.newContext({viewport:{width:1440,height:900}});page=await context.newPage()
 page.on('pageerror',e=>errors.push(e.message));page.on('console',m=>{if(m.type()==='error')errors.push(m.text())});page.on('crash',()=>errors.push('renderer crashed'))
 page.on('response',r=>{const path=new URL(r.url()).pathname;if(r.status()>=400)errors.push(r.status()+' '+path);if(r.status()===200&&path.startsWith('/reports/v1/editor/assets/')&&/\.(?:m?js|css)$/.test(path))checks.push(r.body().then(async b=>{assert.equal(sha(b),sha(await readFile(join(staticRoot,path.slice('/reports/v1/editor/assets/'.length)))));resources.set(path,{size:b.length,sha256:sha(b)})}).catch(e=>errors.push(String(e))))})
 await page.route('**/reports/v1/native/symbol-pc/**',async route=>{
  const request=route.request(),match=new URL(request.url()).pathname.match(/\/symbol-pc\/(\d+)(.*)$/),revision=Number(match[1]),suffix=match[2],bytes=revisions[revision]
  if(!suffix)return route.fulfill({response:await route.fetch({url:base+'/reports/v1/editor/assets/native.html'})})
  requests.push({method:request.method(),path:suffix})
  if(suffix==='/api/context')return route.fulfill({json:{context:{documentId:'symbol-pc',format:'xlsx',revision,parentRevision:revision>1?revision-1:null,scope:{database:'fixture',companyId:'fixture',userId:'fixture',threadId:'fixture'},sourceFile:{path:'symbol.xlsx',size:bytes.length,sha256:sha(bytes),mediaType:media},origin:'upload'},csrfToken:'fixture',capabilities:{xlsx_editor:true},editingEnabled:true}})
  if(suffix==='/api/file')return route.fulfill({body:bytes,contentType:media})
  if(suffix==='/api/save'){
   assert.equal(saved,false,'one actual save only');const input=request.postDataJSON();assert.equal(input.expectedSha256,sha(source));const artifact=python('patch',{operations:input.operations});revisions[2]=await readFile(join(directory,'revision-2.xlsx'));saved=true
   const result={documentId:'symbol-pc',revision:2,parentRevision:1,revisionRegistered:true,artifacts:{xlsx:{downloadUrl,...artifact}},editor:{openUrl:base+'/reports/v1/native/symbol-pc/2'},validation:{ok:false,issues:[{code:'manual_review',message:'符号插入版式待复核，文件已生成。'}]}}
   await writeFile(join(directory,'save.json'),JSON.stringify({request:input,result},null,2));return route.fulfill({json:result})
  }
  throw Error('unexpected native route '+suffix)
 })
 const ready=()=>page.waitForFunction(()=>document.querySelector('#report-editor')?.getAttribute('aria-busy')==='false',null,{timeout:90000})
 const draft=()=>page.evaluate(()=>Object.entries(localStorage).filter(([k])=>k.startsWith('native-editor-draft:')).map(([k,v])=>[k,JSON.parse(v).operations]))
 const operations=async()=>(await draft()).flatMap(([,ops])=>ops)
 const waitOperations=async expected=>{for(let i=0;i<100;i++){const current=await operations();if(isDeepStrictEqual(current,expected))return current;await delay(100)}assert.deepEqual(await operations(),expected)}
 const history=async command=>{await page.locator('[data-ribbon-tab="File"]').click();await page.locator(`[data-ribbon-command="${command}"]`).click()}
 const go=async ref=>{const input=page.locator('[data-u-comp="defined-name"] input');await input.fill(ref);await input.press('Enter');await delay(150)}
 const dialog=page.getByRole('dialog',{name:'插入符号',exact:true}),entry=page.locator('[data-ribbon-command="insert-symbol"]')
 const open=async()=>{await page.locator('[data-ribbon-tab="Insert"]').click();await entry.click();await dialog.waitFor()}
 const assertEntry=async()=>assert.equal(await entry.evaluate(n=>n===document.activeElement),true)
 await page.goto(base+'/reports/v1/native/symbol-pc/1');await ready();await go('A1');await open();stage='initial'
 await inspectSymbolLayout(page,{directory,phase:'category-0',layout,draft})
 if(process.env.WORKBOOK_SYMBOL_BASELINE==='1'){
  assert.equal(saved,false);await Promise.all(checks);assert.deepEqual(errors,[]);await writeFile(join(directory,'baseline.json'),JSON.stringify({baseline:true,manifest:sha(manifest),layout,saved,errors},null,2));console.log(JSON.stringify({baseline:true,cases:layout.cases.length,failures:layout.failures.length}))
 }else{
 assert.deepEqual(layout.failures,[])
 stage='categories'
 for(let index=1;index<5;index++){
  const tab=dialog.locator(`[data-symbol-category="${index}"]`);await tab.click();assert.equal(await tab.evaluate(n=>n===document.activeElement),true)
  await inspectSymbolLayout(page,{directory,phase:'category-'+index,layout,draft});assert.deepEqual(layout.failures,[])
 }
 assert.deepEqual(await operations(),[])
 const tab=dialog.locator('[data-symbol-category="4"]');await tab.focus();await tab.press('ArrowRight');assert.equal(await dialog.locator('[role=tab][aria-selected=true]').getAttribute('data-symbol-category'),'0');await page.keyboard.press('End');assert.equal(await dialog.locator('[role=tab][aria-selected=true]').getAttribute('data-symbol-category'),'4');await page.keyboard.press('Home');assert.equal(await dialog.locator('[role=tab][aria-selected=true]').getAttribute('data-symbol-category'),'0')
 await dialog.locator('[data-symbol="€"]').focus();await page.keyboard.press('ArrowRight');assert.equal(await dialog.locator('[data-symbol="£"]').evaluate(n=>n===document.activeElement),true);await page.keyboard.press('End');assert.equal(await dialog.locator('[data-symbol="¿"]').evaluate(n=>n===document.activeElement),true);await page.keyboard.press('Home');assert.equal(await dialog.locator('[data-symbol="€"]').evaluate(n=>n===document.activeElement),true)
 const columns=await dialog.locator('.workbook-symbol-grid').evaluate(n=>getComputedStyle(n).gridTemplateColumns.split(' ').filter(Boolean).length),symbols=await dialog.locator('[data-symbol]').evaluateAll(nodes=>nodes.map(n=>n.dataset.symbol))
 await page.keyboard.press('ArrowDown');assert.equal(await dialog.locator(`[data-symbol="${symbols[columns]}"]`).evaluate(n=>n===document.activeElement),true);await page.keyboard.press('ArrowUp');assert.equal(await dialog.locator('[data-symbol="€"]').evaluate(n=>n===document.activeElement),true);assert.deepEqual(await operations(),[])
 await dialog.getByRole('button',{name:'关闭插入符号',exact:true}).click();await assertEntry();assert.deepEqual(await operations(),[])
 stage='formula-error';await go('C1');await open();await dialog.locator('[data-symbol-category="0"]').click();await dialog.locator('[data-symbol="€"]').click();assert.match(await dialog.locator('[role=alert]').textContent(),/含公式/)
 await inspectSymbolLayout(page,{directory,phase:'formula-error',layout,draft});assert.deepEqual(layout.failures,[]);assert.deepEqual(await operations(),[])
 await page.keyboard.press('Escape');await dialog.waitFor({state:'hidden'});await assertEntry()
 stage='insert';await go('A1');await open();await dialog.locator('[data-symbol-category="0"]').click();await dialog.locator('[data-symbol="€"]').focus();await page.keyboard.press('Enter');assert.match(await dialog.locator('[data-symbol-status]').textContent(),/已插入 €/)
 await dialog.locator('[data-symbol-category="2"]').click();await dialog.locator('[data-symbol="→"]').focus();await page.keyboard.press('Space');assert.match(await dialog.locator('[data-symbol-status]').textContent(),/已插入 →/)
 const applied=await operations();assert.deepEqual(applied,[{kind:'applyCellEdits',edits:[{sheetName:'Data',row:0,column:0,cell:{value:'价格 & <保真> 😀€→'},writeValue:true}]}]);await inspectSymbolLayout(page,{directory,phase:'inserted',layout,draft});assert.deepEqual(layout.failures,[]);await dialog.locator('[data-symbol-close]').click();await assertEntry()
 const expectedUndo=structuredClone(applied);expectedUndo[0].edits[0].cell.value='价格 & <保真> 😀€'
 await history('undo');await waitOperations(expectedUndo);await history('redo');await waitOperations(applied)
 await page.reload();await ready();assert.deepEqual(await operations(),applied)
 stage='save';await page.locator('[data-action=save]').click();await page.waitForFunction(()=>document.querySelector('.save-state-label')?.textContent?.includes('已保存修订 2'),null,{timeout:90000});assert.equal(saved,true)
 const receipt=JSON.parse(await readFile(join(directory,'save.json'),'utf8')),link=page.locator('[data-action=xlsx-download]');await link.waitFor();const downloading=page.waitForEvent('download');await link.click();const download=await downloading;assert.equal(await download.failure(),null);await download.saveAs(join(directory,'downloaded.xlsx'));const bytes=await readFile(join(directory,'downloaded.xlsx'));assert.deepEqual(bytes,revisions[2]);assert.equal(sha(bytes),receipt.result.artifacts.xlsx.sha256)
 assert.equal(receipt.result.validation.ok,false);assert.match(await page.locator('.workbook-feedback').innerText(),/符号插入版式待复核/)
 const independent=python('verify')
 stage='reopen';await page.goto(receipt.result.editor.openUrl);await ready();await open();await inspectSymbolLayout(page,{directory,phase:'reopened',layout,draft});assert.deepEqual(layout.failures,[]);await page.keyboard.press('Escape');await dialog.waitFor({state:'hidden'});await assertEntry()
 await Promise.all(checks);assert.deepEqual(errors,[]);assert.deepEqual(await readFile(join(staticRoot,'.vite/manifest.json')),manifest)
 await writeFile(join(directory,'evidence.json'),JSON.stringify({ok:true,manifest:sha(manifest),routeIsFixture:true,realPythonSave:true,actualBrowserDownload:true,savedRevisions:1,layout,applied,independent,resources:Object.fromEntries(resources),requests,errors},null,2));console.log(JSON.stringify({ok:true,cases:layout.cases.length,resources:resources.size,directory}))
 }
}catch(error){await page?.screenshot({path:join(directory,'failure.png'),fullPage:true}).catch(()=>{});await writeFile(join(directory,'failure.json'),JSON.stringify({stage,error:String(error),stack:error.stack,saved,errors},null,2));throw error}
finally{await browser?.close();server?.kill();if(server?.exitCode===null)await Promise.race([new Promise(done=>server.once('exit',done)),delay(5000)]);if(server?.exitCode===null)server.kill('SIGKILL');if(downloadServer?.listening)await new Promise(done=>downloadServer.close(done))}
