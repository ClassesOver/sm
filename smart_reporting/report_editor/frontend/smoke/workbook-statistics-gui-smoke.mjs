// 固定源只读统计口径：完整XLSX导入、隐藏表、空值/0/false、无草稿与只读模式。
import assert from 'node:assert/strict'
import {createHash} from 'node:crypto'
import {spawn,spawnSync} from 'node:child_process'
import {setTimeout as delay} from 'node:timers/promises'
import {chromium} from 'playwright'
const frontend=process.cwd(),repo=new URL('../../../',`file://${frontend}/`).pathname,base='http://127.0.0.1:4198'
const fixture=spawnSync(`${repo}/.venv/bin/python`,['-c',`
import base64
from io import BytesIO
from openpyxl import Workbook
from openpyxl.styles import Font
b=Workbook();s=b.active;s.title='Values'
for index,value in enumerate(['alpha',0,False,' ','=""'],1):s.cell(index,1,value)
s['A6'].font=Font(bold=True)
s.protection.sheet=True
h=b.create_sheet('Hidden');h['A1']='hidden';h.sheet_state='hidden'
f=BytesIO();b.save(f);print(base64.b64encode(f.getvalue()).decode())
`],{encoding:'utf8'})
if(fixture.status!==0)throw Error(fixture.stderr)
const bytes=Buffer.from(fixture.stdout.trim(),'base64'),preview=process.env.NATIVE_GUI_PREVIEW==='1'
const server=spawn('./node_modules/.bin/vite',[...(preview?['preview']:[]),'--host','127.0.0.1','--port','4198','--strictPort'],{cwd:frontend,stdio:'ignore'})
let browser
try{
 for(let i=0;i<120;i++){try{if((await fetch(`${base}/reports/v1/editor/assets/native.html`)).ok)break}catch{}await delay(250)}
 browser=await chromium.launch({headless:true,args:['--disable-features=LocalNetworkAccessChecks']})
 for(const forcedReadOnly of (preview?[false]:[false,true])){
  const context=await browser.newContext(),page=await context.newPage(),errors=[];let saves=0
  page.on('pageerror',e=>errors.push(e.message))
  const document={documentId:'statistics',format:'xlsx',revision:1,parentRevision:null,scope:{database:'f',companyId:'f',userId:'f',threadId:'f'},sourceFile:{path:'statistics.xlsx',size:bytes.length,sha256:createHash('sha256').update(bytes).digest('hex'),mediaType:'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'},origin:'upload'}
  await page.route('**/reports/v1/native/statistics/1/api/context',r=>r.fulfill({json:{context:document,csrfToken:'csrf',capabilities:{xlsx_editor:true},editingEnabled:true}}))
  await page.route('**/reports/v1/native/statistics/1/api/file',r=>r.fulfill({body:bytes,contentType:document.sourceFile.mediaType}))
  await page.route('**/reports/v1/native/statistics/1/api/save',r=>{saves++;return r.fulfill({status:500,json:{error:'statistics must not save'}})})
  if(forcedReadOnly){
   assert(!preview,'forced read-only contract uses dev module interception')
   await page.route('**/src/workbook-main.ts*',async route=>{const response=await route.fetch(),body=await response.text(),patched=body.replace('const editable = () =>', 'const editable = () => false &&');assert.notEqual(patched,body);await route.fulfill({response,body:patched})})
  }
  await page.addInitScript(()=>history.replaceState(null,'','/reports/v1/native/statistics/1'))
  await page.goto(`${base}/reports/v1/editor/assets/native.html`)
  await page.waitForFunction(()=>document.querySelector('#report-editor')?.getAttribute('aria-busy')==='false')
  const drafts=()=>page.evaluate(()=>Object.fromEntries(Object.keys(localStorage).filter(k=>k.startsWith('native-editor-draft:')).map(k=>[k,localStorage.getItem(k)])))
  const before=await drafts(),saveLabel=await page.locator('.save-state-label').innerText()
  await page.locator('[data-ribbon-tab="Review"]').click()
  const button=page.locator('[data-ribbon-command="workbook-statistics"]');assert(await button.isEnabled())
  await button.click()
  await page.waitForFunction(()=>document.querySelector('.workbook-feedback')?.textContent==='工作簿统计：2 个工作表 · 5 个有数据的单元格 · 1 个公式。')
  await button.click();await delay(200)
  assert.deepEqual(await drafts(),before);assert.equal(saves,0);assert.equal(await page.locator('.save-state-label').innerText(),saveLabel);assert.deepEqual(errors,[])
  console.log(JSON.stringify({ok:true,preview,forcedReadOnly,message:await page.locator('.workbook-feedback').innerText(),draftUnchanged:true,protectedSheet:true,saves,pageErrors:errors}))
  await context.close()
 }
}finally{await browser?.close();server.kill()}
