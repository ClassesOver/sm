import assert from 'node:assert/strict'
import { spawn, spawnSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import { setTimeout as delay } from 'node:timers/promises'
import { chromium } from 'playwright'
const frontend=process.cwd(), repo=new URL('../../../',`file://${frontend}/`).pathname,base='http://127.0.0.1:4226',clearSource=process.env.DV_REMOVAL_CLEAR_SOURCE==='1',allow=process.env.DV_REMOVAL_ALLOW==='1'||clearSource
function python(payload){const r=spawnSync(`${repo}/.venv/bin/python`,['-c',`
import json,sys,base64
from io import BytesIO
from zipfile import ZipFile,ZIP_DEFLATED
from openpyxl import Workbook,load_workbook
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.styles import PatternFill
from smart_reporting.report_editor.native_office import patch_office
p=json.load(sys.stdin)
if p['mode']=='create':
 b=Workbook();s=b.active;s.title='Source';other=b.create_sheet('Other')
 for i in range(1,6):s.cell(i,1,i);other.cell(i,2,i)
 dv=DataValidation(type='list',formula1='"yes,no"' if p.get('allow') else '=Source!$A$1:$A$5');dv.add('B1:B4');other.add_data_validation(dv)
 f=BytesIO();b.save(f);print(base64.b64encode(f.getvalue()).decode())
elif p['mode']=='patch':print(base64.b64encode(patch_office('xlsx',base64.b64decode(p['bytes']),p['operations'])).decode())
else:
 raw=base64.b64decode(p['bytes']);b=load_workbook(BytesIO(raw));s=b['Other'];before=ZipFile(BytesIO(base64.b64decode(p['original'])));after=ZipFile(BytesIO(raw));print(json.dumps({'sheetNames':b.sheetnames,'rules':[{'range':str(r.sqref),'type':r.type,'formula1':r.formula1,'formula2':r.formula2} for r in s.data_validations.dataValidation],'values':[s.cell(i,2).value for i in range(1,6)],'otherXmlUnchanged':before.read('xl/worksheets/sheet2.xml')==after.read('xl/worksheets/sheet2.xml'),'stylesUnchanged':before.read('xl/styles.xml')==after.read('xl/styles.xml')}))
`],{input:JSON.stringify(payload),encoding:'utf8',cwd:repo});assert.equal(r.status,0,r.stderr);return r.stdout.trim()}
const bytes=Buffer.from(python({mode:'create',allow:allow&&!clearSource}),'base64'),media='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',context={documentId:'cf-probe',format:'xlsx',revision:1,parentRevision:null,scope:{database:'f',companyId:'f',userId:'f',threadId:'f'},sourceFile:{path:'cf.xlsx',size:bytes.length,sha256:createHash('sha256').update(bytes).digest('hex'),mediaType:media},origin:'upload'}
const server=spawn('./node_modules/.bin/vite',['--host','127.0.0.1','--port','4226','--strictPort'],{cwd:frontend,stdio:'ignore'})
let browser,saved,payload
try{
 for(let i=0;i<120;i++){try{if((await fetch(`${base}/reports/v1/editor/assets/native.html`)).ok)break}catch{}await delay(250)}
 browser=await chromium.launch({headless:true});const page=await browser.newPage({viewport:{width:1500,height:1100}}),errors=[]
 page.on('pageerror',e=>{errors.push(e.message);console.log(e.stack)})
 await page.route('**/src/workbook-vendor/grid/create-univer.ts*',async route=>{const r=await route.fetch(),body=await r.text();assert(body.includes('return { univer, univerAPI: FUniver.newAPI(univer) };'));await route.fulfill({response:r,body:body.replace('return { univer, univerAPI: FUniver.newAPI(univer) };','return window.__cfRuntime={univer,univerAPI:FUniver.newAPI(univer)};')})})
 await page.route('**/reports/v1/native/cf-probe/1/api/context',r=>r.fulfill({json:{context,csrfToken:'csrf',capabilities:{xlsx_editor:true},editingEnabled:true}}))
 await page.route('**/reports/v1/native/cf-probe/1/api/file',r=>r.fulfill({body:bytes,contentType:media}))
 await page.route('**/reports/v1/native/cf-probe/1/api/save',async r=>{payload=r.request().postDataJSON();saved=Buffer.from(python({mode:'patch',bytes:bytes.toString('base64'),operations:payload.operations}),'base64');await r.fulfill({json:{documentId:'cf-probe',revision:2,parentRevision:1,revisionRegistered:true,artifacts:{xlsx:{downloadUrl:'/cf.xlsx'}},editor:{openUrl:'/reports/v1/native/cf-probe/2'},validation:{issues:[]}}})})
 await page.route(/\/reports\/v1\/native\/cf-probe\/[12]$/,async r=>r.fulfill({response:await r.fetch({url:`${base}/reports/v1/editor/assets/native.html`})}))
 await page.addInitScript(()=>history.replaceState(null,'','/reports/v1/native/cf-probe/1'))
 await page.goto(`${base}/reports/v1/editor/assets/native.html`);await page.waitForFunction(()=>document.querySelector('#report-editor')?.getAttribute('aria-busy')==='false',null,{timeout:60000}).catch(async error=>{console.log(JSON.stringify({phase:'dv-load-failure',body:(await page.locator('body').innerText()).slice(-4000)}));throw error});await page.locator('[data-ribbon-tab="Home"]').waitFor()
 await page.waitForTimeout(500)
 const beforeDraft=await page.evaluate(()=>Object.fromEntries(Object.entries(localStorage))),beforeSaveLabel=await page.locator('.save-state-label').textContent()
 if(clearSource){
  const first=await page.evaluate(()=>{const api=window.__cfRuntime.univerAPI,book=api.getActiveWorkbook();return api.syncExecuteCommand('sheet.command.remove-sheet',{unitId:book.getId(),subUnitId:book.getSheetByName('Source').getSheetId()})});assert.equal(first,false);assert.deepEqual(await page.evaluate(()=>Object.fromEntries(Object.entries(localStorage))),beforeDraft);assert.equal(await page.locator('.save-state-label').textContent(),beforeSaveLabel)
  await page.evaluate(async()=>{const api=window.__cfRuntime.univerAPI,book=api.getActiveWorkbook(),other=book.getSheetByName('Other');book.setActiveSheet(other);await api.executeCommand('data-validation.mutation.removeRule',{unitId:book.getId(),subUnitId:other.getSheetId(),ruleId:other.getDataValidations()[0].rule.uid})});await page.waitForFunction(()=>window.__cfRuntime.univerAPI.getActiveWorkbook().getSheetByName('Other').getDataValidations().length===0)
  console.log(JSON.stringify({phase:'source-reference-cleared-in-native-manager',initialRejected:first===false}))
 }
 const result=await page.evaluate(async allow=>{
  const api=window.__cfRuntime.univerAPI,book=api.getActiveWorkbook(),source=book.getSheetByName('Source'),other=book.getSheetByName('Other')
  const before=structuredClone(other.getDataValidations().map(item=>item.rule));book.setActiveSheet(source)
  let deleted,error
  try{deleted=api.syncExecuteCommand('sheet.command.remove-sheet',{unitId:book.getId(),subUnitId:source.getSheetId()})}catch(e){error=e.message}
  await new Promise(r=>setTimeout(r,500))
  const after=structuredClone(other.getDataValidations().map(item=>item.rule)),names=book.getSheets().map(s=>s.getSheetName())
  const undo=await api.undo(),undone=structuredClone(other.getDataValidations().map(item=>item.rule)),undoNames=book.getSheets().map(s=>s.getSheetName()),redo=await api.redo(),redone=structuredClone(other.getDataValidations().map(item=>item.rule)),redoNames=book.getSheets().map(s=>s.getSheetName())
  return{before,deleted,error,after,names,undo,undone,undoNames,redo,redone,redoNames,feedback:[...document.querySelectorAll('.workbook-feedback')].map(item=>item.textContent)}
 },allow);console.log(JSON.stringify({phase:'dv-sheet-remove',allow,...result}));
 const failures=[]
 if(allow?result.names.includes('Source'):!result.names.includes('Source'))failures.push('removal result did not match actual dependency')
 if(JSON.stringify(result.after)!==JSON.stringify(result.before))failures.push('refused removal changed conditional rules')
 assert.deepEqual(failures,[])
 if(!allow){assert.notEqual(result.deleted,true);assert.equal(result.undo,false);assert.equal(result.redo,false);assert.deepEqual(result.undoNames,['Source','Other']);assert.deepEqual(result.redoNames,['Source','Other']);assert.deepEqual(await page.evaluate(()=>Object.fromEntries(Object.entries(localStorage))),beforeDraft);assert.equal(await page.locator('.save-state-label').textContent(),beforeSaveLabel);assert.equal(saved,undefined)}
 else{
  assert.equal(result.deleted,true);assert.equal(result.undo,true);assert.equal(result.redo,true);assert.deepEqual(result.undoNames,['Source','Other']);assert.deepEqual(result.redoNames,['Other'])
  await page.waitForFunction(()=>Object.keys(localStorage).filter(key=>key.startsWith('native-editor-draft:')).some(key=>{try{return JSON.parse(localStorage.getItem(key)).operations.some(op=>op.kind==='applySheetEdits'&&op.plan.removals.length)}catch{return false}}),null,{timeout:30000})
  await page.reload();await page.waitForFunction(()=>document.querySelector('#report-editor')?.getAttribute('aria-busy')==='false',null,{timeout:60000});assert.deepEqual(await page.evaluate(()=>window.__cfRuntime.univerAPI.getActiveWorkbook().getSheets().map(sheet=>sheet.getSheetName())),['Other'])
  await page.locator('[data-action="save"]').click();await page.waitForFunction(()=>document.querySelector('.save-state-label')?.textContent==='已保存修订 2',null,{timeout:60000})
  const actual=JSON.parse(python({mode:'inspect',bytes:saved.toString('base64'),original:bytes.toString('base64')}));assert.deepEqual(actual.sheetNames,['Other']);assert.deepEqual(actual.rules,clearSource?[]:[{range:'B1:B4',type:'list',formula1:'"yes,no"',formula2:null}]);assert.equal(actual.otherXmlUnchanged,!clearSource);assert.equal(actual.stylesUnchanged,true);assert.deepEqual(actual.values,[1,2,3,4,5]);const removal={kind:'applySheetEdits',plan:{renames:[],additions:[],removals:['Source'],order:['Other']}};if(clearSource){assert.equal(payload.operations.length,2);assert.equal(payload.operations[0].kind,'replaceSheetDataValidations');assert.equal(payload.operations[0].sheetName,'Other');assert.equal(payload.operations[0].rules.length,0);assert.deepEqual(payload.operations[1],removal)}else assert.deepEqual(payload.operations,[removal])
  await page.route('**/reports/v1/native/cf-probe/2/api/context',route=>route.fulfill({json:{context:{...context,revision:2,parentRevision:1,sourceFile:{...context.sourceFile,size:saved.length,sha256:createHash('sha256').update(saved).digest('hex')}},csrfToken:'csrf',capabilities:{xlsx_editor:true},editingEnabled:true}}));await page.route('**/reports/v1/native/cf-probe/2/api/file',route=>route.fulfill({body:saved,contentType:media}));await page.addInitScript(()=>history.replaceState(null,'','/reports/v1/native/cf-probe/2'));await page.goto(`${base}/reports/v1/native/cf-probe/2`);await page.waitForFunction(()=>document.querySelector('#report-editor')?.getAttribute('aria-busy')==='false',null,{timeout:60000});assert.deepEqual(await page.evaluate(()=>window.__cfRuntime.univerAPI.getActiveWorkbook().getSheets().map(sheet=>sheet.getSheetName())),['Other']);console.log(JSON.stringify({phase:'allowed-remove-save',actual,operations:payload.operations}))
 }
 console.log(JSON.stringify({ok:true,phase:'dv-remove-contract',allow,clearSource,atomicRefusal:!allow||clearSource,allowedHistoryDraftPythonRevision:allow,pageErrors:errors}));assert.deepEqual(errors,[])
}finally{await browser?.close();server.kill()}
