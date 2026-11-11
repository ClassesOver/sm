import assert from 'node:assert/strict'
import { spawn, spawnSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import { setTimeout as delay } from 'node:timers/promises'
import { chromium } from 'playwright'
const frontend=process.cwd(), repo=new URL('../../../',`file://${frontend}/`).pathname,base='http://127.0.0.1:4207',fullColumn=false,editAfterStructure=process.env.CF_EDIT_AFTER_STRUCTURE==='1'
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
 b=Workbook();s=b.active;s.title='Values'
 for row,value in enumerate([5,15,25,35],2):s.cell(row,2,value)
 s['A1']='keep';s['F1']='=SUM(B2:B5)'
 s.conditional_formatting.add('B2:B5',CellIsRule(operator='greaterThan',formula=['10'],stopIfTrue=True,fill=PatternFill('solid',fgColor='FFFF0000')))
 s.conditional_formatting.add('D1:D1048576' if p.get('fullColumn') else 'D5001:D5100',FormulaRule(formula=['D1>0' if p.get('fullColumn') else 'D5001>0'],fill=PatternFill('solid',fgColor='FF00FF00')))
 f=BytesIO();b.save(f)
 zin=ZipFile(BytesIO(f.getvalue()));out=BytesIO();ns='http://schemas.microsoft.com/office/spreadsheetml/2009/9/main'
 base='<conditionalFormatting sqref="B1:B3"><cfRule type="dataBar" priority="3"><dataBar><cfvo type="min"/><cfvo type="max"/><color rgb="FF638EC6"/></dataBar><extLst><ext uri="{B025F937-C7B1-47D3-B67F-A62EFF666E3E}" xmlns:x14="'+ns+'"><x14:id>linked-id</x14:id></ext></extLst></cfRule></conditionalFormatting>'
 twin='<extLst><ext uri="{78C0D931-6437-407D-A8EE-F0AAD7539E65}" xmlns:x14="'+ns+'"><x14:conditionalFormattings><x14:conditionalFormatting xmlns:xm="http://schemas.microsoft.com/office/excel/2006/main"><x14:cfRule type="dataBar" priority="3" id="linked-id"><x14:dataBar minLength="0" maxLength="100"><x14:cfvo type="autoMin"/><x14:cfvo type="autoMax"/><x14:negativeFillColor rgb="FFFF0000"/></x14:dataBar></x14:cfRule><xm:sqref>B1:B3</xm:sqref></x14:conditionalFormatting></x14:conditionalFormattings></ext></extLst>'
 with ZipFile(out,'w',ZIP_DEFLATED) as zout:
  for name in zin.namelist():
   part=zin.read(name)
   if name=='xl/worksheets/sheet1.xml':part=part.decode().replace('</worksheet>',base+twin+'</worksheet>').encode()
   zout.writestr(name,part)
 print(base64.b64encode(out.getvalue()).decode())
elif p['mode']=='patch':print(base64.b64encode(patch_office('xlsx',base64.b64decode(p['bytes']),p['operations'])).decode())
else:
 b=load_workbook(BytesIO(base64.b64decode(p['bytes'])));s=b['Values'];print(json.dumps({'rules':[{'range':str(key.sqref),'type':r.type,'formula':r.formula,'stop':r.stopIfTrue} for key,value in s.conditional_formatting._cf_rules.items() for r in value],'A1':s['A1'].value,'F1':s['F1'].value,'A2':s['A2'].value,'F2':s['F2'].value,'zipXml':ZipFile(BytesIO(base64.b64decode(p['bytes']))).read('xl/worksheets/sheet1.xml').decode()}))
`],{input:JSON.stringify(payload),encoding:'utf8',cwd:repo});assert.equal(r.status,0,r.stderr);return r.stdout.trim()}
const bytes=Buffer.from(python({mode:'create',fullColumn}),'base64'),media='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',context={documentId:'cf-probe',format:'xlsx',revision:1,parentRevision:null,scope:{database:'f',companyId:'f',userId:'f',threadId:'f'},sourceFile:{path:'cf.xlsx',size:bytes.length,sha256:createHash('sha256').update(bytes).digest('hex'),mediaType:media},origin:'upload'}
const server=spawn('./node_modules/.bin/vite',['--host','127.0.0.1','--port','4207','--strictPort'],{cwd:frontend,stdio:'ignore'})
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
 const imported=await page.evaluate(()=>window.__cfRuntime.univerAPI.getActiveWorkbook().getActiveSheet().getConditionalFormattingRules());assert.equal(imported.length,3)
 const result=await page.evaluate(async()=>{
  const api=window.__cfRuntime.univerAPI,sheet=api.getActiveWorkbook().getActiveSheet(),linked=sheet.getConditionalFormattingRules().find(r=>r.rule.type==='dataBar')
  const denied=api.syncExecuteCommand('sheet.command.set-conditional-rule',{unitId:api.getActiveWorkbook().getId(),subUnitId:sheet.getSheetId(),cfId:linked.cfId,rule:{...linked,stopIfTrue:!linked.stopIfTrue}})
  const unchanged=structuredClone(sheet.getConditionalFormattingRules())
  sheet.insertRowsBefore(0,1);await new Promise(r=>setTimeout(r,350));const inserted=structuredClone(sheet.getConditionalFormattingRules())
  const undo=await api.undo();const undone=structuredClone(sheet.getConditionalFormattingRules());const redo=await api.redo();const redone=structuredClone(sheet.getConditionalFormattingRules())
  return{denied,unchanged,inserted,undo,undone,redo,redone}
 });console.log(JSON.stringify({phase:'cf-linked-structure',...result}));assert.equal(result.denied,false);assert.deepEqual(result.unchanged,imported);assert.equal(result.inserted.find(r=>r.rule.type==='dataBar').ranges[0].startRow,1);assert.equal(result.undo,true);assert.deepEqual(result.undone,imported);assert.equal(result.redo,true);assert.deepEqual(result.redone,result.inserted)
 if(editAfterStructure){const edited=await page.evaluate(()=>{const api=window.__cfRuntime.univerAPI,sheet=api.getActiveWorkbook().getActiveSheet(),ordinary=sheet.getConditionalFormattingRules().find(r=>r.rule.type==='highlightCell'&&r.rule.subType==='number');return api.syncExecuteCommand('sheet.command.set-conditional-rule',{unitId:api.getActiveWorkbook().getId(),subUnitId:sheet.getSheetId(),cfId:ordinary.cfId,rule:{...ordinary,rule:{...ordinary.rule,value:20}}})});console.log(JSON.stringify({phase:'cf-ordinary-edit-after-linked-structure',edited,feedback:await page.locator('.workbook-feedback').allTextContents()}));assert.equal(edited,true);await page.waitForFunction(()=>Object.keys(localStorage).filter(key=>key.startsWith('native-editor-draft:')).some(key=>{try{return JSON.parse(localStorage.getItem(key)).operations.some(op=>op.kind==='replaceSheetConditionalFormats'&&op.rules.some(rule=>rule.rule.subType==='number'&&JSON.stringify(rule.rule.value)==='[20]'))}catch{return false}}),null,{timeout:30000}).catch(async error=>{console.log(JSON.stringify({phase:'cf-draft-diagnostic',feedback:await page.locator('.workbook-feedback').allTextContents(),storage:await page.evaluate(()=>Object.fromEntries(Object.keys(localStorage).filter(key=>key.startsWith('native-editor-draft:')).map(key=>[key,localStorage.getItem(key)]))),rules:await page.evaluate(()=>window.__cfRuntime.univerAPI.getActiveWorkbook().getActiveSheet().getConditionalFormattingRules())}));throw error});}
 await page.reload();await page.waitForFunction(()=>document.querySelector('#report-editor')?.getAttribute('aria-busy')==='false',null,{timeout:60000});await page.locator('[data-ribbon-tab="Home"]').waitFor();const restored=await page.evaluate(()=>window.__cfRuntime.univerAPI.getActiveWorkbook().getActiveSheet().getConditionalFormattingRules());assert.equal(restored.find(r=>r.rule.type==='dataBar').ranges[0].startRow,1);if(editAfterStructure)assert.equal(restored.find(r=>r.rule.subType==='number').rule.value,20);
 await page.locator('[data-action="save"]').click();await page.waitForFunction(()=>document.querySelector('.save-state-label')?.textContent==='已保存修订 2',null,{timeout:60000}).catch(async e=>{console.log(JSON.stringify({phase:'cf-linked-save-failed',body:(await page.locator('body').innerText()).slice(-2200)}));throw e})
 const actual=JSON.parse(python({mode:'inspect',bytes:saved.toString('base64')}));assert(actual.rules.some(r=>r.type==='dataBar'&&r.range==='B2:B4'));assert.equal(actual.A2,'keep');assert.equal(actual.F2,'=SUM(B3:B6)');if(editAfterStructure)assert(actual.rules.some(r=>r.type==='cellIs'&&r.formula[0]==='20'));assert(actual.zipXml.includes('<xm:sqref>B2:B4</xm:sqref>'));assert(actual.zipXml.includes('sqref="B2:B4"'));delete actual.zipXml;assert.deepEqual(errors,[]);console.log(JSON.stringify({ok:true,phase:'cf-linked-structure-python-save',actual,operations:payload.operations,pageErrors:errors}))
}finally{await browser?.close();server.kill()}
