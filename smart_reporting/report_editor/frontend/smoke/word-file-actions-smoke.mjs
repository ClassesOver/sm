import assert from 'node:assert/strict'
import {spawn,spawnSync} from 'node:child_process'
import {createHash} from 'node:crypto'
import {mkdir,readFile,readdir,writeFile} from 'node:fs/promises'
import {join} from 'node:path'
import {fileURLToPath} from 'node:url'
import {setTimeout as delay} from 'node:timers/promises'
import {chromium} from 'playwright'
import {probeCanvasTextRendering} from './canvas-font-preflight.mjs'
const frontend=fileURLToPath(new URL('../',import.meta.url)),repo=fileURLToPath(new URL('../../../../',import.meta.url))
const directory=process.env.WORD_FILE_EVIDENCE??'/tmp/word-file-actions-20261114',staticRoot=process.env.WORD_FILE_BUILD??'/tmp/word-remediation-batch3-build'
const port=Number(process.env.WORD_FILE_PORT??4318),origin='http://127.0.0.1:'+port,sha=bytes=>createHash('sha256').update(bytes).digest('hex')
assert(process.env.FONTCONFIG_FILE?.startsWith('/'),'Use absolute FONTCONFIG_FILE for browser evidence')
await mkdir(directory,{recursive:true});assert(!(await readdir(directory)).some(name=>name.startsWith('saved-')&&name.endsWith('.json')),'Existing successful save receipts preserved; do not repeat saves. Resume review from recorded receipt instead.')
const server=spawn(join(repo,'.venv/bin/python'),[join(frontend,'smoke/word-file-actions-server.py'),'--directory',directory,'--static',staticRoot,'--port',String(port)],{cwd:repo,env:{...process.env,PYTHONPATH:repo},stdio:'pipe'})
let log='',browser,page,stage='server';server.stdout.on('data',data=>{log+=data});server.stderr.on('data',data=>{log+=data})
const errors=[],assets=new Map(),assetChecks=[],contexts=[],receipts=[]
const checkpoint=async()=>await writeFile(join(directory,'browser-checkpoint.json'),JSON.stringify({stage,receipts,contexts,errors},null,2))
try{
 for(let i=0;;i++){assert.equal(server.exitCode,null,log);try{if((await fetch(origin+'/__smoke__/state')).ok)break}catch{}assert(i<180,log);await delay(250)}
 const info=JSON.parse(await readFile(join(directory,'server-info.json'),'utf8'))
 browser=await chromium.launch({headless:true});const probe=await probeCanvasTextRendering(browser);await writeFile(join(directory,'font-preflight.json'),JSON.stringify(probe,null,2));assert(probe.ok)
 const context=await browser.newContext({viewport:{width:1450,height:1000},acceptDownloads:true})
 context.on('page',p=>{p.on('pageerror',error=>errors.push(error.message));p.on('response',response=>{const path=new URL(response.url()).pathname;if(!path.startsWith('/reports/v1/editor/assets/')||!/\.(js|css)$/.test(path))return;const check=(async()=>{if(response.status()===304){assert(assets.has(path));return}assert.equal(response.status(),200);const bytes=await response.body(),disk=await readFile(join(staticRoot,path.slice('/reports/v1/editor/assets/'.length)));assert.equal(sha(bytes),sha(disk));assets.set(path,sha(bytes))})();check.catch(()=>{});assetChecks.push(check)})})
 const body=p=>p.getByRole('textbox',{name:'Word 文档编辑区',exact:true}),tab=(p,label)=>p.getByRole('tab',{name:label,exact:true})
 async function ready(p){await body(p).waitFor({timeout:60000});await p.waitForFunction(()=>document.querySelector('.save-state-label')?.textContent==='文档已载入',{timeout:60000})}
 async function readContext(p){const url=p.url().replace(/\/$/,'')+'/api/context',response=await p.request.get(url);assert.equal(response.status(),200);const data=await response.json();contexts.push(data.context);await checkpoint();return data}
 async function fileBytes(p){const response=await p.request.get(p.url().replace(/\/$/,'')+'/api/file');assert.equal(response.status(),200);return await response.body()}
 page=await context.newPage();stage='open-source';await page.goto(origin+info.openPath);await ready(page);const originalContext=await readContext(page);assert.equal(originalContext.context.documentId,info.sourceDocumentId);assert.equal(sha(await fileBytes(page)),info.sourceSha256)
 stage='new';await tab(page,'文件').click();await page.locator('[data-action=file-new]').click();let dialog=page.getByRole('dialog',{name:'新建 Word 文档',exact:true});await dialog.getByRole('textbox',{name:'文件名'}).fill('Smoke New.docx')
 const newResponseWait=page.waitForResponse(r=>r.request().method()==='POST'&&r.url().endsWith('/word/new'));await dialog.getByRole('button',{name:'新建',exact:true}).click();const newResponse=await newResponseWait;assert.equal(newResponse.status(),200,await newResponse.text());const created=await newResponse.json();receipts.push({kind:'new',result:created});await checkpoint();assert.notEqual(created.documentId,info.sourceDocumentId)
 const createdPageWait=context.waitForEvent('page');await dialog.getByRole('link',{name:'打开新文档'}).click();const blank=await createdPageWait;page=blank;await ready(blank);let blankContext=await readContext(blank);assert.equal(blankContext.context.documentId,created.documentId);assert.equal(blankContext.context.displayName,'Smoke New.docx');assert.equal((await body(blank).textContent()).trim(),'');const blankSource=await fileBytes(blank);await writeFile(join(directory,'blank-r1.docx'),blankSource)
 stage='type-first-paragraph';await body(blank).locator('p').first().click();await blank.keyboard.type('First trusted browser edit');await blank.getByText('有未保存修改',{exact:true}).waitFor();assert.equal((await body(blank).textContent()).trim(),'First trusted browser edit')
 stage='save-first-edit';const [saveResponse]=await Promise.all([blank.waitForResponse(r=>r.request().method()==='POST'&&r.url().endsWith('/api/save')),blank.locator('.report-actions [data-action=save]').click()]);assert.equal(saveResponse.status(),200,await saveResponse.text());const saved=await saveResponse.json();receipts.push({kind:'save',result:saved});await checkpoint();assert.equal(saved.revisionRegistered,true);assert.equal(saved.documentId,created.documentId);assert.equal(saved.revision,2)
 stage='download-saved';const downloadLink=blank.getByRole('link',{name:'下载 Word',exact:true});await downloadLink.waitFor();const response=await blank.request.get(await downloadLink.getAttribute('href'));assert.equal(response.status(),200);const savedBytes=await response.body();assert.equal(sha(savedBytes),saved.artifacts.word.sha256);assert.equal(response.headers()['content-disposition'],"attachment; filename*=UTF-8''Smoke%20New.docx");await writeFile(join(directory,'new-saved-r2.docx'),savedBytes)
 stage='reopen-saved';await blank.getByRole('link',{name:'打开新修订继续编辑',exact:true}).click();await ready(blank);blankContext=await readContext(blank);assert.equal(blankContext.context.revision,2);assert.equal(blankContext.context.displayName,'Smoke New.docx');assert.equal((await body(blank).textContent()).trim(),'First trusted browser edit')
 stage='save-as';await tab(blank,'文件').click();await blank.locator('[data-action=file-save-as]').click();dialog=blank.getByRole('dialog',{name:'另存为 Word 文档',exact:true});await dialog.getByRole('textbox',{name:'文件名'}).fill('独立烟测副本.docx');const copyWait=blank.waitForResponse(r=>r.request().method()==='POST'&&r.url().endsWith('/word/save-as'));await dialog.getByRole('button',{name:'另存为',exact:true}).click();const copyResponse=await copyWait;assert.equal(copyResponse.status(),200,await copyResponse.text());const copied=await copyResponse.json();receipts.push({kind:'save-as',result:copied});await checkpoint();assert.notEqual(copied.documentId,saved.documentId);assert.notEqual(copied.documentId,info.sourceDocumentId)
 const copyPageWait=context.waitForEvent('page');await dialog.getByRole('link',{name:'打开新文档'}).click();const copy=await copyPageWait;page=copy;await ready(copy);const copyContext=await readContext(copy);assert.equal(copyContext.context.documentId,copied.documentId);assert.equal(copyContext.context.revision,1);assert.equal(copyContext.context.displayName,'独立烟测副本.docx');const copyBytes=await fileBytes(copy);assert.equal(sha(copyBytes),sha(savedBytes));await writeFile(join(directory,'independent-copy-r1.docx'),copyBytes)
 stage='copy-original-download-name';const originalCopy=copy.getByRole('link',{name:'下载原件',exact:true});assert.equal(await originalCopy.getAttribute('download'),'独立烟测副本.docx');const copyFileResponse=await copy.request.get(new URL(await originalCopy.getAttribute('href'),origin).href);assert.equal(copyFileResponse.headers()['content-disposition'],"attachment; filename*=UTF-8''%E7%8B%AC%E7%AB%8B%E7%83%9F%E6%B5%8B%E5%89%AF%E6%9C%AC.docx")
 stage='dirty-save-as-block';await body(copy).locator('p').first().click();await copy.keyboard.press('End');await copy.keyboard.type(' UNSAVED');await copy.getByText('有未保存修改',{exact:true}).waitFor();await tab(copy,'文件').click();const forbidden=copy.locator('[data-action=file-save-as]');assert.equal(await forbidden.isDisabled(),true);assert.match(await forbidden.getAttribute('title'),/仅复制已保存.*请先保存或撤销/);await copy.screenshot({path:join(directory,'dirty-save-as-explicit-scope.png'),fullPage:true})
 stage='original-preserved';assert.equal(sha(await fileBytes(blank)),sha(savedBytes));const firstPage=context.pages()[0];assert.equal(sha(await fileBytes(firstPage)),info.sourceSha256);const state=await(await fetch(origin+'/__smoke__/state')).json();await writeFile(join(directory,'state.json'),JSON.stringify(state,null,2));assert.equal(state.requests.filter(r=>r.path.endsWith('/api/save')).length,1);assert.equal(state.requests.filter(r=>r.path.endsWith('/word/new')).length,1);assert.equal(state.requests.filter(r=>r.path.endsWith('/word/save-as')).length,1);assert.equal(state.documents.length,3)
 const independent=spawnSync(join(repo,'.venv/bin/python'),['-c',`from pathlib import Path
from io import BytesIO
from zipfile import ZipFile
from docx import Document
from lxml import etree
import sys,json
root=Path(sys.argv[1]);result={}
for name in ('original.docx','blank-r1.docx','new-saved-r2.docx','independent-copy-r1.docx'):
 raw=(root/name).read_bytes()
 with ZipFile(BytesIO(raw)) as z:
  for part in z.namelist():
   if part.endswith(('.xml','.rels')):etree.fromstring(z.read(part))
 texts=[p.text for p in Document(BytesIO(raw)).paragraphs];result[name]=texts
 assert texts==(['Original saved source must remain unchanged'] if name=='original.docx' else [''] if name=='blank-r1.docx' else ['First trusted browser edit'])
print(json.dumps(result))`,directory],{encoding:'utf8'});assert.equal(independent.status,0,independent.stderr);await writeFile(join(directory,'independent-readback.json'),independent.stdout)
 await Promise.all(assetChecks);assert.equal(errors.length,0,errors.join('\n'));stage='complete';await checkpoint();await writeFile(join(directory,'result.json'),JSON.stringify({ok:true,repository:'in-memory smoke only',successfulSaves:1,receipts,sourceSha256:info.sourceSha256,newSavedSha256:sha(savedBytes),copySha256:sha(copyBytes),dirtySaveAsBlocked:true,assets:Object.fromEntries(assets),manifestSha256:sha(await readFile(join(staticRoot,'.vite/manifest.json'))),errors},null,2));console.log(JSON.stringify({ok:true,directory,successfulSaves:1,documents:3,assets:assets.size}))
}catch(error){await checkpoint();await writeFile(join(directory,'failure.json'),JSON.stringify({stage,error:String(error),stack:error.stack,log},null,2));if(page){await page.screenshot({path:join(directory,'failure.png'),fullPage:true}).catch(()=>{});await writeFile(join(directory,'failure.html'),await page.content()).catch(()=>{})}throw error}
finally{await browser?.close();server.kill();await writeFile(join(directory,'server.log'),log)}
