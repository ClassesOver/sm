import assert from 'node:assert/strict'
import { spawn, spawnSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import { setTimeout as delay } from 'node:timers/promises'
import { chromium } from 'playwright'

const frontend=process.cwd(),repo=new URL('../../../',`file://${frontend}/`).pathname,base='http://127.0.0.1:4219'
function python(payload){const result=spawnSync(`${repo}/.venv/bin/python`,['-c',`
import json,sys,base64
from io import BytesIO
from zipfile import ZipFile
from openpyxl import Workbook,load_workbook
from openpyxl.formatting.rule import FormulaRule
from openpyxl.styles import PatternFill
from smart_reporting.report_editor.native_office import patch_office
p=json.load(sys.stdin)
if p['mode']=='create':
 b=Workbook();s=b.active;s.title='Source';other=b.create_sheet('Other')
 for i in range(1,6):s.cell(i,1,i);other.cell(i,2,i)
 s.conditional_formatting.add('A1:A4',FormulaRule(formula=['TRUE'],fill=PatternFill('solid',fgColor='FFFFFF00')))
 other.conditional_formatting.add('B1:B4',FormulaRule(formula=['TRUE'],stopIfTrue=True,fill=PatternFill('solid',fgColor='FFFF0000')))
 other.conditional_formatting.add('B1:B4',FormulaRule(formula=['Source!A1>0'],fill=PatternFill('solid',fgColor='FF00FF00')))
 f=BytesIO();b.save(f);print(base64.b64encode(f.getvalue()).decode())
elif p['mode']=='patch':print(base64.b64encode(patch_office('xlsx',base64.b64decode(p['bytes']),p['operations'])).decode())
else:
 raw=base64.b64decode(p['bytes']);b=load_workbook(BytesIO(raw));source=b['Source'];other=b['Other']
 def rules(s):return [{'range':str(key.sqref),'formula':r.formula,'stop':r.stopIfTrue,'priority':r.priority} for key,value in s.conditional_formatting._cf_rules.items() for r in value]
 before=ZipFile(BytesIO(base64.b64decode(p['original'])));after=ZipFile(BytesIO(raw))
 changed=[name for name in before.namelist() if before.read(name)!=after.read(name)]
 print(json.dumps({'sourceRules':rules(source),'otherRules':rules(other),'sourceValues':[source.cell(i,1).value for i in range(1,7)],'insertedDirectFill':source['A2'].fill.fill_type,'otherValues':[other.cell(i,2).value for i in range(1,6)],'changedParts':changed}))
`],{input:JSON.stringify(payload),encoding:'utf8',cwd:repo});assert.equal(result.status,0,result.stderr);return result.stdout.trim()}
const bytes=Buffer.from(python({mode:'create'}),'base64'),media='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
const context=(source,revision=1)=>({documentId:'cf-cells',format:'xlsx',revision,parentRevision:revision===1?null:1,scope:{database:'f',companyId:'f',userId:'f',threadId:'f'},sourceFile:{path:'cf.xlsx',size:source.length,sha256:createHash('sha256').update(source).digest('hex'),mediaType:media},origin:'upload'})
const server=spawn('./node_modules/.bin/vite',['--host','127.0.0.1','--port','4219','--strictPort'],{cwd:frontend,stdio:'ignore'})
let browser,saved,payload
try{
 for(let i=0;i<120;i++){try{if((await fetch(`${base}/reports/v1/editor/assets/native.html`)).ok)break}catch{}await delay(250)}
 browser=await chromium.launch({headless:true});const page=await browser.newPage({viewport:{width:1500,height:1100}}),errors=[]
 page.on('pageerror',error=>{errors.push(error.message);console.log(error.stack)})
 await page.route('**/src/workbook-vendor/grid/create-univer.ts*',async route=>{const response=await route.fetch(),body=await response.text(),needle='return { univer, univerAPI: FUniver.newAPI(univer) };';assert(body.includes(needle));await route.fulfill({response,body:body.replace(needle,'return window.__cfRuntime={univer,univerAPI:FUniver.newAPI(univer)};')})})
 if(process.env.CF_CELL_DIAGNOSTIC==='1')await page.route('**/src/workbook-data-validation-structure.ts*',async route=>{const response=await route.fetch(),body=await response.text(),needle='const result = original.call(this, command);';assert(body.includes(needle));await route.fulfill({response,body:body.replace(needle,`${needle} (window.__cfCellCollectors??=[]).push(structuredClone({command,result}));`)})})
 for(const revision of [1,2]){
  await page.route(`**/reports/v1/native/cf-cells/${revision}/api/context`,route=>route.fulfill({json:{context:context(revision===1?bytes:saved,revision),csrfToken:'csrf',capabilities:{xlsx_editor:true},editingEnabled:true}}))
  await page.route(`**/reports/v1/native/cf-cells/${revision}/api/file`,route=>route.fulfill({body:revision===1?bytes:saved,contentType:media}))
 }
 await page.route('**/reports/v1/native/cf-cells/1/api/save',async route=>{payload=route.request().postDataJSON();saved=Buffer.from(python({mode:'patch',bytes:bytes.toString('base64'),operations:payload.operations}),'base64');await route.fulfill({json:{documentId:'cf-cells',revision:2,parentRevision:1,revisionRegistered:true,artifacts:{xlsx:{downloadUrl:'/cf.xlsx'}},editor:{openUrl:'/reports/v1/native/cf-cells/2'},validation:{issues:[]}}})})
 await page.route(/\/reports\/v1\/native\/cf-cells\/[12]$/,async route=>route.fulfill({response:await route.fetch({url:`${base}/reports/v1/editor/assets/native.html`})}))
 await page.addInitScript(()=>history.replaceState(null,'','/reports/v1/native/cf-cells/1'))
 const ready=async()=>{await page.waitForFunction(()=>document.querySelector('#report-editor')?.getAttribute('aria-busy')==='false',null,{timeout:60000});await page.locator('[data-ribbon-tab="Home"]').waitFor()}
 const read=()=>page.evaluate(()=>{const book=window.__cfRuntime.univerAPI.getActiveWorkbook();return{source:structuredClone(book.getSheetByName('Source').getConditionalFormattingRules()),other:structuredClone(book.getSheetByName('Other').getConditionalFormattingRules())}})
 const raw=()=>page.evaluate(()=>{const source=window.__cfRuntime.univerAPI.getActiveWorkbook().getSheetByName('Source').getSheet(),snapshot=source.getSnapshot();return{raw:structuredClone(source.getCellRaw(1,0)),projected:structuredClone(source.getCell(1,0)),snapshot:structuredClone(snapshot.cellData),anchorHeight:source.getRowHeight(0),defaultRowHeight:snapshot.defaultRowHeight,rowData:structuredClone(snapshot.rowData),collectors:window.__cfCellCollectors}})
 const coverage=rules=>rules.flatMap(rule=>rule.ranges.flatMap(range=>Array.from({length:range.endRow-range.startRow+1},(_,index)=>`${range.startRow+index}:${range.startColumn}`))).sort()
 const check=state=>{assert.deepEqual(coverage(state.source),['0:0','2:0','3:0','4:0']);assert.deepEqual(state.other.map(rule=>({value:rule.rule.value,stop:rule.stopIfTrue===true,ranges:rule.ranges.map(range=>[range.startRow,range.endRow,range.startColumn,range.endColumn])})),[{value:'=TRUE',stop:true,ranges:[[0,3,1,1]]},{value:'=Source!A1>0',stop:false,ranges:[[0,0,1,1]]},{value:'=Source!A3>0',stop:false,ranges:[[1,3,1,1]]}])}
 await page.goto(`${base}/reports/v1/editor/assets/native.html`);await ready();const before=await read(),beforeRaw=await raw();console.log(JSON.stringify({phase:'raw-before',...beforeRaw}))
 const accepted=await page.evaluate(async()=>{const api=window.__cfRuntime.univerAPI,book=api.getActiveWorkbook(),source=book.getSheetByName('Source');book.setActiveSheet(source);source.getRange('A2').activate();return api.executeCommand('sheet.command.insert-range-move-down',{range:{startRow:1,endRow:1,startColumn:0,endColumn:0}})})
 assert.equal(accepted,true);await page.waitForFunction(()=>window.__cfRuntime.univerAPI.getActiveWorkbook().getSheetByName('Other').getConditionalFormattingRules().length===3);const after=await read(),afterRaw=await raw();check(after);console.log(JSON.stringify({phase:'native-insert',before,after}));console.log(JSON.stringify({phase:'raw-after',...afterRaw}));assert.equal(afterRaw.raw?.s,undefined);assert.equal(afterRaw.rowData[5].h,beforeRaw.anchorHeight)
 assert.equal(await page.evaluate(()=>window.__cfRuntime.univerAPI.undo()),true);assert.deepEqual(await read(),before)
 assert.equal(await page.evaluate(()=>window.__cfRuntime.univerAPI.redo()),true);assert.deepEqual(await read(),after)
 await page.waitForFunction(()=>Object.keys(localStorage).filter(key=>key.startsWith('native-editor-draft:')).some(key=>{try{return JSON.parse(localStorage.getItem(key)).operations.some(op=>op.kind==='applyCellShift')}catch{return false}}),null,{timeout:30000})
 await page.reload();await ready();check(await read())
 await page.locator('[data-action="save"]').click();await page.waitForFunction(()=>document.querySelector('.save-state-label')?.textContent==='已保存修订 2',null,{timeout:60000}).catch(async error=>{console.log(JSON.stringify({phase:'save-failed',body:(await page.locator('body').innerText()).slice(-3000)}));throw error})
 assert.deepEqual(payload.operations,[{kind:'applyCellShift',sheetName:'Source',range:'A2',shift:'down'},{kind:'applyRowHeights',sheetName:'Source',entries:[{index:5,heightPoints:beforeRaw.anchorHeight*72/96}]}])
 const actual=JSON.parse(python({mode:'inspect',bytes:saved.toString('base64'),original:bytes.toString('base64')}));console.log(JSON.stringify({phase:'python-save',actual,operations:payload.operations}))
 assert.deepEqual(actual.otherRules.map(rule=>({range:rule.range,formula:rule.formula[0],stop:rule.stop===true})),[{range:'B1:B4',formula:'TRUE',stop:true},{range:'B1',formula:'Source!A1>0',stop:false},{range:'B2:B4',formula:'Source!A3>0',stop:false}])
 assert.deepEqual(actual.otherRules.map(rule=>rule.priority),[1,2,3]);assert.deepEqual(actual.sourceValues,[1,null,2,3,4,5]);assert.equal(actual.insertedDirectFill,null);assert.deepEqual(actual.otherValues,[1,2,3,4,5]);assert(actual.sourceRules.every(rule=>!rule.range.split(' ').includes('A2')))
 assert.deepEqual(actual.changedParts.sort(),['xl/worksheets/sheet1.xml','xl/worksheets/sheet2.xml'])
 await page.addInitScript(()=>history.replaceState(null,'','/reports/v1/native/cf-cells/2'));await page.goto(`${base}/reports/v1/native/cf-cells/2`);await ready();check(await read());assert.deepEqual(errors,[])
 console.log(JSON.stringify({ok:true,ownGapUnpainted:true,parentPriority:true,nativeUndoRedo:true,draftRecovery:true,pythonPatchOpenpyxl:true,revisionReopen:true,operations:payload.operations,actual,pageErrors:errors}))
}finally{await browser?.close();server.kill()}
