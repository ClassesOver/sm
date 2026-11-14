import assert from 'node:assert/strict'
import {spawn,spawnSync} from 'node:child_process'
import {createHash} from 'node:crypto'
import {mkdir,readFile,writeFile} from 'node:fs/promises'
import {join,resolve,sep} from 'node:path'
import {fileURLToPath} from 'node:url'
import {setTimeout as delay} from 'node:timers/promises'
import {chromium} from 'playwright'

const frontend=fileURLToPath(new URL('../',import.meta.url)),repo=fileURLToPath(new URL('../../../../',import.meta.url))
const output=process.env.PDF_SPLIT_BATCH_OUTPUT??'/dev/shm/office-next-pdf-split-batch-20261113/browser-frozen'
assert(process.env.PDF_SPLIT_BATCH_STATIC&&process.env.PDF_SPLIT_BATCH_ENGINE&&process.env.PDF_SPLIT_BATCH_MANIFEST,'必须显式传入最终冻结 static/engine/manifest，禁止默用 live dist')
const staticRoot=resolve(process.env.PDF_SPLIT_BATCH_STATIC),engineRoot=resolve(process.env.PDF_SPLIT_BATCH_ENGINE)
const port=Number(process.env.PDF_SPLIT_BATCH_PORT??4440),origin=`http://127.0.0.1:${port}`,sha=bytes=>createHash('sha256').update(bytes).digest('hex')
await mkdir(output,{recursive:true})
const manifestBytes=await readFile(join(staticRoot,'.vite/manifest.json')),manifestSha256=sha(manifestBytes),manifest=JSON.parse(manifestBytes)
assert.equal(manifestSha256,process.env.PDF_SPLIT_BATCH_MANIFEST)
const server=spawn(join(repo,'.venv/bin/python'),[join(frontend,'smoke/pdf-split-batch-server.py'),'--directory',output,'--port',String(port)],{cwd:repo,env:{...process.env,PYTHONPATH:repo,PYTHONDONTWRITEBYTECODE:'1',PDF_SMOKE_STATIC_DIRECTORY:staticRoot,AGENT_REPORTING_PDF_ENGINE_DIR:engineRoot},stdio:'pipe'})
let log='',browser,page,stage='server';server.stdout.on('data',b=>{log+=b});server.stderr.on('data',b=>{log+=b})
const errors=[],consoleErrors=[],httpErrors=[],resources=[],resourceTasks=[]
try{
  for(let i=0;;i++){assert.equal(server.exitCode,null,log);try{if((await fetch(origin+'/__smoke__/state')).ok)break}catch{}assert(i<240,log);await delay(250)}
  const info=JSON.parse(await readFile(join(output,'server-info.json'),'utf8'))
  browser=await chromium.launch({headless:true});page=await browser.newPage({viewport:{width:1440,height:900}})
  page.on('pageerror',e=>errors.push(e.message));page.on('console',e=>{if(e.type()==='error')consoleErrors.push(e.text())})
  page.on('response',r=>{
    const url=new URL(r.url()),prefix='/reports/v1/editor/assets/'
    if(r.status()>=400)httpErrors.push({path:url.pathname,status:r.status()})
    if(url.origin!==origin||!url.pathname.startsWith(prefix)||! /\.(?:m?js|css)$/.test(url.pathname)||r.status()!==200)return
    resourceTasks.push((async()=>{const relative=decodeURIComponent(url.pathname.slice(prefix.length)),path=resolve(staticRoot,relative);assert(path.startsWith(staticRoot+sep));const bytes=await r.body(),hash=sha(bytes);assert.equal(hash,sha(await readFile(path)));const keys=Object.entries(manifest).filter(([,v])=>v.file===relative||v.css?.includes(relative)||v.assets?.includes(relative)).map(([k])=>k);assert(keys.length,relative);resources.push({path:relative,sha256:hash,manifestKeys:keys})})())
  })
  const ready=()=>page.waitForFunction(()=>document.querySelector('#report-editor')?.getAttribute('aria-busy')==='false'&&document.querySelector('.pdf-page-content canvas'),null,{timeout:120000})
  const openSplit=async()=>{await page.locator('[data-pdf-ribbon-tab="page"]').click();const control=page.locator('[data-source-command-id="genoffice.pdf.page.splitPdf"]');assert.equal(await control.isDisabled(),false);await control.click();await page.getByRole('dialog',{name:'拆分 PDF',exact:true}).waitFor()}
  const dialog=()=>page.getByRole('dialog',{name:'拆分 PDF',exact:true})
  stage='entry';const entry=await page.goto(origin+info.openPath);await ready();assert(entry);const html=await entry.body();assert.equal(sha(html),sha(await readFile(join(staticRoot,'native.html'))));await writeFile(join(output,'actual-native.html'),html)
  await page.waitForFunction(()=>document.querySelectorAll('.pdf-page').length===5);await Promise.all(resourceTasks);assert.equal(resources.some(r=>r.path.includes('/lazy-pdf-split-')),false,'controls/dialog不得在首次打开之前加载');assert(resources.some(r=>r.path.includes('native-pdf-split-host-')),'同步小宿主应随PDF载入')
  stage='cancel';await openSplit();await Promise.all(resourceTasks);assert(resources.some(r=>r.path.includes('/lazy-pdf-split-')),'首次打开应实际加载controls/dialog');await dialog().getByRole('button',{name:'关闭',exact:true}).click();let state=await(await fetch(origin+'/__smoke__/state')).json();assert.equal(state.savedRevisions,0);assert.equal(state.requests.filter(r=>r.path.endsWith('/api/split-pdf')).length,0)
  stage='pending-source';await page.locator('[data-pdf-ribbon-tab="home"]').click();await page.locator('[data-source-command-id="genoffice.pdf.home.properties.documentProperties"]').click();await page.getByLabel('文档属性 标题',{exact:true}).fill('Split saved title');await page.locator('[data-metadata-apply]').click();await ready()
  await page.locator('[data-pdf-ribbon-tab="page"]').click();await page.locator('[data-source-command-id="genoffice.pdf.page.reverse"]').click();await ready()
  stage='real-confirmation';await openSplit();await dialog().getByLabel('每份页数',{exact:true}).fill('2');await dialog().locator('[data-pdf-split-apply]').click();await page.waitForFunction(()=>document.querySelector('.pdf-split-dialog [role=status]')?.textContent.includes('勾选确认'),null,{timeout:90000})
  state=await(await fetch(origin+'/__smoke__/state')).json();assert.equal(state.savedRevisions,0);assert.equal(state.requests.filter(r=>r.path.endsWith('/api/split-pdf')).length,0)
  await dialog().getByRole('button',{name:'关闭',exact:true}).click();await page.getByRole('checkbox',{name:/我已核对实际 PDF 预览/}).check()
  stage='flush-save-and-split';await openSplit();const saving=page.waitForResponse(r=>r.url().endsWith('/api/save')&&r.request().method()==='POST'),splitting=page.waitForResponse(r=>r.url().endsWith('/api/split-pdf')&&r.request().method()==='POST');await dialog().locator('[data-pdf-split-apply]').click();const saveResponse=await saving,saved=await saveResponse.json();assert.equal(saveResponse.status(),200,JSON.stringify(saved));assert(saved.revisionRegistered);assert.equal(saved.revision,5);assert.equal(saved.validation.ok,false);const splitResponse=await splitting,result=await splitResponse.json();assert.equal(splitResponse.status(),200,JSON.stringify(result));assert.equal(new URL(splitResponse.url()).pathname,'/reports/v1/native/parent-document/5/api/split-pdf');assert.equal(result.source.sha256,saved.artifacts.pdf.sha256);assert.equal(result.source.revision,5);assert.deepEqual(result.parts.map(p=>p.pages),[[1,2],[3,4],[5]]);assert.equal(result.validation.ok,false)
  await dialog().locator('section a[download]').last().waitFor();assert.equal(await dialog().locator('section a[download]').count(),3)
  await page.screenshot({path:join(output,'split-results-desktop.png'),fullPage:true});await page.setViewportSize({width:390,height:700});await page.screenshot({path:join(output,'split-results-narrow.png'),fullPage:true});const layout=await dialog().evaluate(d=>({width:d.clientWidth,scrollWidth:d.scrollWidth,height:d.clientHeight,scrollHeight:d.scrollHeight}));assert(layout.scrollWidth<=layout.width+1);await dialog().locator('section a[download]').last().scrollIntoViewIfNeeded();await page.screenshot({path:join(output,'split-results-narrow-bottom.png'),fullPage:true});await page.setViewportSize({width:1440,height:900})
  stage='downloads';const files=[]
  for(const [index,part]of result.parts.entries()){assert(part.result.artifacts.pdf.downloadUrl);assert.equal(part.result.validation.ok,false);const downloading=page.waitForEvent('download');await dialog().locator('section a[download]').nth(index).click();const download=await downloading;assert.equal(await download.failure(),null);const content=await readFile(await download.path()),artifact=part.result.artifacts.pdf;assert.equal(sha(content),artifact.sha256);assert.equal(content.length,artifact.size);const file=join(output,`part-${index+1}.pdf`);await writeFile(file,content);files.push(file)}
  state=await(await fetch(origin+'/__smoke__/state')).json();assert.equal(state.sourceSha256,info.sourceSha256);assert.equal(state.savedRevisions,1);assert.equal(state.requests.filter(r=>r.path.endsWith('/api/save')&&r.method==='POST').length,1);assert.equal(state.requests.filter(r=>r.path.endsWith('/api/split-pdf')&&r.method==='POST').length,1)
  stage='independent-read';const savedDownload=await page.request.get(saved.artifacts.pdf.downloadUrl);assert.equal(savedDownload.status(),200);const savedBytes=await savedDownload.body();assert.equal(sha(savedBytes),saved.artifacts.pdf.sha256);await writeFile(join(output,'saved-source.pdf'),savedBytes)
  const verify=spawnSync(join(repo,'.venv/bin/python'),['-c',"import json,sys,hashlib;from pypdf import PdfReader;saved=PdfReader(sys.argv[1]);assert saved.metadata.title=='Split saved title';assert [p.extract_text().strip() for p in saved.pages]==['Split source page 5','Split source page 4','Split source page 3','Split source page 2','Split source page 1'];rows=[{'path':p,'sha256':hashlib.sha256(open(p,'rb').read()).hexdigest(),'texts':[x.extract_text().strip() for x in PdfReader(p).pages]}for p in sys.argv[2:]];assert [r['texts'] for r in rows]==[['Split source page 5','Split source page 4'],['Split source page 3','Split source page 2'],['Split source page 1']];print(json.dumps({'savedTitle':saved.metadata.title,'parts':rows}))",join(output,'saved-source.pdf'),...files],{encoding:'utf8'});assert.equal(verify.status,0,verify.stderr);const independent=JSON.parse(verify.stdout);await writeFile(join(output,'independent-verification.json'),JSON.stringify(independent,null,2))
  stage='reopen-child';await page.goto(result.parts[0].result.editor.openUrl);await ready();await page.waitForFunction(()=>document.querySelectorAll('.pdf-page').length===2)
  await Promise.all(resourceTasks);assert.deepEqual(errors,[]);assert.deepEqual(consoleErrors,[]);assert.deepEqual(httpErrors,[])
  await writeFile(join(output,'evidence.json'),JSON.stringify({ok:true,manifestSha256,staticRoot,engineRoot,splitControlsDeferred:true,htmlSha256:sha(html),sourceSha256:info.sourceSha256,saved,result,layout,independent,resources,errors,consoleErrors,httpErrors,state},null,2));console.log(JSON.stringify({ok:true,output,savedRevisions:1,parts:result.parts.length}))
}catch(error){await page?.screenshot({path:join(output,'failure.png'),fullPage:true}).catch(()=>{});await writeFile(join(output,'failure.json'),JSON.stringify({stage,error:String(error),errors,consoleErrors,httpErrors},null,2));throw error}
finally{await browser?.close();server.kill();await writeFile(join(output,'server.log'),log);if(server.exitCode===null)await Promise.race([new Promise(r=>server.once('exit',r)),delay(5000)]);if(server.exitCode===null)server.kill('SIGKILL')}
