import assert from 'node:assert/strict'
import { spawn, spawnSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import { setTimeout as delay } from 'node:timers/promises'
import { chromium } from 'playwright'
const frontend=process.cwd(), repo=new URL('../../../',`file://${frontend}/`).pathname,base='http://127.0.0.1:4223',fullColumn=false,editAfterStructure=process.env.CF_EDIT_AFTER_STRUCTURE==='1'
function python(payload){const r=spawnSync(`${repo}/.venv/bin/python`,['-c',`
import json,sys,base64
from io import BytesIO
from zipfile import ZipFile,ZIP_DEFLATED
from openpyxl import Workbook,load_workbook
from openpyxl.formatting.rule import CellIsRule,FormulaRule
from openpyxl.styles import PatternFill
from smart_reporting.report_editor.native_office import patch_office
p=json.load(sys.stdin)
if p['mode']=='create':
 b=Workbook();s=b.active;s.title='Source';other=b.create_sheet('Other')
 for i in range(1,6):s.cell(i,1,i);other.cell(i,2,i)
 other.conditional_formatting.add('B1:B4',FormulaRule(formula=['TRUE'],stopIfTrue=True,fill=PatternFill('solid',fgColor='FFFF0000')))
 other.conditional_formatting.add('B1:B4',FormulaRule(formula=['Source!A1>0'],fill=PatternFill('solid',fgColor='FF00FF00')))
 f=BytesIO();b.save(f);print(base64.b64encode(f.getvalue()).decode())
elif p['mode']=='patch':print(base64.b64encode(patch_office('xlsx',base64.b64decode(p['bytes']),p['operations'])).decode())
else:
 b=load_workbook(BytesIO(base64.b64decode(p['bytes'])));s=b['Other'];print(json.dumps({'rules':[{'range':str(key.sqref),'type':r.type,'formula':r.formula,'stop':r.stopIfTrue} for key,value in s.conditional_formatting._cf_rules.items() for r in value],'A1':s['A1'].value,'F1':s['F1'].value,'A2':s['A2'].value,'F2':s['F2'].value,'zipXml':ZipFile(BytesIO(base64.b64decode(p['bytes']))).read('xl/worksheets/sheet1.xml').decode()}))
`],{input:JSON.stringify(payload),encoding:'utf8',cwd:repo});assert.equal(r.status,0,r.stderr);return r.stdout.trim()}
const bytes=Buffer.from(python({mode:'create',fullColumn}),'base64'),media='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',context={documentId:'cf-probe',format:'xlsx',revision:1,parentRevision:null,scope:{database:'f',companyId:'f',userId:'f',threadId:'f'},sourceFile:{path:'cf.xlsx',size:bytes.length,sha256:createHash('sha256').update(bytes).digest('hex'),mediaType:media},origin:'upload'}
const server=spawn('./node_modules/.bin/vite',['--host','127.0.0.1','--port','4223','--strictPort'],{cwd:frontend,stdio:'ignore'})
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
 const result=await page.evaluate(async()=>{
  const api=window.__cfRuntime.univerAPI,book=api.getActiveWorkbook(),source=book.getSheetByName('Source'),other=book.getSheetByName('Other')
  const before=structuredClone(other.getConditionalFormattingRules());book.setActiveSheet(source)
  let deleted,error
  try{deleted=api.syncExecuteCommand('sheet.command.remove-sheet',{unitId:book.getId(),subUnitId:source.getSheetId()})}catch(e){error=e.message}
  await new Promise(r=>setTimeout(r,500))
  const after=structuredClone(other.getConditionalFormattingRules()),names=book.getSheets().map(s=>s.getSheetName())
  const undo=await api.undo(),undone=structuredClone(other.getConditionalFormattingRules()),undoNames=book.getSheets().map(s=>s.getSheetName()),redo=await api.redo(),redone=structuredClone(other.getConditionalFormattingRules()),redoNames=book.getSheets().map(s=>s.getSheetName())
  return{before,deleted,error,after,names,undo,undone,undoNames,redo,redone,redoNames,feedback:[...document.querySelectorAll('.workbook-feedback')].map(item=>item.textContent)}
 });console.log(JSON.stringify({phase:'cf-sheet-remove',...result}));
 const failures=[]
 if(!result.names.includes('Source'))failures.push('referenced sheet removed despite fixed-source refusal contract')
 if(JSON.stringify(result.after)!==JSON.stringify(result.before))failures.push('refused removal changed conditional rules')
 console.log(JSON.stringify({ok:failures.length===0,phase:'cf-remove-contract',failures,pageErrors:errors}));assert.deepEqual(failures,[])
}finally{await browser?.close();server.kill()}
