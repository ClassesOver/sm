// 同源 HTTP 授权/文件/preview 为夹具；DOCX 创建、inspect、冻结资产和浏览器 UI 均真实执行，禁止保存。
import assert from 'node:assert/strict'
import {createServer} from 'node:http'
import {spawnSync} from 'node:child_process'
import {createHash} from 'node:crypto'
import {mkdir,readFile,writeFile} from 'node:fs/promises'
import {join,resolve,extname} from 'node:path'
import {fileURLToPath} from 'node:url'
import {chromium} from 'playwright'

const repo=fileURLToPath(new URL('../../../../',import.meta.url)),root='/dev/shm/office-ui-combinations-20261113/density'
const staticRoot=resolve(process.env.DOCX_DENSITY_STATIC),expectedManifest=process.env.DOCX_DENSITY_MANIFEST,baseline=process.env.DOCX_DENSITY_BASELINE==='1'
const out=resolve(process.env.DOCX_DENSITY_OUT??join(root,baseline?'browser-v2':'browser-v3')),port=Number(process.env.DOCX_DENSITY_PORT??4628),origin=`http://127.0.0.1:${port}`,prefix='/reports/v1/editor/assets/'
const hash=b=>createHash('sha256').update(b).digest('hex'),media='application/vnd.openxmlformats-officedocument.wordprocessingml.document'
assert(expectedManifest,'DOCX_DENSITY_MANIFEST required')
await mkdir(out,{recursive:true});await mkdir(join(root,'fixtures'),{recursive:true})
const manifestSha256=hash(await readFile(join(staticRoot,'.vite/manifest.json')));assert.equal(manifestSha256,expectedManifest)
const fixtureCode=String.raw`import json,sys,hashlib
from pathlib import Path
from zipfile import ZipFile
from lxml import etree
from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from smart_reporting.reporting.delivery.docx_native import inspect_docx
p=json.load(sys.stdin);path=Path(p['path'])
if not path.exists():
 d=Document();para=d.add_paragraph('Review density plain text. ')
 for i,author in enumerate(['Alice','Bob','Carol'][:p['count']]):
  rev=OxmlElement('w:ins');rev.set(qn('w:id'),str(i+1));rev.set(qn('w:author'),author);rev.set(qn('w:date'),'2026-11-13T00:00:00Z')
  run=OxmlElement('w:r');text=OxmlElement('w:t');text.text=author+' insertion ';run.append(text);rev.append(run);para._p.append(rev)
 para.add_run('Tail unchanged.');d.add_paragraph('Second plain paragraph.');d.save(path)
raw=path.read_bytes()
with ZipFile(path) as z:
 doc=etree.fromstring(z.read('word/document.xml'));authors=doc.xpath('//w:ins/@w:author',namespaces={'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main'})
assert len(authors)==p['count']
print(json.dumps({'sha256':hashlib.sha256(raw).hexdigest(),'authors':authors,'model':inspect_docx(raw)}))
`
const fixtures=new Map()
for(const count of [0,1,3]){
 const path=join(root,'fixtures',`authors-${count}.docx`),r=spawnSync(join(repo,'.venv/bin/python'),['-c',fixtureCode],{cwd:repo,input:JSON.stringify({count,path}),encoding:'utf8',env:{...process.env,PYTHONPATH:repo,TMPDIR:'/tmp'},maxBuffer:20*1024*1024})
 assert.equal(r.status,0,r.stderr);const info=JSON.parse(r.stdout),bytes=await readFile(path);assert.equal(info.sha256,hash(bytes));assert.equal(info.model.sourceSha256,hash(bytes));fixtures.set(count,{...info,bytes})
 await writeFile(join(root,'fixtures',`authors-${count}-inspect.json`),JSON.stringify(info,null,2))
}
let browser,page,stage='setup';const http=[],resources=[],assetChecks=[],errors=[],warnings=[],cases=[]
const server=createServer(async(req,res)=>{
 const record={url:req.url,method:req.method};http.push(record)
 const json=(value,status=200)=>{res.writeHead(status,{'Content-Type':'application/json'});res.end(JSON.stringify(value))}
 try{
  const path=new URL(req.url,origin).pathname,api=/^\/reports\/v1\/native\/density-(0|1|3)\/1\/api\/(context|file|preview)$/.exec(path)
  assert(req.method==='GET'||(req.method==='POST'&&api?.[2]==='preview'),'no-save smoke only permits reads and preview')
  if(api){const count=Number(api[1]),f=fixtures.get(count),id=`density-${count}`
   if(api[2]==='context')return json({context:{documentId:id,format:'docx',revision:1,scope:{database:'fixture',companyId:'fixture',userId:'density-user',threadId:id},sourceFile:{path:`authors-${count}.docx`,size:f.bytes.length,sha256:f.sha256,mediaType:media},origin:'upload'},csrfToken:'density-csrf',capabilities:{docx_editor:true},editingEnabled:true})
   if(api[2]==='preview'){let raw='';for await(const chunk of req)raw+=chunk;record.body=raw?JSON.parse(raw):null;assert(!record.body?.operations?.length,'preview must not submit document operations');return json({sourceSha256:f.sha256,draftSha256:f.sha256,model:f.model})}
   res.writeHead(200,{'Content-Type':media});return res.end(f.bytes)
  }
  if(path==='/favicon.ico'){res.writeHead(204);return res.end()}
  const relative=/^\/reports\/v1\/native\/density-(0|1|3)\/1$/.test(path)?'native.html':path.startsWith(prefix)?decodeURIComponent(path.slice(prefix.length)):null
  assert(relative&&!relative.includes('..'),'unexpected HTTP fixture path');const disk=join(staticRoot,relative),bytes=await readFile(disk);record.sha256=hash(bytes)
  res.writeHead(200,{'Content-Type':{'.html':'text/html','.js':'application/javascript','.css':'text/css','.wasm':'application/wasm','.woff2':'font/woff2','.ttf':'font/ttf'}[extname(disk)]??'application/octet-stream'});res.end(bytes)
 }catch(error){record.error=String(error);json({detail:String(error)},500)}
})
await new Promise(done=>server.listen(port,'127.0.0.1',done))
try{
 const downloadsPath='/home/junge/codex-evidence/smart_reporting/office-ui-combinations-20261113/density-downloads';await mkdir(downloadsPath,{recursive:true})
 browser=await chromium.launch({headless:true,executablePath:process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE??'/snap/bin/chromium',downloadsPath})
 for(const viewport of baseline?[{width:1600,height:1000}]:[{width:1600,height:1000},{width:640,height:600}])for(const count of baseline?[0,3]:[0,1,3]){
  stage=`${viewport.width}-${count}`;console.log(stage)
  const context=await browser.newContext({viewport,acceptDownloads:false});page=await context.newPage()
  page.on('pageerror',error=>errors.push(String(error)));page.on('console',message=>{if(message.type()==='error')errors.push(message.text());if(message.type()==='warning')warnings.push({stage,message:message.text()})})
  page.on('response',response=>{const path=new URL(response.url()).pathname;if(path.startsWith(prefix)&&/\.(js|css)$/.test(path))assetChecks.push((async()=>{const bytes=await response.body(),expected=await readFile(join(staticRoot,path.slice(prefix.length)));assert.equal(response.status(),200);assert.equal(hash(bytes),hash(expected));resources.push({case:stage,path,sha256:hash(bytes)})})())})
  await page.goto(`${origin}/reports/v1/native/density-${count}/1`);await page.locator('.docx-source-home').waitFor({timeout:60000})
  await page.locator('[data-tab-id="review"]').click();await page.locator('[data-action="revision-filter-authors"]').waitFor();await page.evaluate(()=>document.fonts.ready)
  const state=()=>page.evaluate(()=>({doc:document.querySelector('[aria-label="Word 文档编辑区"]').editor.getJSON(),drafts:Object.fromEntries(Object.entries(localStorage).filter(([key])=>key.startsWith('native-editor-draft:')))}))
  const before=await state(),people=page.locator('[data-action="revision-filter-authors"]'),mode=page.locator('[data-action="revision-display"]'),insdel=page.locator('[data-action="revision-filter-insdel"]'),format=page.locator('[data-action="revision-filter-format"]')
  const authorsState=await people.evaluate(el=>({multiple:el.multiple,size:el.size,disabled:el.disabled,authors:Array.from(el.options,o=>o.value),selected:Array.from(el.selectedOptions,o=>o.value)}))
  assert.equal(authorsState.multiple,true);assert.equal(authorsState.disabled,count===0);assert.deepEqual(authorsState.authors,fixtures.get(count).authors);assert.deepEqual(authorsState.selected,[])
  const geometry=await page.locator('.docx-ribbon').evaluate(root=>{
   const rect=el=>{if(!el)return null;const r=el.getBoundingClientRect();return{x:r.x,y:r.y,width:r.width,height:r.height,right:r.right,bottom:r.bottom}}
   const body=root.querySelector('.ribbon-body'),content=body.querySelector('.ribbon-content'),groups=Array.from(content.querySelectorAll(':scope > .ribbon-group'))
   const nodes=Array.from(content.querySelectorAll('button,input,select,label')).map(el=>({tag:el.tagName,action:el.dataset.action??null,name:el.getAttribute('aria-label')??el.textContent,disabled:el.disabled??false,title:el.title,box:rect(el)}))
   const display=content.querySelector('.docx-review-display-items')
   return{ribbon:rect(root),body:rect(body),content:rect(content),revisions:rect(content.querySelector('.docx-review-revisions-items')),display:rect(display),displayGridRows:display?getComputedStyle(display).gridTemplateRows:null,scrollWidth:body.scrollWidth,clientWidth:body.clientWidth,groups:groups.map(el=>({name:el.getAttribute('aria-label'),box:rect(el)})),nodes}
  })
  const reachability=await page.locator('.docx-ribbon .ribbon-body').evaluate(body=>{
   const nodes=Array.from(body.querySelectorAll('.ribbon-content > .ribbon-group button,.ribbon-content > .ribbon-group input,.ribbon-content > .ribbon-group select'))
   return nodes.map(el=>{const b=body.getBoundingClientRect(),r=el.getBoundingClientRect();body.scrollLeft+=r.left-b.left-(b.width-r.width)/2;const a=el.getBoundingClientRect();return{action:el.dataset.action??null,name:el.getAttribute('aria-label')??el.textContent,scrollLeft:body.scrollLeft,box:{x:a.x,y:a.y,width:a.width,height:a.height},reachable:a.left>=b.left-1&&a.right<=b.right+1&&a.top>=b.top-1&&a.bottom<=b.bottom+1}})
  })
  if(!baseline){assert(geometry.body.height<200,'ribbon no longer expands to roughly330px');assert(geometry.body.x>=-1&&geometry.body.right<=viewport.width+1&&geometry.body.bottom<=viewport.height,'ribbon scroll viewport must fit the actual browser viewport');assert(geometry.revisions&&geometry.display);assert.equal(geometry.displayGridRows.split(' ').length,3,'Show Markup must not create an implicit fourth grid row');assert(reachability.every(x=>x.reachable),'all commands must remain reachable through horizontal scrolling')}
  await page.locator('.docx-ribbon .ribbon-body').evaluate(el=>el.scrollLeft=0);await page.screenshot({path:join(out,`${stage}-start.png`)})
  await page.locator('.docx-ribbon .ribbon-body').evaluate(el=>el.scrollLeft=el.scrollWidth);await page.screenshot({path:join(out,`${stage}-end.png`)})
  const six=await page.locator('[aria-label="受支持正文修订"] button').evaluateAll(nodes=>nodes.map(el=>({action:el.dataset.action,name:el.getAttribute('aria-label')||el.textContent,disabled:el.disabled,reason:el.getAttribute('aria-description')||el.title})))
  assert.equal(six.length,6);for(const command of six){assert(command.name?.trim());if(command.disabled)assert(command.reason?.trim())}
  await mode.selectOption('original');assert(await page.locator('[data-native-docx-review-state]').evaluate(el=>el.classList.contains('rev-display-original')))
  await mode.selectOption('all');await insdel.uncheck();assert.equal(await page.locator('[data-native-docx-review-state]').getAttribute('data-rev-ins-del'),'false');await insdel.check()
  await format.uncheck();assert(await page.locator('[aria-label="Word 文档编辑区"]').evaluate(el=>el.classList.contains('rev-hide-format')));await format.check()
  if(count){await people.selectOption(fixtures.get(count).authors);assert.deepEqual(await people.evaluate(el=>Array.from(el.selectedOptions,o=>o.value)),fixtures.get(count).authors);assert.deepEqual(JSON.parse(await page.locator('[data-native-docx-review-state]').getAttribute('data-rev-hidden-authors')),fixtures.get(count).authors);await people.selectOption([])}
  assert.deepEqual(await state(),before,'view-only interaction must preserve document and draft')
  const result={viewport,count,sourceSha256:fixtures.get(count).sha256,authorsState,geometry,reachability,six,documentAndDraftUnchanged:true};cases.push(result);await writeFile(join(out,`${stage}.json`),JSON.stringify(result,null,2));await context.close()
 }
 await Promise.all(assetChecks);assert(resources.length>0);assert.deepEqual(errors,[]);assert(http.every(r=>!r.error));assert(!http.some(r=>/save|export|download/.test(r.url)))
 await writeFile(join(out,'result.json'),JSON.stringify({ok:true,scope:'same-origin HTTP authorization/file/preview fixture; real DOCX inspect, frozen assets and browser UI; zero save/export/download',staticRoot,manifestSha256,baseline,cases,http,resources,errors,warnings,warningCount:warnings.length},null,2));console.log(JSON.stringify({ok:true,out,cases:cases.length}))
}catch(error){await page?.screenshot({path:join(out,'failure.png')}).catch(()=>{});await writeFile(join(out,'failure.json'),JSON.stringify({stage,error:String(error),stack:error.stack,cases,http,resources,errors,warnings,warningCount:warnings.length,staticRoot,manifestSha256},null,2));throw error}
finally{await browser?.close();await new Promise(done=>server.close(done))}
