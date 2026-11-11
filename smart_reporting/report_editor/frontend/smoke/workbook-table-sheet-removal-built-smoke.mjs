import assert from 'node:assert/strict'
import { spawn, spawnSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import { readFileSync } from 'node:fs'
import { setTimeout as delay } from 'node:timers/promises'
import { chromium } from 'playwright'
const frontend=process.cwd(), repo=new URL('../../../',`file://${frontend}/`).pathname,base='http://127.0.0.1:4235',allow=process.env.TABLE_REMOVAL_CLEAR==='1'
function python(payload){const r=spawnSync(`${repo}/.venv/bin/python`,['-c',`
import json,sys,base64
from io import BytesIO
from zipfile import ZipFile,ZIP_DEFLATED
from openpyxl import Workbook,load_workbook
from openpyxl.formatting.rule import CellIsRule,FormulaRule
from openpyxl.styles import PatternFill
from openpyxl.worksheet.table import Table
from openpyxl.worksheet.datavalidation import DataValidation
from smart_reporting.report_editor.native_office import patch_office
p=json.load(sys.stdin)
if p['mode']=='create':
 b=Workbook();s=b.active;s.title='Source';other=b.create_sheet('Other')
 s.cell(1,1,'Amount')
 for i in range(1,6):
  other.cell(i,2,i)
  if i>1:s.cell(i,1,i)
 s.add_table(Table(displayName='SalesData',ref='A1:A5'));other.cell(1,3,'=SUM(SalesData[Amount])')
 f=BytesIO();b.save(f)
 if p.get('readonly'):
  old=ZipFile(BytesIO(f.getvalue()));f=BytesIO()
  with ZipFile(f,'w',ZIP_DEFLATED) as out:
   for item in old.infolist():
    data=old.read(item.filename)
    if item.filename=='xl/tables/table1.xml':data=data.replace(b'tableColumns count="1"',b'tableColumns count="9"')
    out.writestr(item,data)
 print(base64.b64encode(f.getvalue()).decode())
elif p['mode']=='patch':print(base64.b64encode(patch_office('xlsx',base64.b64decode(p['bytes']),p['operations'])).decode())
else:
 raw=base64.b64decode(p['bytes']);b=load_workbook(BytesIO(raw));before=ZipFile(BytesIO(base64.b64decode(p['original'])));after=ZipFile(BytesIO(raw));print(json.dumps({'sheetNames':b.sheetnames,'values':[b['Other'].cell(i,2).value for i in range(1,6)],'tableParts':[n for n in after.namelist() if n.startswith('xl/tables/')],'remainingTables':list(b['Other'].tables),'otherC1':b['Other']['C1'].value,'stylesUnchanged':before.read('xl/styles.xml')==after.read('xl/styles.xml')}))
`],{input:JSON.stringify(payload),encoding:'utf8',cwd:repo});assert.equal(r.status,0,r.stderr);return r.stdout.trim()}
const bytes=Buffer.from(python({mode:'create',readonly:process.env.TABLE_REMOVAL_READONLY==='1',reference:process.env.CHART_REMOVAL_REFERENCE??'Source'}),'base64'),media='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',context={documentId:'cf-probe',format:'xlsx',revision:1,parentRevision:null,scope:{database:'f',companyId:'f',userId:'f',threadId:'f'},sourceFile:{path:'cf.xlsx',size:bytes.length,sha256:createHash('sha256').update(bytes).digest('hex'),mediaType:media},origin:'upload'}
const server=spawn('./node_modules/.bin/vite',['preview','--host','127.0.0.1','--port','4235','--strictPort'],{cwd:frontend,stdio:'ignore'})
let browser,saved,payload
try{
 for(let i=0;i<120;i++){try{if((await fetch(`${base}/reports/v1/editor/assets/native.html`)).ok)break}catch{}await delay(250)}
 browser=await chromium.launch({headless:true});const page=await browser.newPage({viewport:{width:1500,height:1100}}),errors=[],scriptProof=[]
 page.on('pageerror',e=>{errors.push(e.message);console.log(e.stack)})
 page.on('response',response=>{const url=new URL(response.url());if(url.pathname.startsWith('/reports/v1/editor/assets/')&&url.pathname.endsWith('.js'))scriptProof.push((async()=>{assert.equal(response.status(),200);const body=await response.body(),path=`../static/${url.pathname.slice('/reports/v1/editor/assets/'.length)}`;assert.equal(createHash('sha256').update(body).digest('hex'),createHash('sha256').update(readFileSync(path)).digest('hex'));return url.pathname})())})
 await page.route('**/reports/v1/native/cf-probe/1/api/context',r=>r.fulfill({json:{context,csrfToken:'csrf',capabilities:{xlsx_editor:true},editingEnabled:true}}))
 await page.route('**/reports/v1/native/cf-probe/1/api/file',r=>r.fulfill({body:bytes,contentType:media}))
 await page.route('**/reports/v1/native/cf-probe/1/api/save',async r=>{payload=r.request().postDataJSON();saved=Buffer.from(python({mode:'patch',bytes:bytes.toString('base64'),operations:payload.operations}),'base64');await r.fulfill({json:{documentId:'cf-probe',revision:2,parentRevision:1,revisionRegistered:true,artifacts:{xlsx:{downloadUrl:'/cf.xlsx'}},editor:{openUrl:'/reports/v1/native/cf-probe/2'},validation:{issues:[]}}})})
 await page.route(/\/reports\/v1\/native\/cf-probe\/[12]$/,async r=>r.fulfill({response:await r.fetch({url:`${base}/reports/v1/editor/assets/native.html`})}))
 await page.addInitScript(()=>history.replaceState(null,'','/reports/v1/native/cf-probe/1'))
 await page.goto(`${base}/reports/v1/editor/assets/native.html`);await page.waitForFunction(()=>document.querySelector('#report-editor')?.getAttribute('aria-busy')==='false',null,{timeout:60000}).catch(async error=>{console.log(JSON.stringify({phase:'chart-load-failure',body:(await page.locator('body').innerText()).slice(-4000)}));throw error});await page.locator('[data-ribbon-tab="Home"]').waitFor()
 await page.waitForTimeout(500)
 const beforeDraft=await page.evaluate(()=>Object.fromEntries(Object.entries(localStorage))),beforeSaveLabel=await page.locator('.save-state-label').textContent()
 const tab=name=>page.locator('[data-u-comp="slide-tab-item"]').filter({hasText:name})
 const history=async action=>{await page.locator('[data-ribbon-tab="File"]').click();await page.locator(`[data-ribbon-command="${action}"]`).click()}
 const remove=async()=>{await tab('Source').click({button:'right'});await page.getByText('删除',{exact:true}).last().click();await page.getByRole('button',{name:'确定',exact:true}).click()}
 if(allow){await tab('Other').click();await page.locator('[data-ribbon-tab="Home"]').click();await page.locator('[data-ribbon-command="goto-open"]').click();await page.locator('[data-goto-reference]').fill('C1');await page.locator('.workbook-ribbon-goto-dialog button[type="submit"]').click();await page.keyboard.type('1');await page.keyboard.press('Enter');await page.waitForTimeout(300)}
 await remove()
 if(!allow){await page.getByText(/工作表 "Other" 仍引用表格 "SalesData"，已拒绝删除。/).waitFor();await tab('Source').waitFor();await history('undo');await tab('Source').waitFor();await history('redo');await tab('Source').waitFor();assert.deepEqual(await page.evaluate(()=>Object.fromEntries(Object.entries(localStorage))),beforeDraft);assert.equal(await page.locator('.save-state-label').textContent(),beforeSaveLabel);assert.equal(saved,undefined)}
 else {await tab('Source').waitFor({state:'detached'});await history('undo');await tab('Source').waitFor();await history('redo');await tab('Source').waitFor({state:'detached'})
 {  await page.waitForFunction(()=>Object.keys(localStorage).filter(key=>key.startsWith('native-editor-draft:')).some(key=>{try{return JSON.parse(localStorage.getItem(key)).operations.some(op=>op.kind==='applySheetEdits'&&op.plan.removals.length)}catch{return false}}),null,{timeout:30000})
  await page.reload();await page.waitForFunction(()=>document.querySelector('#report-editor')?.getAttribute('aria-busy')==='false',null,{timeout:60000});await tab('Other').waitFor();assert.equal(await tab('Source').count(),0)
  await page.locator('[data-action="save"]').click();await page.waitForFunction(()=>document.querySelector('.save-state-label')?.textContent==='已保存修订 2',null,{timeout:60000})
  const actual=JSON.parse(python({mode:'inspect',bytes:saved.toString('base64'),original:bytes.toString('base64')}));assert.deepEqual(actual.sheetNames,['Other']);assert.deepEqual(actual.tableParts,[]);assert.deepEqual(actual.remainingTables,[]);assert.equal(actual.otherC1,1);assert.equal(actual.stylesUnchanged,true);assert.deepEqual(actual.values,[1,2,3,4,5]);assert.deepEqual(payload.operations.map(op=>op.kind),['applyCellEdits','applySheetEdits']);assert.deepEqual(payload.operations[1],{kind:'applySheetEdits',plan:{renames:[],additions:[],removals:['Source'],order:['Other']}})
  await page.route('**/reports/v1/native/cf-probe/2/api/context',route=>route.fulfill({json:{context:{...context,revision:2,parentRevision:1,sourceFile:{...context.sourceFile,size:saved.length,sha256:createHash('sha256').update(saved).digest('hex')}},csrfToken:'csrf',capabilities:{xlsx_editor:true},editingEnabled:true}}));await page.route('**/reports/v1/native/cf-probe/2/api/file',route=>route.fulfill({body:saved,contentType:media}));await page.addInitScript(()=>history.replaceState(null,'','/reports/v1/native/cf-probe/2'));await page.goto(`${base}/reports/v1/native/cf-probe/2`);await page.waitForFunction(()=>document.querySelector('#report-editor')?.getAttribute('aria-busy')==='false',null,{timeout:60000});await tab('Other').waitFor();assert.equal(await tab('Source').count(),0);console.log(JSON.stringify({phase:'allowed-remove-save',actual,operations:payload.operations}))
 }

 }
 const scripts=await Promise.all(scriptProof);assert(scripts.some(path=>/workbook-main-/.test(path)));console.log(JSON.stringify({ok:true,preview:true,phase:'table-sheet-remove-contract',allow,atomicRefusal:!allow,allowedHistoryDraftPythonRevision:allow,js200AndHashMatch:scripts.length,assets:[...new Set(scripts.filter(path=>/workbook-(main|engine-|structure|chart-references|xml-parser)/.test(path)))],pageErrors:errors}));assert.deepEqual(errors,[])
}finally{await browser?.close();server.kill()}
