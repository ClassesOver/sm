// 后半程专项：等价重建草稿；不是恢复 r1 请求，也不重复完整控件。
import assert from 'node:assert/strict'
import {spawn,spawnSync} from 'node:child_process'
import {createHash} from 'node:crypto'
import {copyFile,mkdir,readFile,writeFile} from 'node:fs/promises'
import {join} from 'node:path'
import {fileURLToPath} from 'node:url'
import {setTimeout as delay} from 'node:timers/promises'
import {once} from 'node:events'
import {chromium} from 'playwright'
const frontend=fileURLToPath(new URL('../',import.meta.url)),repo=fileURLToPath(new URL('../../../../',import.meta.url))
const base='/home/junge/codex-evidence/smart_reporting/office-image-links-measure-20261113',family=join(base,'xlsx'),r1=join(family,'browser-final-v3-r1'),out=process.env.EXTERNAL_LINKS_OUT
assert(out);await mkdir(out,{recursive:false})
const staticRoot=join(base,'final-source-v3/smart_reporting/report_editor/static'),enginePath=join(base,'xlsx-runtime-final-v1/dist/cli.mjs'),python=join(repo,'.venv/bin/python'),port=4529,origin='http://127.0.0.1:'+port,sha=b=>createHash('sha256').update(b).digest('hex')
for(const name of ['fixture.xlsx','replacement.xlsx'])await copyFile(join(r1,name),join(out,name))
const previous=JSON.parse(await readFile(join(r1,'server-info.json'),'utf8')),source=await readFile(join(out,'replacement.xlsx'))
const operations=JSON.parse(await readFile(join(family,'fixture-check/request.json'),'utf8')).operations
Object.assign(operations[1],{size:source.length,sha256:sha(source),bytesBase64:source.toString('base64')})
const pythonInputs=[['smart_reporting.reporting.delivery.office_engine',join(base,'final-source-v3/smart_reporting/reporting/delivery/office_engine.py')],['smart_reporting.reporting.delivery.xlsx',join(family,'python-final-v4/smart_reporting/reporting/delivery/xlsx.py')],['smart_reporting.report_editor.native_office',join(base,'final-source-v3/smart_reporting/report_editor/native_office.py')]]
const identities=await Promise.all(pythonInputs.map(async([module,path])=>({module,path,sha256:sha(await readFile(path))})))
assert.equal(identities[1].sha256,'97d3c209a68d82bc42a10802aec47ee9de3cc19a3bc3c76fd6cd5a101c8f234e')
const manifestSha=sha(await readFile(join(staticRoot,'.vite/manifest.json'))),runtimeSha=sha(await readFile(enginePath))
assert.equal(manifestSha,'5658c601dbbba3447288e85c0da97914e99778719232d14c6ff1ce1f1bf01aa4');assert.equal(runtimeSha,'1623e1b838a0e5a6460aa83e401dde8d4b20138619c4a8c502678605c7cdd2a9')
await writeFile(join(out,'input-identity.json'),JSON.stringify({kind:'reconstructed-draft-continuation',notRecoveredR1Payload:true,sourceSha256:sha(await readFile(join(out,'fixture.xlsx'))),replacementSha256:sha(source),manifestSha,runtimeSha,pythonInputs:identities},null,2))
const bootstrap=['import hashlib,importlib.util,json,runpy,sys','from pathlib import Path','inputs=json.loads(sys.argv[1])','actual=[]','for name,path in inputs:',' spec=importlib.util.spec_from_file_location(name,path)',' module=importlib.util.module_from_spec(spec)',' sys.modules[name]=module',' spec.loader.exec_module(module)',' actual.append({"module":name,"path":module.__file__,"sha256":hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()})','Path(sys.argv[2]).write_text(json.dumps(actual,indent=2))','script=sys.argv[3]','sys.argv=[script]+sys.argv[4:]','runpy.run_path(script,run_name="__main__")'].join('\n')
const server=spawn(python,['-c',bootstrap,JSON.stringify(pythonInputs),join(out,'actual-python-imports.json'),join(frontend,'smoke/workbook-ai-charts-server.py'),'--directory',out,'--port',String(port),'--source',join(out,'fixture.xlsx')],{cwd:repo,env:{...process.env,PYTHONPATH:repo,PDF_SMOKE_STATIC_DIRECTORY:staticRoot,AGENT_REPORTING_WORKBOOK_ENGINE_DIR:join(base,'xlsx-runtime-final-v1')},stdio:'pipe'})
let log='',browser,page,stage='server';server.stdout.on('data',b=>log+=b);server.stderr.on('data',b=>log+=b)
const errors=[],consoleErrors=[],assetErrors=[],assets=new Map(),externalRequests=[]
try{
 for(let n=0;;n++){assert.equal(server.exitCode,null,log);try{if((await fetch(origin+'/__smoke__/state')).ok)break}catch{}assert(n<240,log);await delay(250)}
 assert.deepEqual(JSON.parse(await readFile(join(out,'actual-python-imports.json'),'utf8')),identities)
 const info=JSON.parse(await readFile(join(out,'server-info.json'),'utf8'));assert.equal(info.sourceSha256,previous.sourceSha256);assert.deepEqual(info.context,previous.context)
 browser=await chromium.launch({headless:true,executablePath:'/snap/chromium/current/usr/lib/chromium-browser/chrome'});page=await browser.newPage({viewport:{width:1440,height:1000},acceptDownloads:true});page.setDefaultTimeout(30000)
 page.on('pageerror',error=>errors.push(error.message));page.on('console',message=>{if(message.type()==='error')consoleErrors.push(message.text())});page.on('request',request=>{if(!request.url().startsWith(origin)&&!request.url().startsWith('data:')&&!request.url().startsWith('blob:'))externalRequests.push(request.url())})
 await page.route('**/reports/v1/editor/assets/**',async route=>{const path=new URL(route.request().url()).pathname;try{const response=await route.fetch(),actual=await response.body(),disk=await readFile(join(staticRoot,decodeURIComponent(path.slice('/reports/v1/editor/assets/'.length))));assert.equal(response.status(),200);assert.equal(sha(actual),sha(disk));assets.set(path,sha(actual));await route.fulfill({response,body:actual})}catch(error){assetErrors.push({path,error:String(error)});await route.abort()}})
 const identity={documentId:info.context.documentId,revision:info.context.revision,sourceSha256:info.sourceSha256,scope:info.context.scope}
 await writeFile(join(out,'reconstructed-draft.json'),JSON.stringify({version:1,identity,operations},null,2))
 await page.addInitScript(({identity,operations})=>{if(location.pathname.endsWith('/'+identity.revision)){const s=identity.scope,key='native-editor-draft:v1:'+JSON.stringify([s.database,s.companyId,s.userId,s.threadId,identity.documentId,identity.revision,identity.sourceSha256]);localStorage.setItem(key,JSON.stringify({version:1,identity,operations}))}},{identity,operations})
 const ready=()=>page.waitForFunction(()=>document.querySelector('#report-editor')?.getAttribute('aria-busy')==='false',null,{timeout:90000})
 stage='reconstructed-draft-load';await page.goto(origin+info.openPath);await ready();await page.waitForLoadState('networkidle');await page.screenshot({path:join(out,'reconstructed-draft.png')})
 stage='save';const waiting=page.waitForResponse(response=>response.url().endsWith('/api/save')&&response.request().method()==='POST');await page.locator('[data-action=save]').click();const response=await waiting,saved=await response.json()
 await writeFile(join(out,'actual-save-request.json'),JSON.stringify(response.request().postDataJSON(),null,2));await writeFile(join(out,'actual-save-response.json'),JSON.stringify({httpStatus:response.status(),...saved},null,2))
 assert.equal(response.status(),200,JSON.stringify(saved));assert.equal(saved.revisionRegistered,true);assert.equal(saved.revision,info.context.revision+1);assert.deepEqual(response.request().postDataJSON().operations,operations)
 stage='download';const [download]=await Promise.all([page.waitForEvent('download'),page.locator('[data-action=xlsx-download]').click()]);await download.saveAs(join(out,'external-links.xlsx'));assert.equal(sha(await readFile(join(out,'external-links.xlsx'))),saved.artifacts.xlsx.sha256)
 const verify=spawnSync(python,[join(frontend,'smoke/workbook-external-links-verify.py'),out],{cwd:repo,encoding:'utf8'});await writeFile(join(out,'independent-readback.log'),verify.stdout+verify.stderr);assert.equal(verify.status,0,verify.stderr||verify.stdout)
 stage='reopen';await page.waitForLoadState('networkidle');await page.goto(saved.editor.openUrl);await ready();await page.waitForLoadState('networkidle');const reopened=await page.request.get(page.url()+'/api/file');assert.equal(sha(await reopened.body()),saved.artifacts.xlsx.sha256)
 await page.locator('[data-ribbon-tab=Formulas]').click();await page.locator('[data-ribbon-command=external-links-panel]').click();const pane=page.locator('.workbook-external-links');await pane.waitFor();assert.equal(await pane.locator('tbody tr').count(),1);assert((await pane.innerText()).includes('must-not-fetch.invalid'));await page.screenshot({path:join(out,'reopened.png')})
 const state=await(await fetch(origin+'/__smoke__/state')).json();assert.equal(state.savedRevisions,1);assert.equal(state.plannerCalls,0);assert.equal(state.sourceSha256,info.sourceSha256);assert.deepEqual(errors,[]);assert.deepEqual(externalRequests,[])
 for(const input of identities)assert.equal(sha(await readFile(input.path)),input.sha256);assert.equal(sha(await readFile(enginePath)),runtimeSha);assert.equal(sha(await readFile(join(staticRoot,'.vite/manifest.json'))),manifestSha)
 await writeFile(join(out,'evidence.json'),JSON.stringify({ok:true,kind:'reconstructed-draft-continuation',notRecoveredR1Payload:true,browserVersion:browser.version(),state,sourceSha256:info.sourceSha256,savedSha256:saved.artifacts.xlsx.sha256,manifestSha,runtimeSha,pythonInputs:identities,actualStaticAssets:[...assets],browserErrors:errors,consoleErrors,assetErrors,externalRequests,validation:saved.validation,independentReadback:JSON.parse(verify.stdout)},null,2));console.log(JSON.stringify({ok:true,assets:assets.size,assetErrors:assetErrors.length,savedSha256:saved.artifacts.xlsx.sha256}))
}catch(error){await page?.screenshot({path:join(out,'failure.png')}).catch(()=>{});await writeFile(join(out,'failure.json'),JSON.stringify({stage,error:String(error),stack:error.stack,errors,consoleErrors,assetErrors,externalRequests},null,2));throw error}
finally{await writeFile(join(out,'server.log'),log);await browser?.close();if(server.exitCode===null){const done=once(server,'exit');server.kill('SIGTERM');await done}}
