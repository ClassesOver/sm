import assert from 'node:assert/strict'
import { spawn, spawnSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import { setTimeout as delay } from 'node:timers/promises'
import { chromium } from 'playwright'
const clearSource=process.env.NAME_REMOVAL_CLEAR_SOURCE==='1'
const frontend=process.cwd(), repo=new URL('../../../',`file://${frontend}/`).pathname,base='http://127.0.0.1:4229',fullColumn=false,editAfterStructure=process.env.CF_EDIT_AFTER_STRUCTURE==='1'
function python(payload){const r=spawnSync(`${repo}/.venv/bin/python`,['-c',`
import json,sys,base64
from io import BytesIO
from zipfile import ZipFile,ZIP_DEFLATED
from openpyxl import Workbook,load_workbook
from openpyxl.formatting.rule import CellIsRule,FormulaRule
from openpyxl.styles import PatternFill
from openpyxl.workbook.defined_name import DefinedName
from openpyxl.worksheet.datavalidation import DataValidation
from smart_reporting.report_editor.native_office import patch_office
p=json.load(sys.stdin)
if p['mode']=='create':
 b=Workbook();s=b.active;s.title='Source';other=b.create_sheet('Other');b.create_sheet('Third')
 for i in range(1,6):s.cell(i,1,i);other.cell(i,2,i)
 name=DefinedName('DeleteDependency',attr_text=p.get('formula','Source!$A$1'))
 scope=p.get('scope','global')
 if scope=='global':b.defined_names.add(name)
 else:b[scope].defined_names.add(name)
 f=BytesIO();b.save(f);print(base64.b64encode(f.getvalue()).decode())
elif p['mode']=='patch':print(base64.b64encode(patch_office('xlsx',base64.b64decode(p['bytes']),p['operations'])).decode())
else:
 raw=base64.b64decode(p['bytes']);before=ZipFile(BytesIO(base64.b64decode(p['original'])));after=ZipFile(BytesIO(raw));b=load_workbook(BytesIO(raw));print(json.dumps({'sheetNames':b.sheetnames,'names':[{'name':n.name,'ref':n.attr_text} for n in b.defined_names.values()]+[{'name':n.name,'ref':n.attr_text,'scope':s.title} for s in b for n in s.defined_names.values()],'values':[b['Other'].cell(i,2).value for i in range(1,6)],'stylesUnchanged':before.read('xl/styles.xml')==after.read('xl/styles.xml'),'otherXmlUnchanged':before.read('xl/worksheets/sheet2.xml')==after.read('xl/worksheets/sheet2.xml')}))
`],{input:JSON.stringify(payload),encoding:'utf8',cwd:repo});assert.equal(r.status,0,r.stderr);return r.stdout.trim()}
const bytes=Buffer.from(python({mode:'create',fullColumn,formula:process.env.NAME_REMOVAL_FORMULA??'Source!$A$1',scope:process.env.NAME_REMOVAL_SCOPE??'global'}),'base64'),media='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',context={documentId:'cf-probe',format:'xlsx',revision:1,parentRevision:null,scope:{database:'f',companyId:'f',userId:'f',threadId:'f'},sourceFile:{path:'cf.xlsx',size:bytes.length,sha256:createHash('sha256').update(bytes).digest('hex'),mediaType:media},origin:'upload'}
const server=spawn('./node_modules/.bin/vite',['--host','127.0.0.1','--port','4229','--strictPort'],{cwd:frontend,stdio:'ignore'})
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
 const result=await page.evaluate(async()=>{const api=window.__cfRuntime.univerAPI,b=api.getActiveWorkbook();const remove=name=>api.syncExecuteCommand('sheet.command.remove-sheet',{unitId:b.getId(),subUnitId:b.getSheetByName(name).getSheetId()});const initial=b.getDefinedNames().map(n=>({name:n.getName(),scope:n.getLocalSheetId?.(),formula:n.getFormulaOrRefString()}));const first=remove('Source'),names=b.getDefinedNames().map(n=>({name:n.getName(),scope:n.getLocalSheetId?.(),formula:n.getFormulaOrRefString()}));await new Promise(r=>setTimeout(r,800));const undo=await api.undo(),restored=b.getDefinedNames().map(n=>({name:n.getName(),scope:n.getLocalSheetId?.(),formula:n.getFormulaOrRefString()})),redo=await api.redo();await new Promise(r=>setTimeout(r,800));const second=remove('Other');return{first,second,initial,names,undo,restored,redo,sheets:b.getSheets().map(s=>s.getSheetName()),feedback:[...document.querySelectorAll('.workbook-feedback')].map(n=>n.textContent)}});console.log(JSON.stringify({phase:'owned-scope-following-delete',...result,pageErrors:errors}));assert.equal(result.first,true);assert.deepEqual(result.names,[]);assert.equal(result.undo,true);assert.deepEqual(result.restored,result.initial);assert.equal(result.redo,true);assert.equal(result.second,true);assert.deepEqual(result.sheets,['Third'])
}finally{await browser?.close();server.kill()}
