import assert from 'node:assert/strict'
import {readFileSync} from 'node:fs'
import {createHash} from 'node:crypto'
import {spawn,spawnSync} from 'node:child_process'
import {setTimeout as delay} from 'node:timers/promises'
import {chromium} from 'playwright'
const frontend=process.cwd(),repo=new URL('../../../',`file://${frontend}/`).pathname,base='http://127.0.0.1:4198',preview=process.env.NATIVE_GUI_PREVIEW==='1'
function python(payload){const result=spawnSync(`${repo}/.venv/bin/python`,['-c',`
import base64,json,sys
from io import BytesIO
from openpyxl import Workbook,load_workbook
from smart_reporting.report_editor.native_office import patch_office
p=json.load(sys.stdin)
if p['mode']=='create':
 b=Workbook();s=b.active;s.title='Values';s['A1']=5;s['A2']=3;s['B1']='=CELL("filename",A1)';s['C1']='=RATE(A1,-100,100,10)';s['D1']='=_xlfn.MINIFS(A1:A2,A1:A2,99)';s['E1']='=_xlfn.MAXIFS(A1:A2,A1:A2,99)';s['F1']='=SUM(A1:A2)';s['B2']='keep';b.create_sheet('Other Sheet');f=BytesIO();b.save(f);print(base64.b64encode(f.getvalue()).decode())
elif p['mode']=='patch':print(base64.b64encode(patch_office('xlsx',base64.b64decode(p['bytes']),p['operations'])).decode())
else:
 b=load_workbook(BytesIO(base64.b64decode(p['bytes'])));print(json.dumps({'C1':b['Values']['C1'].value,'B1':b['Values']['B1'].value,'B2':b['Values']['B2'].value,'A1':b['Values']['A1'].value,'D1':b['Values']['D1'].value,'E1':b['Values']['E1'].value,'F1':b['Values']['F1'].value}))
`],{input:JSON.stringify(payload),encoding:'utf8',cwd:repo});if(result.status!==0)throw Error(result.stderr);return result.stdout.trim()}
const bytes=Buffer.from(python({mode:'create'}),'base64'),media='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
const ctx=source=>({documentId:'function-dialog',format:'xlsx',revision:1,parentRevision:null,scope:{database:'f',companyId:'f',userId:'f',threadId:'f'},sourceFile:{path:'报表/运营 %.xlsx',size:source.length,sha256:createHash('sha256').update(source).digest('hex'),mediaType:media},origin:'upload'})
const server=spawn('./node_modules/.bin/vite',[...(preview?['preview']:[]),'--host','127.0.0.1','--port','4198','--strictPort'],{cwd:frontend,stdio:'ignore'})
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
 const goto=async reference=>{await page.locator('[data-ribbon-tab="Home"]').click();await page.locator('[data-ribbon-command="goto-open"]').click();await page.locator('[data-goto-reference]').fill(reference);await page.locator('.workbook-ribbon-goto-dialog button[type="submit"]').click();if(preview)console.log(JSON.stringify({phase:'ribbon-goto-focus',...(await page.evaluate(()=>({active:document.activeElement?.outerHTML?.slice(0,300),namebox:document.querySelector('[data-u-comp="defined-name"] input')?.value})))}))}
 let verifyFirstNamebox=preview
 const values=async()=>{if(!preview)return page.evaluate(()=>window.__valuesRuntime.univerAPI.getActiveWorkbook().getActiveSheet().getRange('A1:F1').getValues()[0]);if(verifyFirstNamebox){verifyFirstNamebox=false;const namebox=page.locator('[data-u-comp="defined-name"] input');await namebox.fill('A1:F1');await namebox.press('Enter');console.log(JSON.stringify({phase:'first-native-namebox'}))}else await goto('A1:F1');const sentinel=`pending-proof-${Date.now()}-${Math.random()}`;await page.evaluate(text=>navigator.clipboard.writeText(text),sentinel);await page.keyboard.press('Control+c');await page.waitForFunction(async text=>(await navigator.clipboard.readText())!==text,sentinel,{timeout:5000});const text=await page.evaluate(()=>navigator.clipboard.readText());console.log(JSON.stringify({phase:'native-clipboard',text}));return text.trimEnd().split('\t').map((value,index)=>index===1?value:Number(value))}
 const check=async(expectedInput,expectedSum)=>{let row;for(let attempt=0;attempt<30;attempt++){row=await values();if(row?.[0]===expectedInput&&row[1]==='报表/[运营 %.xlsx]Values'&&typeof row[2]==='number'&&Number.isFinite(row[2])&&row[3]===0&&row[4]===0&&row[5]===expectedSum)break;await delay(200)}assert.equal(row[0],expectedInput);assert.equal(row[1],'报表/[运营 %.xlsx]Values');assert.equal(row[3],0);assert.equal(row[4],0);assert.equal(row[5],expectedSum);const r=row[2],growth=(1+r)**expectedInput;assert(Math.abs(100*growth-100/r*(growth-1)+10)<1e-5);console.log(JSON.stringify({phase:'values',preview,row}))}
 await page.goto(`${base}/reports/v1/editor/assets/native.html`);await ready();await check(5,8)
 await goto('A1');if(!preview){const a1=await page.evaluate(()=>{const rect=window.__valuesRuntime.univerAPI.getActiveWorkbook().getActiveSheet().getRange('A1').getCellRect(),canvas=[...document.querySelectorAll('#workbook-grid canvas')].map(node=>node.getBoundingClientRect()).find(rect=>rect.x>=0&&rect.y>=0&&rect.width>500&&rect.height>100);return{x:canvas.x+rect.x+rect.width/2,y:canvas.y+rect.y+rect.height/2}});await page.mouse.click(a1.x,a1.y)}await page.keyboard.type('10');await page.keyboard.press('Enter');await check(10,13)
 await page.reload();await ready();await check(10,13)
 await page.locator('[data-action="save"]').click();await page.waitForFunction(()=>document.querySelector('.save-state-label')?.textContent==='已保存修订 2',null,{timeout:60000})
 const actual=JSON.parse(python({mode:'inspect',bytes:saved.toString('base64')}));assert.deepEqual(actual,{C1:'=RATE(A1,-100,100,10)',B1:'=CELL("filename",A1)',B2:'keep',A1:10,D1:'=_xlfn.MINIFS(A1:A2,A1:A2,99)',E1:'=_xlfn.MAXIFS(A1:A2,A1:A2,99)',F1:'=SUM(A1:A2)'})
 assert.equal(payload.operations.filter(op=>op.kind==='applyCellEdits').flatMap(op=>op.edits).length,1)
 await page.route('**/reports/v1/native/function-dialog/2/api/context',r=>r.fulfill({json:{context:{...ctx(saved),revision:2,parentRevision:1},csrfToken:'csrf',capabilities:{xlsx_editor:true},editingEnabled:true}}))
 await page.route('**/reports/v1/native/function-dialog/2/api/file',r=>r.fulfill({body:saved,contentType:media}))
 await page.addInitScript(()=>history.replaceState(null,'','/reports/v1/native/function-dialog/2'));await page.goto(`${base}/reports/v1/native/function-dialog/2`);await ready();await check(10,13)
 if(preview){const scripts=await Promise.all(scriptProof);assert(scripts.some(path=>/workbook-main-/.test(path)));assert(scripts.some(path=>/workbook-insert-function-/.test(path)));assert(scripts.some(path=>/workbook-future-functions-/.test(path)));console.log(JSON.stringify({phase:'built-proof',js200AndHashMatch:scripts.length,nativeClipboard:true,functionAssets:[...new Set(scripts.filter(path=>/workbook-(main|engine-|insert-function-|future-functions-)/.test(path)))]}))}
 assert.deepEqual(errors,[]);console.log(JSON.stringify({ok:true,preview,initialOverrides:true,inputRecalculation:true,draftRecovery:true,pythonPatchAndOpenpyxl:true,revisionReopen:true,actual,pageErrors:errors}))
}finally{await browser?.close();server.kill()}
