import assert from 'node:assert/strict'
import {readFileSync} from 'node:fs'
import {createHash} from 'node:crypto'
import {spawn,spawnSync} from 'node:child_process'
import {setTimeout as delay} from 'node:timers/promises'
import {chromium} from 'playwright'
const frontend=process.cwd(),repo=new URL('../../../',`file://${frontend}/`).pathname,base='http://127.0.0.1:4202',preview=process.env.NATIVE_GUI_PREVIEW==='1'
function python(payload){const result=spawnSync(`${repo}/.venv/bin/python`,['-c',`
import base64,json,sys
from io import BytesIO
from openpyxl import Workbook,load_workbook
from openpyxl.styles import PatternFill
from smart_reporting.report_editor.native_office import patch_office
p=json.load(sys.stdin)
if p['mode']=='create':
 b=Workbook();s=b.active;s.title='Values'
 for row,(month,amount) in enumerate([('2026-06',10),('2026-05',20),('2026-06',30),('2026-06',40),('2026-05',50)],1):s.cell(row,1,month);s.cell(row,2,amount)
 for row,tail in enumerate(['','+0','*1'],1):s.cell(row,4,'=SUMIFS(B1:B5,A1:A5,"2026-06")'+tail)
 s['F1']='keep';s.freeze_panes='B2';s['A1'].fill=PatternFill('solid',fgColor='FFFF0000');s['B1'].fill=PatternFill('solid',fgColor='FF00FF00');f=BytesIO();b.save(f);print(base64.b64encode(f.getvalue()).decode())
elif p['mode']=='pixels':
 from PIL import Image
 im=Image.open(BytesIO(base64.b64decode(p['bytes']))).convert('RGB');boxes={}
 for name,color in [('a',(255,0,0)),('b',(0,255,0))]:
  points=[(x,y) for y in range(im.height) for x in range(im.width) if im.getpixel((x,y))==color]
  assert len(points)>100,(name,len(points))
  boxes[name]={'left':min(x for x,y in points),'right':max(x for x,y in points),'top':min(y for x,y in points),'bottom':max(y for x,y in points)}
 print(json.dumps(boxes))
elif p['mode']=='patch':print(base64.b64encode(patch_office('xlsx',base64.b64decode(p['bytes']),p['operations'])).decode())
else:
 b=load_workbook(BytesIO(base64.b64decode(p['bytes'])));s=b['Values'];print(json.dumps({'A1':s['A1'].value,'A1type':s['A1'].data_type,'B1':s['B1'].value,'D1':s['D1'].value,'D2':s['D2'].value,'D3':s['D3'].value,'F1':s['F1'].value,'rtl':s.sheet_view.rightToLeft,'freeze':s.freeze_panes}))
`],{input:JSON.stringify(payload),encoding:'utf8',cwd:repo});if(result.status!==0)throw Error(result.stderr);return result.stdout.trim()}
const bytes=Buffer.from(python({mode:'create'}),'base64'),media='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
const ctx=source=>({documentId:'function-dialog',format:'xlsx',revision:1,parentRevision:null,scope:{database:'f',companyId:'f',userId:'f',threadId:'f'},sourceFile:{path:'报表/运营 %.xlsx',size:source.length,sha256:createHash('sha256').update(source).digest('hex'),mediaType:media},origin:'upload'})
const server=spawn('./node_modules/.bin/vite',[...(preview?['preview']:[]),'--host','127.0.0.1','--port','4202','--strictPort'],{cwd:frontend,stdio:'ignore'})
let browser,saved,payload
try{
 for(let i=0;i<120;i++){try{if((await fetch(`${base}/reports/v1/editor/assets/native.html`)).ok)break}catch{}await delay(250)}
 browser=await chromium.launch({headless:true,args:['--disable-features=LocalNetworkAccessChecks']})
 const page=await browser.newPage({viewport:{width:1440,height:1100},permissions:['clipboard-read','clipboard-write']}),errors=[]
 const scriptProof=[];if(preview)page.on('response',response=>{const url=new URL(response.url());if(url.pathname.startsWith('/reports/v1/editor/assets/')&&url.pathname.endsWith('.js'))scriptProof.push((async()=>{assert.equal(response.status(),200);const body=await response.body(),path=`../static/${url.pathname.slice('/reports/v1/editor/assets/'.length)}`;assert.equal(createHash('sha256').update(body).digest('hex'),createHash('sha256').update(readFileSync(path)).digest('hex'));return url.pathname})())})
 page.on('pageerror',error=>{errors.push(error.message);console.log(error.stack)})
 if(!preview)await page.route('**/src/workbook-vendor/grid/create-univer.ts*',async route=>{const response=await route.fetch(),body=await response.text();assert(body.includes('return { univer, univerAPI: FUniver.newAPI(univer) };'));await route.fulfill({response,body:body.replace('return { univer, univerAPI: FUniver.newAPI(univer) };','return window.__valuesRuntime = { univer, univerAPI: FUniver.newAPI(univer) };')})})
 await page.route('**/reports/v1/native/function-dialog/1/api/context',r=>r.fulfill({json:{context:ctx(bytes),csrfToken:'csrf',capabilities:{xlsx_editor:true},editingEnabled:true}}))
 await page.route('**/reports/v1/native/function-dialog/1/api/file',r=>r.fulfill({body:bytes,contentType:media}))
 await page.route('**/reports/v1/native/function-dialog/1/api/save',async r=>{payload=r.request().postDataJSON();saved=Buffer.from(python({mode:'patch',bytes:bytes.toString('base64'),operations:payload.operations}),'base64');await r.fulfill({json:{documentId:'function-dialog',revision:2,parentRevision:1,revisionRegistered:true,artifacts:{xlsx:{downloadUrl:'/functions.xlsx'}},editor:{openUrl:'/reports/v1/native/function-dialog/2'},validation:{issues:[]}}})})
 await page.route(/\/reports\/v1\/native\/function-dialog\/[12]$/,async r=>r.fulfill({response:await r.fetch({url:`${base}/reports/v1/editor/assets/native.html`})}))
 await page.addInitScript(()=>history.replaceState(null,'','/reports/v1/native/function-dialog/1'))
 const ready=()=>page.waitForFunction(()=>document.querySelector('#report-editor')?.getAttribute('aria-busy')==='false')
 const goto=async reference=>{await page.locator('[data-ribbon-tab="Home"]').click();await page.locator('[data-ribbon-command="goto-open"]').click();await page.locator('[data-goto-reference]').fill(reference);await page.locator('.workbook-ribbon-goto-dialog button[type="submit"]').click()}
 const copiedValues=async()=>{await goto('D1:D3');const sentinel=`rtl-pending-${Date.now()}-${Math.random()}`;await page.evaluate(text=>navigator.clipboard.writeText(text),sentinel);await page.keyboard.press('Control+c');for(let attempt=0;attempt<200;attempt++){const text=await page.evaluate(()=>navigator.clipboard.readText());if(text!==sentinel&&text.trim().split(/\r?\n/).length===3){console.log(JSON.stringify({phase:'rtl-native-clipboard',text}));return text.trim().split(/\r?\n/).map(Number)}await delay(50)}throw new Error('原生复制未覆盖本次剪贴板sentinel')}
 const check=async expected=>{if(preview){const values=await copiedValues();assert.deepEqual(values,[expected,expected,expected]);return}await page.waitForFunction(expected=>{const sheet=window.__valuesRuntime?.univerAPI.getActiveWorkbook()?.getActiveSheet();return sheet&&sheet.getRange('D1:D3').getValues().flat().every(value=>value===expected)},expected);const snapshot=await page.evaluate(()=>{const sheet=window.__valuesRuntime.univerAPI.getActiveWorkbook().getActiveSheet();return{amount:sheet.getRange('B1').getValue(),month:sheet.getRange('A1').getValue(),results:sheet.getRange('D1:D3').getValues().flat()}});assert.equal(snapshot.month,'2026-06');console.log(JSON.stringify({phase:'rtl-values',...snapshot}))}
 await page.goto(`${base}/reports/v1/editor/assets/native.html`);await ready();console.log(JSON.stringify({phase:'rtl-initial-dom',text:(await page.locator('#report-editor').innerText()).slice(0,1800),feedback:await page.locator('.workbook-feedback').allTextContents(),status:await page.locator('.save-state-label').allTextContents(),body:(await page.locator('body').innerText()).slice(-1200)}));if(await page.locator('[data-ribbon-tab="Home"]').count()===0)throw new Error('工作簿初始化失败：'+(await page.locator('.save-state-label').allTextContents()).join('；'));await check(80)
 const toggle=async()=>{await page.locator('[data-ribbon-tab="View"]').click();await page.locator('[data-ribbon-command="toggle-right-to-left"]').click()}
 const waitDirection=async expected=>{await page.locator('[data-ribbon-tab="View"]').click();await page.waitForFunction(expected=>document.querySelector('[data-ribbon-command="toggle-right-to-left"]')?.getAttribute('aria-pressed')===String(expected),expected)}
 const pixels=async()=>{await delay(250);return JSON.parse(python({mode:'pixels',bytes:(await page.locator('#workbook-grid').screenshot()).toString('base64')}))}
 const ltr=await pixels();assert(ltr.a.left<ltr.b.left,JSON.stringify(ltr))
 await toggle();await waitDirection(true)
 const rtl=await pixels();assert(rtl.a.left>rtl.b.left,JSON.stringify(rtl))
 await page.locator('[data-ribbon-tab="File"]').click();await page.locator('[data-ribbon-command="undo"]').click();await waitDirection(false)
 assert((await pixels()).a.left<(await pixels()).b.left)
 await page.locator('[data-ribbon-tab="File"]').click();await page.locator('[data-ribbon-command="redo"]').click();await waitDirection(true)
 await goto('B1');const target=await pixels(),surface=await page.locator('#workbook-grid').boundingBox();assert(surface)
 const hit={x:surface.x+(target.b.left+target.b.right)/2,y:surface.y+(target.b.top+target.b.bottom)/2};console.log(JSON.stringify({phase:'rtl-pixels-target',ltr,rtl,target,surface,hit}));await page.mouse.click(hit.x,hit.y)
 if(!preview)assert.equal(await page.evaluate(()=>window.__valuesRuntime.univerAPI.getActiveWorkbook().getActiveRange().getA1Notation()),'B1')
 await page.keyboard.type('15');await page.keyboard.press('Enter');await check(85)
 await waitDirection(true)
 console.log(JSON.stringify({phase:'rtl-native-mirror',ltr,rtl,target,surface,hit,mouseHitLogicalB1:true,undoRedo:true,frozenB2:true}))
 await page.reload();await ready();await check(85);await waitDirection(true)
 await page.locator('[data-action="save"]').click();await page.waitForFunction(()=>document.querySelector('.save-state-label')?.textContent==='已保存修订 2',null,{timeout:60000})
 const actual=JSON.parse(python({mode:'inspect',bytes:saved.toString('base64')}));assert.deepEqual(actual,{A1:'2026-06',A1type:'s',B1:15,D1:'=SUMIFS(B1:B5,A1:A5,"2026-06")',D2:'=SUMIFS(B1:B5,A1:A5,"2026-06")+0',D3:'=SUMIFS(B1:B5,A1:A5,"2026-06")*1',F1:'keep',rtl:true,freeze:'B2'})
 assert.equal(payload.operations.filter(op=>op.kind==='applyCellEdits').flatMap(op=>op.edits).length,1)
 assert(payload.operations.some(op=>op.kind==='applyPageSetups'&&op.setups.some(setup=>setup.rightToLeft===true)))
 await page.route('**/reports/v1/native/function-dialog/2/api/context',r=>r.fulfill({json:{context:{...ctx(saved),revision:2,parentRevision:1},csrfToken:'csrf',capabilities:{xlsx_editor:true},editingEnabled:true}}))
 await page.route('**/reports/v1/native/function-dialog/2/api/file',r=>r.fulfill({body:saved,contentType:media}))
 await page.addInitScript(()=>history.replaceState(null,'','/reports/v1/native/function-dialog/2'));await page.goto(`${base}/reports/v1/native/function-dialog/2`);await ready();await check(85);await waitDirection(true)
 if(preview){const scripts=await Promise.all(scriptProof);assert(scripts.some(path=>/workbook-main-/.test(path)));console.log(JSON.stringify({phase:'rtl-built-proof',js200AndHashMatch:scripts.length,assets:[...new Set(scripts.filter(path=>/workbook-(main|engine-|insert-function-|future-functions-)/.test(path)))]}))}
 assert.deepEqual(errors,[]);console.log(JSON.stringify({ok:true,preview,rtlMirrorAndMouseHit:true,freeze:true,undoRedo:true,keyboardAmountRecalculation:true,draftRecovery:true,pythonPatchAndOpenpyxl:true,revisionReopen:true,actual,pageErrors:errors}))
}finally{await browser?.close();server.kill()}
