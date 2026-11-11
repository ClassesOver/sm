// 官方DV checkbox：真实Ribbon/鼠标/剪贴板/草稿/Python保存/新修订链接。
import assert from 'node:assert/strict'
import {spawn,spawnSync} from 'node:child_process'
import {createHash} from 'node:crypto'
import {setTimeout as delay} from 'node:timers/promises'
import {chromium} from 'playwright'
import {readFile} from 'node:fs/promises'
const frontend=process.cwd(),repo=new URL('../../../',`file://${frontend}/`).pathname,port=Number(process.env.WORKBOOK_SMOKE_PORT??4201),preview=process.env.WORKBOOK_SMOKE_PREVIEW==='1',base=`http://127.0.0.1:${port}`,media='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
function py(p){const r=spawnSync(`${repo}/.venv/bin/python`,['-c',`
import base64,json,sys
from zipfile import ZipFile
from io import BytesIO
from openpyxl import Workbook,load_workbook
from openpyxl.worksheet.datavalidation import DataValidation
from smart_reporting.report_editor.native_office import patch_office
p=json.load(sys.stdin)
if p['mode']=='create':
 b=Workbook();s=b.active;s.title='Checks';s['B1']='keep';s['A2']=0;v=DataValidation(type='list',formula1='"1,0"');v.add('D1');s.add_data_validation(v);t=b.create_sheet('Protected');t.protection.sheet=True;t['A1']='private';f=BytesIO();b.save(f);print(base64.b64encode(f.getvalue()).decode())
elif p['mode']=='patch':print(base64.b64encode(patch_office('xlsx',base64.b64decode(p['bytes']),p['operations'])).decode())
else:
 data=base64.b64decode(p['bytes']);b=load_workbook(BytesIO(data));s=b['Checks']
 with ZipFile(BytesIO(data)) as z,ZipFile(BytesIO(base64.b64decode(p['source']))) as original:
  xml=z.read('xl/worksheets/sheet1.xml').decode();assert set(z.namelist())==set(original.namelist());changed=[name for name in z.namelist() if z.read(name)!=original.read(name)]
 print(json.dumps({'A2':s['A2'].value,'B1':s['B1'].value,'lists':[str(v.sqref) for v in s.data_validations.dataValidation if v.type=='list'],'protected':b['Protected'].protection.sheet,'protectedValue':b['Protected']['A1'].value,'checkboxMetadata':'urn:smart-reporting:xlsx:checkbox:1' in xml,'changedParts':changed}))
`],{cwd:repo,env:{...process.env,PYTHONPATH:repo},input:JSON.stringify(p),encoding:'utf8'});assert.equal(r.status,0,r.stderr);return r.stdout.trim()}
const bytes=Buffer.from(py({mode:'create'}),'base64');let saved,payload,browser
const ctx=(data,revision)=>({documentId:'checkbox',format:'xlsx',revision,parentRevision:revision===1?null:1,scope:{database:'f',companyId:'f',userId:'f',threadId:'f'},sourceFile:{path:'checkbox.xlsx',size:data.length,sha256:createHash('sha256').update(data).digest('hex'),mediaType:media},origin:'upload'})
const server=spawn('./node_modules/.bin/vite',[...(preview?['preview']:[]),'--host','127.0.0.1','--port',String(port),'--strictPort'],{cwd:frontend,stdio:'ignore'})
try{
 for(let i=0;i<100;i++){try{if((await fetch(`${base}/reports/v1/editor/assets/native.html`)).ok)break}catch{}await delay(250)}
 browser=await chromium.launch({headless:true});const page=await browser.newPage({viewport:{width:1440,height:1100},permissions:['clipboard-read','clipboard-write']}),errors=[]
 page.on('pageerror',e=>errors.push(e.message))
 const assetChecks=[];if(preview)page.on('response',r=>{const name=new URL(r.url()).pathname.split('/').at(-1);if(/^lazy-workbook-.*\.js$/.test(name))assetChecks.push((async()=>{const bytes=await r.body(),local=await readFile(`${frontend}/../static/assets/${name}`),sha256=createHash('sha256').update(bytes).digest('hex');assert.equal(r.status(),200);assert.equal(sha256,createHash('sha256').update(local).digest('hex'));return{name,status:200,sha256,staticMatch:true}})())})
 for(const rev of [1,2]){
 await page.route(`**/reports/v1/native/checkbox/${rev}/api/context`,r=>r.fulfill({json:{context:ctx(rev===1?bytes:saved,rev),csrfToken:'csrf',capabilities:{xlsx_editor:true},editingEnabled:true}}))
 await page.route(`**/reports/v1/native/checkbox/${rev}/api/file`,r=>r.fulfill({body:rev===1?bytes:saved,contentType:media}))
 }
 await page.route('**/reports/v1/native/checkbox/1/api/save',async r=>{payload=r.request().postDataJSON();assert.equal(payload.expectedSha256,ctx(bytes,1).sourceFile.sha256);saved=Buffer.from(py({mode:'patch',bytes:bytes.toString('base64'),operations:payload.operations}),'base64');await r.fulfill({json:{documentId:'checkbox',revision:2,parentRevision:1,revisionRegistered:true,artifacts:{xlsx:{downloadUrl:'/checkbox.xlsx'}},editor:{openUrl:'/reports/v1/native/checkbox/2'},validation:{issues:[]}}})})
 await page.route(/\/reports\/v1\/native\/checkbox\/[12]$/,async r=>r.fulfill({response:await r.fetch({url:`${base}/reports/v1/editor/assets/native.html`})}))
 page.on('dialog',d=>d.accept())
 const ready=()=>page.waitForFunction(()=>document.querySelector('#report-editor')?.getAttribute('aria-busy')==='false')
 const go=async ref=>{const box=page.locator('[data-u-comp="defined-name"] input');await box.fill(ref);await box.press('Enter')}
 let copySequence=0
 const snapshot=async()=>{await go('A2');const sentinel=`checkbox-copy-${++copySequence}`;await page.evaluate(s=>navigator.clipboard.writeText(s),sentinel);await page.keyboard.press('Control+c');for(let i=0;i<40;i++){const raw=(await page.evaluate(()=>navigator.clipboard.readText())).trim();if(raw!==sentinel){assert.match(raw,/^[01]$/);return Number(raw)}await delay(25)}throw new Error('原生复制未覆盖本次clipboard sentinel')}
 const expectValue=async value=>{for(let i=0;i<20;i++){if(await snapshot()===value)return;await delay(100)}assert.equal(await snapshot(),value)}
 const clickCheck=async()=>{const p=await page.locator('#workbook-grid canvas').evaluateAll(cs=>{const c=cs.map(n=>n.getBoundingClientRect()).filter(r=>r.x>=0&&r.y>=0&&r.width>500&&r.height>100).sort((a,b)=>b.width*b.height-a.width*a.height)[0];return{x:c.x+90,y:c.y+56}});await delay(400);await page.mouse.click(p.x,p.y);await delay(200)}
 await page.goto(`${base}/reports/v1/native/checkbox/1`);await ready()
 await page.locator('[data-u-comp="defined-name"] input').fill('A2');await page.locator('[data-u-comp="defined-name"] input').press('Enter');await page.locator('[data-ribbon-tab="Insert"]').click();await page.locator('[data-ribbon-command="insert-checkbox"]').click()
 await delay(200);await clickCheck();await expectValue(1)
 await clickCheck();await expectValue(0)
 await page.keyboard.press('Control+z');await expectValue(1)
 await page.keyboard.press('Control+y');await expectValue(0)
 await page.reload();await ready();await expectValue(0)
 await clickCheck();await expectValue(1)
 const saveRect=await page.locator('[data-action="save"]').boundingBox();await page.mouse.click(saveRect.x+saveRect.width/2,saveRect.y+saveRect.height/2)
 const next=page.locator('.native-next-revision');await next.waitFor();const link=await next.boundingBox();await page.mouse.click(link.x+link.width/2,link.y+link.height/2);await page.waitForURL('**/checkbox/2');await ready();await expectValue(1)
 await clickCheck();await expectValue(0)
 assert.deepEqual(errors,[])
 const file=JSON.parse(py({mode:'inspect',bytes:saved.toString('base64'),source:bytes.toString('base64')}));assert.equal(file.A2,1);assert.equal(file.B1,'keep');assert.equal(file.protected,true);assert.equal(file.protectedValue,'private');assert.equal(file.checkboxMetadata,true);assert.deepEqual(file.lists.sort(),['A2','D1']);assert.deepEqual(file.changedParts,['xl/worksheets/sheet1.xml'])
 console.log(JSON.stringify({phase:'ribbon-checkbox-undo-draft-save-reopen',preview,operations:payload.operations.map(i=>i.kind),file,errors,assets:await Promise.all(assetChecks)}))
}finally{await browser?.close();server.kill()}
