import assert from 'node:assert/strict'
import { spawn, spawnSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import { setTimeout as delay } from 'node:timers/promises'
import { chromium } from 'playwright'
const frontend=process.cwd(), repo=new URL('../../../',`file://${frontend}/`).pathname,base='http://127.0.0.1:4205',fullColumn=process.env.CF_FULL_COLUMN==='1'
function python(payload){const r=spawnSync(`${repo}/.venv/bin/python`,['-c',`
import json,sys,base64
from io import BytesIO
from openpyxl import Workbook,load_workbook
from openpyxl.formatting.rule import CellIsRule,FormulaRule
from openpyxl.styles import PatternFill
from smart_reporting.report_editor.native_office import patch_office
p=json.load(sys.stdin)
if p['mode']=='create':
 b=Workbook();s=b.active;s.title='Values'
 for row,value in enumerate([5,15,25,35],2):s.cell(row,2,value)
 s['A1']='keep';s['F1']='=SUM(B2:B5)'
 s.conditional_formatting.add('B2:B5',CellIsRule(operator='greaterThan',formula=['10'],stopIfTrue=True,fill=PatternFill('solid',fgColor='FFFF0000')))
 s.conditional_formatting.add('D1:D1048576' if p.get('fullColumn') else 'D5001:D5100',FormulaRule(formula=['D1>0' if p.get('fullColumn') else 'D5001>0'],fill=PatternFill('solid',fgColor='FF00FF00')))
 f=BytesIO();b.save(f);print(base64.b64encode(f.getvalue()).decode())
elif p['mode']=='patch':print(base64.b64encode(patch_office('xlsx',base64.b64decode(p['bytes']),p['operations'])).decode())
else:
 b=load_workbook(BytesIO(base64.b64decode(p['bytes'])));s=b['Values'];print(json.dumps({'rules':[{'range':str(key.sqref),'type':r.type,'formula':r.formula,'stop':r.stopIfTrue} for key,value in s.conditional_formatting._cf_rules.items() for r in value],'A1':s['A1'].value,'F1':s['F1'].value}))
`],{input:JSON.stringify(payload),encoding:'utf8',cwd:repo});assert.equal(r.status,0,r.stderr);return r.stdout.trim()}
const bytes=Buffer.from(python({mode:'create',fullColumn}),'base64'),media='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',context={documentId:'cf-probe',format:'xlsx',revision:1,parentRevision:null,scope:{database:'f',companyId:'f',userId:'f',threadId:'f'},sourceFile:{path:'cf.xlsx',size:bytes.length,sha256:createHash('sha256').update(bytes).digest('hex'),mediaType:media},origin:'upload'}
const server=spawn('./node_modules/.bin/vite',['--host','127.0.0.1','--port','4205','--strictPort'],{cwd:frontend,stdio:'ignore'})
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
 await page.goto(`${base}/reports/v1/editor/assets/native.html`);await page.waitForFunction(()=>document.querySelector('#report-editor')?.getAttribute('aria-busy')==='false',null,{timeout:60000}).catch(async error=>{console.log(JSON.stringify({phase:'cf-load-failure',body:(await page.locator('body').innerText()).slice(-4000)}));throw error});await page.locator('[data-ribbon-tab="Home"]').waitFor()
 const imported=await page.evaluate(()=>window.__cfRuntime.univerAPI.getActiveWorkbook().getActiveSheet().getConditionalFormattingRules());assert.equal(imported.length,2);console.log(JSON.stringify({phase:'cf-import',rules:imported}))
 if(fullColumn){assert.equal(imported[1].ranges[0].endRow,1048575);await page.locator('[data-ribbon-command="cf-open"]').click();await page.getByText('D1:D1048576',{exact:true}).waitFor();assert.deepEqual(errors,[]);console.log(JSON.stringify({ok:true,phase:'cf-full-column-live',endRow:1048575,pageErrors:errors}));}else{
 const structural=await page.evaluate(async()=>{const api=window.__cfRuntime.univerAPI,sheet=api.getActiveWorkbook().getActiveSheet();sheet.insertRowsBefore(0,1);await new Promise(resolve=>setTimeout(resolve,250));const inserted=structuredClone(sheet.getConditionalFormattingRules());sheet.deleteRows(0,1);await new Promise(resolve=>setTimeout(resolve,250));return{inserted,deleted:sheet.getConditionalFormattingRules()}})
 console.log(JSON.stringify({phase:'cf-structure',...structural}));assert.equal(structural.inserted[0].ranges[0].startRow,2);assert.equal(structural.inserted[1].ranges[0].startRow,5001);assert.deepEqual(structural.deleted,imported)
 await page.locator('[data-ribbon-command="cf-open"]').click();await delay(600)
 await page.getByText('大于10',{exact:true}).dblclick();await delay(400)
 await page.locator('input[value="10"]:visible').fill('20');await page.getByRole('button',{name:'确认',exact:true}).click();await delay(400)
 assert.equal(await page.evaluate(()=>window.__cfRuntime.univerAPI.getActiveWorkbook().getActiveSheet().getConditionalFormattingRules()[0].rule.value),20)
 const row=page.getByText('大于20',{exact:true}).locator('../..');await row.hover();await row.locator('.univerjs-icon-delete-icon').click();await delay(350)
 assert.equal(await page.evaluate(()=>window.__cfRuntime.univerAPI.getActiveWorkbook().getActiveSheet().getConditionalFormattingRules().length),1)
 await page.locator('[data-ribbon-tab="File"]').click();await page.locator('[data-ribbon-command="undo"]').click();await delay(200)
 assert.equal(await page.evaluate(()=>window.__cfRuntime.univerAPI.getActiveWorkbook().getActiveSheet().getConditionalFormattingRules()[0].rule.value),20)
 await page.locator('[data-ribbon-command="redo"]').click();await delay(200)
 assert.equal(await page.evaluate(()=>window.__cfRuntime.univerAPI.getActiveWorkbook().getActiveSheet().getConditionalFormattingRules().length),1)
 await page.locator('[data-ribbon-command="undo"]').click();await delay(200)
 await page.reload();await page.waitForFunction(()=>document.querySelector('#report-editor')?.getAttribute('aria-busy')==='false',null,{timeout:60000});await page.locator('[data-ribbon-tab="Home"]').waitFor()
 const restored=await page.evaluate(()=>window.__cfRuntime.univerAPI.getActiveWorkbook().getActiveSheet().getConditionalFormattingRules());assert.equal(restored.length,2);assert.equal(restored[0].rule.value,20)
 await page.locator('[data-action="save"]').click();await page.waitForFunction(()=>document.querySelector('.save-state-label')?.textContent==='已保存修订 2',null,{timeout:60000})
 const actual=JSON.parse(python({mode:'inspect',bytes:saved.toString('base64')}));assert.equal(actual.rules.length,2);assert.equal(actual.rules[0].formula[0],'20');assert.equal(actual.rules[1].formula[0],'D5001>0');assert.equal(actual.A1,'keep');assert.equal(actual.F1,'=SUM(B2:B5)')
 console.log(JSON.stringify({ok:true,phase:'cf-dev-manager-edit-delete-undo-draft-save',actual,operations:payload.operations,pageErrors:errors}))
 assert.deepEqual(errors,[])
 }
}finally{await browser?.close();server.kill()}
