import assert from 'node:assert/strict'
import {spawnSync} from 'node:child_process'
import {createHash} from 'node:crypto'
import {mkdir,readFile,writeFile} from 'node:fs/promises'
import {resolve} from 'node:path'
import {fileURLToPath} from 'node:url'
import {chromium} from 'playwright'
import {createServer,preview} from 'vite'

const frontend=fileURLToPath(new URL('../',import.meta.url)),repo=resolve(frontend,'../../..')
const directory=resolve(process.env.PDF_HEADING_OUTPUT??'/dev/shm/office-next-pdf-heading-20261113/red')
await mkdir(directory,{recursive:true})
const hash=bytes=>createHash('sha256').update(bytes).digest('hex')
const staticRoot=process.env.PDF_HEADING_STATIC_ROOT?resolve(process.env.PDF_HEADING_STATIC_ROOT):null
const sourceRoot=process.env.PDF_HEADING_SOURCE_ROOT?resolve(process.env.PDF_HEADING_SOURCE_ROOT):frontend
const sourceHashes={}
for(const name of ['src/pdf-main.ts','src/pdf-view-ribbon.ts','src/pdf-heading-outline.ts','src/vendor/genoffice-pdf/renderer/heading-outline.ts'])sourceHashes[name]=hash(await readFile(resolve(sourceRoot,name)))
let manifestSha256=null
if(staticRoot){
 assert.ok(process.env.PDF_HEADING_MANIFEST_SHA256&&process.env.PDF_HEADING_SOURCE_ROOT,'冻结模式显式指定manifest SHA和源码快照目录')
 manifestSha256=hash(await readFile(resolve(staticRoot,'.vite/manifest.json')))
 assert.equal(manifestSha256,process.env.PDF_HEADING_MANIFEST_SHA256)
}
const sourcePdfDirectory=process.env.PDF_HEADING_SOURCE_PDF_DIRECTORY?resolve(process.env.PDF_HEADING_SOURCE_PDF_DIRECTORY):null
if(staticRoot)assert.ok(sourcePdfDirectory,'冻结模式复用已生成的三份真实 PDF')
const sourceArgs=sourcePdfDirectory?['-c',`
import base64,json,sys
from pathlib import Path
from smart_reporting.reporting.delivery.pdf_native import inspect_pdf
sources={}
for kind in ['headings','plain','embedded']:
 data=(Path(sys.argv[1])/(kind+'.pdf')).read_bytes()
 sources[kind]={'bytes':base64.b64encode(data).decode(),'model':inspect_pdf(data)}
print(json.dumps(sources))
`,sourcePdfDirectory]:[resolve(frontend,'smoke/pdf-heading-outline-source.py')]
const source=spawnSync(resolve(repo,'.venv/bin/python'),sourceArgs,{cwd:repo,env:{...process.env,PYTHONPATH:repo},encoding:'utf8',maxBuffer:10*1024*1024})
assert.equal(source.status,0,source.stderr)
const sources=JSON.parse(source.stdout),requests=[],results=[],failures=[],errors=[],assets=new Map(),assetChecks=[],assetErrors=[]
for(const[kind,value]of Object.entries(sources)){value.bytes=Buffer.from(value.bytes,'base64');await writeFile(resolve(directory,`${kind}.pdf`),value.bytes)}
const port=Number(process.env.PDF_HEADING_PORT??4464)
const server=staticRoot
 ?await preview({root:frontend,configFile:resolve(frontend,'vite.config.ts'),build:{outDir:staticRoot},preview:{host:'127.0.0.1',port,strictPort:true}})
 :await createServer({root:frontend,configFile:resolve(frontend,'vite.config.ts'),cacheDir:resolve(directory,'vite-cache'),server:{host:'127.0.0.1',port,strictPort:true}})
