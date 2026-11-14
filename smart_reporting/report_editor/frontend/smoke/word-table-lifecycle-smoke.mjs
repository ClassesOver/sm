import assert from 'node:assert/strict'
import {spawn,spawnSync} from 'node:child_process'
import {createHash} from 'node:crypto'
import {access,mkdir,readFile,readdir,stat,writeFile} from 'node:fs/promises'
import {join} from 'node:path'
import {fileURLToPath} from 'node:url'
import {setTimeout as delay} from 'node:timers/promises'
import {chromium} from 'playwright'
import {probeCanvasTextRendering} from './canvas-font-preflight.mjs'
const frontend=fileURLToPath(new URL('../',import.meta.url)),repo=fileURLToPath(new URL('../../../../',import.meta.url)),python=join(repo,'.venv/bin/python')
const directory=process.env.WORD_TABLE_LIFECYCLE_EVIDENCE??'/tmp/word-table-lifecycle-20261114',staticRoot=process.env.WORD_TABLE_LIFECYCLE_BUILD??'/tmp/word-table-lifecycle-build',port=Number(process.env.WORD_TABLE_LIFECYCLE_PORT??4387),origin=`http://127.0.0.1:${port}`,sha=b=>createHash('sha256').update(b).digest('hex'),exists=p=>access(p).then(()=>true,()=>false)
process.env.FONTCONFIG_FILE='/workspace/sm/smart_reporting/report_editor/frontend/smoke/canvas-fontconfig.conf'
await mkdir(directory,{recursive:true})
const fixture=join(directory,'fixture.docx'),names=['split-r2','delete-r3']
if(!await exists(fixture)){
 const made=spawnSync(python,['-c',`from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
import sys
d=Document();d.add_paragraph('Before KEEP')
for i in range(2):
 t=d.add_table(rows=3,cols=2)
 for r,row in enumerate(t.rows):
  for c,cell in enumerate(row.cells):cell.paragraphs[0].add_run('Cell '+str(r)+'/'+str(c)).italic=True
 for tag,value in [('tblCaption','Caption keep'),('tblDescription','Description keep')]:
  n=OxmlElement('w:'+tag);n.set(qn('w:val'),value);t._tbl.tblPr.append(n)
 d.add_paragraph('Between KEEP' if i==0 else 'After KEEP')
d.sections[0].header.paragraphs[0].text='HEADER KEEP';d.sections[0].footer.paragraphs[0].text='FOOTER KEEP';d.save(sys.argv[1])`,fixture],{encoding:'utf8'});assert.equal(made.status,0,made.stderr)
}
if(process.env.WORD_TABLE_LIFECYCLE_FIXTURE_ONLY==='1'){console.log(fixture);process.exit(0)}
assert(await exists(join(staticRoot,'.vite/manifest.json')),'Wait for the frozen production build')
async function files(root){const out=[];for(const e of await readdir(root,{withFileTypes:true})){const p=join(root,e.name);if(e.isDirectory())out.push(...await files(p));else if(e.isFile())out.push(p)}return out}
for(const name of names)if(await exists(join(directory,name+'-saved.json'))){
 const receipt=JSON.parse(await readFile(join(directory,name+'-saved.json'),'utf8')),artifact=receipt.artifacts.word
 if(!await exists(join(directory,name+'.docx')))for(const path of await files(directory)){if((await stat(path)).size!==artifact.size)continue;const bytes=await readFile(path);if(sha(bytes)===artifact.sha256){await writeFile(join(directory,name+'.docx'),bytes);break}}
 assert(await exists(join(directory,name+'.docx')),'Successful save receipt exists: recover its artifact; never submit it again');assert.equal(sha(await readFile(join(directory,name+'.docx'))),artifact.sha256)
}
const resumedSplit=await exists(join(directory,'split-r2.docx')),resumedDelete=await exists(join(directory,'delete-r3.docx'));assert(!resumedDelete||resumedSplit)
let serverCode=await readFile(join(frontend,'smoke/word-review-presets-server.py'),'utf8');const loop="        for name in ('content-r2','protected-r3'):";assert(serverCode.includes(loop));serverCode=serverCode.replace(loop,"        for name in ('split-r2','delete-r3'):\n            if not (resume_directory / (name+'-saved.json')).exists(): continue")
const serverScript=join(directory,'server.py');await writeFile(serverScript,serverCode);await writeFile(join(directory,'source.docx'),await readFile(fixture));const serverDirectory=join(directory,'server-'+Date.now())
const server=spawn(python,[serverScript,'--directory',serverDirectory,'--static',staticRoot,'--port',String(port)],{cwd:repo,env:{...process.env,PYTHONPATH:repo,WORD_PRESETS_REOPEN_FILE:fixture,...(resumedSplit?{WORD_FAMILIES_RESUME_DIRECTORY:directory}:{})},stdio:'pipe'})
let log='',browser,page,stage='server';server.stdout.on('data',d=>log+=d);server.stderr.on('data',d=>log+=d)
const errors=[],checks=[],assets=new Map(),saves=[]
const body=()=>page.getByRole('textbox',{name:'Word 文档编辑区',exact:true}),tables=()=>body().locator('table'),pm=()=>body().evaluate(el=>el.editor.getJSON()),drafts=()=>page.evaluate(()=>Object.fromEntries(Object.keys(localStorage).filter(k=>k.startsWith('native-editor-draft:')).map(k=>[k,JSON.parse(localStorage.getItem(k))])))
async function pending(name,kind){await page.waitForFunction(kind=>Object.keys(localStorage).some(k=>k.startsWith('native-editor-draft:')&&JSON.parse(localStorage.getItem(k)).operations?.some(op=>op.kind===kind)),kind,{timeout:12000});const data=await drafts();await writeFile(join(directory,name+'-pending.json'),JSON.stringify(data,null,2));const ops=Object.values(data).flatMap(d=>d.operations??[]);assert.equal(ops.length,1,JSON.stringify(ops));assert.equal(ops[0].kind,kind);assert.deepEqual((await pm()).attrs.nativeDocxOperations,ops);return ops[0]}
async function save(name,kind,revision){const wait=page.waitForResponse(r=>r.request().method()==='POST'&&r.url().endsWith('/save'));await page.locator('[data-action=save]').click();const response=await wait,request=response.request().postDataJSON(),receipt=await response.json();await writeFile(join(directory,name+'-save-request.json'),JSON.stringify(request,null,2));assert.equal(response.status(),200,JSON.stringify(receipt));await writeFile(join(directory,name+'-saved.json'),JSON.stringify(receipt,null,2));assert.equal(request.operations.length,1);assert.equal(request.operations[0].kind,kind);assert.equal(receipt.revision,revision);assert.equal(receipt.revisionRegistered,true);const download=await page.request.get(receipt.artifacts.word.downloadUrl);assert.equal(download.status(),200);const bytes=await download.body();assert.equal(bytes.length,receipt.artifacts.word.size);assert.equal(sha(bytes),receipt.artifacts.word.sha256);await writeFile(join(directory,name+'.docx'),bytes);saves.push({name,revision,sha256:sha(bytes),validation:receipt.validation});await page.goto(receipt.editor.openUrl);await body().waitFor({timeout:60000});await body().getByText('After KEEP',{exact:true}).waitFor()}
try{
 for(let i=0;;i++){assert.equal(server.exitCode,null,log);try{if(await exists(join(serverDirectory,'server-info.json'))&&(await fetch(origin+'/__smoke__/state')).ok)break}catch{}assert(i<180,log);await delay(250)}
 const info=JSON.parse(await readFile(join(serverDirectory,'server-info.json'),'utf8'));browser=await chromium.launch({headless:true});const probe=await probeCanvasTextRendering(browser);await writeFile(join(directory,'font-preflight.json'),JSON.stringify(probe,null,2));assert(probe.ok,JSON.stringify(probe));page=await browser.newPage({viewport:{width:1500,height:1100}});page.on('pageerror',e=>errors.push(e.message));page.on('response',r=>{const path=new URL(r.url()).pathname;if(!path.startsWith('/reports/v1/editor/assets/')||!/\.(js|css)$/.test(path))return;const check=(async()=>{if(r.status()===304){assert(assets.has(path),'304 requires a previously verified 200');return}assert.equal(r.status(),200);const bytes=await r.body(),disk=await readFile(join(staticRoot,path.slice('/reports/v1/editor/assets/'.length)));assert.equal(sha(bytes),sha(disk));assets.set(path,sha(bytes))})();check.catch(()=>{});checks.push(check)})
 stage='open';await page.goto(origin+info.openPath);await body().waitFor({timeout:60000});await body().getByText('After KEEP',{exact:true}).waitFor()
 if(!resumedSplit){
  stage='pending-comment-lock';const clean=await pm();await body().getByText('Before KEEP',{exact:true}).click();await page.keyboard.press('Home');await page.keyboard.press('Shift+End');await page.locator('[data-tab-id=review]').click();await page.locator('[data-action=comment-create]').click();const input=page.locator('[data-new-comment-text]');await input.waitFor({state:'visible'});const typed='Unsubmitted comment KEEP';await input.fill(typed);await tables().nth(1).locator('tr').nth(1).locator('td').first().click();await page.locator('[data-tab-id=tableLayout]').click();for(const action of ['table-delete','table-split-table']){const button=page.locator('[data-action='+action+']');assert(await button.isDisabled());assert.match(await button.getAttribute('title'),/完成或取消批注输入/)}assert.equal(await input.inputValue(),typed);assert.deepEqual(await pm(),clean);assert.equal(Object.values(await drafts()).flatMap(d=>d.operations??[]).length,0);await page.screenshot({path:join(directory,'pending-comment-lock.png'),fullPage:true});await writeFile(join(directory,'pending-comment-lock.json'),JSON.stringify({ok:true,inputPreserved:typed,deleteDisabled:true,splitDisabled:true,nativeDraftOperations:[]},null,2));await page.locator('[data-new-comment-cancel]').click();assert.equal(await input.inputValue(),'');assert.deepEqual(await pm(),clean);assert.equal(Object.values(await drafts()).flatMap(d=>d.operations??[]).length,0)
  stage='split-first-row-disabled';assert.equal(await tables().count(),2);const anchors=info.model.blocks.filter(b=>b.type==='table');assert.equal(anchors.length,2);assert.equal(anchors[0].expectedObjectSha256,anchors[1].expectedObjectSha256);assert(anchors.every(a=>a.tableLifecycleEditable===true));await tables().nth(1).locator('tr').nth(0).locator('td').first().click();await page.locator('[data-tab-id=tableLayout]').click();const split=page.locator('[data-action=table-split-table]');assert(await split.isDisabled());assert.match(await split.getAttribute('title'),/第一行|首行/)
  stage='split-ui';await tables().nth(1).locator('tr').nth(1).locator('td').first().click();assert(await split.isEnabled());const before=await pm();await split.click();const op=await pending('split-r2','splitTable');assert.deepEqual(op,{kind:'splitTable',blockId:anchors[1].blockId,expectedObjectSha256:anchors[1].expectedObjectSha256,row:1});assert.equal(await tables().count(),3);const after=await pm(),parts=after.content;await writeFile(join(directory,'split-after-pm.json'),JSON.stringify(after,null,2));const ti=parts.map((n,i)=>n.type==='docTable'?i:-1).filter(i=>i>=0);assert.equal(parts[ti[1]].content.length,1);assert.equal(parts[ti[1]+1].type,'docParagraph');assert(!parts[ti[1]+1].content?.length);assert.equal(parts[ti[2]].content.length,2);assert.equal(parts[ti[2]].attrs.docxIndex,null);assert.equal(parts[ti[2]].attrs.tblCaption,null);assert.equal(parts[ti[2]].attrs.tblDescription,null)
  stage='split-undo-redo';await body().focus();await page.keyboard.press('Control+z');assert.deepEqual(await pm(),before);await page.waitForTimeout(300);assert.equal(Object.values(await drafts()).flatMap(d=>d.operations??[]).length,0);await page.keyboard.press('Control+y');assert.deepEqual(await pm(),after);assert.deepEqual(await pending('split-redo','splitTable'),op);await page.screenshot({path:join(directory,'split-pending.png'),fullPage:true});stage='save-split';await save('split-r2','splitTable',2)
 }
 if(!resumedDelete){
  stage='delete-context';assert.equal(await tables().count(),3);assert.equal(await tables().nth(1).locator('tr').count(),1);assert.equal(await tables().nth(2).locator('tr').count(),2);await tables().nth(2).locator('td').first().click({button:'right'});const menu=page.getByRole('menu',{name:'Word 文档菜单',exact:true});await menu.waitFor();const command=menu.locator('[data-context-action=deleteTable]');assert(await command.isEnabled());await command.click();const op=await pending('delete-r3','deleteTable');assert.equal(op.blockId,sha(JSON.parse(await readFile(join(directory,'split-r2-saved.json'),'utf8')).artifacts.word.sha256+':block:5'));assert.equal(await tables().count(),2);await page.screenshot({path:join(directory,'delete-pending.png'),fullPage:true});stage='save-delete';await save('delete-r3','deleteTable',3)
 }
 stage='reopened-delete';assert.equal(await tables().count(),2);assert.equal(await tables().nth(0).locator('tr').count(),3);assert.equal(await tables().nth(1).locator('tr').count(),1);await page.screenshot({path:join(directory,'delete-reopened.png'),fullPage:true})
 stage='independent';const verify=spawnSync(python,['-c',`import json,sys
from copy import deepcopy
from zipfile import ZipFile
from lxml import etree as E
from docx import Document
p=sys.argv[1];ns={'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main'};W='{'+ns['w']+'}';xml=lambda n:E.tostring(n)
with ZipFile(p+'/fixture.docx') as a,ZipFile(p+'/split-r2.docx') as b,ZipFile(p+'/delete-r3.docx') as c:
 assert set(a.namelist())==set(b.namelist())==set(c.namelist())
 for name in a.namelist():
  if name!='word/document.xml':assert a.read(name)==b.read(name)==c.read(name),name
 roots=[E.fromstring(z.read('word/document.xml')) for z in [a,b,c]];bodies=[r.find('w:body',ns) for r in roots];ts=[r.findall('./w:body/w:tbl',ns) for r in roots];assert [len(t) for t in ts]==[2,3,2];assert xml(ts[0][0])==xml(ts[0][1]);assert xml(ts[0][0])==xml(ts[1][0])==xml(ts[2][0]);assert xml(ts[1][1])==xml(ts[2][1])
 rows=ts[0][1].findall('w:tr',ns);assert [xml(r) for r in ts[1][1].findall('w:tr',ns)]==[xml(rows[0])];assert [xml(r) for r in ts[1][2].findall('w:tr',ns)]==[xml(r) for r in rows[1:]]
 for tag in ['tblPr','tblGrid']:assert xml(ts[0][1].find('w:'+tag,ns))==xml(ts[1][1].find('w:'+tag,ns))
 lower=deepcopy(ts[0][1].find('w:tblPr',ns))
 for tag in ['tblCaption','tblDescription']:
  node=lower.find('w:'+tag,ns);lower.remove(node);assert ts[1][2].find('./w:tblPr/w:'+tag,ns) is None
 assert xml(lower)==xml(deepcopy(ts[1][2].find('w:tblPr',ns)));assert xml(ts[0][1].find('w:tblGrid',ns))==xml(ts[1][2].find('w:tblGrid',ns))
 expected=deepcopy(bodies[0]);original=expected.findall('w:tbl',ns)[1];at=list(expected).index(original);expected.remove(original)
 for offset,node in enumerate([ts[1][1],E.Element(W+'p'),ts[1][2]]):expected.insert(at+offset,deepcopy(node))
 assert xml(expected)==xml(deepcopy(bodies[1])),'split must preserve every unrelated body node';expected.remove(expected.findall('w:tbl',ns)[2]);assert xml(expected)==xml(deepcopy(bodies[2])),'delete must remove the exact lower table only'
 for file,counts in [('fixture.docx',[3,3]),('split-r2.docx',[3,1,2]),('delete-r3.docx',[3,1])]:
  d=Document(p+'/'+file);assert [len(t.rows) for t in d.tables]==counts;assert all(len(t.columns)==2 for t in d.tables);assert all(run.italic for t in d.tables for row in t.rows for cell in row.cells for para in cell.paragraphs for run in para.runs);assert d.sections[0].header.paragraphs[0].text=='HEADER KEEP';assert d.sections[0].footer.paragraphs[0].text=='FOOTER KEEP'
 print(json.dumps({'exactRowsCellParagraphRunXML':True,'tablePropertiesWidthsAndStylePreserved':True,'lowerAltTextCleared':True,'identicalUnaffectedTablePreserved':True,'nonTargetPartsAndHeaderFooterPreserved':True,'packageIdentityPreserved':True}))`,directory],{encoding:'utf8'});await writeFile(join(directory,'independent.json'),verify.stdout);await writeFile(join(directory,'independent-stderr.txt'),verify.stderr);assert.equal(verify.status,0,verify.stderr)
 const state=await(await fetch(origin+'/__smoke__/state')).json();await writeFile(join(directory,'http-final-'+Date.now()+'.json'),JSON.stringify(state,null,2));assert.equal(state.requests.filter(r=>r.method==='POST'&&r.path.endsWith('/save')).length,saves.length);await Promise.all(checks);assert.deepEqual(errors,[]);await writeFile(join(directory,'result.json'),JSON.stringify({ok:true,scope:'Real FastAPI/native publication with scoped in-memory repositories; no production database',savesThisRun:saves,resumedSplit,resumedDelete,completedArtifacts:await Promise.all(names.map(async name=>({name,receipt:JSON.parse(await readFile(join(directory,name+'-saved.json'),'utf8')),sha256:sha(await readFile(join(directory,name+'.docx')))}))),assets:Object.fromEntries(assets),manifestSha256:sha(await readFile(join(staticRoot,'.vite/manifest.json'))),errors},null,2));console.log(JSON.stringify({ok:true,directory,saves:saves.length,assets:assets.size}))
}catch(error){await writeFile(join(directory,'failure-'+Date.now()+'.json'),JSON.stringify({stage,error:String(error),stack:error.stack,log,errors},null,2));if(page){await writeFile(join(directory,'failure-dom.html'),await page.content()).catch(()=>{});await writeFile(join(directory,'failure-drafts.json'),JSON.stringify(await drafts(),null,2)).catch(()=>{});await writeFile(join(directory,'failure-pm.json'),JSON.stringify(await pm(),null,2)).catch(()=>{});await page.screenshot({path:join(directory,'failure.png'),fullPage:true}).catch(()=>{})}throw error}
finally{await Promise.allSettled(checks);await writeFile(join(directory,'asset-evidence-'+Date.now()+'.json'),JSON.stringify({assets:Object.fromEntries(assets),manifestSha256:sha(await readFile(join(staticRoot,'.vite/manifest.json')))},null,2));await browser?.close();server.kill();await writeFile(join(directory,'server-'+Date.now()+'.log'),log)}
