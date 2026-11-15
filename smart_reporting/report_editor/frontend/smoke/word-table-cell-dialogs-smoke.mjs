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
const directory=process.env.WORD_TABLE_CELLS_EVIDENCE??'/tmp/word-table-cells-20261114',staticRoot=process.env.WORD_TABLE_CELLS_BUILD??'/tmp/word-table-cells-build',port=Number(process.env.WORD_TABLE_CELLS_PORT??4397),origin=`http://127.0.0.1:${port}`,sha=b=>createHash('sha256').update(b).digest('hex'),exists=p=>access(p).then(()=>true,()=>false)
process.env.FONTCONFIG_FILE='/workspace/sm/smart_reporting/report_editor/frontend/smoke/canvas-fontconfig.conf'
await mkdir(directory,{recursive:true})
const fixture=join(directory,'fixture.docx'),names=['insert-r2','up-r3','left-r4']
if(!await exists(fixture)){
 const made=spawnSync(python,['-c',`from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
import sys
d=Document();d.add_paragraph('Before KEEP')
for i in range(2):
 t=d.add_table(rows=3,cols=3);t.autofit=False
 widths=[1600,2400,3200]
 for c,node in enumerate(t._tbl.tblGrid):node.set(qn('w:w'),str(widths[c]))
 tw=t._tbl.tblPr.find(qn('w:tblW'));tw.set(qn('w:type'),'dxa');tw.set(qn('w:w'),'7200')
 for r,row in enumerate(t.rows):
  for c,cell in enumerate(row.cells):
   cell.paragraphs[0].add_run(str(r)+'/'+str(c)).italic=True
   pp=cell.paragraphs[0]._p.get_or_add_pPr();align=OxmlElement('w:jc');align.set(qn('w:val'),'center');pp.append(align)
   cell._tc.get_or_add_tcPr().find(qn('w:tcW')).set(qn('w:w'),str(widths[c]))
   sh=OxmlElement('w:shd');sh.set(qn('w:fill'),['DDEEFF','FFEEDD','DDFFEE'][c]);cell._tc.get_or_add_tcPr().append(sh)
 for tag,value in [('tblCaption','Caption keep'),('tblDescription','Description keep')]:
  n=OxmlElement('w:'+tag);n.set(qn('w:val'),value);t._tbl.tblPr.append(n)
 d.add_paragraph('Between KEEP' if i==0 else 'After KEEP')
d.sections[0].header.paragraphs[0].text='HEADER KEEP';d.sections[0].footer.paragraphs[0].text='FOOTER KEEP';d.save(sys.argv[1])`,fixture],{encoding:'utf8'});assert.equal(made.status,0,made.stderr)
}
if(process.env.WORD_TABLE_CELLS_FIXTURE_ONLY==='1'){console.log(fixture);process.exit(0)}
assert(await exists(join(staticRoot,'.vite/manifest.json')),'Wait for the frozen production build')
async function files(root){const out=[];for(const e of await readdir(root,{withFileTypes:true})){const p=join(root,e.name);if(e.isDirectory())out.push(...await files(p));else if(e.isFile())out.push(p)}return out}
for(const name of names)if(await exists(join(directory,name+'-saved.json'))){
 const receipt=JSON.parse(await readFile(join(directory,name+'-saved.json'),'utf8')),artifact=receipt.artifacts.word
 if(!await exists(join(directory,name+'.docx')))for(const path of await files(directory)){if((await stat(path)).size!==artifact.size)continue;const bytes=await readFile(path);if(sha(bytes)===artifact.sha256){await writeFile(join(directory,name+'.docx'),bytes);break}}
 assert(await exists(join(directory,name+'.docx')),'Successful save receipt exists: recover its artifact; never submit it again');assert.equal(sha(await readFile(join(directory,name+'.docx'))),artifact.sha256)
}
const completed=[];for(const name of names)completed.push(await exists(join(directory,name+'.docx')));assert(completed.every((v,i)=>!v||completed.slice(0,i).every(Boolean)))
let serverCode=await readFile(join(frontend,'smoke/word-review-presets-server.py'),'utf8');const loop="        for name in ('content-r2','protected-r3'):";assert(serverCode.includes(loop));serverCode=serverCode.replace(loop,"        for name in ('insert-r2','up-r3','left-r4'):\n            if not (resume_directory / (name+'-saved.json')).exists(): continue")
const serverScript=join(directory,'server.py');await writeFile(serverScript,serverCode);await writeFile(join(directory,'source.docx'),await readFile(fixture));const serverDirectory=join(directory,'server-'+Date.now())
const server=spawn(python,[serverScript,'--directory',serverDirectory,'--static',staticRoot,'--port',String(port)],{cwd:repo,env:{...process.env,PYTHONPATH:repo,WORD_PRESETS_REOPEN_FILE:fixture,...(completed[0]?{WORD_FAMILIES_RESUME_DIRECTORY:directory}:{})},stdio:'pipe'})
let log='',browser,page,stage='server';server.stdout.on('data',d=>log+=d);server.stderr.on('data',d=>log+=d)
const errors=[],checks=[],assets=new Map(),saves=[]
const body=()=>page.getByRole('textbox',{name:'Word 文档编辑区',exact:true}),tables=()=>body().locator('table'),pm=()=>body().evaluate(el=>el.editor.getJSON()),drafts=()=>page.evaluate(()=>Object.fromEntries(Object.keys(localStorage).filter(k=>k.startsWith('native-editor-draft:')).map(k=>[k,JSON.parse(localStorage.getItem(k))])))
async function pending(name,kind){await page.waitForFunction(kind=>Object.keys(localStorage).some(k=>k.startsWith('native-editor-draft:')&&JSON.parse(localStorage.getItem(k)).operations?.some(op=>op.kind===kind)),kind,{timeout:12000});const data=await drafts();await writeFile(join(directory,name+'-pending.json'),JSON.stringify(data,null,2));const ops=Object.values(data).flatMap(d=>d.operations??[]);assert.equal(ops.length,1,JSON.stringify(ops));assert.equal(ops[0].kind,kind);assert.deepEqual((await pm()).attrs.nativeDocxOperations,ops);return ops[0]}
async function save(name,kind,revision){const wait=page.waitForResponse(r=>r.request().method()==='POST'&&r.url().endsWith('/save'));wait.catch(()=>{});await page.locator('[data-action=save]').click();const response=await wait,request=response.request().postDataJSON(),receipt=await response.json();await writeFile(join(directory,name+'-save-request.json'),JSON.stringify(request,null,2));assert.equal(response.status(),200,JSON.stringify(receipt));await writeFile(join(directory,name+'-saved.json'),JSON.stringify(receipt,null,2));assert.equal(request.operations.length,1);assert.equal(request.operations[0].kind,kind);assert.equal(receipt.revision,revision);assert.equal(receipt.revisionRegistered,true);const download=await page.request.get(receipt.artifacts.word.downloadUrl);assert.equal(download.status(),200);const bytes=await download.body();assert.equal(bytes.length,receipt.artifacts.word.size);assert.equal(sha(bytes),receipt.artifacts.word.sha256);await writeFile(join(directory,name+'.docx'),bytes);saves.push({name,revision,sha256:sha(bytes),validation:receipt.validation});await page.goto(receipt.editor.openUrl);await body().waitFor({timeout:60000});await body().getByText('After KEEP',{exact:true}).waitFor()}
try{
 for(let i=0;;i++){assert.equal(server.exitCode,null,log);try{if(await exists(join(serverDirectory,'server-info.json'))&&(await fetch(origin+'/__smoke__/state')).ok)break}catch{}assert(i<180,log);await delay(250)}
 const info=JSON.parse(await readFile(join(serverDirectory,'server-info.json'),'utf8'));browser=await chromium.launch({headless:true});const probe=await probeCanvasTextRendering(browser);await writeFile(join(directory,'font-preflight.json'),JSON.stringify(probe,null,2));assert(probe.ok,JSON.stringify(probe));page=await browser.newPage({viewport:{width:1500,height:1100}});page.on('pageerror',e=>errors.push(e.message));page.on('response',r=>{const path=new URL(r.url()).pathname;if(!path.startsWith('/reports/v1/editor/assets/')||!/\.(js|css)$/.test(path))return;const check=(async()=>{if(r.status()===304){assert(assets.has(path),'304 requires a previously verified 200');return}assert.equal(r.status(),200);const bytes=await r.body(),disk=await readFile(join(staticRoot,path.slice('/reports/v1/editor/assets/'.length)));assert.equal(sha(bytes),sha(disk));assets.set(path,sha(bytes))})();check.catch(()=>{});checks.push(check)})
 stage='open';await page.goto(origin+info.openPath);await body().waitFor({timeout:60000});await body().getByText('After KEEP',{exact:true}).waitFor()
 const select=async(row,col)=>{await tables().nth(1).locator('tr').nth(row).locator('td,th').nth(col).locator('p').first().click();await page.locator('[data-tab-id=tableLayout]').click()}
 const dialog=label=>page.getByRole('dialog',{name:label,exact:true})
 const noOps=async()=>assert.equal(Object.values(await drafts()).flatMap(d=>d.operations??[]).length,0)
 const submit=async(label,mode,count)=>{const d=dialog(label);await d.locator('input[name=table-cells-mode][value='+mode+']').check();if(count!==undefined)await d.getByRole('spinbutton',{name:'数量',exact:true}).fill(String(count));await d.getByRole('button',{name:'确定',exact:true}).click()}
 if(!completed[0]){
  stage='pending-comment-lock';const clean=await pm();await body().getByText('Before KEEP',{exact:true}).click();await page.keyboard.press('Home');await page.keyboard.press('Shift+End');await page.locator('[data-tab-id=review]').click();await page.locator('[data-action=comment-create]').click();const input=page.locator('[data-new-comment-text]');await input.waitFor({state:'visible'});await input.fill('Unsubmitted comment KEEP');await select(0,1);for(const action of ['table-insert-cells','table-delete-cells']){const button=page.locator('[data-action='+action+']');assert(await button.isDisabled());assert.match(await button.getAttribute('title'),/完成或取消批注输入/)}assert.equal(await input.inputValue(),'Unsubmitted comment KEEP');assert.deepEqual(await pm(),clean);await noOps();await page.locator('[data-new-comment-cancel]').click()
  stage='cancel-invalid-budget';await select(0,1);const before=await pm();await page.locator('[data-action=table-insert-cells]').click();assert.equal(await dialog('插入单元格').getByRole('spinbutton',{name:'数量',exact:true}).inputValue(),'1');await submit('插入单元格','right',0);assert.match(await dialog('插入单元格').getByRole('alert').innerText(),/数量/);assert.equal(await dialog('插入单元格').getByRole('spinbutton',{name:'数量',exact:true}).inputValue(),'0');assert.deepEqual(await pm(),before);await noOps();await submit('插入单元格','below',100);assert((await dialog('插入单元格').getByRole('alert').innerText()).length>0);assert.deepEqual(await pm(),before);await noOps();await dialog('插入单元格').getByRole('button',{name:'取消',exact:true}).click();assert.deepEqual(await pm(),before)
  stage='stale-modal';await tables().nth(1).locator('tr').nth(0).locator('td,th').nth(1).click({button:'right'});const menu=page.getByRole('menu',{name:'Word 文档菜单',exact:true});await menu.locator('[data-context-action=insertCells]').click();await dialog('插入单元格').waitFor();await body().evaluate(el=>{const editor=el.editor;editor.commands.setTextSelection(1)});await page.waitForTimeout(200);assert(await dialog('插入单元格').getByRole('button',{name:'确定',exact:true}).isDisabled());assert((await dialog('插入单元格').getByRole('alert').innerText()).length>0);assert.deepEqual(await pm(),before);await noOps();await dialog('插入单元格').getByRole('button',{name:'取消',exact:true}).click()
  const state=await(await fetch(origin+'/__smoke__/state')).json();assert.equal(state.requests.filter(r=>r.method==='POST'&&r.path.endsWith('/save')).length,0)
  stage='insert-right';await page.reload();await body().waitFor({timeout:60000});await body().getByText('After KEEP',{exact:true}).waitFor();assert.deepEqual(await pm(),before);await select(0,1);await page.locator('[data-action=table-insert-cells]').click();await submit('插入单元格','right',2);const op=await pending('insert-r2','editTableCells'),anchor=info.model.blocks.filter(b=>b.type==='table')[1];assert.deepEqual(op,{kind:'editTableCells',blockId:anchor.blockId,expectedObjectSha256:anchor.expectedObjectSha256,change:{type:'insert',rect:{top:0,left:1,bottom:1,right:2},where:'right',count:2}});assert.equal(await tables().nth(1).locator('tr').first().locator('td,th').count(),5);const after=await pm();await body().focus();await page.keyboard.press('Control+z');assert.deepEqual(await pm(),before);await page.waitForTimeout(300);await noOps();await page.keyboard.press('Control+y');assert.deepEqual(await pm(),after);assert.deepEqual(await pending('insert-redo','editTableCells'),op);await page.screenshot({path:join(directory,'insert-pending.png'),fullPage:true});await save('insert-r2','editTableCells',2)
 }
 if(!completed[1]){
  stage='shift-up-context';await tables().nth(1).locator('tr').first().locator('td,th').first().click({button:'right'});const menu=page.getByRole('menu',{name:'Word 文档菜单',exact:true});await menu.locator('[data-context-action=deleteCells]').click();await submit('删除单元格','shiftUp');const op=await pending('up-r3','editTableCells');assert.deepEqual(op.change,{type:'delete',rect:{top:0,left:0,bottom:1,right:1},mode:'shiftUp'});assert.equal(await tables().nth(1).locator('tr').first().locator('td,th').first().innerText(),'1/0');await save('up-r3','editTableCells',3)
 }
 if(!completed[2]){
  stage='shift-left-ribbon';await select(1,1);await page.locator('[data-action=table-delete-cells]').click();await submit('删除单元格','shiftLeft');const op=await pending('left-r4','editTableCells');assert.deepEqual(op.change,{type:'delete',rect:{top:1,left:1,bottom:2,right:2},mode:'shiftLeft'});await page.screenshot({path:join(directory,'left-pending.png'),fullPage:true});await save('left-r4','editTableCells',4)
 }
 stage='reopened-left';assert.equal(await tables().count(),2);assert.equal(await tables().nth(1).locator('tr').count(),3);await page.screenshot({path:join(directory,'left-reopened.png'),fullPage:true})
 stage='independent';const verify=spawnSync(python,['-c',`import json,sys
from copy import deepcopy
from zipfile import ZipFile
from lxml import etree as E
p=sys.argv[1];ns={'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main'};W='{'+ns['w']+'}';xml=lambda n:E.tostring(n) if n is not None else None
names=['fixture','insert-r2','up-r3','left-r4'];zs=[ZipFile(p+'/'+n+'.docx') for n in names];roots=[E.fromstring(z.read('word/document.xml')) for z in zs];bodies=[r.find('w:body',ns) for r in roots];ts=[r.findall('./w:body/w:tbl',ns) for r in roots]
assert all(set(z.namelist())==set(zs[0].namelist()) for z in zs)
for name in zs[0].namelist():
 if name!='word/document.xml':assert len({z.read(name) for z in zs})==1,name
assert all(len(t)==2 for t in ts);assert xml(ts[0][0])==xml(ts[0][1]);assert all(xml(t[0])==xml(ts[0][0]) for t in ts)
for b in bodies:
 b=deepcopy(b);b.remove(b.findall('w:tbl',ns)[1]);assert xml(b)==xml((lambda e:(e.remove(e.findall('w:tbl',ns)[1]),e)[1])(deepcopy(bodies[0])))
rows=lambda t:[r.findall('w:tc',ns) for r in t.findall('w:tr',ns)];cells=[rows(t[1]) for t in ts];text=lambda c:''.join(c.itertext()) if False else ''.join(c.xpath('.//w:t/text()',namespaces=ns))
assert [[text(c) for c in r] for r in cells[1]]==[[str(y)+'/0',str(y)+'/1','','',str(y)+'/2'] for y in range(3)]
assert [[text(c) for c in r] for r in cells[2]]==[['1/0','0/1','','','0/2'],['2/0','1/1','','','1/2'],['','2/1','','','2/2']]
assert [[text(c) for c in r] for r in cells[3]]==[['1/0','0/1','','','0/2'],['2/0','','','1/2'],['','2/1','','','2/2']]
for y in range(3):
 for old,new in [(0,0),(1,1),(2,4)]:assert xml(cells[0][y][old].find('w:p',ns))==xml(cells[1][y][new].find('w:p',ns))
 for new in [2,3]:
  c=cells[1][y][new];assert not c.xpath('.//w:t',namespaces=ns);assert c.find('./w:tcPr/w:shd',ns).get(W+'fill')==cells[0][y][1].find('./w:tcPr/w:shd',ns).get(W+'fill')
for y in range(3):
 for x in range(5):
  sy=min(y+1,2) if x==0 else y
  c=cells[2][y][x];src=cells[1][sy][x]
  if y==2 and x==0:assert not c.xpath('.//w:t',namespaces=ns);assert xml(c.find('./w:p/w:pPr',ns))==xml(src.find('./w:p/w:pPr',ns))
  else:assert xml(c.find('w:p',ns))==xml(src.find('w:p',ns))
for y,r in enumerate(cells[3]):
 for x,c in enumerate(r):assert xml(c.find('w:p',ns))==xml(cells[2][y][x+(1 if y==1 and x>=1 else 0)].find('w:p',ns))
gap=ts[3][1].findall('w:tr',ns)[1].find('./w:trPr/w:gridAfter',ns);assert gap is not None and gap.get(W+'val')=='1'
grid=lambda t:[int(n.get(W+'w')) for n in t.find('w:tblGrid',ns)];assert grid(ts[0][1])==[1600,2400,3200]
sect=roots[0].find('./w:body/w:sectPr',ns);page=sect.find('w:pgSz',ns);margin=sect.find('w:pgMar',ns);maxwidth=int(page.get(W+'w'))-int(margin.get(W+'left'))-int(margin.get(W+'right'));widths=grid(ts[1][1]);assert widths==[round(w*min(1,maxwidth/12000)) for w in [1600,2400,2400,2400,3200]];assert sum(widths)<=maxwidth;assert grid(ts[2][1])==grid(ts[3][1])==widths
for n,t in enumerate(ts):
 target=t[1];assert target.find('./w:tblPr/w:tblLayout',ns).get(W+'type')=='fixed';assert int(target.find('./w:tblPr/w:tblW',ns).get(W+'w'))==sum(grid(target))
 for r in rows(target):
  for x,c in enumerate(r):assert int(c.find('./w:tcPr/w:tcW',ns).get(W+'w'))==grid(target)[x]
print(json.dumps({'exactSurvivingParagraphAndRunXML':True,'blankParagraphAndFillInheritance':True,'shiftUpAndLeftTextAndGridAfter':True,'fittedGridAndCellWidths':widths,'identicalUnaffectedTableAndBodyPreserved':True,'nonTargetZIPPartsHeaderFooterPreserved':True}))`,directory],{encoding:'utf8'});await writeFile(join(directory,'independent.json'),verify.stdout);await writeFile(join(directory,'independent-stderr.txt'),verify.stderr);assert.equal(verify.status,0,verify.stderr)
 const state=await(await fetch(origin+'/__smoke__/state')).json();await writeFile(join(directory,'http-final-'+Date.now()+'.json'),JSON.stringify(state,null,2));assert.equal(state.requests.filter(r=>r.method==='POST'&&r.path.endsWith('/save')).length,saves.length);await Promise.all(checks);assert.deepEqual(errors,[]);await writeFile(join(directory,'result.json'),JSON.stringify({ok:true,scope:'Real FastAPI/native publication with scoped in-memory repositories; no production database',finalGridGapScope:'Downloaded shift-left gridAfter source reopens; further cell editing of non-plain grid sources is outside supported scope',savesThisRun:saves,resumed:completed,guardChecks:{pendingCommentInputPreserved:true,cancelNoOp:true,invalidCountInputPreserved:true,rowCountBudgetRefused:true,staleSelectionDisabled:true,preSaveHTTPCount:0,undoRedoExact:true},completedArtifacts:await Promise.all(names.map(async name=>({name,receipt:JSON.parse(await readFile(join(directory,name+'-saved.json'),'utf8')),sha256:sha(await readFile(join(directory,name+'.docx')))}))),assets:Object.fromEntries(assets),manifestSha256:sha(await readFile(join(staticRoot,'.vite/manifest.json'))),errors},null,2));console.log(JSON.stringify({ok:true,directory,saves:saves.length,assets:assets.size}))
}catch(error){await writeFile(join(directory,'failure-'+Date.now()+'.json'),JSON.stringify({stage,error:String(error),stack:error.stack,log,errors},null,2));if(page){await writeFile(join(directory,'failure-dom.html'),await page.content()).catch(()=>{});await writeFile(join(directory,'failure-drafts.json'),JSON.stringify(await drafts(),null,2)).catch(()=>{});await writeFile(join(directory,'failure-pm.json'),JSON.stringify(await pm(),null,2)).catch(()=>{});await page.screenshot({path:join(directory,'failure.png'),fullPage:true}).catch(()=>{})}throw error}
finally{await Promise.allSettled(checks);await writeFile(join(directory,'asset-evidence-'+Date.now()+'.json'),JSON.stringify({assets:Object.fromEntries(assets),manifestSha256:sha(await readFile(join(staticRoot,'.vite/manifest.json')))},null,2));await browser?.close();server.kill();await writeFile(join(directory,'server-'+Date.now()+'.log'),log)}