if(!staticRoot)await server.listen()
const base=new URL(server.resolvedUrls.local[0]).origin
let browser
try{
 browser=await chromium.launch({headless:true})
 const kinds=process.env.PDF_HEADING_KINDS?.split(',')??['headings','plain','embedded']
 const viewports=process.env.PDF_HEADING_VIEWPORTS?.split(',').map(value=>value.split('x').map(Number))??[[1440,900],[390,844]]
 for(const[width,height]of viewports)for(const kind of kinds){
  const page=await browser.newPage({viewport:{width,height}}),key=`${kind}-${width}x${height}`,path=`/reports/v1/native/pdf-heading-${kind}/1`,source=sources[kind]
  page.on('pageerror',error=>errors.push({key,message:error.message}));page.on('console',entry=>{if(entry.type()==='error')errors.push({key,message:entry.text()})})
  if(staticRoot)page.on('response',response=>{
   const url=new URL(response.url()),prefix='/reports/v1/editor/assets/'
   if(!url.pathname.startsWith(prefix)||!/\.(?:m?js|css)$/.test(url.pathname))return
   assetChecks.push((async()=>{
    const path=decodeURIComponent(url.pathname.slice(prefix.length))
    assert.ok(!path.split('/').includes('..'));assert.equal(response.status(),200)
    const bytes=await response.body(),sha256=hash(bytes)
    assert.equal(sha256,hash(await readFile(resolve(staticRoot,path))),path)
    assets.set(path,{path,size:bytes.length,sha256})
   })().catch(error=>assetErrors.push(String(error))))
  })
  await page.addInitScript(()=>{if(location.origin!=='null')localStorage.clear()})
  await page.route(`**${path}/api/**`,async route=>{
   const operation=new URL(route.request().url()).pathname.split('/').at(-1);requests.push({key,operation,method:route.request().method()})
   if(operation==='context')return route.fulfill({json:{context:{documentId:`pdf-heading-${kind}`,revision:1,parentRevision:null,format:'pdf',origin:'upload',scope:{database:'fixture',companyId:'fixture',userId:'fixture',threadId:'fixture'},sourceFile:{path:`${kind}.pdf`,size:source.bytes.length,sha256:source.model.sourceSha256,mediaType:'application/pdf'}},csrfToken:'fixture',capabilities:{pdf_editor:true},editingEnabled:true}})
   if(operation==='file')return route.fulfill({body:source.bytes,contentType:'application/pdf'})
   if(operation==='preview'){assert.deepEqual(route.request().postDataJSON().operations,[]);return route.fulfill({json:{sourceSha256:source.model.sourceSha256,model:source.model,appliedOperationIndices:[],skippedOperations:[]}})}
   return route.fulfill({status:500,json:{detail:{code:'fixture_read_only',message:'标题目录验证不保存或发布'}}})
  })
  await page.route(`**${path}`,async route=>route.fulfill({response:await route.fetch({url:`${base}/reports/v1/editor/assets/native.html`})}))
  await page.goto(new URL(path,base).href)
  await page.waitForFunction(()=>document.querySelector('#report-editor')?.getAttribute('aria-busy')==='false'&&document.querySelector('.pdf-page-content canvas'),null,{timeout:60000})
  const operations=()=>page.evaluate(()=>Object.entries(localStorage).filter(([key])=>key.startsWith('native-editor-draft:')).map(([key,value])=>[key,JSON.parse(value).operations]))
  const before=await operations()
  await page.locator('[data-pdf-ribbon-tab="view"]').click()
  const entry=page.locator('[data-source-command-id="genoffice.pdf.view.navigation.outline"]'),disabled=await entry.isDisabled()
  if(!disabled)await entry.click()
  await page.waitForFunction(()=>['complete','empty','error'].includes(document.querySelector('[data-pdf-heading-status]')?.getAttribute('data-state')),null,{timeout:4000}).catch(()=>{})
  const panel=page.locator('.pdf-outline'),titles=await panel.locator('.pdf-outline-link').allTextContents(),notice=await panel.locator('[data-pdf-heading-status]').evaluateAll(nodes=>nodes[0]?.textContent??null)
  const expected=kind==='headings'?['User Guide','Chapter Alpha','Section Details','Chapter Beta']:kind==='embedded'?['Embedded First','Embedded Last']:[]
  const matched=JSON.stringify(titles)===JSON.stringify(expected)
  const jumps=[]
  if(matched&&titles.length)for(const title of expected){
   const link=panel.getByRole('button',{name:title,exact:true});await link.scrollIntoViewIfNeeded()
   const hit=await link.evaluate(node=>{const r=node.getBoundingClientRect();return node.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2))})
   await link.click();const target=kind==='embedded'?(title==='Embedded First'?0:2):title==='User Guide'?0:title==='Chapter Beta'?2:1
   await page.waitForFunction(id=>document.querySelector('.pdf-page.is-active')?.getAttribute('data-page-id')===id,`sha256:${source.model.sourceSha256}:page:${target}`)
   await page.waitForFunction(id=>{
    const viewport=document.querySelector('.pdf-document-pages'),card=[...document.querySelectorAll('.pdf-page')].find(node=>node.getAttribute('data-page-id')===id)
    return viewport&&card&&Math.abs(card.getBoundingClientRect().top-viewport.getBoundingClientRect().top)<=20
   },`sha256:${source.model.sourceSha256}:page:${target}`)
   await page.locator(`.pdf-page[data-page-id="sha256:${source.model.sourceSha256}:page:${target}"] .pdf-page-content canvas`).waitFor()
   jumps.push({title,hit,target,scrolledToPage:true});assert.ok(hit)
  }
  const editDisabled=await panel.locator('[data-source-command-id="genoffice.pdf.view.outline.edit"]').isDisabled()
  assert.deepEqual(await operations(),before)
  await page.screenshot({path:resolve(directory,`${key}.png`)})
  const readOnly=kind!=='headings'||editDisabled&&Boolean(notice?.includes('只读')&&notice?.includes('标题'))
  results.push({key,kind,disabled,titles,expected,matched,notice,editDisabled,readOnly,jumps,draftUnchanged:true})
  if(!matched||!readOnly||kind!=='plain'&&disabled)failures.push({key,matched,readOnly,disabled,titles,notice})
  await Promise.all(assetChecks);await page.goto('about:blank');await page.close()
 }
 assert.deepEqual(errors,[])
 assert.ok(requests.every(item=>['context','file','preview'].includes(item.operation)))
 await Promise.all(assetChecks);assert.deepEqual(assetErrors,[])
 if(staticRoot){
  assert.equal(hash(await readFile(resolve(staticRoot,'.vite/manifest.json'))),manifestSha256)
  const manifest=JSON.parse(await readFile(resolve(staticRoot,'.vite/manifest.json'),'utf8'))
  const pdf=Object.values(manifest).find(entry=>entry.name==='pdf-main'&&entry.isDynamicEntry)
  assert.ok(pdf&&assets.has(pdf.file),'实际PDF模块必须来自所指定冻结构建')
  assert.ok([...assets.keys()].some(path=>path.endsWith('.css')))
 }
 const build={staticRoot,manifestSha256,sourceRoot,sourceHashes}
 await writeFile(resolve(directory,'evidence.json'),JSON.stringify({scope:`Real ${staticRoot?'frozen':'development'} native host, product outline UI, actual source PDFs and PDF.js; identity/context/file/initial preview are explicit HTTP fixtures; no save/export/publication.`,build,sourceHashes,sourcePdfDirectory,sources:Object.fromEntries(Object.entries(sources).map(([key,value])=>[key,{sha256:hash(value.bytes),size:value.bytes.length,pages:value.model.pages.length}])),results,failures,requests,assets:[...assets.values()],assetResponseChecks:assetChecks.length,assetErrors,errors},null,2))
 console.log(JSON.stringify({cases:results.length,failures,requests,errors},null,2));assert.deepEqual(failures,[])
}catch(error){await writeFile(resolve(directory,'failure.json'),JSON.stringify({error:String(error),stack:error.stack,build:{staticRoot,manifestSha256,sourceRoot,sourceHashes},results,failures,requests,assets:[...assets.values()],assetErrors,errors},null,2));throw error}
finally{await browser?.close();if(staticRoot)await new Promise(resolve=>server.httpServer.close(resolve));else await server.close()}
