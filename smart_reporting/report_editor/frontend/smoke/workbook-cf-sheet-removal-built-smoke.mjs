import assert from 'node:assert/strict'
import { spawn, spawnSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import { readFileSync } from 'node:fs'
import { setTimeout as delay } from 'node:timers/promises'
import { chromium } from 'playwright'
const frontend=process.cwd(), repo=new URL('../../../',`file://${frontend}/`).pathname,base='http://127.0.0.1:4225',clearSource=process.env.CF_REMOVAL_CLEAR_SOURCE==='1',allow=process.env.CF_REMOVAL_ALLOW==='1'||clearSource
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
 other.conditional_formatting.add('B1:B4',FormulaRule(formula=['TRUE' if p.get('allow') else 'Source!A1>0'],fill=PatternFill('solid',fgColor='FF00FF00')))
 f=BytesIO();b.save(f);print(base64.b64encode(f.getvalue()).decode())
elif p['mode']=='patch':print(base64.b64encode(patch_office('xlsx',base64.b64decode(p['bytes']),p['operations'])).decode())
else:
 raw=base64.b64decode(p['bytes']);b=load_workbook(BytesIO(raw));s=b['Other'];before=ZipFile(BytesIO(base64.b64decode(p['original'])));after=ZipFile(BytesIO(raw));print(json.dumps({'sheetNames':b.sheetnames,'rules':[{'range':str(key.sqref),'type':r.type,'formula':r.formula,'stop':r.stopIfTrue,'priority':r.priority} for key,value in s.conditional_formatting._cf_rules.items() for r in value],'values':[s.cell(i,2).value for i in range(1,6)],'otherXmlUnchanged':before.read('xl/worksheets/sheet2.xml')==after.read('xl/worksheets/sheet2.xml'),'stylesUnchanged':before.read('xl/styles.xml')==after.read('xl/styles.xml')}))
`],{input:JSON.stringify(payload),encoding:'utf8',cwd:repo});assert.equal(r.status,0,r.stderr);return r.stdout.trim()}
const bytes=Buffer.from(python({mode:'create',allow:allow&&!clearSource}),'base64'),media='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',context={documentId:'cf-probe',format:'xlsx',revision:1,parentRevision:null,scope:{database:'f',companyId:'f',userId:'f',threadId:'f'},sourceFile:{path:'cf.xlsx',size:bytes.length,sha256:createHash('sha256').update(bytes).digest('hex'),mediaType:media},origin:'upload'}
const server=spawn('./node_modules/.bin/vite',['preview','--host','127.0.0.1','--port','4225','--strictPort'],{cwd:frontend,stdio:'ignore'})
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
 await page.goto(`${base}/reports/v1/editor/assets/native.html`);await page.waitForFunction(()=>document.querySelector('#report-editor')?.getAttribute('aria-busy')==='false',null,{timeout:60000}).catch(async error=>{console.log(JSON.stringify({phase:'cf-load-failure',body:(await page.locator('body').innerText()).slice(-4000)}));throw error});await page.locator('[data-ribbon-tab="Home"]').waitFor()
 await page.waitForTimeout(500)
 const beforeDraft=await page.evaluate(()=>Object.fromEntries(Object.entries(localStorage))),beforeSaveLabel=await page.locator('.save-state-label').textContent()
 const tab=name=>page.locator('[data-u-comp="slide-tab-item"]').filter({hasText:name})
 let expectedRuleCount=2
 const manager=async()=>{await tab('Other').click();await page.locator('[data-ribbon-tab="Home"]').click();await page.locator('[data-ribbon-command="cf-open"]').click();await page.getByText('B1:B4',{exact:true}).first().waitFor();assert.equal(await page.getByText('B1:B4',{exact:true}).count(),expectedRuleCount)}
 const history=async action=>{await page.locator('[data-ribbon-tab="File"]').click();return page.locator(`[data-ribbon-command="${action}"]`)}
 await tab('Source').click({button:'right'});await page.getByText('删除',{exact:true}).last().click();await page.getByRole('button',{name:'确定',exact:true}).click()
 if(!allow||clearSource){await page.getByText('工作表 "Other" 的条件格式仍引用 "Source"，已拒绝删除。',{exact:true}).waitFor();await tab('Source').waitFor();await (await history('undo')).click();await tab('Source').waitFor();await tab('Other').waitFor();await (await history('redo')).click();await tab('Source').waitFor();await tab('Other').waitFor();assert.deepEqual(await page.evaluate(()=>Object.fromEntries(Object.entries(localStorage))),beforeDraft);assert.equal(await page.locator('.save-state-label').textContent(),beforeSaveLabel);assert.equal(saved,undefined);await manager();if(clearSource){const row=page.getByText('B1:B4',{exact:true}).nth(1).locator('../..');await row.hover();await row.locator('.univerjs-icon-delete-icon').click();expectedRuleCount=1;await page.waitForFunction(()=>[...document.querySelectorAll('body *')].filter(node=>node.children.length===0&&node.textContent==='B1:B4').length===1);await tab('Source').click({button:'right'});await page.getByText('删除',{exact:true}).last().click();await page.getByRole('button',{name:'确定',exact:true}).click()} }
 if(allow){
  await tab('Source').waitFor({state:'detached'});await manager();await (await history('undo')).click();await tab('Source').waitFor();await manager();await (await history('redo')).click();await tab('Source').waitFor({state:'detached'});await manager()
  await page.waitForFunction(()=>Object.keys(localStorage).filter(key=>key.startsWith('native-editor-draft:')).some(key=>{try{return JSON.parse(localStorage.getItem(key)).operations.some(op=>op.kind==='applySheetEdits'&&op.plan.removals.length)}catch{return false}}),null,{timeout:30000})
  await page.reload();await page.waitForFunction(()=>document.querySelector('#report-editor')?.getAttribute('aria-busy')==='false',null,{timeout:60000});await tab('Other').waitFor();assert.equal(await tab('Source').count(),0);await manager()
  await page.locator('[data-action="save"]').click();await page.waitForFunction(()=>document.querySelector('.save-state-label')?.textContent==='已保存修订 2',null,{timeout:60000})
  const actual=JSON.parse(python({mode:'inspect',bytes:saved.toString('base64'),original:bytes.toString('base64')}));assert.deepEqual(actual.sheetNames,['Other']);assert.deepEqual(actual.rules.map(rule=>({range:rule.range,formula:rule.formula[0],stop:rule.stop===true,priority:rule.priority})),clearSource?[{range:'B1:B4',formula:'TRUE',stop:true,priority:1}]:[{range:'B1:B4',formula:'TRUE',stop:true,priority:1},{range:'B1:B4',formula:'TRUE',stop:false,priority:2}]);assert.equal(actual.otherXmlUnchanged,!clearSource);assert.equal(actual.stylesUnchanged,true);assert.deepEqual(actual.values,[1,2,3,4,5]);const removal={kind:'applySheetEdits',plan:{renames:[],additions:[],removals:['Source'],order:['Other']}};if(clearSource){assert.equal(payload.operations.length,2);assert.equal(payload.operations[0].kind,'replaceSheetConditionalFormats');assert.equal(payload.operations[0].sheetName,'Other');assert.equal(payload.operations[0].rules.length,1);assert.deepEqual(payload.operations[1],removal)}else assert.deepEqual(payload.operations,[removal])
  await page.route('**/reports/v1/native/cf-probe/2/api/context',route=>route.fulfill({json:{context:{...context,revision:2,parentRevision:1,sourceFile:{...context.sourceFile,size:saved.length,sha256:createHash('sha256').update(saved).digest('hex')}},csrfToken:'csrf',capabilities:{xlsx_editor:true},editingEnabled:true}}));await page.route('**/reports/v1/native/cf-probe/2/api/file',route=>route.fulfill({body:saved,contentType:media}));await page.addInitScript(()=>history.replaceState(null,'','/reports/v1/native/cf-probe/2'));await page.goto(`${base}/reports/v1/native/cf-probe/2`);await page.waitForFunction(()=>document.querySelector('#report-editor')?.getAttribute('aria-busy')==='false',null,{timeout:60000});await tab('Other').waitFor();assert.equal(await tab('Source').count(),0);await manager();console.log(JSON.stringify({phase:'allowed-remove-save',actual,operations:payload.operations}))
 }
 const scripts=await Promise.all(scriptProof);assert(scripts.some(path=>/workbook-main-/.test(path)));console.log(JSON.stringify({ok:true,preview:true,phase:'cf-remove-contract',allow,clearSource,atomicRefusal:!allow||clearSource,allowedHistoryDraftPythonRevision:allow,js200AndHashMatch:scripts.length,assets:[...new Set(scripts.filter(path=>/workbook-(main|engine-|structure)/.test(path)))],pageErrors:errors}));assert.deepEqual(errors,[])
}finally{await browser?.close();server.kill()}
