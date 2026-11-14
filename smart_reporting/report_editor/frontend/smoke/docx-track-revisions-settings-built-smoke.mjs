import assert from 'node:assert/strict'
import {createServer} from 'node:http'
import {spawn,spawnSync} from 'node:child_process'
import {createHash} from 'node:crypto'
import {mkdtemp,readFile,writeFile,mkdir} from 'node:fs/promises'
import {tmpdir} from 'node:os'
import {join,resolve,extname} from 'node:path'
import {fileURLToPath} from 'node:url'
import {setTimeout as delay} from 'node:timers/promises'
import {chromium} from 'playwright'

const frontend=fileURLToPath(new URL('../',import.meta.url)),repo=fileURLToPath(new URL('../../../../',import.meta.url))
const staticRoot=resolve(process.env.DOCX_TEST_DIST??'/tmp/docx-track-revisions-static-20261113')
const output=resolve(process.env.DOCX_TEST_OUTPUT??await mkdtemp(join(tmpdir(),'docx-track-setting-browser-')))
const assetPrefix='/reports/v1/editor/assets/'
const manifest=await readFile(join(staticRoot,'.vite/manifest.json')),manifestSha256=createHash('sha256').update(manifest).digest('hex')
const port=Number(process.env.DOCX_TEST_PORT??4381),base=`http://127.0.0.1:${port}`,documentId='track-revision-settings-smoke'
const mediaType='application/vnd.openxmlformats-officedocument.wordprocessingml.document',hash=bytes=>createHash('sha256').update(bytes).digest('hex')
await mkdir(output,{recursive:true})
const runPython=input=>{
 const result=spawnSync(join(repo,'.venv/bin/python'),['-c',String.raw`
import base64,json,sys
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile
from hashlib import sha256
from lxml import etree
from docx import Document
from smart_reporting.reporting.delivery.docx_native import inspect_docx,patch_docx
p=json.load(sys.stdin)
if p['mode']=='create':
 d=Document();d.add_paragraph('跟踪修订设置持久化');b=BytesIO();d.save(b);Path(p['path']).write_bytes(b.getvalue())
 with ZipFile(BytesIO(b.getvalue())) as src,ZipFile(p['path'],'a') as out:
  out.writestr('customXml/track-settings-keep.xml','<keep xmlns="urn:track-settings">preserve</keep>')
 print(json.dumps({'sha256':sha256(Path(p['path']).read_bytes()).hexdigest(),'model':inspect_docx(Path(p['path']).read_bytes())},ensure_ascii=False))
elif p['mode']=='inspect':
 b=Path(p['path']).read_bytes();print(json.dumps({'sha256':sha256(b).hexdigest(),'model':inspect_docx(b)},ensure_ascii=False))
elif p['mode']=='patch':
 source=Path(p['source']).read_bytes();out=patch_docx(source,p['operations']);Path(p['output']).write_bytes(out)
 with ZipFile(BytesIO(source)) as a,ZipFile(BytesIO(out)) as b:
  names=set(a.namelist())|set(b.namelist());changed=[n for n in sorted(names) if not n.endswith('/') and (n not in a.namelist() or n not in b.namelist() or a.read(n)!=b.read(n))]
  assert set(changed)=={'word/settings.xml','docProps/core.xml'},changed
  assert a.read('customXml/track-settings-keep.xml')==b.read('customXml/track-settings-keep.xml')
 print(json.dumps({'sha256':sha256(out).hexdigest(),'changedParts':changed,'model':inspect_docx(out)},ensure_ascii=False))
`],{cwd:repo,env:{...process.env,PYTHONPATH:repo},input:JSON.stringify(input),encoding:'utf8',maxBuffer:30*1024*1024})
 if(result.status!==0)throw new Error(result.stderr||`python exited ${result.status}`)
 return JSON.parse(result.stdout.trim())
}
const sourcePath=join(output,'revision-1.docx'),firstPath=join(output,'revision-2.docx'),secondPath=join(output,'revision-3.docx')
const initial=runPython({mode:'create',path:sourcePath});assert.equal(initial.model.trackRevisions,false)
const revisions=new Map([[1,await readFile(sourcePath)]]),models=new Map([[1,initial.model]]),downloadBytes=new Map(),saveEvidence=[],loaded=new Map(),errors=[]
const server=createServer(async(req,res)=>{
 try{
  const url=new URL(req.url??'/',base),pathname=decodeURIComponent(url.pathname)
  if(pathname==='/reports/v1/editor/assets/native.html'||pathname==='/reports/v1/editor/assets/'){
   const file=join(staticRoot,'native.html');res.writeHead(200,{'content-type':'text/html'});res.end(await readFile(file));return
  }
  const assetPrefix='/reports/v1/editor/assets/',assetPath=pathname.startsWith(assetPrefix)?resolve(staticRoot,pathname.slice(assetPrefix.length)):''
  if(assetPath&&assetPath.startsWith(staticRoot+'/')){res.writeHead(200,{'content-type':({'.js':'text/javascript','.css':'text/css','.html':'text/html','.woff2':'font/woff2','.wasm':'application/wasm'})[extname(assetPath)]??'application/octet-stream'});res.end(await readFile(assetPath));return}
  if(pathname.startsWith('/__download__/')){const revision=Number(pathname.split('/').at(-1)),bytes=downloadBytes.get(revision);if(!bytes){res.writeHead(404);res.end();return}res.writeHead(200,{'content-type':mediaType,'content-disposition':`attachment; filename=revision-${revision}.docx`});res.end(bytes);return}
  res.writeHead(404);res.end('not found')
 }catch(error){res.writeHead(500);res.end(String(error))}
})
await new Promise((resolve,reject)=>{server.once('error',reject);server.listen(port,'127.0.0.1',resolve)})
let browser,page
try{
 browser=await chromium.launch({headless:true,...(process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE?{executablePath:process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE}:{})})
 page=await browser.newPage({viewport:{width:1500,height:960},acceptDownloads:true})
 page.on('pageerror',error=>errors.push(error.message));page.on('console',message=>{if(message.type()==='error')errors.push(message.text())})
 page.on('response',response=>{const path=new URL(response.url()).pathname;if(path.startsWith(assetPrefix)&&/\.(?:js|css)$/.test(path)&&response.status()===200){const file=resolve(staticRoot,path.slice(assetPrefix.length));loaded.set(path,response.body().then(async body=>{assert.equal(hash(body),hash(await readFile(file)),path)}))}})
 const currentRevision=request=>Number(new URL(request.url()).pathname.split('/')[5])
 await page.route(`**/reports/v1/native/${documentId}/*/api/context`,route=>{const revision=currentRevision(route.request()),bytes=revisions.get(revision);return route.fulfill({json:{context:{documentId,format:'docx',revision,parentRevision:revision-1||null,scope:{database:'fixture',companyId:'fixture',userId:'authorized-reviewer',threadId:'track-settings'},sourceFile:{path:`revision-${revision}.docx`,size:bytes.length,sha256:hash(bytes),mediaType},origin:'upload'},csrfToken:'fixture-csrf',capabilities:{docx_editor:true},editingEnabled:true}})})
 await page.route(`**/reports/v1/native/${documentId}/*/api/file`,route=>route.fulfill({body:revisions.get(currentRevision(route.request())),contentType:mediaType}))
 await page.route(`**/reports/v1/native/${documentId}/*/api/preview`,route=>{const model=models.get(currentRevision(route.request()));return route.fulfill({json:{sourceSha256:model.sourceSha256,draftSha256:model.sourceSha256,model}})})
 await page.route(`**/reports/v1/native/${documentId}/*/api/save`,async route=>{
  const revision=currentRevision(route.request()),next=revision+1,payload=route.request().postDataJSON(),enabled=next===2
  assert.equal(payload.expectedSha256,models.get(revision).sourceSha256)
  assert.deepEqual(payload.operations,[{kind:'setTrackRevisions',sourceSha256:models.get(revision).sourceSha256,enabled}])
  const source=join(output,`revision-${revision}.docx`),target=next===2?firstPath:secondPath
  const saved=runPython({mode:'patch',source,output:target,operations:payload.operations})
  assert.equal(saved.model.trackRevisions,enabled);assert.deepEqual(saved.changedParts,['docProps/core.xml','word/settings.xml'])
  const bytes=await readFile(target);revisions.set(next,bytes);models.set(next,saved.model);downloadBytes.set(next,bytes);saveEvidence.push({revision:next,enabled,sourceSha256:models.get(revision).sourceSha256,sha256:hash(bytes),changedParts:saved.changedParts})
  await route.fulfill({json:{documentId,revision:next,parentRevision:revision,revisionRegistered:true,artifacts:{word:{downloadUrl:`/__download__/${next}`,size:bytes.length,sha256:hash(bytes)}},editor:{openUrl:`/reports/v1/native/${documentId}/${next}`},validation:{ok:false,issues:[{code:'fixture_pending',message:'独立回读验收中'}]}}})
 })
 await page.route(new RegExp(`/reports/v1/native/${documentId}/[0-9]+$`),async route=>{const response=await route.fetch({url:`${base}/reports/v1/editor/assets/native.html`});await route.fulfill({response})})
 const open=async revision=>{await page.goto(`${base}/reports/v1/native/${documentId}/${revision}`);await page.locator('.docx-source-home').waitFor({timeout:60000});await page.locator('[data-tab-id="review"]').click();const toggle=page.locator('[data-review-track-changes]');await toggle.waitFor();assert.equal(await toggle.getAttribute('aria-pressed'),String(models.get(revision).trackRevisions),`revision ${revision} Review state`);return toggle}
 const save=async(revision,expectedEnabled)=>{
  await page.locator('[data-action="save"]').click();await page.waitForFunction(next=>(document.querySelector('.save-state-label')?.textContent??'').includes(`已保存修订 ${next}`),revision+1,{timeout:60000})
  const link=page.getByRole('link',{name:'下载 Word',exact:true}),downloadUrl=await link.getAttribute('href')
  const [download]=await Promise.all([page.waitForEvent('download'),link.click()]);assert.match(download.suggestedFilename(),/\.docx$/)
  const response=await page.request.get(new URL(downloadUrl,base).toString());assert.equal(response.status(),200)
  const downloaded=await response.body(),downloadedPath=join(output,`revision-${revision+1}-download.docx`),expected=revisions.get(revision+1)
  await writeFile(downloadedPath,downloaded);assert.equal(hash(downloaded),hash(expected))
  const independentlyRead=runPython({mode:'inspect',path:downloadedPath});assert.equal(independentlyRead.model.trackRevisions,expectedEnabled)
  assert.equal(independentlyRead.sha256,hash(downloaded));assert.deepEqual(saveEvidence.at(-1).changedParts,['docProps/core.xml','word/settings.xml'])
  return downloadedPath
 }
 const firstToggle=await open(1);await firstToggle.click();assert.equal(await firstToggle.getAttribute('aria-pressed'),'true')
 await save(1,true);await open(2)
 const secondToggle=page.locator('[data-review-track-changes]');await secondToggle.click();assert.equal(await secondToggle.getAttribute('aria-pressed'),'false')
 await save(2,false);await open(3)
 await Promise.all(loaded.values());assert.ok([...loaded.keys()].some(path=>path.includes('lazy-docx-main-')));assert.ok([...loaded.keys()].some(path=>path.includes('native-docx-engine-')))
 assert.deepEqual(errors,[])
 const result={ok:true,temporary:output,manifestSha256,browserVersion:browser.version(),bridgeSha256:hash(await readFile(join(repo,'smart_reporting/reporting/doc_engine/dist/edit-docx.mjs'))),loadedAssets:[...loaded.keys()],saveEvidence,finalTrackRevisions:models.get(3).trackRevisions,errors}
 await writeFile(join(output,'result.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result))
}catch(error){if(page){await writeFile(join(output,'failure.html'),await page.content()).catch(()=>{});await page.screenshot({path:join(output,'failure.png'),fullPage:true}).catch(()=>{})}await writeFile(join(output,'failure.txt'),String(error));throw error
}finally{await browser?.close();await new Promise(resolve=>server.close(resolve))}
