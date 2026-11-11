import assert from 'node:assert/strict'
import { spawn, spawnSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import { setTimeout as delay } from 'node:timers/promises'
import { chromium } from 'playwright'
const allow=process.env.CHART_REMOVAL_REFERENCE==='Other'
const frontend=process.cwd(), repo=new URL('../../../',`file://${frontend}/`).pathname,base='http://127.0.0.1:4231',fullColumn=false,editAfterStructure=process.env.CF_EDIT_AFTER_STRUCTURE==='1'
function python(payload){const r=spawnSync(`${repo}/.venv/bin/python`,['-c',`
import json,sys,base64
from io import BytesIO
from zipfile import ZipFile,ZIP_DEFLATED
from openpyxl import Workbook,load_workbook
from openpyxl.formatting.rule import CellIsRule,FormulaRule
from openpyxl.styles import PatternFill
from openpyxl.chart import BarChart,Reference
from openpyxl.worksheet.datavalidation import DataValidation
from smart_reporting.report_editor.native_office import patch_office
p=json.load(sys.stdin)
if p['mode']=='create':
 b=Workbook();s=b.active;s.title='Source';other=b.create_sheet('Other')
 for i in range(1,6):s.cell(i,1,i);other.cell(i,2,i)
 chart=BarChart();chart.add_data(Reference(b[p.get('reference','Source')],min_col=1,min_row=1,max_row=5));other.add_chart(chart,'D2')
 f=BytesIO();b.save(f);print(base64.b64encode(f.getvalue()).decode())
elif p['mode']=='patch':print(base64.b64encode(patch_office('xlsx',base64.b64decode(p['bytes']),p['operations'])).decode())
else:
 raw=base64.b64decode(p['bytes']);b=load_workbook(BytesIO(raw));before=ZipFile(BytesIO(base64.b64decode(p['original'])));after=ZipFile(BytesIO(raw));print(json.dumps({'sheetNames':b.sheetnames,'values':[b['Other'].cell(i,2).value for i in range(1,6)],'chartXmlUnchanged':before.read('xl/charts/chart1.xml')==after.read('xl/charts/chart1.xml'),'chartXml':after.read('xl/charts/chart1.xml').decode(),'otherXmlUnchanged':before.read('xl/worksheets/sheet2.xml')==after.read('xl/worksheets/sheet2.xml'),'stylesUnchanged':before.read('xl/styles.xml')==after.read('xl/styles.xml')}))
`],{input:JSON.stringify(payload),encoding:'utf8',cwd:repo});assert.equal(r.status,0,r.stderr);return r.stdout.trim()}
const bytes=Buffer.from(python({mode:'create',reference:process.env.CHART_REMOVAL_REFERENCE??'Source'}),'base64'),media='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',context={documentId:'cf-probe',format:'xlsx',revision:1,parentRevision:null,scope:{database:'f',companyId:'f',userId:'f',threadId:'f'},sourceFile:{path:'cf.xlsx',size:bytes.length,sha256:createHash('sha256').update(bytes).digest('hex'),mediaType:media},origin:'upload'}
const server=spawn('./node_modules/.bin/vite',['--host','127.0.0.1','--port','4231','--strictPort'],{cwd:frontend,stdio:'ignore'})
let browser,saved,payload
try{
 for(let i=0;i<120;i++){try{if((await fetch(`${base}/reports/v1/editor/assets/native.html`)).ok)break}catch{}await delay(250)}
 browser=await chromium.launch({headless:true});const page=await browser.newPage({viewport:{width:1500,height:1100}}),errors=[]
 page.on('pageerror',e=>{errors.push(e.message);console.log(e.stack)})
 await page.route('**/src/workbook-vendor/grid/create-univer.ts*',async route=>{const r=await route.fetch(),body=await r.text();assert(body.includes('return { univer, univerAPI: FUniver.newAPI(univer) };'));await route.fulfill({response:r,body:body.replace('return { univer, univerAPI: FUniver.newAPI(univer) };','return window.__cfRuntime={univer,univerAPI:FUniver.newAPI(univer)};')})})
 if(process.env.CF_SPLIT_OFFICIAL==='1')await page.route('**/src/workbook-data-validation-structure.ts*',async route=>{
  const response=await route.fetch(),body=await response.text(),needle='service.onCommandExecute = collect;'
  assert(body.includes(needle))
  await route.fulfill({response,body:body.replace(needle,`service.onCommandExecute=function(command){const result=original.call(this,command);window.__cfOfficialSplit=structuredClone(result);return result};`)})
 })
 await page.route('**/reports/v1/native/cf-probe/1/api/context',r=>r.fulfill({json:{context,csrfToken:'csrf',capabilities:{xlsx_editor:true},editingEnabled:true}}))
 await page.route('**/reports/v1/native/cf-probe/1/api/file',r=>r.fulfill({body:bytes,contentType:media}))
 await page.route('**/reports/v1/native/cf-probe/1/api/save',async r=>{payload=r.request().postDataJSON();saved=Buffer.from(python({mode:'patch',bytes:bytes.toString('base64'),operations:payload.operations}),'base64');await r.fulfill({json:{documentId:'cf-probe',revision:2,parentRevision:1,revisionRegistered:true,artifacts:{xlsx:{downloadUrl:'/cf.xlsx'}},editor:{openUrl:'/reports/v1/native/cf-probe/2'},validation:{issues:[]}}})})
 await page.route(/\/reports\/v1\/native\/cf-probe\/[12]$/,async r=>r.fulfill({response:await r.fetch({url:`${base}/reports/v1/editor/assets/native.html`})}))
 await page.addInitScript(()=>history.replaceState(null,'','/reports/v1/native/cf-probe/1'))
 await page.goto(`${base}/reports/v1/editor/assets/native.html`);await page.waitForFunction(()=>document.querySelector('#report-editor')?.getAttribute('aria-busy')==='false',null,{timeout:60000}).catch(async error=>{console.log(JSON.stringify({phase:'cf-load-failure',body:(await page.locator('body').innerText()).slice(-4000)}));throw error});await page.locator('[data-ribbon-tab="Home"]').waitFor()
 const draftBefore=await page.evaluate(()=>Object.fromEntries(Object.entries(localStorage)))
 const result=await page.evaluate(async()=>{
  const api=window.__cfRuntime.univerAPI,book=api.getActiveWorkbook(),source=book.getSheetByName('Source')
  book.setActiveSheet(source)
  const before=structuredClone(book.getSnapshot())
  let deleted,error
  try{deleted=api.syncExecuteCommand('sheet.command.remove-sheet',{unitId:book.getId(),subUnitId:source.getSheetId()})}catch(e){error=e.message}
  await new Promise(r=>setTimeout(r,700))
  const after=structuredClone(book.getSnapshot()),afterNames=book.getSheets().map(s=>s.getSheetName())
  const undo=await api.undo(),undone=structuredClone(book.getSnapshot()),redo=await api.redo(),redone=structuredClone(book.getSnapshot())
  return{unitId:book.getId(),before,deleted,error,after,afterNames,undo,undone,redo,redone,feedback:[...document.querySelectorAll('.workbook-feedback')].map(item=>item.textContent)}
 });
 const draftAfter=await page.evaluate(()=>Object.fromEntries(Object.entries(localStorage)))
 const summary={...result,snapshotUnchanged:JSON.stringify(result.before)===JSON.stringify(result.after),undoRestores:JSON.stringify(result.before)===JSON.stringify(result.undone),redoReproduces:JSON.stringify(result.after)===JSON.stringify(result.redone),draftBefore,draftAfter,chartsBefore:result.before.sheets?.['sheet-1']?.charts,chartsAfter:result.after.sheets?.['sheet-1']?.charts}
 delete summary.before;delete summary.after;delete summary.undone;delete summary.redone
 console.log(JSON.stringify({phase:'chart-sheet-remove',...summary}));
 const failures=[]
 if(!allow&&!result.afterNames.includes('Source'))failures.push('chart-referenced sheet removed despite fixed-source refusal contract')
 if(!allow&&JSON.stringify(result.before)!==JSON.stringify(result.after))failures.push('refused removal changed complete workbook snapshot')
 if(!allow&&(result.undo||result.redo))failures.push('refused removal added history')
 if(!allow&&JSON.stringify(draftBefore)!==JSON.stringify(draftAfter))failures.push('refused removal changed local draft')
 console.log(JSON.stringify({ok:failures.length===0,phase:'chart-remove-contract',failures,pageErrors:errors}));assert.deepEqual(failures,[])
 if(allow){
  assert.equal(result.deleted,true);assert.deepEqual(result.afterNames,['Other']);assert.equal(result.undo,true);assert.equal(result.redo,true)
  await page.waitForFunction(()=>Object.keys(localStorage).some(key=>{try{return JSON.parse(localStorage.getItem(key)).operations.some(op=>op.kind==='applySheetEdits'&&op.plan.removals.length)}catch{return false}}),null,{timeout:30000})
  await page.reload();await page.waitForFunction(()=>document.querySelector('#report-editor')?.getAttribute('aria-busy')==='false',null,{timeout:60000});assert.deepEqual(await page.evaluate(()=>window.__cfRuntime.univerAPI.getActiveWorkbook().getSheets().map(s=>s.getSheetName())),['Other'])
  await page.locator('[data-action="save"]').click();await page.waitForFunction(()=>document.querySelector('.save-state-label')?.textContent==='已保存修订 2',null,{timeout:60000})
  const actual=JSON.parse(python({mode:'inspect',bytes:saved.toString('base64'),original:bytes.toString('base64')}));assert.deepEqual(actual.sheetNames,['Other']);assert.equal(actual.chartXmlUnchanged,true);assert.equal(actual.otherXmlUnchanged,true);assert.equal(actual.stylesUnchanged,true);assert.deepEqual(actual.values,[1,2,3,4,5]);assert.deepEqual(payload.operations,[{kind:'applySheetEdits',plan:{renames:[],additions:[],removals:['Source'],order:['Other']}}])
  await page.route('**/reports/v1/native/cf-probe/2/api/context',route=>route.fulfill({json:{context:{...context,revision:2,parentRevision:1,sourceFile:{...context.sourceFile,size:saved.length,sha256:createHash('sha256').update(saved).digest('hex')}},csrfToken:'csrf',capabilities:{xlsx_editor:true},editingEnabled:true}}));await page.route('**/reports/v1/native/cf-probe/2/api/file',route=>route.fulfill({body:saved,contentType:media}));await page.addInitScript(()=>history.replaceState(null,'','/reports/v1/native/cf-probe/2'));await page.goto(`${base}/reports/v1/native/cf-probe/2`);await page.waitForFunction(()=>document.querySelector('#report-editor')?.getAttribute('aria-busy')==='false',null,{timeout:60000});assert.deepEqual(await page.evaluate(()=>window.__cfRuntime.univerAPI.getActiveWorkbook().getSheets().map(s=>s.getSheetName())),['Other']);console.log(JSON.stringify({phase:'chart-nondependent-save',actual,operations:payload.operations,pageErrors:errors}));assert.deepEqual(errors,[])
 }

}finally{await browser?.close();server.kill()}
