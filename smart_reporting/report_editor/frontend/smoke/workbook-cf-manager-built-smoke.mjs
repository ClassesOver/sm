import assert from 'node:assert/strict'
import { spawn, spawnSync } from 'node:child_process'
import { readFileSync } from 'node:fs'
import { createHash } from 'node:crypto'
import { setTimeout as delay } from 'node:timers/promises'
import { chromium } from 'playwright'
const frontend=process.cwd(), repo=new URL('../../../',`file://${frontend}/`).pathname,base='http://127.0.0.1:4206',linkedStructure=process.env.CF_LINKED_STRUCTURE==='1'
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
function linkedPython(payload){const r=spawnSync(`${repo}/.venv/bin/python`,['-c',`
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
const bytes=Buffer.from((linkedStructure?linkedPython:python)({mode:'create'}),'base64'),media='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
const context=source=>({documentId:'cf-built',format:'xlsx',revision:1,parentRevision:null,scope:{database:'f',companyId:'f',userId:'f',threadId:'f'},sourceFile:{path:'cf.xlsx',size:source.length,sha256:createHash('sha256').update(source).digest('hex'),mediaType:media},origin:'upload'})
const server=spawn('./node_modules/.bin/vite',['preview','--host','127.0.0.1','--port','4206','--strictPort'],{cwd:frontend,stdio:'ignore'})
let browser,saved,payload
try{
 for(let i=0;i<120;i++){try{if((await fetch(`${base}/reports/v1/editor/assets/native.html`)).ok)break}catch{}await delay(250)}
 browser=await chromium.launch({headless:true});const page=await browser.newPage({viewport:{width:1500,height:1100}}),errors=[],scriptProof=[]
 page.on('pageerror',e=>{errors.push(e.message);console.log(e.stack)})
 page.on('response',response=>{const url=new URL(response.url());if(url.pathname.startsWith('/reports/v1/editor/assets/')&&url.pathname.endsWith('.js'))scriptProof.push((async()=>{assert.equal(response.status(),200);const body=await response.body(),path=`../static/${url.pathname.slice('/reports/v1/editor/assets/'.length)}`;assert.equal(createHash('sha256').update(body).digest('hex'),createHash('sha256').update(readFileSync(path)).digest('hex'));return url.pathname})())})
 await page.route('**/reports/v1/native/cf-built/1/api/context',r=>r.fulfill({json:{context:context(bytes),csrfToken:'csrf',capabilities:{xlsx_editor:true},editingEnabled:true}}))
 await page.route('**/reports/v1/native/cf-built/1/api/file',r=>r.fulfill({body:bytes,contentType:media}))
 await page.route('**/reports/v1/native/cf-built/1/api/save',async r=>{payload=r.request().postDataJSON();saved=Buffer.from(python({mode:'patch',bytes:bytes.toString('base64'),operations:payload.operations}),'base64');await r.fulfill({json:{documentId:'cf-built',revision:2,parentRevision:1,revisionRegistered:true,artifacts:{xlsx:{downloadUrl:'/cf.xlsx'}},editor:{openUrl:'/reports/v1/native/cf-built/2'},validation:{issues:[]}}})})
 await page.route(/\/reports\/v1\/native\/cf-built\/[12]$/,async r=>r.fulfill({response:await r.fetch({url:`${base}/reports/v1/editor/assets/native.html`})}))
 await page.addInitScript(()=>history.replaceState(null,'','/reports/v1/native/cf-built/1'))
 const ready=async()=>{await page.waitForFunction(()=>document.querySelector('#report-editor')?.getAttribute('aria-busy')==='false',null,{timeout:60000});if(await page.locator('[data-ribbon-tab="Home"]').count()===0)throw Error('初始化失败：'+(await page.locator('body').innerText()).slice(-1000))}
 const manager=async()=>{await page.locator('[data-ribbon-tab="Home"]').click();await page.locator('[data-ribbon-command="cf-open"]').click()}
 const history=async action=>{await page.locator('[data-ribbon-tab="File"]').click();await page.locator(`[data-ribbon-command="${action}"]`).click()}
 const rule=number=>page.getByText(`大于${number}`,{exact:true})
 await page.goto(`${base}/reports/v1/editor/assets/native.html`);await ready();await manager();await rule(10).waitFor();await page.getByText('D5001:D5100',{exact:true}).waitFor();await page.screenshot({path:'/tmp/workbook-cf-built-import.png'})
 if(linkedStructure){
  await page.locator('[data-ribbon-command="goto-open"]').click();await page.locator('[data-goto-reference]').fill('A1');await page.locator('.workbook-ribbon-goto-dialog button[type="submit"]').click();await page.locator('[data-ribbon-command="insert-row-here"]').click();await page.getByText('D5002:D5101',{exact:true}).waitFor();await delay(700)
 }
 await rule(10).dblclick();await page.locator('input[value="10"]:visible').fill('20');await page.getByRole('button',{name:'确认',exact:true}).click();await rule(20).waitFor()
 const row=rule(20).locator('../..');await row.hover();await row.locator('.univerjs-icon-delete-icon').click();await rule(20).waitFor({state:'detached'})
 await history('undo');await rule(20).waitFor();await history('redo');await rule(20).waitFor({state:'detached'});await history('undo');await rule(20).waitFor()
 await page.waitForFunction(()=>Object.keys(localStorage).filter(key=>key.startsWith('native-editor-draft:')).some(key=>{try{return JSON.parse(localStorage.getItem(key)).operations.some(op=>op.kind==='replaceSheetConditionalFormats'&&op.rules.some(rule=>rule.rule.subType==='number'&&JSON.stringify(rule.rule.value)==='[20]'))}catch{return false}}),null,{timeout:30000});
 await page.reload();await ready();await manager();await rule(20).waitFor();await page.getByText(linkedStructure?'D5002:D5101':'D5001:D5100',{exact:true}).waitFor()
 await page.locator('[data-action="save"]').click();await page.waitForFunction(()=>document.querySelector('.save-state-label')?.textContent==='已保存修订 2',null,{timeout:60000})
 const actual=JSON.parse((linkedStructure?linkedPython:python)({mode:'inspect',bytes:saved.toString('base64')}));
 if(linkedStructure){assert.equal(actual.rules.length,3);assert(actual.rules.some(r=>r.type==='cellIs'&&r.formula[0]==='20'));assert(actual.rules.some(r=>r.type==='dataBar'&&r.range==='B2:B4'));assert(actual.zipXml.includes('<xm:sqref>B2:B4</xm:sqref>'));assert.equal(actual.A2,'keep');assert.equal(actual.F2,'=SUM(B3:B6)');delete actual.zipXml}
 else{assert.equal(actual.rules.length,2);assert.equal(actual.rules[0].formula[0],'20');assert.equal(actual.rules[1].formula[0],'D5001>0');assert.equal(actual.A1,'keep');assert.equal(actual.F1,'=SUM(B2:B5)')}
 assert.equal(payload.operations.filter(op=>op.kind==='replaceSheetConditionalFormats').length,1)
 await page.route('**/reports/v1/native/cf-built/2/api/context',r=>r.fulfill({json:{context:{...context(saved),revision:2,parentRevision:1},csrfToken:'csrf',capabilities:{xlsx_editor:true},editingEnabled:true}}))
 await page.route('**/reports/v1/native/cf-built/2/api/file',r=>r.fulfill({body:saved,contentType:media}))
 await page.addInitScript(()=>history.replaceState(null,'','/reports/v1/native/cf-built/2'));await page.goto(`${base}/reports/v1/native/cf-built/2`);await ready();await manager();await rule(20).waitFor();await page.getByText(linkedStructure?'D5002:D5101':'D5001:D5100',{exact:true}).waitFor()
 const scripts=await Promise.all(scriptProof);assert(scripts.some(path=>/workbook-main-/.test(path)));assert.deepEqual(errors,[])
 console.log(JSON.stringify({ok:true,preview:true,linkedStructure,officialManagerEditDeleteUndoRedo:true,draftRecovery:true,pythonPatchOpenpyxl:true,revisionReopen:true,actual,js200AndHashMatch:scripts.length,assets:[...new Set(scripts.filter(path=>/workbook-(main|engine-|conditional-formatting)/.test(path)))],pageErrors:errors}))
}finally{await browser?.close();server.kill()}
