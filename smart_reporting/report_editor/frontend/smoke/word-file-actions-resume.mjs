/** Continue verification from successful receipts; server rejects all save/create/export mutations. */
import assert from 'node:assert/strict'
import {spawn,spawnSync} from 'node:child_process'
import {createHash} from 'node:crypto'
import {readFile,writeFile} from 'node:fs/promises'
import {join} from 'node:path'
import {fileURLToPath} from 'node:url'
import {setTimeout as delay} from 'node:timers/promises'
import {chromium} from 'playwright'
const frontend=fileURLToPath(new URL('../',import.meta.url)),repo=fileURLToPath(new URL('../../../../',import.meta.url))
const directory=process.env.WORD_FILE_EVIDENCE??'/tmp/word-file-actions-20261114-run2',staticRoot=process.env.WORD_FILE_BUILD??'/tmp/word-remediation-batch3-build',port=Number(process.env.WORD_FILE_PORT??4318),origin='http://127.0.0.1:'+port,sha=bytes=>createHash('sha256').update(bytes).digest('hex')
const checkpoint=JSON.parse(await readFile(join(directory,'browser-checkpoint.json'),'utf8')),info=JSON.parse(await readFile(join(directory,'server-info.json'),'utf8'))
const saved=checkpoint.receipts.find(row=>row.kind==='save').result,copied=checkpoint.receipts.find(row=>row.kind==='save-as').result
assert.equal(saved.revisionRegistered,true);assert.notEqual(saved.documentId,copied.documentId)
const server=spawn(join(repo,'.venv/bin/python'),[join(frontend,'smoke/word-file-actions-server.py'),'--directory',directory,'--static',staticRoot,'--port',String(port),'--resume'],{cwd:repo,env:{...process.env,PYTHONPATH:repo},stdio:'pipe'})
let browser,page,stage='resume-server',log='';server.stdout.on('data',data=>log+=data);server.stderr.on('data',data=>log+=data)
const errors=[],assets=new Map(),checks=[]
try{
 for(let i=0;;i++){assert.equal(server.exitCode,null,log);try{if((await fetch(origin+'/__smoke__/state')).ok)break}catch{}assert(i<180,log);await delay(250)}
 const paths=JSON.parse(await readFile(join(directory,'resume-info.json'),'utf8')).paths
 browser=await chromium.launch({headless:true});const context=await browser.newContext({viewport:{width:1450,height:1000}})
 context.on('page',p=>{p.on('pageerror',error=>errors.push(error.message));p.on('response',r=>{const path=new URL(r.url()).pathname;if(!path.startsWith('/reports/v1/editor/assets/')||!/\.(js|css)$/.test(path))return;const check=(async()=>{assert.equal(r.status(),200);const bytes=await r.body(),disk=await readFile(join(staticRoot,path.slice('/reports/v1/editor/assets/'.length)));assert.equal(sha(bytes),sha(disk));assets.set(path,sha(bytes))})();check.catch(()=>{});checks.push(check)})})
 const body=p=>p.getByRole('textbox',{name:'Word 文档编辑区',exact:true})
 async function open(id,revision){const p=await context.newPage();await p.goto(origin+paths[id+':'+revision]);await body(p).waitFor({timeout:60000});await p.waitForFunction(()=>document.querySelector('.save-state-label')?.textContent==='文档已载入');return p}
 stage='resume-copy';const copy=await open(copied.documentId,1);page=copy;assert.equal((await body(copy).textContent()).trim(),'First trusted browser edit');let response=await copy.request.get(copy.url()+'/api/context');assert.equal(response.status(),200);const current=await response.json();assert.equal(current.context.displayName,'独立烟测副本.docx');assert.equal(current.context.documentId,copied.documentId)
 stage='unicode-original-download';const link=copy.getByRole('link',{name:'下载原件',exact:true});assert.equal(await link.getAttribute('download'),'独立烟测副本.docx');response=await copy.request.get(new URL(await link.getAttribute('href'),origin).href);assert.equal(response.status(),200);assert.equal(response.headers()['content-disposition'],"attachment; filename*=UTF-8''%E7%8B%AC%E7%AB%8B%E7%83%9F%E6%B5%8B%E5%89%AF%E6%9C%AC.docx");const bytes=await response.body();assert.equal(sha(bytes),saved.artifacts.word.sha256)
 stage='dirty-save-as-block';await body(copy).locator('p').first().click();await copy.keyboard.press('End');await copy.keyboard.type(' UNSAVED');await copy.getByText('有未保存修改',{exact:true}).waitFor();await copy.getByRole('tab',{name:'文件',exact:true}).click();const forbidden=copy.locator('[data-action=file-save-as]');assert.equal(await forbidden.isDisabled(),true);assert.match(await forbidden.getAttribute('title'),/仅复制已保存.*请先保存或撤销/);await copy.screenshot({path:join(directory,'dirty-save-as-explicit-scope.png'),fullPage:true})
 stage='original-preserved';const original=await open(info.sourceDocumentId,1);response=await original.request.get(original.url()+'/api/file');assert.equal(sha(await response.body()),info.sourceSha256);const parent=await open(saved.documentId,2);response=await parent.request.get(parent.url()+'/api/file');assert.equal(sha(await response.body()),saved.artifacts.word.sha256);assert.equal((await body(parent).textContent()).trim(),'First trusted browser edit')
 const state=await(await fetch(origin+'/__smoke__/state')).json();await writeFile(join(directory,'state.json'),JSON.stringify(state,null,2));for(const [suffix,count] of [['/api/save',1],['/word/new',1],['/word/save-as',1]])assert.equal(state.requests.filter(row=>row.method==='POST'&&row.path.endsWith(suffix)).length,count);assert.equal(state.documents.length,3)
 const verified=spawnSync(join(repo,'.venv/bin/python'),['-c',`from pathlib import Path
from zipfile import ZipFile
from io import BytesIO
from docx import Document
from lxml import etree
import json,sys
root=Path(sys.argv[1]);result={}
for name in ('original.docx','blank-r1.docx','new-saved-r2.docx','independent-copy-r1.docx'):
 raw=(root/name).read_bytes()
 with ZipFile(BytesIO(raw)) as z:
  for part in z.namelist():
   if part.endswith(('.xml','.rels')):etree.fromstring(z.read(part))
 text=[p.text for p in Document(BytesIO(raw)).paragraphs];result[name]=text
 assert text==(['Original saved source must remain unchanged'] if name=='original.docx' else [''] if name=='blank-r1.docx' else ['First trusted browser edit'])
print(json.dumps(result))`,directory],{encoding:'utf8'});assert.equal(verified.status,0,verified.stderr);await writeFile(join(directory,'independent-readback.json'),verified.stdout)
 await Promise.all(checks);assert.equal(errors.length,0,errors.join('\n'));await writeFile(join(directory,'result.json'),JSON.stringify({ok:true,repository:'scoped in-memory smoke only; resumed existing successful immutable contexts with fresh grants',buildScope:JSON.parse(await readFile(join(directory,'build-scope.json'),'utf8')),successfulSaves:1,repeatedSavesDuringResume:0,receipts:checkpoint.receipts,sourceSha256:info.sourceSha256,newSavedSha256:saved.artifacts.word.sha256,copySha256:sha(bytes),dirtySaveAsBlocked:true,assets:Object.fromEntries(assets),manifestSha256:sha(await readFile(join(staticRoot,'.vite/manifest.json'))),errors},null,2));console.log(JSON.stringify({ok:true,directory,successfulSaves:1,repeatedSavesDuringResume:0,documents:3,assets:assets.size}))
}catch(error){await writeFile(join(directory,'resume-failure.json'),JSON.stringify({stage,error:String(error),stack:error.stack,log},null,2));if(page){await page.screenshot({path:join(directory,'resume-failure.png'),fullPage:true}).catch(()=>{});await writeFile(join(directory,'resume-failure.html'),await page.content()).catch(()=>{})}throw error}
finally{await browser?.close();server.kill();await writeFile(join(directory,'resume-server.log'),log)}
