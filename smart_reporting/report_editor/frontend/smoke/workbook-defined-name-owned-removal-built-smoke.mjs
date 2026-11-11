import assert from 'node:assert/strict'
import { spawn, spawnSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import { readFileSync } from 'node:fs'
import { setTimeout as delay } from 'node:timers/promises'
import { chromium } from 'playwright'
const frontend=process.cwd(), repo=new URL('../../../',`file://${frontend}/`).pathname,base='http://127.0.0.1:4229',clearSource=process.env.NAME_REMOVAL_CLEAR_SOURCE==='1',allow=process.env.NAME_REMOVAL_ALLOW==='1'||clearSource
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
const bytes=Buffer.from(python({mode:'create',formula:process.env.NAME_REMOVAL_FORMULA??'Source!$A$1',scope:'Source'}),'base64'),media='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',context={documentId:'cf-probe',format:'xlsx',revision:1,parentRevision:null,scope:{database:'f',companyId:'f',userId:'f',threadId:'f'},sourceFile:{path:'cf.xlsx',size:bytes.length,sha256:createHash('sha256').update(bytes).digest('hex'),mediaType:media},origin:'upload'}
const server=spawn('./node_modules/.bin/vite',['preview','--host','127.0.0.1','--port','4229','--strictPort'],{cwd:frontend,stdio:'ignore'})
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
 await page.goto(`${base}/reports/v1/editor/assets/native.html`);await page.waitForFunction(()=>document.querySelector('#report-editor')?.getAttribute('aria-busy')==='false',null,{timeout:60000}).catch(async error=>{console.log(JSON.stringify({phase:'defined-name-load-failure',body:(await page.locator('body').innerText()).slice(-4000)}));throw error});await page.locator('[data-ribbon-tab="Home"]').waitFor()
 await page.waitForTimeout(500)
 const tab=name=>page.locator('[data-u-comp="slide-tab-item"]').filter({hasText:name})
 const remove=async name=>{await tab(name).click({button:'right'});await page.getByText('删除',{exact:true}).last().click();await page.getByRole('button',{name:'确定',exact:true}).click();await tab(name).waitFor({state:'detached'});await page.waitForTimeout(800)}
 await remove('Source');await remove('Other');await tab('Third').waitFor();assert.equal(await tab('Source').count(),0);assert.equal(await tab('Other').count(),0)
 await page.locator('[data-ribbon-tab="Formulas"]').click();await page.locator('[data-ribbon-command="name-manager-open"]').click();assert.equal(await page.locator('.workbook-defined-name-list option').filter({hasText:'DeleteDependency'}).count(),0);await page.getByRole('button',{name:'关闭名称管理器',exact:true}).click()
 const scripts=await Promise.all(scriptProof);assert(scripts.some(path=>/workbook-main-/.test(path)));console.log(JSON.stringify({ok:true,preview:true,phase:'defined-name-owned-consecutive-delete',ownedLocalRemovedAndNextDeletionAllowed:true,js200AndHashMatch:scripts.length,assets:[...new Set(scripts.filter(path=>/workbook-(main|engine-|structure)/.test(path)))],pageErrors:errors}));assert.deepEqual(errors,[])
}finally{await browser?.close();server.kill()}
