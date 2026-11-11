import assert from 'node:assert/strict'
import { spawn,spawnSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import { readFileSync } from 'node:fs'
import { setTimeout as delay } from 'node:timers/promises'
import { chromium } from 'playwright'
const frontend=process.cwd(),repo=new URL('../../../',`file://${frontend}/`).pathname,base='http://127.0.0.1:4220'
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
 s.conditional_formatting.add('A1:A4',FormulaRule(formula=['TRUE'],fill=PatternFill('solid',fgColor='FFFFFF00')))
 other.conditional_formatting.add('B1:B4',FormulaRule(formula=['TRUE'],stopIfTrue=True,fill=PatternFill('solid',fgColor='FFFF0000')))
 other.conditional_formatting.add('B1:B4',FormulaRule(formula=['Source!A1>0'],fill=PatternFill('solid',fgColor='FF00FF00')))
 f=BytesIO();b.save(f);print(base64.b64encode(f.getvalue()).decode())
elif p['mode']=='patch':print(base64.b64encode(patch_office('xlsx',base64.b64decode(p['bytes']),p['operations'])).decode())
else:
 raw=base64.b64decode(p['bytes']);b=load_workbook(BytesIO(raw));source=b['Source'];other=b['Other']
 def rules(s):return [{'range':str(key.sqref),'formula':r.formula,'stop':r.stopIfTrue,'priority':r.priority} for key,value in s.conditional_formatting._cf_rules.items() for r in value]
 before=ZipFile(BytesIO(base64.b64decode(p['original'])));after=ZipFile(BytesIO(raw))
 print(json.dumps({'sourceRules':rules(source),'rules':rules(other),'sourceValues':[source.cell(i,1).value for i in range(1,7)],'insertedDirectFill':source['A2'].fill.fill_type,'lastRowHeight':source.row_dimensions[6].height,'otherValues':[other.cell(i,2).value for i in range(1,6)],'changedParts':[name for name in before.namelist() if before.read(name)!=after.read(name)]}))
`],{input:JSON.stringify(payload),encoding:'utf8',cwd:repo});assert.equal(r.status,0,r.stderr);return r.stdout.trim()}
const bytes=Buffer.from(python({mode:'create'}),'base64'),media='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
const context=source=>({documentId:'cf-split-built',format:'xlsx',revision:1,parentRevision:null,scope:{database:'f',companyId:'f',userId:'f',threadId:'f'},sourceFile:{path:'cf.xlsx',size:source.length,sha256:createHash('sha256').update(source).digest('hex'),mediaType:media},origin:'upload'})
const server=spawn('./node_modules/.bin/vite',['preview','--host','127.0.0.1','--port','4220','--strictPort'],{cwd:frontend,stdio:'ignore'})
let browser,saved,payload
try{
 for(let i=0;i<120;i++){try{if((await fetch(`${base}/reports/v1/editor/assets/native.html`)).ok)break}catch{}await delay(250)}
 browser=await chromium.launch({headless:true});const page=await browser.newPage({viewport:{width:1500,height:1100}}),errors=[],scriptProof=[]
 page.on('pageerror',e=>{errors.push(e.message);console.log(e.stack)})
 page.on('response',response=>{const url=new URL(response.url());if(url.pathname.startsWith('/reports/v1/editor/assets/')&&url.pathname.endsWith('.js'))scriptProof.push((async()=>{assert.equal(response.status(),200);const body=await response.body(),path=`../static/${url.pathname.slice('/reports/v1/editor/assets/'.length)}`;assert.equal(createHash('sha256').update(body).digest('hex'),createHash('sha256').update(readFileSync(path)).digest('hex'));return url.pathname})())})
 await page.route('**/reports/v1/native/cf-split-built/1/api/context',r=>r.fulfill({json:{context:context(bytes),csrfToken:'csrf',capabilities:{xlsx_editor:true},editingEnabled:true}}))
 await page.route('**/reports/v1/native/cf-split-built/1/api/file',r=>r.fulfill({body:bytes,contentType:media}))
 await page.route('**/reports/v1/native/cf-split-built/1/api/save',async r=>{payload=r.request().postDataJSON();saved=Buffer.from(python({mode:'patch',bytes:bytes.toString('base64'),operations:payload.operations}),'base64');await r.fulfill({json:{documentId:'cf-split-built',revision:2,parentRevision:1,revisionRegistered:true,artifacts:{xlsx:{downloadUrl:'/cf.xlsx'}},editor:{openUrl:'/reports/v1/native/cf-split-built/2'},validation:{issues:[]}}})})
 await page.route(/\/reports\/v1\/native\/cf-split-built\/[12]$/,async r=>r.fulfill({response:await r.fetch({url:`${base}/reports/v1/editor/assets/native.html`})}))
 await page.addInitScript(()=>history.replaceState(null,'','/reports/v1/native/cf-split-built/1'))
 const ready=async()=>{await page.waitForFunction(()=>document.querySelector('#report-editor')?.getAttribute('aria-busy')==='false',null,{timeout:60000});await page.locator('[data-ribbon-tab="Home"]').waitFor()}
 const goto=async ref=>{await page.locator('[data-ribbon-tab="Home"]').click();await page.locator('[data-ribbon-command="goto-open"]').click();await page.locator('[data-goto-reference]').fill(ref);await page.locator('.workbook-ribbon-goto-dialog button[type="submit"]').click()}
 const manager=async()=>{await page.locator('[data-ribbon-tab="Home"]').click();await page.locator('[data-ribbon-command="cf-open"]').click()}
 const history=async action=>{await page.locator('[data-ribbon-tab="File"]').click();await page.locator(`[data-ribbon-command="${action}"]`).click()}
 const groups=async count=>{await goto('Other!B1');await manager();await page.getByText('B1:B4',{exact:true}).first().waitFor();if(count===3){await page.getByText('B1',{exact:true}).waitFor();await page.getByText('B2:B4',{exact:true}).waitFor()}else{assert.equal(await page.getByText('B2:B4',{exact:true}).count(),0)}}
 const own=async shifted=>{await goto('Source!A2');await manager();await page.getByText(shifted?/^A1.*A3:A5$/:/^A1:A4$/).first().waitFor()}
 await page.goto(`${base}/reports/v1/editor/assets/native.html`);await ready();await groups(2);await own(false);await goto('Source!A2');await page.locator('[data-ribbon-command="insert-cells"]').click();await page.locator('input[name="workbook-cells-choice"][value="shift-vertical"]').check();await page.locator('.workbook-ribbon-cells-dialog button[type="submit"]').click();await groups(3);await own(true)
 await history('undo');await groups(2);await own(false);await history('redo');await groups(3);await own(true)
 await page.waitForFunction(()=>Object.keys(localStorage).filter(key=>key.startsWith('native-editor-draft:')).some(key=>{try{return JSON.parse(localStorage.getItem(key)).operations.some(op=>op.kind==='applyCellShift')}catch{return false}}),null,{timeout:30000})
 await page.reload();await ready();await groups(3);await own(true)
 await page.locator('[data-action="save"]').click();await page.waitForFunction(()=>document.querySelector('.save-state-label')?.textContent==='已保存修订 2',null,{timeout:60000})
 const actual=JSON.parse(python({mode:'inspect',bytes:saved.toString('base64'),original:bytes.toString('base64')}));assert.deepEqual(actual.rules.map(rule=>({range:rule.range,formula:rule.formula[0],stop:rule.stop===true})),[{range:'B1:B4',formula:'TRUE',stop:true},{range:'B1',formula:'Source!A1>0',stop:false},{range:'B2:B4',formula:'Source!A3>0',stop:false}]);assert.deepEqual(actual.rules.map(rule=>rule.priority),[1,2,3]);assert.deepEqual(actual.sourceRules.map(rule=>rule.range),['A1 A3:A5']);assert.equal(actual.insertedDirectFill,null);assert.equal(actual.lastRowHeight,18);assert.deepEqual(actual.sourceValues,[1,null,2,3,4,5]);assert.deepEqual(actual.otherValues,[1,2,3,4,5]);assert.deepEqual(actual.changedParts.sort(),['xl/worksheets/sheet1.xml','xl/worksheets/sheet2.xml']);assert.deepEqual(payload.operations,[{kind:'applyCellShift',sheetName:'Source',range:'A2',shift:'down'},{kind:'applyRowHeights',sheetName:'Source',entries:[{index:5,heightPoints:18}]}])
 await page.route('**/reports/v1/native/cf-split-built/2/api/context',r=>r.fulfill({json:{context:{...context(saved),revision:2,parentRevision:1},csrfToken:'csrf',capabilities:{xlsx_editor:true},editingEnabled:true}}))
 await page.route('**/reports/v1/native/cf-split-built/2/api/file',r=>r.fulfill({body:saved,contentType:media}))
 await page.addInitScript(()=>history.replaceState(null,'','/reports/v1/native/cf-split-built/2'));await page.goto(`${base}/reports/v1/native/cf-split-built/2`);await ready();await groups(3);await own(true)
 const scripts=await Promise.all(scriptProof);assert(scripts.some(path=>/workbook-main-/.test(path)));assert.deepEqual(errors,[]);console.log(JSON.stringify({ok:true,preview:true,ownGapUnpainted:true,crossSheetSplitPriority:true,nativeUndoRedo:true,draftRecovery:true,pythonPatchOpenpyxl:true,revisionReopen:true,operations:payload.operations,actual,js200AndHashMatch:scripts.length,assets:[...new Set(scripts.filter(path=>/workbook-(main|engine-|structure)/.test(path)))],pageErrors:errors}))
}finally{await browser?.close();server.kill()}
