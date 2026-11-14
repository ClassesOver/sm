// 构建验收：授权及修订登记为夹具，DOCX 解析、替换、下载和独立回读使用真实引擎。
import assert from 'node:assert/strict'
import {createHash} from 'node:crypto'
import {readFile,writeFile,mkdir} from 'node:fs/promises'
import {createServer} from 'node:http'
import {spawnSync} from 'node:child_process'
import {dirname,resolve,extname} from 'node:path'
import {fileURLToPath} from 'node:url'
import {chromium} from 'playwright'
import {inspectDocxFind} from './office-docx-find-layout.mjs'
const fixtureRoot=dirname(fileURLToPath(import.meta.url)),repo=resolve(fixtureRoot,'../../../..')
const output=resolve(process.env.DOCX_TEST_OUTPUT??'/tmp/docx-find-smoke'),staticRoot=resolve(repo,'smart_reporting/report_editor/static'),runtime=resolve(repo,'smart_reporting/reporting/doc_engine')
const port=Number(process.env.DOCX_TEST_PORT??4349),base='http://127.0.0.1:'+port,prefix='/reports/v1/editor/assets/',mediaType='application/vnd.openxmlformats-officedocument.wordprocessingml.document'
const sha=bytes=>createHash('sha256').update(bytes).digest('hex'),manifestPath=resolve(staticRoot,'.vite/manifest.json'),bridgePath=resolve(runtime,'dist/edit-docx.mjs')
const manifestSha256=sha(await readFile(manifestPath)),bridgeSha256=sha(await readFile(bridgePath))
assert.equal(manifestSha256,process.env.DOCX_EXPECTED_MANIFEST_SHA256,'必须提供冻结 manifest 身份')
await mkdir(output,{recursive:true})
const fixture=payload=>{const r=spawnSync(resolve(repo,'.venv/bin/python'),[resolve(fixtureRoot,'docx-find-fixture.py')],{cwd:repo,env:{...process.env,PYTHONPATH:repo,AGENT_REPORTING_DOC_ENGINE_DIR:runtime},input:JSON.stringify(payload),encoding:'utf8',maxBuffer:30*1024*1024,timeout:180000});assert.equal(r.status,0,r.stderr);return JSON.parse(r.stdout)}
const source=fixture({mode:'create'}),bytes=Buffer.from(source.bytes,'base64');await writeFile(resolve(output,'source.docx'),bytes)
const requests=[],identities=[],chunks=new Map(),errors=[],routeErrors=[],layouts=[],saves=[]
let saved,downloadIdentity
const server=createServer(async(req,res)=>{try{const path=new URL(req.url,base).pathname;if(path==='/favicon.ico'){res.writeHead(204);res.end();return}assert.ok(path.startsWith(prefix));const file=resolve(staticRoot,path.slice(prefix.length));assert.ok(file.startsWith(staticRoot+'/'));res.writeHead(200,{'Content-Type':{'.js':'application/javascript','.css':'text/css','.woff2':'font/woff2','.html':'text/html','.svg':'image/svg+xml','.png':'image/png'}[extname(file)]??'application/octet-stream'});res.end(await readFile(file))}catch{if(!res.headersSent)res.writeHead(404);res.end('not found')}})
await new Promise((ok,no)=>{server.once('error',no);server.listen(port,'127.0.0.1',ok)})
let browser,page
try{
 browser=await chromium.launch({headless:true})
 for(const editingEnabled of [true,false]){
  page=await browser.newPage({viewport:{width:1440,height:900},acceptDownloads:true})
  page.on('pageerror',e=>errors.push(e.message));page.on('console',m=>{if(m.type()==='error')errors.push(m.text())})
  page.on('response',response=>{const path=new URL(response.url()).pathname;if(response.status()>=400)errors.push(response.status()+' '+path);if(response.ok()&&path.startsWith(prefix)&&/\.(js|css)$/.test(path))identities.push(response.body().then(async body=>{const disk=await readFile(resolve(staticRoot,path.slice(prefix.length)));assert.equal(sha(body),sha(disk));chunks.set(path,{sha256:sha(body),size:body.length})}))})
  const docId='fixture-find-'+editingEnabled,pathBase='/reports/v1/native/'+docId
  await page.route(base+pathBase+'/*',async route=>route.fulfill({body:await readFile(resolve(staticRoot,'native.html')),contentType:'text/html'}))
  await page.route('**'+pathBase+'/*/api/**',async route=>{
   try{
    const req=route.request(),path=new URL(req.url()).pathname,revision=Number(path.split('/')[5]),current=revision===1?source:saved,currentBytes=Buffer.from(current.bytes,'base64');requests.push({editingEnabled,method:req.method(),path})
    if(path.endsWith('/context'))return route.fulfill({json:{context:{documentId:docId,format:'docx',revision,parentRevision:revision===1?null:1,scope:{database:'fixture',companyId:'fixture',userId:'fixture',threadId:'fixture'},sourceFile:{path:'revision-'+revision+'.docx',size:currentBytes.length,sha256:current.sha256,mediaType},origin:'upload'},csrfToken:'fixture-only',capabilities:{docx_editor:editingEnabled},editingEnabled}})
    if(path.endsWith('/file'))return route.fulfill({body:currentBytes,contentType:mediaType})
    if(path.endsWith('/preview')){const payload=req.postDataJSON();assert.equal(payload.expectedSha256,current.sha256);const preview=payload.operations.length?fixture({mode:'patch',bytes:current.bytes,operations:payload.operations}):current;return route.fulfill({json:{sourceSha256:current.sha256,draftSha256:preview.sha256,model:preview.model}})}
    if(path.endsWith('/save')){assert.ok(editingEnabled);assert.equal(req.headers()['x-csrf-token'],'fixture-only');const payload=req.postDataJSON();assert.equal(payload.expectedSha256,source.sha256);saved=fixture({mode:'patch',bytes:source.bytes,operations:payload.operations});saves.push(payload);await writeFile(resolve(output,'revision-2.docx'),Buffer.from(saved.bytes,'base64'));return route.fulfill({json:{documentId:docId,revision:2,parentRevision:1,revisionRegistered:true,artifacts:{word:{downloadUrl:'/fixture-find-download.docx',size:Buffer.from(saved.bytes,'base64').length,sha256:saved.sha256}},editor:{openUrl:pathBase+'/2'},validation:{ok:false,issues:[{code:'fixture_review',message:'验收夹具待复核，保留 Word 下载'}]}}})}
    throw Error('未预期 API '+path)
   }catch(e){routeErrors.push(e.message);return route.fulfill({status:500,json:{detail:e.message}})}
  })
  await page.route('**/fixture-find-download.docx',route=>route.fulfill({body:Buffer.from(saved.bytes,'base64'),contentType:mediaType,headers:{'Content-Disposition':'attachment; filename="revision-2.docx"'}}))
  await page.goto(base+pathBase+'/1');await page.locator('.docx-source-home').waitFor({timeout:60000})
  const editor=page.getByRole('textbox',{name:'Word 文档编辑区'}),panel=page.locator('.docx-find-replace')
  const snapshot=()=>editor.evaluate(node=>({doc:node.editor.getJSON(),undo:node.editor.can().undo(),redo:node.editor.can().redo()}))
  const draft=()=>page.evaluate(()=>Object.fromEntries(Object.entries(localStorage).filter(([key])=>key.startsWith('native-editor-draft:'))))
  const layout=await inspectDocxFind(page,{output,editingEnabled,draft,snapshot});layouts.push(layout)
  assert.deepEqual(layout.failures,[],'查找界面验收失败')
  if(editingEnabled){
   await panel.locator('[data-find-replacement]').fill('dog');await panel.locator('[data-find-action=replace-all]').click()
   await panel.locator('[data-find-status]').filter({hasText:'已替换 13 处'}).waitFor()
   await editor.evaluate(node=>node.editor.view.focus());await page.keyboard.press('Control+z');assert.equal(await panel.locator('.find-result').count(),13)
   await page.keyboard.press('Control+Shift+z');assert.equal(await panel.locator('.find-result').count(),0)
   const edited=await editor.evaluate(node=>node.editor.getJSON());await panel.locator('[data-find-action=close]').click();await page.reload();await page.locator('.docx-source-home').waitFor({timeout:60000});assert.deepEqual(await editor.evaluate(node=>node.editor.getJSON()),edited);await page.locator('[data-action=save]').click()
   await page.getByText('验收夹具待复核，保留 Word 下载',{exact:true}).waitFor({timeout:60000});assert.equal(saves.length,1);assert.equal(saves[0].operations.length,12)
   const pending=page.waitForEvent('download');await page.getByRole('link',{name:'下载 Word',exact:true}).click();const download=await pending;const downloaded=await readFile(await download.path());assert.equal(sha(downloaded),saved.sha256);await writeFile(resolve(output,'downloaded-revision-2.docx'),downloaded);downloadIdentity={sha256:sha(downloaded),size:downloaded.length}
   const expected=JSON.parse(JSON.stringify(source.independent).replaceAll('cat','dog'));assert.deepEqual(saved.independent.paragraphs,expected.paragraphs);assert.deepEqual(saved.independent.tables,expected.tables)
   for(const [part,identity]of Object.entries(source.independent.parts))if(!['word/document.xml','docProps/core.xml'].includes(part))assert.equal(saved.independent.parts[part],identity,part)
   await page.goto(base+pathBase+'/2');await page.locator('.docx-source-home').waitFor({timeout:60000});await page.locator('[data-action=find]').click();await panel.locator('[data-find-query]').fill('dog');assert.equal(await panel.locator('.find-result').count(),13);await page.screenshot({path:resolve(output,'reopened-revision-2.png')})
  }else assert.equal(saves.length,1)
  await page.close()
 }
 await Promise.all(identities);assert.deepEqual(errors,[]);assert.deepEqual(routeErrors,[]);assert.equal(sha(await readFile(manifestPath)),manifestSha256);assert.equal(sha(await readFile(bridgePath)),bridgeSha256)
 const evidence={ok:true,manifestSha256,bridgeSha256,browser:browser.version(),source:{sha256:source.sha256,size:bytes.length,independent:source.independent},saved:{sha256:saved.sha256,size:Buffer.from(saved.bytes,'base64').length,independent:saved.independent},layouts,saves,download:downloadIdentity,requests,chunks:Object.fromEntries(chunks),errors,routeErrors,routeIsFixture:true,productionAuthTested:false}
 await writeFile(resolve(output,'evidence.json'),JSON.stringify(evidence,null,2));console.log(JSON.stringify({ok:true,output,manifestSha256,cases:layouts.reduce((n,l)=>n+l.cases.length,0),assets:chunks.size,saves:saves.length}))
}catch(e){await page?.screenshot({path:resolve(output,'failure.png'),fullPage:true}).catch(()=>{});throw e}
finally{await browser?.close();await new Promise(ok=>server.close(ok))}
