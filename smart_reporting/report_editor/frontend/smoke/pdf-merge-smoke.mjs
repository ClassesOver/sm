import assert from 'node:assert/strict'
import {spawn,spawnSync} from 'node:child_process'
import {createHash} from 'node:crypto'
import {mkdir,readFile,writeFile} from 'node:fs/promises'
import {join,resolve,sep} from 'node:path'
import {fileURLToPath} from 'node:url'
import {setTimeout as delay} from 'node:timers/promises'
import {chromium} from 'playwright'

const frontend=fileURLToPath(new URL('../',import.meta.url)),repo=fileURLToPath(new URL('../../../../',import.meta.url))
const output=process.env.PDF_MERGE_OUTPUT??'/dev/shm/office-next-pdf-merge-20261113/browser-frozen'
assert(process.env.PDF_MERGE_STATIC&&process.env.PDF_MERGE_ENGINE&&process.env.PDF_MERGE_MANIFEST&&process.env.PDF_MERGE_SNAPSHOT,'必须显式传入最终冻结 static/engine/manifest，禁止默用 live dist')
const staticRoot=resolve(process.env.PDF_MERGE_STATIC),engineRoot=resolve(process.env.PDF_MERGE_ENGINE)
const port=Number(process.env.PDF_MERGE_PORT??4441),origin=`http://127.0.0.1:${port}`,sha=bytes=>createHash('sha256').update(bytes).digest('hex')
await mkdir(output,{recursive:true})
const manifestBytes=await readFile(join(staticRoot,'.vite/manifest.json')),manifestSha256=sha(manifestBytes),manifest=JSON.parse(manifestBytes)
assert.equal(manifestSha256,process.env.PDF_MERGE_MANIFEST)
const snapshotRoot=resolve(process.env.PDF_MERGE_SNAPSHOT),backendRegistry=JSON.parse(await readFile(join(snapshotRoot,'BACKEND-SNAPSHOT-SHA256.json'),'utf8'))
const backendPaths=['smart_reporting/report_editor/native_api.py','smart_reporting/report_editor/native_pdf_extract.py','smart_reporting/report_editor/native_pdf_merge.py','smart_reporting/report_editor/native.py','smart_reporting/report_editor/native_publication.py','smart_reporting/report_editor/native_models.py','smart_reporting/report_editor/_file_identity.py','smart_reporting/reporting/delivery/pdf_native.py','smart_reporting/reporting/delivery/office_engine.py']
async function recordBackend(name){
  const files=await Promise.all(backendPaths.map(async path=>{const liveSha256=sha(await readFile(join(repo,path))),snapshotSha256=sha(await readFile(join(snapshotRoot,'backend-baseline',path))),registrySha256=backendRegistry.find(row=>row.path===path)?.sha256;return{path,liveSha256,snapshotSha256,registrySha256,matches:liveSha256===snapshotSha256&&liveSha256===registrySha256}}))
  const result={recordedAtUtc:new Date().toISOString(),files,allMatch:files.every(row=>row.matches),scope:'Nine named PDF chain files only; live Python host, no isolation or whole-baseline execution claim.'};await writeFile(join(output,name),JSON.stringify(result,null,2));assert(result.allMatch,JSON.stringify(result));return result
}
const executedHarnesses=[]
for(const [name,path]of [['runner.mjs',fileURLToPath(import.meta.url)],['server.py',join(frontend,'smoke/pdf-merge-server.py')],['inherited-server.py',join(frontend,'smoke/pdf-form-create-server.py')]]){
  const bytes=await readFile(path);await writeFile(join(output,`executed-${name}`),bytes);executedHarnesses.push({path,sha256:sha(bytes),copy:`executed-${name}`})
}
await writeFile(join(output,'executed-harness-identities.json'),JSON.stringify({recordedAtUtc:new Date().toISOString(),capture:'Startup copies before server/browser execution',files:executedHarnesses},null,2))
const backendBefore=await recordBackend('backend-before.json')
const server=spawn(join(repo,'.venv/bin/python'),[join(frontend,'smoke/pdf-merge-server.py'),'--directory',output,'--port',String(port)],{cwd:repo,env:{...process.env,PYTHONPATH:repo,PYTHONDONTWRITEBYTECODE:'1',PDF_SMOKE_STATIC_DIRECTORY:staticRoot,AGENT_REPORTING_PDF_ENGINE_DIR:engineRoot},stdio:'pipe'})
let log='',browser,page,stage='server';server.stdout.on('data',b=>{log+=b});server.stderr.on('data',b=>{log+=b})
const errors=[],consoleErrors=[],httpErrors=[],resources=[],resourceTasks=[]
try{
  for(let i=0;;i++){assert.equal(server.exitCode,null,log);try{if((await fetch(origin+'/__smoke__/state')).ok)break}catch{}assert(i<240,log);await delay(250)}
  const info=JSON.parse(await readFile(join(output,'server-info.json'),'utf8'))
  const attachments=spawnSync(join(repo,'.venv/bin/python'),['-c',"import sys;from reportlab.pdfgen.canvas import Canvas;from pathlib import Path;root=Path(sys.argv[1]);[(lambda c,labels:([c.drawString(30,300,label) or c.showPage() for label in labels],c.save()))(Canvas(str(root/name),pagesize=(300,400)),labels)for name,labels in [('external-a.pdf',['External A1','External A2']),('external-b.pdf',['External B1'])]]",output],{encoding:'utf8'});assert.equal(attachments.status,0,attachments.stderr)
  const fixtures=[];for(const name of ['source.pdf','external-a.pdf','external-b.pdf']){const bytes=await readFile(join(output,name));fixtures.push({path:name,size:bytes.length,sha256:sha(bytes)})}
  await writeFile(join(output,'fixture-identities-before-browser.json'),JSON.stringify({recordedAtUtc:new Date().toISOString(),files:fixtures},null,2))
  browser=await chromium.launch({headless:true});page=await browser.newPage({viewport:{width:1440,height:900}})
  page.on('pageerror',e=>errors.push(e.message));page.on('console',e=>{if(e.type()==='error')consoleErrors.push(e.text())})
  page.on('response',r=>{
    const url=new URL(r.url()),prefix='/reports/v1/editor/assets/'
    if(r.status()>=400)httpErrors.push({path:url.pathname,status:r.status()})
    if(url.origin!==origin||!url.pathname.startsWith(prefix)||! /\.(?:m?js|css)$/.test(url.pathname)||r.status()!==200)return
    resourceTasks.push((async()=>{const relative=decodeURIComponent(url.pathname.slice(prefix.length)),path=resolve(staticRoot,relative);assert(path.startsWith(staticRoot+sep));const bytes=await r.body(),hash=sha(bytes);assert.equal(hash,sha(await readFile(path)));const keys=Object.entries(manifest).filter(([,v])=>v.file===relative||v.css?.includes(relative)||v.assets?.includes(relative)).map(([k])=>k);assert(keys.length,relative);resources.push({path:relative,sha256:hash,manifestKeys:keys})})())
  })
  const ready=()=>page.waitForFunction(()=>document.querySelector('#report-editor')?.getAttribute('aria-busy')==='false'&&document.querySelector('.pdf-page-content canvas'),null,{timeout:120000})
  const openMerge=async()=>{await page.locator('[data-pdf-ribbon-tab="page"]').click();const control=page.locator('[data-source-command-id="genoffice.pdf.page.mergePdf"]');assert.equal(await control.isDisabled(),false);await control.click();await page.getByRole('dialog',{name:'合并 PDF',exact:true}).waitFor()}
  const dialog=()=>page.getByRole('dialog',{name:'合并 PDF',exact:true})
  stage='entry';const entry=await page.goto(origin+info.openPath);await ready();assert(entry);const html=await entry.body();assert.equal(sha(html),sha(await readFile(join(staticRoot,'native.html'))));await writeFile(join(output,'actual-native.html'),html)
  await page.waitForFunction(()=>document.querySelectorAll('.pdf-page').length===3);await Promise.all(resourceTasks);assert.equal(resources.some(r=>r.path.includes('/lazy-pdf-merge-')),false,'merge controls/dialog must not load before the first open')
  stage='cancel';await openMerge();await Promise.all(resourceTasks);assert(resources.some(r=>r.path.includes('/lazy-pdf-merge-')),'first open must load actual merge controls/dialog');await dialog().getByRole('button',{name:'关闭',exact:true}).click();let state=await(await fetch(origin+'/__smoke__/state')).json();assert.equal(state.savedRevisions,0);assert.equal(state.requests.filter(r=>r.path.endsWith('/api/merge-pdf')).length,0)
  stage='pending-source';await page.locator('[data-pdf-ribbon-tab="home"]').click();await page.locator('[data-source-command-id="genoffice.pdf.home.properties.documentProperties"]').click();await page.getByLabel('文档属性 标题',{exact:true}).fill('Merge saved title');await page.locator('[data-metadata-apply]').click();await ready()
  await page.locator('[data-pdf-ribbon-tab="page"]').click();await page.locator('[data-source-command-id="genoffice.pdf.page.reverse"]').click();await ready()
  stage='real-confirmation';await openMerge();await dialog().getByLabel('选择合并 PDF 文件',{exact:true}).setInputFiles([join(output,'external-a.pdf'),join(output,'external-b.pdf')]);await dialog().getByRole('button',{name:'上移 external-b.pdf',exact:true}).click();await dialog().locator('[data-pdf-merge-apply]').click();await page.waitForFunction(()=>document.querySelector('.pdf-merge-dialog [role=status]')?.textContent.includes('勾选确认'),null,{timeout:90000})
  state=await(await fetch(origin+'/__smoke__/state')).json();assert.equal(state.savedRevisions,0);assert.equal(state.requests.filter(r=>r.path.endsWith('/api/merge-pdf')).length,0)
  await dialog().getByRole('button',{name:'关闭',exact:true}).click();await page.getByRole('checkbox',{name:/我已核对实际 PDF 预览/}).check()
  stage='flush-save-and-merge';await openMerge();const saving=page.waitForResponse(r=>r.url().endsWith('/api/save')&&r.request().method()==='POST'),merging=page.waitForResponse(r=>r.url().endsWith('/api/merge-pdf')&&r.request().method()==='POST');await dialog().locator('[data-pdf-merge-apply]').click();const saveResponse=await saving,saved=await saveResponse.json();assert.equal(saveResponse.status(),200,JSON.stringify(saved));assert(saved.revisionRegistered);assert.equal(saved.revision,5);assert.equal(saved.validation.ok,false);const mergeResponse=await merging,result=await mergeResponse.json();assert.equal(mergeResponse.status(),200,JSON.stringify(result));assert.equal(new URL(mergeResponse.url()).pathname,'/reports/v1/native/parent-document/5/api/merge-pdf');assert.equal(result.source.sha256,saved.artifacts.pdf.sha256);assert.equal(result.source.revision,5);assert.equal(result.validation.ok,false)
  assert.deepEqual(result.source.externalSha256s,[sha(await readFile(join(output,'external-b.pdf'))),sha(await readFile(join(output,'external-a.pdf')))])
  await dialog().locator('a[download]').waitFor();await page.screenshot({path:join(output,'merge-results-desktop.png'),fullPage:true});await page.setViewportSize({width:390,height:700});await page.screenshot({path:join(output,'merge-results-narrow.png'),fullPage:true});const layout=await dialog().evaluate(d=>({width:d.clientWidth,scrollWidth:d.scrollWidth,height:d.clientHeight,scrollHeight:d.scrollHeight}));assert(layout.scrollWidth<=layout.width+1);await dialog().locator('a[download]').scrollIntoViewIfNeeded();await page.screenshot({path:join(output,'merge-results-narrow-bottom.png'),fullPage:true});await page.setViewportSize({width:1440,height:900})
  stage='download';const downloading=page.waitForEvent('download');await dialog().locator('a[download]').click();const download=await downloading;assert.equal(await download.failure(),null);const bytes=await readFile(await download.path()),artifact=result.artifacts.pdf;assert.equal(sha(bytes),artifact.sha256);assert.equal(bytes.length,artifact.size);await writeFile(join(output,'merged.pdf'),bytes)
  state=await(await fetch(origin+'/__smoke__/state')).json();assert.equal(state.sourceSha256,info.sourceSha256);assert.equal(state.savedRevisions,1);assert.equal(state.requests.filter(r=>r.path.endsWith('/api/save')&&r.method==='POST').length,1);assert.equal(state.requests.filter(r=>r.path.endsWith('/api/merge-pdf')&&r.method==='POST').length,1)
  stage='independent-read';const savedDownload=await page.request.get(saved.artifacts.pdf.downloadUrl);assert.equal(savedDownload.status(),200);const savedBytes=await savedDownload.body();assert.equal(sha(savedBytes),saved.artifacts.pdf.sha256);await writeFile(join(output,'saved-source.pdf'),savedBytes)
  const verify=spawnSync(join(repo,'.venv/bin/python'),['-c',"import json,sys;from pypdf import PdfReader;saved=PdfReader(sys.argv[1]);merged=PdfReader(sys.argv[2]);assert saved.metadata.title=='Merge saved title';assert merged.metadata.title=='Merge saved title';assert [p.extract_text().strip() for p in saved.pages]==['Merge source page 3','Merge source page 2','Merge source page 1'];texts=[p.extract_text().strip() for p in merged.pages];assert texts==['Merge source page 3','Merge source page 2','Merge source page 1','External B1','External A1','External A2'];print(json.dumps({'savedTitle':saved.metadata.title,'mergedTitle':merged.metadata.title,'texts':texts}))",join(output,'saved-source.pdf'),join(output,'merged.pdf')],{encoding:'utf8'});assert.equal(verify.status,0,verify.stderr);const independent=JSON.parse(verify.stdout);await writeFile(join(output,'independent-verification.json'),JSON.stringify(independent,null,2))
  stage='reopen-child';await page.goto(result.editor.openUrl);await ready();await page.waitForFunction(()=>document.querySelectorAll('.pdf-page').length===6)
  await Promise.all(resourceTasks);assert.deepEqual(errors,[]);assert.deepEqual(consoleErrors,[]);assert.deepEqual(httpErrors,[])
  const backendAfter=await recordBackend('backend-after.json');assert.deepEqual(backendAfter.files,backendBefore.files)
  await writeFile(join(output,'evidence.json'),JSON.stringify({ok:true,manifestSha256,staticRoot,engineRoot,mergeControlsDeferred:true,executedHarnesses,fixtures,backendBefore,backendAfter,htmlSha256:sha(html),sourceSha256:info.sourceSha256,saved,result,layout,independent,resources,resourceCounts:{browserRecords:resources.length,uniqueResources:new Set(resources.map(row=>row.path)).size},errors,consoleErrors,httpErrors,state},null,2));console.log(JSON.stringify({ok:true,output,savedRevisions:1,mergedPages:6}))
}catch(error){await recordBackend('backend-after-failure.json').catch(()=>{});await page?.screenshot({path:join(output,'failure.png'),fullPage:true}).catch(()=>{});await writeFile(join(output,'failure.json'),JSON.stringify({stage,error:String(error),bodyText:await page?.locator('body').innerText().catch(()=>null),errors,consoleErrors,httpErrors},null,2));throw error}
finally{await browser?.close();server.kill();await writeFile(join(output,'server.log'),log);if(server.exitCode===null)await Promise.race([new Promise(r=>server.once('exit',r)),delay(5000)]);if(server.exitCode===null)server.kill('SIGKILL')}
