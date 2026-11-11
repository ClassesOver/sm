// 固定源14预设入口的代表组合；真实菜单/撤销/草稿/Python文件与修订重开。
import assert from 'node:assert/strict'
import {readFileSync} from 'node:fs'
import {spawn,spawnSync} from 'node:child_process'
import {createHash} from 'node:crypto'
import {setTimeout as delay} from 'node:timers/promises'
import {chromium} from 'playwright'
const preview=process.env.NATIVE_GUI_PREVIEW==='1'
const frontend=process.cwd(),repo=new URL('../../../',`file://${frontend}/`).pathname,port=Number(process.env.WORKBOOK_STYLE_SMOKE_PORT??4202),base=`http://127.0.0.1:${port}`,media='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
function python(p){const r=spawnSync(`${repo}/.venv/bin/python`,['-c',`
import base64,json,sys
from io import BytesIO
from openpyxl import Workbook,load_workbook
from openpyxl.styles import Font,Border,Side
from smart_reporting.report_editor.native_office import patch_office
p=json.load(sys.stdin)
if p['mode']=='create':
 b=Workbook();s=b.active;s.title='Presets'
 for r in [1,2]:
  for c in [1,2,4,5,7,8,10]:
   cell=s.cell(r,c,r*10+c);cell.font=Font(name='Arial',size=11,italic=True,color='112233');cell.number_format='0.00';cell.border=Border(bottom=Side(style='double',color='123456'))
 s['A1']='=1+1';s['M1']='untouched';f=BytesIO();b.save(f);print(base64.b64encode(f.getvalue()).decode())
elif p['mode']=='patch':print(base64.b64encode(patch_office('xlsx',base64.b64decode(p['bytes']),p['operations'])).decode())
else:
 s=load_workbook(BytesIO(base64.b64decode(p['bytes'])))['Presets']
 def color(c):return None if c is None else c.rgb[-6:] if c.type=='rgb' else str(c.indexed)
 def edge(e):return None if e is None or e.style is None else {'style':e.style,'color':color(e.color)}
 def cell(a):
  c=s[a];return {'value':c.value,'italic':c.font.italic,'bold':c.font.bold,'size':c.font.sz,'font':c.font.name,'color':color(c.font.color),'fill':color(c.fill.fgColor),'number':c.number_format,'top':edge(c.border.top),'bottom':edge(c.border.bottom),'left':edge(c.border.left),'right':edge(c.border.right)}
 print(json.dumps({a:cell(a) for a in ['A1','A2','B1','B2','D1','D2','E1','E2','G1','G2','H1','H2','J1','J2','M1']}))
`],{cwd:repo,input:JSON.stringify(p),encoding:'utf8'});assert.equal(r.status,0,r.stderr);return r.stdout.trim()}
const bytes=Buffer.from(python({mode:'create'}),'base64');let saved,payload,browser
const ctx=(data,revision)=>({documentId:'cell-presets',format:'xlsx',revision,parentRevision:revision===1?null:1,scope:{database:'f',companyId:'f',userId:'f',threadId:'f'},sourceFile:{path:'presets.xlsx',size:data.length,sha256:createHash('sha256').update(data).digest('hex'),mediaType:media},origin:'upload'})
const server=spawn('./node_modules/.bin/vite',[...(preview?['preview']:[]),'--host','127.0.0.1','--port',String(port),'--strictPort'],{cwd:frontend,stdio:'ignore'})
try{
 for(let i=0;i<120;i++){try{if((await fetch(`${base}/reports/v1/editor/assets/native.html`)).ok)break}catch{}await delay(250)}
 browser=await chromium.launch({headless:true});const page=await browser.newPage({viewport:{width:1440,height:1100}}),errors=[];page.on('pageerror',e=>errors.push(e.message));page.on('dialog',d=>d.accept())
 const scriptProof=[];if(preview)page.on('response',response=>{const url=new URL(response.url());if(url.pathname.startsWith('/reports/v1/editor/assets/')&&url.pathname.endsWith('.js'))scriptProof.push((async()=>{assert.equal(response.status(),200);const bytes=await response.body();assert.equal(createHash('sha256').update(bytes).digest('hex'),createHash('sha256').update(readFileSync(`../static/${url.pathname.slice('/reports/v1/editor/assets/'.length)}`)).digest('hex'));return url.pathname})())})
 if(!preview)await page.route('**/src/workbook-vendor/grid/create-univer.ts*',async route=>{const response=await route.fetch(),body=await response.text();assert(body.includes('return { univer, univerAPI: FUniver.newAPI(univer) };'));await route.fulfill({response,body:body.replace('return { univer, univerAPI: FUniver.newAPI(univer) };','return window.__styleRuntime = { univer, univerAPI: FUniver.newAPI(univer) };')})})
 for(const rev of [1,2]){
  await page.route(`**/reports/v1/native/cell-presets/${rev}/api/context`,r=>r.fulfill({json:{context:ctx(rev===1?bytes:saved,rev),csrfToken:'csrf',capabilities:{xlsx_editor:true},editingEnabled:true}}))
  await page.route(`**/reports/v1/native/cell-presets/${rev}/api/file`,r=>r.fulfill({body:rev===1?bytes:saved,contentType:media}))
 }
 await page.route('**/reports/v1/native/cell-presets/1/api/save',async r=>{payload=r.request().postDataJSON();saved=Buffer.from(python({mode:'patch',bytes:bytes.toString('base64'),operations:payload.operations}),'base64');await r.fulfill({json:{documentId:'cell-presets',revision:2,parentRevision:1,revisionRegistered:true,artifacts:{xlsx:{downloadUrl:'/presets.xlsx'}},editor:{openUrl:'/reports/v1/native/cell-presets/2'},validation:{issues:[]}}})})
 await page.route(/\/reports\/v1\/native\/cell-presets\/[12]$/,async r=>r.fulfill({response:await r.fetch({url:`${base}/reports/v1/editor/assets/native.html`})}))
 const ready=()=>page.waitForFunction(()=>document.querySelector('#report-editor')?.getAttribute('aria-busy')==='false')
 const go=async ref=>{await page.locator('[data-ribbon-tab="Home"]').click();await page.locator('[data-ribbon-command="goto-open"]').click();await page.locator('[data-goto-reference]').fill(ref);await page.locator('.workbook-ribbon-goto-dialog button[type="submit"]').click()}
 const apply=async(ref,id)=>{await go(ref);const select=page.locator('select[data-ribbon-control="cell-style"]');assert.equal(await select.locator('option').count(),15);await select.selectOption(id)}
 const style=ref=>page.evaluate(ref=>window.__styleRuntime.univerAPI.getActiveWorkbook().getActiveSheet().getRange(ref).getCellStyleData(),ref)
 const waitStyle=async(ref,expected)=>{if(preview)return;for(let i=0;i<100;i++){const actual=await style(ref);try{assert.partialDeepStrictEqual(actual,expected);return actual}catch{}await delay(50)}assert.partialDeepStrictEqual(await style(ref),expected)}
 await page.goto(`${base}/reports/v1/native/cell-presets/1`);await ready()
 await apply('A1:B2','input');await waitStyle('A1',{bg:{rgb:'#FFCC99'},cl:{rgb:'#3F3F76'}})
 await apply('D1:E2','heading-1');await waitStyle('D1',{bl:1,fs:15,cl:{rgb:'#44546A'}})
 await apply('G1:H2','total');await waitStyle('G1',{bl:1})
 await apply('J1:J2','good');await waitStyle('J1',{bg:{rgb:'#C6EFCE'},cl:{rgb:'#006100'}})
 // good两条官方属性命令：一次undo只退回最后的fill，字体颜色仍是good。
 await go('J1');await page.keyboard.press('Control+z');await waitStyle('J1',{cl:{rgb:'#006100'}});if(!preview)assert.notEqual((await style('J1')).bg?.rgb,'#C6EFCE')
 await page.keyboard.press('Control+y');await waitStyle('J1',{bg:{rgb:'#C6EFCE'},cl:{rgb:'#006100'}})
 await page.reload();await ready();await waitStyle('J1',{bg:{rgb:'#C6EFCE'},cl:{rgb:'#006100'}});await waitStyle('D1',{bl:1,fs:15})
 await page.locator('[data-action="save"]').click();const next=page.locator('.native-next-revision');await next.waitFor()
 const file=JSON.parse(python({mode:'inspect',bytes:saved.toString('base64')}))
 const edge=(style,color)=>({style,color})
 for(const a of ['A1','A2','B1','B2']){assert.equal(file[a].fill,'FFCC99');assert.equal(file[a].color,'3F3F76');for(const side of ['top','bottom','left','right'])assert.deepEqual(file[a][side],edge('thin','7F7F7F'))}
 for(const a of ['D1','D2','E1','E2']){assert.equal(file[a].bold,true);assert.equal(file[a].size,15);assert.equal(file[a].color,'44546A');assert.deepEqual(file[a].bottom,a.endsWith('2')?edge('thin','4472C4'):edge('double','123456'))}
 for(const a of ['G1','G2','H1','H2']){assert.equal(file[a].bold,true);assert.deepEqual(file[a].top,a.endsWith('1')?edge('thin','4472C4'):null);assert.deepEqual(file[a].bottom,edge('double','123456'))}
 for(const a of ['J1','J2']){assert.equal(file[a].fill,'C6EFCE');assert.equal(file[a].color,'006100')}
 for(const [a,c]of Object.entries(file)){if(a==='M1')continue;assert.equal(c.italic,true);assert.equal(c.number,'0.00');assert.equal(c.font,'Arial')}
 assert.equal(file.A1.value,'=1+1');assert.equal(file.M1.value,'untouched')
 await next.click();await page.waitForURL('**/cell-presets/2');await ready();await waitStyle('A1',{bg:{rgb:'#FFCC99'},cl:{rgb:'#3F3F76'}});await waitStyle('D1',{bl:1,fs:15});await waitStyle('J1',{bg:{rgb:'#C6EFCE'}})
 if(preview){const scripts=await Promise.all(scriptProof);console.log(JSON.stringify({phase:'cell-styles-built-proof',js200AndSha:scripts.length,assets:[...new Set(scripts.filter(path=>/workbook-(main|cell-style-presets|engine-)/.test(path)))]}))}
 assert.deepEqual(errors,[]);console.log(JSON.stringify({ok:true,mode:preview?'built-with-file-verification':'dev-runtime-readonly-observer',menuPresets:['input','heading-1','total','good'],sourceStepUndo:!preview,undoRedoExecuted:true,draftRecovery:true,pythonPatchAndOpenpyxl:true,revisionReopen:true,file,pageErrors:errors,operations:payload.operations.map(op=>op.kind)}))
}finally{await browser?.close();server.kill()}
