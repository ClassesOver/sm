import assert from 'node:assert/strict'
import { spawn, spawnSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import { readFileSync } from 'node:fs'
import { setTimeout as delay } from 'node:timers/promises'
import { chromium } from 'playwright'
const frontend=process.cwd(), repo=new URL('../../../',`file://${frontend}/`).pathname,base='http://127.0.0.1:4227',clearSource=process.env.DV_REMOVAL_CLEAR_SOURCE==='1',allow=process.env.DV_REMOVAL_ALLOW==='1'||clearSource
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
const server=spawn('./node_modules/.bin/vite',['preview','--host','127.0.0.1','--port','4227','--strictPort'],{cwd:frontend,stdio:'ignore'})
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
 await page.goto(`${base}/reports/v1/editor/assets/native.html`);await page.waitForFunction(()=>document.querySelector('#report-editor')?.getAttribute('aria-busy')==='false',null,{timeout:60000}).catch(async error=>{console.log(JSON.stringify({phase:'dv-load-failure',body:(await page.locator('body').innerText()).slice(-4000)}));throw error});await page.locator('[data-ribbon-tab="Home"]').waitFor()
 await page.waitForTimeout(500)
 const beforeDraft=await page.evaluate(()=>Object.fromEntries(Object.entries(localStorage))),beforeSaveLabel=await page.locator('.save-state-label').textContent()
 const tab=name=>page.locator('[data-u-comp="slide-tab-item"]').filter({hasText:name})
 const panel=async()=>{await tab('Other').click();await page.locator('[data-ribbon-tab="Data"]').click();await page.locator('[data-ribbon-command="dv-open"]').click()}
 const history=async action=>{await page.locator('[data-ribbon-tab="File"]').click();await page.locator(`[data-ribbon-command="${action}"]`).click()}
 const remove=async()=>{await tab('Source').click({button:'right'});await page.getByText('删除',{exact:true}).last().click();await page.getByRole('button',{name:'确定',exact:true}).click()}
 await remove();await page.getByText('工作表 "Other" 的数据验证仍引用 "Source"，已拒绝删除。',{exact:true}).waitFor();await tab('Source').waitFor();await history('undo');await tab('Source').waitFor();await history('redo');await tab('Source').waitFor();assert.deepEqual(await page.evaluate(()=>Object.fromEntries(Object.entries(localStorage))),beforeDraft);assert.equal(await page.locator('.save-state-label').textContent(),beforeSaveLabel);assert.equal(saved,undefined)
 await panel();const row=page.getByText('B1:B4',{exact:true}).locator('..');await row.hover();await row.locator('.univerjs-icon-delete-icon').click();await page.getByText('B1:B4',{exact:true}).waitFor({state:'detached'})
 await remove();await tab('Source').waitFor({state:'detached'});await history('undo');await tab('Source').waitFor();await history('redo');await tab('Source').waitFor({state:'detached'})
 {  await page.waitForFunction(()=>Object.keys(localStorage).filter(key=>key.startsWith('native-editor-draft:')).some(key=>{try{return JSON.parse(localStorage.getItem(key)).operations.some(op=>op.kind==='applySheetEdits'&&op.plan.removals.length)}catch{return false}}),null,{timeout:30000})
  await page.reload();await page.waitForFunction(()=>document.querySelector('#report-editor')?.getAttribute('aria-busy')==='false',null,{timeout:60000});await tab('Other').waitFor();assert.equal(await tab('Source').count(),0)
  await page.locator('[data-action="save"]').click();await page.waitForFunction(()=>document.querySelector('.save-state-label')?.textContent==='已保存修订 2',null,{timeout:60000})
  const actual=JSON.parse(python({mode:'inspect',bytes:saved.toString('base64'),original:bytes.toString('base64')}));assert.deepEqual(actual.sheetNames,['Other']);assert.deepEqual(actual.rules,clearSource?[]:[{range:'B1:B4',type:'list',formula1:'"yes,no"',formula2:null}]);assert.equal(actual.otherXmlUnchanged,!clearSource);assert.equal(actual.stylesUnchanged,true);assert.deepEqual(actual.values,[1,2,3,4,5]);const removal={kind:'applySheetEdits',plan:{renames:[],additions:[],removals:['Source'],order:['Other']}};if(clearSource){assert.equal(payload.operations.length,2);assert.equal(payload.operations[0].kind,'replaceSheetDataValidations');assert.equal(payload.operations[0].sheetName,'Other');assert.equal(payload.operations[0].rules.length,0);assert.deepEqual(payload.operations[1],removal)}else assert.deepEqual(payload.operations,[removal])
  await page.route('**/reports/v1/native/cf-probe/2/api/context',route=>route.fulfill({json:{context:{...context,revision:2,parentRevision:1,sourceFile:{...context.sourceFile,size:saved.length,sha256:createHash('sha256').update(saved).digest('hex')}},csrfToken:'csrf',capabilities:{xlsx_editor:true},editingEnabled:true}}));await page.route('**/reports/v1/native/cf-probe/2/api/file',route=>route.fulfill({body:saved,contentType:media}));await page.addInitScript(()=>history.replaceState(null,'','/reports/v1/native/cf-probe/2'));await page.goto(`${base}/reports/v1/native/cf-probe/2`);await page.waitForFunction(()=>document.querySelector('#report-editor')?.getAttribute('aria-busy')==='false',null,{timeout:60000});await tab('Other').waitFor();assert.equal(await tab('Source').count(),0);console.log(JSON.stringify({phase:'allowed-remove-save',actual,operations:payload.operations}))
 }
 const scripts=await Promise.all(scriptProof);assert(scripts.some(path=>/workbook-main-/.test(path)));console.log(JSON.stringify({ok:true,preview:true,phase:'dv-remove-contract',clearSource:true,atomicRefusal:true,allowedHistoryDraftPythonRevision:true,js200AndHashMatch:scripts.length,assets:[...new Set(scripts.filter(path=>/workbook-(main|engine-|structure)/.test(path)))],pageErrors:errors}));assert.deepEqual(errors,[])
}finally{await browser?.close();server.kill()}
