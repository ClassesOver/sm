import assert from 'node:assert/strict'
import {createHash} from 'node:crypto'
import {readFile,writeFile,mkdir,access} from 'node:fs/promises'
import {createServer} from 'node:http'
import {spawnSync} from 'node:child_process'
import {dirname,resolve,extname} from 'node:path'
import {fileURLToPath} from 'node:url'
import {chromium} from 'playwright'

const name=process.argv[2]
assert.ok(['toc','comment'].includes(name))
const fixtureRoot=dirname(fileURLToPath(import.meta.url)),repo=resolve(fixtureRoot,'../../../..')
const output=resolve(process.env.DOCX_TEST_OUTPUT??'/tmp/native-word-toc-thread-smoke',name),staticRoot=process.env.DOCX_TEST_DIST??resolve(repo,'smart_reporting/report_editor/static')
const runtime=process.env.DOCX_TEST_ENGINE??resolve(repo,'smart_reporting/reporting/doc_engine')
const port=Number(process.env.DOCX_TEST_PORT??(name==='toc'?4321:4322)),base='http://127.0.0.1:'+port
const prefix='/reports/v1/editor/assets/', docId='fixture-native-'+name, pathBase='/reports/v1/native/'+docId+'/'
const mediaType='application/vnd.openxmlformats-officedocument.wordprocessingml.document'
const sha=b=>createHash('sha256').update(b).digest('hex')
const manifestSha256=sha(await readFile(resolve(staticRoot,'.vite/manifest.json')))
assert.equal(manifestSha256,process.env.DOCX_EXPECTED_MANIFEST_SHA256)
const bridgeSha256=sha(await readFile(resolve(runtime,'dist/edit-docx.mjs')))
await mkdir(output,{recursive:true})
const file=(n)=>resolve(output,'revision-'+n+'.docx')
const engine=(payload)=>{
 const p=spawnSync(resolve(repo,'.venv/bin/python'),[resolve(fixtureRoot,'native-word-toc-thread-fixture.py')],{cwd:repo,env:{...process.env,PYTHONPATH:repo,AGENT_REPORTING_DOC_ENGINE_DIR:runtime},input:JSON.stringify(payload),encoding:'utf8',maxBuffer:20*1024*1024,timeout:120000})
 assert.equal(p.status,0,p.stderr||String(p.error??p.signal));return JSON.parse(p.stdout)
}
const exists=async p=>access(p).then(()=>true,()=>false)
const revisions={},requests=[],actions=[],chunks=new Map(),identities=[],errors=[]
revisions[1]=await exists(file(1))?engine({mode:'inspect',source:file(1)}):engine({mode:'create',case:name,output:file(1)})
for(let n=2;await exists(file(n));n++){
 revisions[n]=engine({mode:'inspect',source:file(n)})
 const prior=resolve(output,'save-'+(n-1)+'-'+n+'.json')
 if(await exists(prior))requests.push({from:n-1,to:n,operations:JSON.parse(await readFile(prior,'utf8')).operations,resumed:true})
}
const toBytes=(entry)=>Buffer.from(entry.bytes,'base64')
const record=(n)=>({revision:n,sourceSha256:revisions[n].model.sourceSha256,facts:revisions[n].facts})
const server=createServer(async (req,res)=>{
 try{
  const p=new URL(req.url,base).pathname
  if(p==='/favicon.ico'){res.writeHead(200,{'Content-Type':'image/svg+xml'});res.end('<svg xmlns="http://www.w3.org/2000/svg"/>');return}
  assert.ok(p.startsWith(prefix));const f=resolve(staticRoot,p.slice(prefix.length));assert.ok(f.startsWith(staticRoot+'/'))
  const mime={'.js':'application/javascript','.css':'text/css','.woff2':'font/woff2','.html':'text/html','.svg':'image/svg+xml','.png':'image/png'}
  res.writeHead(200,{'Content-Type':mime[extname(f)]??'application/octet-stream'});res.end(await readFile(f))
 }catch{if(!res.headersSent)res.writeHead(404);res.end('not found')}
})
await new Promise((ok,no)=>{server.once('error',no);server.listen(port,'127.0.0.1',ok)})
let browser,page,routeError
try{
 browser=await chromium.launch({headless:true})
 page=await browser.newPage({viewport:{width:1600,height:1100}})
 page.on('pageerror',e=>errors.push(e.message));page.on('console',m=>{if(m.type()==='error')errors.push(m.text())})
 page.on('response',r=>{const p=new URL(r.url()).pathname;if(r.status()>=400)errors.push(r.status()+' '+p);if(r.ok()&&p.startsWith(prefix)&&p.endsWith('.js'))identities.push(r.body().then(async b=>{const disk=await readFile(resolve(staticRoot,p.slice(prefix.length)));assert.equal(sha(b),sha(disk),p);chunks.set(p,sha(b))}))})
 await page.route(new RegExp(pathBase+'[0-9]+$'),async r=>r.fulfill({body:await readFile(resolve(staticRoot,'native.html')),contentType:'text/html'}))
 await page.route('**'+pathBase+'*/api/**',async route=>{
  try {
   const req=route.request(),p=new URL(req.url()).pathname,n=Number(p.split('/')[5]),entry=revisions[n],post=req.method()==='POST'?req.postDataJSON():null
   if(p.endsWith('/context'))return await route.fulfill({json:{context:{documentId:docId,format:'docx',revision:n,parentRevision:n>1?n-1:null,scope:{database:'fixture',companyId:'fixture',userId:'fixture',threadId:'fixture'},sourceFile:{path:'revision-'+n+'.docx',size:toBytes(entry).length,sha256:entry.model.sourceSha256,mediaType},origin:'upload'},csrfToken:'fixture-only-csrf',capabilities:{docx_editor:true},editingEnabled:true}})
   if(p.endsWith('/file'))return await route.fulfill({body:toBytes(entry),contentType:mediaType})
   assert.equal(post?.expectedSha256,entry.model.sourceSha256)
   if(p.endsWith('/preview')){assert.deepEqual(post.operations,[]);return await route.fulfill({json:{sourceSha256:entry.model.sourceSha256,draftSha256:entry.model.sourceSha256,model:entry.model}})}
   assert.ok(p.endsWith('/save'))
   assert.equal(post.operations.length,1)
   assert.equal(revisions[n+1],undefined)
   const next=engine({mode:'patch',source:file(n),output:file(n+1),operations:post.operations})
   requests.push({from:n,to:n+1,operations:post.operations})
   await writeFile(resolve(output,'save-'+n+'-'+(n+1)+'.json'),JSON.stringify(post,null,2))
   revisions[n+1]=next
   return await route.fulfill({json:{documentId:docId,revision:n+1,parentRevision:n,revisionRegistered:true,artifacts:{word:{downloadUrl:'/download-'+(n+1)+'.docx',size:toBytes(next).length,sha256:next.model.sourceSha256}},editor:{openUrl:pathBase+(n+1)},validation:{ok:true,issues:[]}}})
  }catch(e){routeError=e;await route.fulfill({status:500,json:{detail:String(e)}})}
 })
 await page.route(/\/download-\d+\.docx$/, r=>r.fulfill({body:toBytes(revisions[Number(r.request().url().match(/-(\d+)\.docx$/)[1])]),contentType:mediaType}))
 const open=async(n)=>{await page.goto(base+pathBase+n);await page.locator('.docx-source-home').waitFor({timeout:60000})}
 const save=async(n,kind)=>{
  await page.locator('[data-action=save]').click()
  try{await page.waitForFunction(n=>document.querySelector('.save-state-label')?.textContent?.includes('已保存修订 '+n)||document.querySelector('.save-state-label')?.textContent?.includes('保存失败'),n,{timeout:15000})}catch(e){throw routeError??e}
  if(routeError)throw routeError
  const link=page.getByRole('link',{name:'下载 Word',exact:true}); const href=await link.getAttribute('href')
  assert.equal(new URL(href,base).pathname,'/download-'+n+'.docx')
  const raw=Buffer.from(await page.evaluate(async url=>Array.from(new Uint8Array(await(await fetch(url)).arrayBuffer())),href))
  assert.equal(sha(raw),revisions[n].model.sourceSha256)
  assert.equal(requests.at(-1).operations[0].kind,kind)
  await open(n)
  return revisions[n].facts
 }
 const screenshot=async(s)=>page.screenshot({path:resolve(output,s+'.png'),fullPage:true})
 const download=async n=>{
  const bytes=Buffer.from(await page.evaluate(async url=>Array.from(new Uint8Array(await(await fetch(url)).arrayBuffer())),base+'/download-'+n+'.docx'))
  assert.equal(sha(bytes),revisions[n].model.sourceSha256)
 }
 const currentRevision=Math.max(...Object.keys(revisions).map(Number))
 await open(currentRevision)
 if(name==='toc'){
  const refs=()=>page.locator('[data-tab-id=references]').click()
  const insert=page.locator('[data-action=toc-insert]'),update=page.locator('[data-action=toc-update]')
  const lines=page.locator('.tiptap .doc-protected-field-toc')
  const checkLines=async()=>{assert.equal(await lines.count(),2);assert.match(await lines.nth(0).textContent(),/业务概览 & 总览/);assert.match(await lines.nth(1).textContent(),/区域说明/)}
  const checkDoc=(facts)=>{assert.equal(facts.tocFields.length,1);assert.equal(facts.dirtyFields.length,1);assert.equal(facts.text.filter(x=>x==='正文不要被改写').length,1)}
  if(currentRevision<2){
   await page.getByText('目录前言',{exact:true}).click()
   await page.keyboard.press('End')
   await refs()
   assert.equal(await update.isDisabled(),true)
   await insert.click({timeout:5000})
   await checkLines()
   await screenshot('insert-draft')
   const a=await save(2,'insertToc')
   assert.deepEqual(a.changedParts,['word/document.xml'])
  }else await download(currentRevision)
  checkDoc(revisions[2].facts)
  await checkLines()
  if(currentRevision<3){
   await refs()
   await update.click({timeout:5000})
   await checkLines()
   const b=await save(3,'updateToc')
   assert.ok(b.changedParts.every(n=>n==='word/document.xml'))
  }
  checkDoc(revisions[3].facts)
  await checkLines()
  await screenshot('updated-reopened')
  actions.push('insertToc','updateToc')
 } else {
  const openComments=async()=>{await page.locator('[data-tab-id=review]').click();await page.locator('[data-action=comment-text-list]').click()}
  const toggle=page.locator('[data-comment-resolve]'),remove=page.locator('[data-comment-delete]'),menu=page.locator('[data-comment-target]')
  const setState=async(done)=>{await openComments();assert.equal(await toggle.textContent(),done?'解决线程':'重新打开线程');await toggle.click();assert.equal(await toggle.textContent(),done?'重新打开线程':'解决线程')}
  assert.equal(revisions[1].model.commentThreads.targets.length,2)
  if(currentRevision<2){
   await setState(true)
   await screenshot('resolved-draft')
   const a=await save(2,'resolveComment')
   assert.equal(requests.at(-1).operations[0].done,true)
   assert.deepEqual(a.changedParts,['word/commentsExtended.xml'])
  }else await download(currentRevision)
  assert.equal(revisions[2].facts.done[0],'1')
  if(currentRevision<3){
   await setState(false)
   const b=await save(3,'resolveComment')
   assert.equal(requests.at(-1).operations[0].done,false)
   assert.deepEqual(b.changedParts,['word/commentsExtended.xml'])
  }
  assert.equal(revisions[3].facts.done[0],'0')
  if(currentRevision<4){
   await openComments();assert.equal(await menu.locator('option').count(),2)
   page.once('dialog',d=>d.dismiss())
   await remove.click();assert.equal(await menu.locator('option').count(),2)
   page.once('dialog',d=>d.accept())
   await remove.click();assert.equal(await menu.locator('option').count(),0)
   await save(4,'deleteComment')
  }
  const c=revisions[4].facts
  assert.deepEqual(c.text,revisions[1].facts.text)
  assert.deepEqual(c.commentAnchors,{commentRangeStart:[],commentRangeEnd:[],commentReference:[]})
  assert.equal(revisions[4].model.commentThreads.targets.length,0)
  await screenshot('deleted-reopened')
  actions.push('resolveComment','reopenComment','deleteComment')
 }
 await page.waitForLoadState('networkidle');await Promise.all(identities)
 assert.deepEqual(errors,[])
 assert.ok([...chunks.keys()].some(p=>p.includes('lazy-docx-main-')))
 assert.equal(sha(await readFile(resolve(staticRoot,'.vite/manifest.json'))),manifestSha256,'manifest changed during browser run')
 assert.equal(sha(await readFile(resolve(runtime,'dist/edit-docx.mjs'))),bridgeSha256,'bridge changed during browser run')
 const evidence={ok:true,name,manifestSha256,bridgeSha256,browser:browser.version(),actions,requests,revisions:Object.keys(revisions).map(record),chunks:Object.fromEntries(chunks),errors,routeIsFixture:true,realPythonSave:true}
 await writeFile(resolve(output,'evidence.json'),JSON.stringify(evidence,null,2))
 console.log(JSON.stringify({name,actions,manifestSha256,bridgeSha256,errors,evidence:resolve(output,'evidence.json')}))
}catch(e){
 await page?.screenshot({path:resolve(output,'failure.png'),fullPage:true}).catch(()=>{})
 console.error('routeError:',routeError,'errors:',errors,'requests:',requests,await page?.locator('.save-state-label').textContent().catch(()=>null))
 throw e
}finally{await browser?.close();await new Promise(r=>server.close(r))}
