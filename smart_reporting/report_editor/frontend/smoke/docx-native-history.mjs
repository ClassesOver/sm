// 原生复杂 DOCX 未保存页眉/链接/页码的真实 UI 专项；统一正文历史专项；禁止保存与导出。
import assert from 'node:assert/strict'
import {readFile,writeFile,mkdir} from 'node:fs/promises'
import {resolve,extname} from 'node:path'
import {createHash} from 'node:crypto'
import {createServer} from 'node:http'
import {chromium} from 'playwright'
const artifact=process.env.DOCX_COMPLEX_ARTIFACT??'/tmp/sr-word-complex-20261111',output=process.env.DOCX_COMPLEX_EVIDENCE??artifact+'/native-history'
const staticRoot=resolve(process.env.DOCX_TEST_DIST??new URL('../../static',import.meta.url).pathname),port=Number(process.env.DOCX_TEST_PORT??4390),base='http://127.0.0.1:'+port,prefix='/reports/v1/editor/assets/'
const sha=b=>createHash('sha256').update(b).digest('hex'),bytes=await readFile(resolve(artifact,'downloaded-native.docx')),model=JSON.parse(await readFile(resolve(artifact,'native-model.json'),'utf8'))
assert.equal(sha(bytes),'7f4e32ee954f8eaaa98e97e904932369199971d323edf17b8cbbad578cde0391');assert.equal(model.sourceSha256,sha(bytes))
const manifestSha256=sha(await readFile(resolve(staticRoot,'.vite/manifest.json')))
await mkdir(output,{recursive:true})
const server=createServer(async(req,res)=>{try{const path=new URL(req.url,base).pathname;assert.ok(path.startsWith(prefix));const f=resolve(staticRoot,path.slice(prefix.length));assert.ok(f.startsWith(staticRoot+'/'));const body=await readFile(f);res.writeHead(200,{'Content-Type':({'.js':'application/javascript','.css':'text/css','.html':'text/html','.woff2':'font/woff2','.png':'image/png','.svg':'image/svg+xml'})[extname(f)]??'application/octet-stream'});res.end(body)}catch{res.writeHead(404);res.end('not found')}})
await new Promise((ok,no)=>{server.once('error',no);server.listen(port,'127.0.0.1',ok)})
let browser
try{
 browser=await chromium.launch({headless:true});const page=await browser.newPage({viewport:{width:1600,height:1500}}),errors=[],chunks={},identities=[],saveExportRequests=[]
 page.on('pageerror',e=>errors.push(e.message));page.on('console',m=>{if(m.type()==='error')errors.push(m.text())})
 page.on('response',r=>{const p=new URL(r.url()).pathname;if(r.status()>=400)errors.push(r.status()+' '+p);if(r.ok()&&p.startsWith(prefix)&&p.endsWith('.js'))identities.push(r.body().then(async b=>{assert.equal(sha(b),sha(await readFile(resolve(staticRoot,p.slice(prefix.length)))));chunks[p]=sha(b)}))})
 await page.route('**/favicon.ico',r=>r.fulfill({body:'',status:200}))
 await page.route('**/reports/v1/native/fixture-pagination/1',async r=>r.fulfill({body:await readFile(resolve(staticRoot,'native.html')),contentType:'text/html'}))
 await page.route('**/reports/v1/native/fixture-pagination/1/api/**',async r=>{const p=new URL(r.request().url()).pathname;if(p.endsWith('/context'))return r.fulfill({json:{context:{documentId:'fixture-pagination',format:'docx',revision:1,parentRevision:null,scope:{database:'f',companyId:'f',userId:'f',threadId:'f'},sourceFile:{path:'downloaded-native.docx',size:bytes.length,sha256:sha(bytes),mediaType:'application/vnd.openxmlformats-officedocument.wordprocessingml.document'},origin:'report'},csrfToken:'fixture',capabilities:{docx_editor:true},editingEnabled:true}});if(p.endsWith('/file'))return r.fulfill({body:bytes});if(!p.endsWith('/preview')){saveExportRequests.push(p);return r.fulfill({status:500,json:{error:'probe forbids save/export'}})};return r.fulfill({json:{sourceSha256:sha(bytes),draftSha256:sha(bytes),model}})})
 await page.goto(base+'/reports/v1/native/fixture-pagination/1');await page.locator('.docx-source-home').waitFor({timeout:20000}).catch(async e=>{await page.screenshot({path:resolve(output,'load-failure.png')});console.error(JSON.stringify({errors,body:await page.locator('body').innerText()}));throw e})
 const draft = () => page.evaluate(() => Object.fromEntries(Object.entries(localStorage).filter(([key]) => key.startsWith('native-editor-draft:'))))
 const body = page.locator('.editor-scroll .ProseMirror').first()
 const choose = async n => {
  await page.locator('[data-tab-id=layout]').click()
  await body.locator('p').filter({hasText: 'BODY'+n+'01'}).first().click()
  await page.waitForFunction(n => document.querySelector('[data-source-action=layout-section-label]')?.textContent?.startsWith('第 '+n+' 节'), n)
 }
 const preview = async () => {
  await page.locator('[data-tab-id=view]').click();await page.locator('[data-action=pagination-preview]').click()
  await page.waitForFunction(()=>window.__previewDebug?.slices?.length>0);await page.evaluate(()=>document.fonts.ready)
  const before=await draft()
  const result=await page.locator('.pv-page').evaluateAll(pages=>pages.map((p,i)=>({section:window.__previewDebug.slices[i].section,pageNo:window.__previewDebug.slices[i].pageNo,header:p.querySelector('.page-hf-header')?.textContent??'',footer:p.querySelector('.page-hf-footer')?.textContent??''})))
  await page.keyboard.press('Escape');await page.locator('.pv-overlay').waitFor({state:'hidden'})
  assert.deepEqual(await draft(),before,'预览关闭不得改写草稿');return result
 }
 const editHeader=async text=>{
  await page.locator('[data-tab-id=headerFooter]').click()
  const hf=page.locator('.docx-hf-editor-host [contenteditable=true]')
  await hf.click();await page.keyboard.press('Control+a');await page.keyboard.type(text)
 }
 const undo=async()=>{await body.locator('p').first().click();await page.keyboard.press('Control+z')}
 const reset=async()=>{await page.evaluate(()=>localStorage.clear());await page.reload();await page.locator('.docx-source-home').waitFor({timeout:20000});if(typeof baseline!=='undefined')assert.deepEqual(await preview(),baseline,'清草稿重开原件不得残留旧预览')}
 const baseline=await preview()
 await choose(1);await editHeader('LIVE_HEADER_FIRST')
 const textPreview=await preview();assert.ok(textPreview.every(p=>p.header.includes('LIVE_HEADER_FIRST')))
 await undo();const headerAfterCtrlZ=await preview();const headerUiUndoRestored=JSON.stringify(headerAfterCtrlZ)===JSON.stringify(baseline);assert.equal(headerUiUndoRestored,true,'正文 Ctrl+Z 必须恢复已提交页眉');
 await body.locator('p').first().click();await page.keyboard.press('Control+Shift+z');assert.deepEqual(await preview(),textPreview,'正文 Redo 必须恢复页眉');
 await reset()
 await choose(2);await page.locator('[data-tab-id=headerFooter]').click()
 const link=page.locator('[data-source-action=hf-link-previous]');assert.equal(await link.isChecked(),true);await link.uncheck()
 await choose(1);await editHeader('LIVE_HEADER_OWNER')
 const linkPreview=await preview();assert.ok(linkPreview.filter(p=>p.section===0).every(p=>p.header.includes('LIVE_HEADER_OWNER')))
 assert.ok(linkPreview.filter(p=>p.section>0).every(p=>p.header.trim()===baseline.find(q=>q.section===p.section).header.trim()),'断链节保留原页眉快照')
 await reset()
 await choose(2);await page.locator('[data-source-action=page-number-format]').click()
 await page.getByLabel('页码编号格式',{exact:true}).selectOption('upperRoman');await page.getByLabel('起始页码',{exact:true}).fill('7')
 await page.getByRole('dialog',{name:'页码格式',exact:true}).getByRole('button',{name:'确定',exact:true}).click()
 const numberPreview=await preview(),second=numberPreview.filter(p=>p.section===1)
 assert.equal(second[0].pageNo,7);assert.ok(second[0].footer.includes('VII'));assert.ok(second[1].footer.includes('VIII'))
 await undo();const numberAfterCtrlZ=await preview();const numberUiUndoRestored=JSON.stringify(numberAfterCtrlZ)===JSON.stringify(baseline)
 await choose(2);await page.locator('[data-source-action=page-number-format]').click();await page.getByLabel('页码编号格式',{exact:true}).selectOption('decimal');await page.getByLabel('起始页码',{exact:true}).fill('1');await page.getByRole('dialog',{name:'页码格式',exact:true}).getByRole('button',{name:'确定',exact:true}).click()
 assert.deepEqual(await preview(),baseline,'真实页码UI恢复原值后不得残留旧预览')
 assert.equal(numberUiUndoRestored,true,'正文 Ctrl+Z 必须恢复页码格式与起始号')
 const historyBoundary={headerUiUndoRestored,numberUiUndoRestored,note:'正文原生 Ctrl+Z/Redo 与非正文意图统一历史'}
 await page.waitForLoadState('networkidle');await Promise.all(identities);assert.deepEqual(errors,[]);assert.equal(sha(await readFile(resolve(staticRoot,'.vite/manifest.json'))),manifestSha256)
 const evidence={sourceSha256:sha(bytes),manifestSha256,baseline,textPreview,linkPreview,numberPreview,historyBoundary,headerAfterCtrlZ,headerUiUndoRestored,numberAfterCtrlZ,numberUiUndoRestored,draft:await draft(),chunks,errors,saveExportRequests};assert.deepEqual(saveExportRequests,[])
 await writeFile(resolve(output,'evidence.json'),JSON.stringify(evidence,null,2));console.log(JSON.stringify({ok:true,output,pages:baseline.length,manifestSha256,headerUiUndoRestored,numberUiUndoRestored,errors,saveExportRequests}))
}finally{await browser?.close();await new Promise(ok=>server.close(ok))}
