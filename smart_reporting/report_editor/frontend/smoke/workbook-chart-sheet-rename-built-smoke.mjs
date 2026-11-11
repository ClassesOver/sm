import assert from 'node:assert/strict'
import {spawn,spawnSync} from 'node:child_process'
import {createHash} from 'node:crypto'
import {readFileSync} from 'node:fs'
import {setTimeout as delay} from 'node:timers/promises'
import {chromium} from 'playwright'
const frontend=process.cwd(),repo=new URL('../../../',`file://${frontend}/`).pathname,base='http://127.0.0.1:4233'
const namespace=process.env.CHART_RENAME_NAMESPACE??'default',newName="财务 O'Brien"
assert(['default','alias'].includes(namespace))
const sha=bytes=>createHash('sha256').update(bytes).digest('hex')
function python(payload){const result=spawnSync(`${repo}/.venv/bin/python`,['-c',`
import json,sys,base64,re
from io import BytesIO
from zipfile import ZipFile,ZIP_DEFLATED
from openpyxl import Workbook,load_workbook
from openpyxl.chart import BarChart,Reference
from smart_reporting.report_editor.native_office import patch_office
p=json.load(sys.stdin)
if p['mode']=='create':
 b=Workbook();s=b.active;s.title='Source';other=b.create_sheet('Other')
 for i in range(1,6):s.cell(i,1,i);other.cell(i,2,i)
 c=BarChart();c.add_data(Reference(s,min_col=1,min_row=1,max_row=5));other.add_chart(c,'D2')
 f=BytesIO();b.save(f);out=BytesIO()
 with ZipFile(BytesIO(f.getvalue())) as before,ZipFile(out,'w',ZIP_DEFLATED) as after:
  for entry in before.infolist():
   raw=before.read(entry.filename)
   if entry.filename=='xl/charts/chart1.xml' and p['namespace']=='alias':
    xml=raw.decode().replace('xmlns="http://schemas.openxmlformats.org/drawingml/2006/chart"','xmlns:q="http://schemas.openxmlformats.org/drawingml/2006/chart"')
    raw=re.sub(r'<(/?)([A-Za-z][\\w]*)(?=[\\s/>])',r'<\\1q:\\2',xml).encode()
   after.writestr(entry,raw)
 print(base64.b64encode(out.getvalue()).decode())
elif p['mode']=='patch':print(base64.b64encode(patch_office('xlsx',base64.b64decode(p['bytes']),p['operations'])).decode())
else:
 raw=base64.b64decode(p['bytes']);b=load_workbook(BytesIO(raw));before=ZipFile(BytesIO(base64.b64decode(p['original'])));after=ZipFile(BytesIO(raw))
 old=before.read('xl/charts/chart1.xml').decode();new=after.read('xl/charts/chart1.xml').decode();name=p['newName'];formula="'"+name.replace("'","''")+"'!$A$1:$A$5"
 print(json.dumps({'sheetNames':b.sheetnames,'formula':b['Other']._charts[0].series[0].val.numRef.f,'chartXml':new,'chartOnlyFormulaChanged':new==old.replace("'Source'!$A$1:$A$5",formula.replace('&','&amp;').replace('<','&lt;').replace('>','&gt;')),'changedParts':[name for name in before.namelist() if before.read(name)!=after.read(name)],'values':[b['Other'].cell(i,2).value for i in range(1,6)]},ensure_ascii=False))
`],{input:JSON.stringify(payload),encoding:'utf8',cwd:repo});assert.equal(result.status,0,result.stderr);return result.stdout.trim()}
const bytes=Buffer.from(python({mode:'create',namespace}),'base64'),media='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
const context={documentId:'chart-rename',format:'xlsx',revision:1,parentRevision:null,scope:{database:'f',companyId:'f',userId:'f',threadId:'f'},sourceFile:{path:'chart.xlsx',size:bytes.length,sha256:sha(bytes),mediaType:media},origin:'upload'}
const server=spawn('./node_modules/.bin/vite',['preview','--host','127.0.0.1','--port','4233','--strictPort'],{cwd:frontend,stdio:'ignore'})
let browser,saved,payload,saveCount=0
try{
 for(let i=0;i<120;i++){try{if((await fetch(`${base}/reports/v1/editor/assets/native.html`)).ok)break}catch{}await delay(250)}
 browser=await chromium.launch({headless:true});const page=await browser.newPage({viewport:{width:1500,height:1100}}),errors=[],scriptProof=[]
 page.on('pageerror',error=>errors.push(error.message))
 page.on('response',response=>{const url=new URL(response.url());if(url.pathname.startsWith('/reports/v1/editor/assets/')&&url.pathname.endsWith('.js'))scriptProof.push((async()=>{assert.equal(response.status(),200);const body=await response.body();assert.equal(sha(body),sha(readFileSync(`../static/${url.pathname.slice('/reports/v1/editor/assets/'.length)}`)));return url.pathname})())})
 for(const revision of [1,2]){
  await page.route(`**/reports/v1/native/chart-rename/${revision}/api/context`,route=>route.fulfill({json:{context:revision===1?context:{...context,revision:2,parentRevision:1,sourceFile:{...context.sourceFile,size:saved.length,sha256:sha(saved)}},csrfToken:'csrf',capabilities:{xlsx_editor:true},editingEnabled:true}}))
  await page.route(`**/reports/v1/native/chart-rename/${revision}/api/file`,route=>route.fulfill({body:revision===1?bytes:saved,contentType:media}))
 }
 await page.route('**/reports/v1/native/chart-rename/1/api/save',async route=>{saveCount++;payload=route.request().postDataJSON();saved=Buffer.from(python({mode:'patch',bytes:bytes.toString('base64'),operations:payload.operations}),'base64');await route.fulfill({json:{documentId:'chart-rename',revision:2,parentRevision:1,revisionRegistered:true,artifacts:{xlsx:{downloadUrl:'/chart.xlsx'}},editor:{openUrl:'/reports/v1/native/chart-rename/2'},validation:{issues:[]}}})})
 await page.route(/\/reports\/v1\/native\/chart-rename\/[12]$/,async route=>route.fulfill({response:await route.fetch({url:`${base}/reports/v1/editor/assets/native.html`})}))
 await page.addInitScript(()=>history.replaceState(null,'','/reports/v1/native/chart-rename/1'))
 const ready=async()=>{await page.waitForFunction(()=>document.querySelector('#report-editor')?.getAttribute('aria-busy')==='false',null,{timeout:60000});await page.locator('[data-ribbon-tab="Home"]').waitFor()}
 const tab=name=>page.locator('[data-u-comp="slide-tab-item"]').filter({hasText:name})
 const history=async action=>{await page.locator('[data-ribbon-tab="File"]').click();await page.locator(`[data-ribbon-command="${action}"]`).click()}
 await page.goto(`${base}/reports/v1/editor/assets/native.html`);await ready()
 await tab('Source').click();await tab('Source').dblclick();const editor=page.locator('[data-u-comp="slide-tab-item"] [contenteditable="true"]');await editor.fill(newName);await editor.press('Enter');await tab(newName).waitFor()
 await history('undo');await tab('Source').waitFor();await history('redo');await tab(newName).waitFor()
 await page.waitForFunction(()=>Object.keys(localStorage).filter(key=>key.startsWith('native-editor-draft:')).some(key=>{try{return JSON.parse(localStorage.getItem(key)).operations.some(op=>op.kind==='applySheetEdits'&&op.plan.renames.length)}catch{return false}}),null,{timeout:30000})
 await page.reload();await ready();await tab(newName).waitFor();assert.equal(await tab('Source').count(),0)
 await page.locator('[data-action="save"]').click();await page.waitForFunction(()=>document.querySelector('.save-state-label')?.textContent==='已保存修订 2',null,{timeout:60000})
 assert.deepEqual(payload.operations,[{kind:'applySheetEdits',plan:{renames:[{sheetName:'Source',newName}],additions:[],removals:[],order:[newName,'Other']}}])
 const actual=JSON.parse(python({mode:'inspect',bytes:saved.toString('base64'),original:bytes.toString('base64'),newName}))
 assert.deepEqual(actual.sheetNames,[newName,'Other']);assert.equal(actual.formula,"'财务 O''Brien'!$A$1:$A$5");assert.equal(actual.chartOnlyFormulaChanged,true);assert.deepEqual(actual.values,[1,2,3,4,5]);assert.deepEqual(actual.changedParts.sort(),['xl/charts/chart1.xml','xl/workbook.xml'])
 await page.addInitScript(()=>history.replaceState(null,'','/reports/v1/native/chart-rename/2'));await page.goto(`${base}/reports/v1/native/chart-rename/2`);await ready();await tab(newName).waitFor();assert.equal(await tab('Source').count(),0)
 await page.waitForTimeout(500)
 const beforeDraft=await page.evaluate(()=>Object.fromEntries(Object.entries(localStorage))),beforeSaveLabel=await page.locator('.save-state-label').textContent(),beforeTabs=await page.locator('[data-u-comp="slide-tab-item"]').allTextContents()
 await tab(newName).click({button:'right'});await page.getByText('删除',{exact:true}).last().click();await page.getByRole('button',{name:'确定',exact:true}).click()
 await page.getByText(`工作表 "Other" 的图表 "xl/charts/chart1.xml" 仍引用 "${newName}"，已拒绝删除。`,{exact:true}).waitFor()
 await tab(newName).waitFor();await history('undo');await tab(newName).waitFor();await history('redo');await tab(newName).waitFor()
 assert.deepEqual(await page.locator('[data-u-comp="slide-tab-item"]').allTextContents(),beforeTabs)
 assert.deepEqual(await page.evaluate(()=>Object.fromEntries(Object.entries(localStorage))),beforeDraft);assert.equal(await page.locator('.save-state-label').textContent(),beforeSaveLabel);assert.equal(saveCount,1)
 const scripts=await Promise.all(scriptProof);assert(scripts.some(path=>/workbook-main-/.test(path)));assert.deepEqual(errors,[])
 console.log(JSON.stringify({ok:true,namespace,pureUiRename:true,undoRedo:true,draftReload:true,pythonChartFormulaAndParts:actual,revision2Reopen:true,renamedChartDeletionAtomicRefusal:true,saveCount,js200AndHashMatch:scripts.length,assets:[...new Set(scripts.filter(path=>/workbook-(main|engine-|structure|chart-references|xml-parser)/.test(path)))],pageErrors:errors}))
}finally{await browser?.close();server.kill()}
