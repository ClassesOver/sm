import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { spawn, spawnSync } from 'node:child_process'
import { setTimeout as delay } from 'node:timers/promises'
import { chromium } from 'playwright'
const frontend=process.cwd(),repo=new URL('../../../',`file://${frontend}/`).pathname,base='http://127.0.0.1:4195',media='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
function python(p) {
 const r=spawnSync(`${repo}/.venv/bin/python`,['-c',`
import base64,json,sys,re
from io import BytesIO
from zipfile import ZipFile,ZIP_DEFLATED
from openpyxl import Workbook,load_workbook
from openpyxl.worksheet.table import Table,TableStyleInfo
p=json.load(sys.stdin)
if p['mode']=='create':
 b=Workbook();s=b.active;s.title='Summary'
 for row in [('Name','Qty'),('Ada',3),('Grace',7),('Lin',9)]:s.append(row)
 t=Table(displayName='Staff',ref='A1:B4');t.tableStyleInfo=TableStyleInfo(name='MyStyle',showRowStripes=True);s.add_table(t)
 raw=BytesIO();b.save(raw);src=ZipFile(BytesIO(raw.getvalue()));out=BytesIO()
 custom='<dxfs count="3"><dxf><font><color rgb="FFFF0000"/></font><fill><patternFill><bgColor rgb="FF5B9BD5"/></patternFill></fill></dxf><dxf><fill><patternFill><bgColor rgb="FFDEEBF7"/></patternFill></fill></dxf><dxf><fill><patternFill><bgColor rgb="FFFFC000"/></patternFill></fill></dxf></dxfs><tableStyles count="1"><tableStyle name="MyStyle" pivot="0" count="2"><tableStyleElement type="headerRow" dxfId="0"/><tableStyleElement type="firstRowStripe" dxfId="1"/><tableStyleElement type="totalRow" dxfId="2"/></tableStyle></tableStyles>'
 with ZipFile(out,'w',ZIP_DEFLATED) as dest:
  for name in src.namelist():
   data=src.read(name)
   if name=='xl/styles.xml':data=re.sub(r'<tableStyles\\b[^>]*(?:/>|>[\\s\\S]*?</tableStyles>)','',data.decode()).replace('</styleSheet>',custom+'</styleSheet>').encode()
   dest.writestr(name,data)
 print(base64.b64encode(out.getvalue()).decode())
elif p['mode']=='patch':
 from smart_reporting.report_editor.native_office import patch_office
 print(base64.b64encode(patch_office('xlsx',base64.b64decode(p['bytes']),p['operations'])).decode())
elif p['mode']=='inspect':
 raw=base64.b64decode(p['bytes']);z=ZipFile(BytesIO(raw));t=load_workbook(BytesIO(raw)).active.tables['Staff']
 print(json.dumps({'style':t.tableStyleInfo.name,'stripes':t.tableStyleInfo.showRowStripes,'styles':base64.b64encode(z.read('xl/styles.xml')).decode(),'sheet':base64.b64encode(z.read('xl/worksheets/sheet1.xml')).decode()}))
else:
 from PIL import Image
 im=Image.open(BytesIO(base64.b64decode(p['bytes']))).convert('RGB');counts={rgb:count for count,rgb in im.getcolors(im.width*im.height)}
 print(json.dumps({name:counts.get(tuple(rgb),0) for name,rgb in {'header':[91,155,213],'stripe':[222,235,247],'totals':[255,192,0]}.items()}))
`],{cwd:repo,env:{...process.env,PYTHONPATH:repo},input:JSON.stringify(p),encoding:'utf8',maxBuffer:20*1024*1024});if(r.status)throw Error(r.stderr);return r.stdout.trim()
}
const source=Buffer.from(python({mode:'create'}),'base64'),before=JSON.parse(python({mode:'inspect',bytes:source.toString('base64')}))
const ctx=bytes=>({documentId:'custom-table',format:'xlsx',revision:1,parentRevision:null,scope:{database:'f',companyId:'f',userId:'f',threadId:'f'},sourceFile:{path:'custom.xlsx',size:bytes.length,sha256:createHash('sha256').update(bytes).digest('hex'),mediaType:media},origin:'upload'})
const preview=process.env.NATIVE_GUI_PREVIEW==='1'
const server=spawn('./node_modules/.bin/vite',[...(preview?['preview']:[]),'--host','127.0.0.1','--port','4195','--strictPort'],{cwd:frontend,stdio:'ignore'})
let browser,saved,savePayload
try {
 for(let i=0;i<120;i++){try{if((await fetch(`${base}/reports/v1/editor/assets/native.html`)).ok)break}catch{}await delay(250)}
 browser=await chromium.launch({headless:true,args:['--disable-features=LocalNetworkAccessChecks']})
 const loadedChunks=[]
 const context=await browser.newContext({viewport:{width:1440,height:1000}}),page=await context.newPage(),errors=[]
 page.on('pageerror',e=>errors.push(e.message))
 page.on('response',response=>{if(/\/lazy-workbook-table-style-read-[^/]+\.js$/.test(new URL(response.url()).pathname))loadedChunks.push({url:response.url(),status:response.status()})})
 await page.route('**/reports/v1/native/custom-table/1/api/context',r=>r.fulfill({json:{context:ctx(source),csrfToken:'csrf',capabilities:{xlsx_editor:true},editingEnabled:true}}))
 await page.route('**/reports/v1/native/custom-table/1/api/file',r=>r.fulfill({body:source,contentType:media}))
 await page.route('**/reports/v1/native/custom-table/1/api/save',async r=>{
  savePayload=r.request().postDataJSON();saved=Buffer.from(python({mode:'patch',bytes:source.toString('base64'),operations:savePayload.operations}),'base64')
  await r.fulfill({json:{documentId:'custom-table',revision:2,parentRevision:1,revisionRegistered:true,artifacts:{xlsx:{downloadUrl:'/custom-download.xlsx'}},editor:{openUrl:'/reports/v1/native/custom-table/2'},validation:{issues:[]}}})
 })
 await page.route(/\/reports\/v1\/native\/custom-table\/[12]$/,async r=>r.fulfill({response:await r.fetch({url:`${base}/reports/v1/editor/assets/native.html`})}))
 await page.addInitScript(()=>history.replaceState(null,'','/reports/v1/native/custom-table/1'))
 await page.goto(`${base}/reports/v1/editor/assets/native.html`)
 const ready=async()=>{await page.locator('.workbook-ribbon').waitFor({timeout:60000});await page.waitForFunction(()=>document.querySelector('#report-editor')?.getAttribute('aria-busy')==='false');await page.waitForFunction(()=>{const r=document.querySelector('.workbook-grid')?.getBoundingClientRect();return r&&document.elementFromPoint(r.x+90,r.y+64)?.getAttribute('data-u-comp')==='render-canvas'})}
 const select=async()=>{await ready();await page.locator('.workbook-grid').click({position:{x:90,y:64}});await page.locator('[data-ribbon-tab="Table Design"]').click()}
 const pixels=async(label)=>{await delay(500);return JSON.parse(python({mode:'pixels',bytes:(await page.locator('.workbook-grid').screenshot(label?{path:`/tmp/custom-dxf-${label}.png`}:{})).toString('base64')}))}
 const stripes=()=>page.getByRole('checkbox',{name:'行条纹',exact:true})
 await select();const initial=await pixels('initial');assert(initial.header>100);assert(initial.stripe>100)
 await page.getByRole('checkbox',{name:'标题行',exact:true}).click({noWaitAfter:true});const withoutHeader=await pixels('header-off');assert.equal(withoutHeader.header,0);assert(withoutHeader.stripe>100)
 await page.locator('[data-ribbon-tab="File"]').click();await page.locator('[data-ribbon-command="undo"]').click();await select();assert((await pixels()).header>100)
 await page.getByRole('checkbox',{name:'汇总行',exact:true}).check();const withTotals=await pixels('totals-on');console.log(JSON.stringify({phase:'totals',withTotals}));assert(withTotals.totals>100)
 await page.locator('[data-ribbon-tab="File"]').click();await page.locator('[data-ribbon-command="undo"]').click();await select();assert.equal((await pixels()).totals,0)
 await stripes().uncheck();const disabled=await pixels('stripe-off');console.log(JSON.stringify({phase:'pixels',initial,disabled,feedback:await page.locator('.workbook-feedback').innerText()}));assert(disabled.header>100);assert(disabled.stripe<initial.stripe/2)
 await page.locator('[data-ribbon-tab="File"]').click();await page.locator('[data-ribbon-command="undo"]').click();await select();assert.equal(await stripes().isChecked(),true)
 await page.locator('[data-ribbon-tab="File"]').click();await page.locator('[data-ribbon-command="redo"]').click();await select();assert.equal(await stripes().isChecked(),false)
 await page.reload();await select();assert.equal(await stripes().isChecked(),false)
 await page.locator('[data-action="save"]').click();await page.waitForFunction(()=>document.querySelector('.save-state-label')?.textContent==='已保存修订 2',null,{timeout:60000})
 const after=JSON.parse(python({mode:'inspect',bytes:saved.toString('base64')}));assert.equal(after.style,'MyStyle');assert.equal(after.stripes,false);assert.equal(after.styles,before.styles);assert.equal(after.sheet,before.sheet)
 await page.route('**/reports/v1/native/custom-table/2/api/context',r=>r.fulfill({json:{context:{...ctx(saved),revision:2,parentRevision:1},csrfToken:'csrf',capabilities:{xlsx_editor:true},editingEnabled:true}}))
 await page.route('**/reports/v1/native/custom-table/2/api/file',r=>r.fulfill({body:saved,contentType:media}))
 await page.addInitScript(()=>history.replaceState(null,'','/reports/v1/native/custom-table/2'))
 await page.goto(`${base}/reports/v1/native/custom-table/2`);await select();assert.equal(await stripes().isChecked(),false)
 const reopened=await pixels('reopened');assert(reopened.header>100);assert(reopened.stripe<initial.stripe/2);assert.deepEqual(errors,[])
 if(preview){assert(loadedChunks.length>0,'built custom style reader chunk must load');assert(loadedChunks.every(chunk=>chunk.status===200))}
 console.log(JSON.stringify({ok:true,preview,loadedChunks,case:'existing-custom-dxf',browser:browser.version(),initial,disabled,reopened,undoRedo:true,draftRestored:true,revision2Reopened:true,stylesAndCellBytesPreserved:true,operations:savePayload.operations,pageErrors:errors}))
}finally{await browser?.close();server.kill()}
