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
 b=Workbook();s=b.active;s.title='Values';s['A1']=2;s['A2']=3;s['B1']='=SUM(A1:A2)';s['B2']='keep';b.create_sheet('Other Sheet');f=BytesIO();b.save(f);print(base64.b64encode(f.getvalue()).decode())
elif p['mode']=='patch':print(base64.b64encode(patch_office('xlsx',base64.b64decode(p['bytes']),p['operations'])).decode())
else:
 b=load_workbook(BytesIO(base64.b64decode(p['bytes'])));print(json.dumps({'C3':b['Values']['C3'].value,'B1':b['Values']['B1'].value,'B2':b['Values']['B2'].value}))
`],{input:JSON.stringify(payload),encoding:'utf8',cwd:repo});if(result.status!==0)throw Error(result.stderr);return result.stdout.trim()}
const bytes=Buffer.from(python({mode:'create'}),'base64'),media='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
const ctx=source=>({documentId:'function-dialog',format:'xlsx',revision:1,parentRevision:null,scope:{database:'f',companyId:'f',userId:'f',threadId:'f'},sourceFile:{path:'functions.xlsx',size:source.length,sha256:createHash('sha256').update(source).digest('hex'),mediaType:media},origin:'upload'})
const server=spawn('./node_modules/.bin/vite',[...(preview?['preview']:[]),'--host','127.0.0.1','--port','4198','--strictPort'],{cwd:frontend,stdio:'ignore'})
let browser,saved,payload,activePage
try{
 for(let i=0;i<120;i++){try{if((await fetch(`${base}/reports/v1/editor/assets/native.html`)).ok)break}catch{}await delay(250)}
 browser=await chromium.launch({headless:true,args:['--disable-features=LocalNetworkAccessChecks']});const page=await browser.newPage({viewport:{width:1440,height:1100}}),errors=[]
 page.on('framenavigated',frame=>{if(frame===page.mainFrame())console.log(JSON.stringify({phase:'navigation',url:frame.url()}))})
 activePage=page
 const scriptProof=[]
 if(preview)page.on('response',response=>{const url=new URL(response.url());if(url.pathname.startsWith('/reports/v1/editor/assets/')&&url.pathname.endsWith('.js'))scriptProof.push((async()=>{assert.equal(response.status(),200);const body=await response.body(),path=`../static/${url.pathname.slice('/reports/v1/editor/assets/'.length)}`;assert.equal(createHash('sha256').update(body).digest('hex'),createHash('sha256').update(readFileSync(path)).digest('hex'));return url.pathname})())})
 let guardStage='startup';page.on('pageerror',error=>{errors.push(error.message);console.log(JSON.stringify({phase:'pageerror',guardStage,message:error.message,stack:error.stack}))})
 if(process.env.FUNCTION_GUI_GUARDS==='1')await page.route('**/src/workbook-main.ts*',async route=>{const response=await route.fetch(),body=await response.text(),patched=body.replace('const editable = () =>','const editable = () => !window.__fnReadOnly &&');assert.notEqual(patched,body);await route.fulfill({response,body:patched})})
 if(!preview){
  await page.route('**/src/workbook-function-runtime.ts*',async route=>{const response=await route.fetch();let body=await response.text();body=body.replace('export function createWorkbookFunctionHost(', 'function createWorkbookFunctionHostOriginal(');body+='\nexport function createWorkbookFunctionHost(runtime,options){window.__fnRuntime=runtime;const host=createWorkbookFunctionHostOriginal(runtime,options),evaluate=host.evaluate;host.evaluate=async(...args)=>{try{const result=await evaluate(...args);window.__fnEvaluation={expressions:args[1],result};return result}catch(error){window.__fnEvaluation={error:String(error)};throw error}};return host}';await route.fulfill({response,body})})
  await page.route('**/src/workbook-function-catalog.ts*',async route=>{const response=await route.fetch();let body=await response.text();body=body.replace('import { FunctionType }','import { FunctionType, IFunctionService }');body+='\nwindow.__fnServiceToken=IFunctionService;';await route.fulfill({response,body})})
 }
 await page.route('**/reports/v1/native/function-dialog/1/api/context',r=>r.fulfill({json:{context:ctx(bytes),csrfToken:'csrf',capabilities:{xlsx_editor:true},editingEnabled:true}}))
 await page.route('**/reports/v1/native/function-dialog/1/api/file',r=>r.fulfill({body:bytes,contentType:media}))
 await page.route('**/reports/v1/native/function-dialog/1/api/save',async r=>{payload=r.request().postDataJSON();saved=Buffer.from(python({mode:'patch',bytes:bytes.toString('base64'),operations:payload.operations}),'base64');await r.fulfill({json:{documentId:'function-dialog',revision:2,parentRevision:1,revisionRegistered:true,artifacts:{xlsx:{downloadUrl:'/functions.xlsx'}},editor:{openUrl:'/reports/v1/native/function-dialog/2'},validation:{issues:[]}}})})
 await page.route(/\/reports\/v1\/native\/function-dialog\/[12]$/,async r=>r.fulfill({response:await r.fetch({url:`${base}/reports/v1/editor/assets/native.html`})}))
 await page.addInitScript(()=>history.replaceState(null,'','/reports/v1/native/function-dialog/1'))
 await page.goto(`${base}/reports/v1/editor/assets/native.html`);await page.waitForFunction(()=>document.querySelector('#report-editor')?.getAttribute('aria-busy')==='false')
 const goto=async reference=>{await page.locator('[data-ribbon-tab="Home"]').click();await page.locator('[data-ribbon-command="goto-open"]').click();await page.locator('[data-goto-reference]').fill(reference);await page.locator('.workbook-ribbon-goto-dialog button[type="submit"]').click()}
 const draft=()=>page.evaluate(()=>Object.fromEntries(Object.keys(localStorage).filter(k=>k.startsWith('native-editor-draft:')).map(k=>[k,localStorage.getItem(k)])))
 if(process.env.FUNCTION_GUI_GUARDS==='1'){
  assert(!preview)
  await goto('B1');const before=await draft(),fx=page.locator('[data-u-comp="formula-bar"] .univerjs-icon-fx-icon')
  const nativeFxPhysical=await fx.count()>0;console.log(JSON.stringify({phase:'fx-host',nativeFxPhysical,formulaBars:await page.locator('[data-u-comp="formula-bar"]').count()}));assert(nativeFxPhysical,'source-native formula bar fx must be mounted');const triggerFx=async()=>{await fx.click()}
  guardStage='native-open';await triggerFx();await page.locator('.function-args-dialog').waitFor();assert.equal(await page.locator('.workbook-function-root [role="dialog"]').count(),1);assert.equal(await page.locator('.fn-args-row input').first().inputValue(),'A1:A2')
  guardStage='cancel';await page.locator('.function-args-dialog .dialog-actions .secondary').click();await page.keyboard.press('Escape');assert.deepEqual(await draft(),before)
  await page.locator('[data-ribbon-tab="Review"]').click();await page.locator('[data-ribbon-command="sheet-protect"]').click();await page.locator('[data-ribbon-tab="Formulas"]').click();assert(await page.locator('[data-ribbon-command="insert-function-open"]').isDisabled())
  const protectedDraft=await draft();guardStage='protected-fx';await triggerFx();await page.waitForFunction(()=>document.querySelector('.workbook-feedback')?.textContent?.includes('工作表受保护'));assert.equal(await page.locator('.workbook-function-root [role="dialog"]').count(),0);await page.keyboard.press('Escape');assert.deepEqual(await draft(),protectedDraft)
  await page.locator('[data-ribbon-tab="Review"]').click();await page.locator('[data-ribbon-command="sheet-protect"]').click();await page.locator('[data-ribbon-tab="Formulas"]').click()
  await page.evaluate(()=>{window.__fnReadOnly=true});const readonlyDraft=await draft();guardStage='readonly-fx';await triggerFx();await page.waitForFunction(()=>document.querySelector('.workbook-feedback')?.textContent?.includes('不可编辑'));assert.equal(await page.locator('.workbook-function-root [role="dialog"]').count(),0);await page.keyboard.press('Escape');assert.deepEqual(await draft(),readonlyDraft)
  await page.evaluate(()=>{window.__fnReadOnly=false});await goto('B1');guardStage='fx-confirm';await triggerFx();await page.locator('.function-args-dialog').waitFor();await page.locator('.fn-args-row input').first().fill('A1');await page.locator('.function-args-dialog .primary-action').click();await page.waitForFunction(()=>!document.querySelector('.function-args-dialog'));assert.equal(await page.evaluate(()=>window.__fnRuntime.univerAPI.getActiveWorkbook().getActiveSheet().getRange('B1').getFormula()),'=SUM(A1)');await page.keyboard.press('Escape')
  assert.deepEqual(errors,[]);console.log(JSON.stringify({ok:true,case:'native-fx-readonly-protection',nativeFxPhysical,nativeFxSingleDialog:true,cancelNoDraft:true,protectedBlocked:true,injectedReadonlyBlocked:true,pageErrors:errors}));process.exitCode=0
 }else{
 await goto('C3');const before=await draft()
 await page.locator('[data-ribbon-tab="Formulas"]').click();await page.locator('[data-ribbon-command="insert-function-open:Financial"]').click()
 await page.locator('.insert-function-dialog').waitFor();assert.equal(await page.locator('[aria-label="函数类别"]').inputValue(),'Financial')
 await page.locator('.fn-filter-row input').fill('SUM');await page.locator('.fn-row').filter({has:page.locator('strong',{hasText:/^SUM\(/})}).dblclick()
 await page.locator('.function-args-dialog').waitFor();assert.equal(await page.locator('.fn-args-name').innerText(),'SUM');assert.deepEqual(await draft(),before)
 await page.locator('.fn-args-row input').first().fill('A1:A2');await page.waitForFunction(()=>document.querySelector('.fn-args-result strong')?.textContent==='5')
 if(!preview){
  const fallback=[...readFileSync('src/workbook-function-catalog-dialog.tsx','utf8').matchAll(/name: '([A-Z][A-Z0-9.]*)'/g)].map(match=>match[1])
  const registry=await page.evaluate(names=>{const service=window.__fnRuntime.univer.__getInjector().get(window.__fnServiceToken);return {count:names.length,missing:names.filter(name=>!service.hasExecutor(name))}},fallback)
  console.log(JSON.stringify({phase:'fallback-registry',...registry}));assert.deepEqual(registry.missing,[])
  // 真实pointer range pick更换当前选区；写回仍须落在捕获的C3。
  const point=await page.evaluate(()=>{const rect=window.__fnRuntime.univerAPI.getActiveWorkbook().getActiveSheet().getRange('A1').getCellRect(),canvas=[...document.querySelectorAll('#workbook-grid canvas')].map(node=>node.getBoundingClientRect()).find(rect=>rect.x>=0&&rect.y>=0&&rect.width>500&&rect.height>100);return{x:canvas.x+rect.x+rect.width/2,y:canvas.y+rect.y+rect.height/2}})
  console.log(JSON.stringify({phase:'range-point',point}))
  await page.locator('.fn-args-pick').first().click();await page.mouse.click(point.x,point.y);await page.waitForFunction(()=>document.querySelector('.fn-args-row input')?.value==='A1');await page.locator('.fn-args-pick').click();await page.locator('.fn-args-row input').first().fill('A1:A2')
 }
 await page.locator('.function-args-dialog .primary-action').click();await page.waitForFunction(()=>!document.querySelector('.function-args-dialog'))
 await page.reload();await page.waitForFunction(()=>document.querySelector('#report-editor')?.getAttribute('aria-busy')==='false')
 await page.locator('[data-action="save"]').click();await page.waitForFunction(()=>document.querySelector('.save-state-label')?.textContent==='已保存修订 2',null,{timeout:60000})
 const actual=JSON.parse(python({mode:'inspect',bytes:saved.toString('base64')}));assert.equal(actual.C3,'=SUM(A1:A2)');assert.equal(actual.B2,'keep')
 await page.route('**/reports/v1/native/function-dialog/2/api/context',r=>r.fulfill({json:{context:{...ctx(saved),revision:2,parentRevision:1},csrfToken:'csrf',capabilities:{xlsx_editor:true},editingEnabled:true}}))
 await page.route('**/reports/v1/native/function-dialog/2/api/file',r=>r.fulfill({body:saved,contentType:media}))
 await page.addInitScript(()=>history.replaceState(null,'','/reports/v1/native/function-dialog/2'));await page.goto(`${base}/reports/v1/native/function-dialog/2`);await page.waitForFunction(()=>document.querySelector('#report-editor')?.getAttribute('aria-busy')==='false')
 await goto('C3');await page.locator('[data-ribbon-tab="Formulas"]').click();await page.locator('[data-ribbon-command="insert-function-open"]').click();await page.locator('.function-args-dialog').waitFor();assert.equal(await page.locator('.fn-args-row input').first().inputValue(),'A1:A2');await page.locator('.function-args-dialog .secondary').last().click()
 if(preview){
  await page.keyboard.press('Escape');await goto('C3');const beforeFx=await draft(),fx=page.locator('[data-u-comp="formula-bar"] .univerjs-icon-fx-icon');assert.equal(await fx.count(),1);await fx.click();await page.locator('.function-args-dialog').waitFor();assert.equal(await page.locator('.workbook-function-root [role="dialog"]').count(),1);await page.locator('.function-args-dialog .secondary').last().click();await page.keyboard.press('Escape');assert.deepEqual(await draft(),beforeFx)
  const point=await page.evaluate(()=>{const rect=[...document.querySelectorAll('#workbook-grid canvas')].map(node=>node.getBoundingClientRect()).find(rect=>rect.x>=0&&rect.y>=0&&rect.width>500&&rect.height>100);return{x:rect.x+140,y:rect.y+80}});await page.mouse.click(point.x,point.y);await page.keyboard.press('Shift+F3');await page.locator('.workbook-function-root [role="dialog"]').waitFor();assert.equal(await page.locator('.workbook-function-root [role="dialog"]').count(),1);await page.keyboard.press('Escape');await page.waitForFunction(()=>!document.querySelector('.workbook-function-root [role="dialog"]'))
  const scripts=await Promise.all(scriptProof);assert(scripts.some(path=>/workbook-main-/.test(path)));console.log(JSON.stringify({phase:'built-proof',js200AndHashMatch:scripts.length,physicalFxCancelEscape:true,shiftF3FromGrid:true}))
 }
 assert.deepEqual(errors,[]);console.log(JSON.stringify({ok:true,preview,actual,formulaDraftAndRevisionReopen:true,categorySearch:true,enginePreview:true,rangePickAndCapturedCell:!preview,pageErrors:errors}))
 }
}catch(error){if(activePage)console.error(await activePage.evaluate(()=>({evaluation:window.__fnEvaluation,fxHas:window.__fnFxHas,openStarted:window.__fnOpenStarted,target:window.__fnTarget,catalog:!!document.querySelector('.insert-function-dialog'),feedback:document.querySelector('.workbook-feedback')?.textContent,result:document.querySelector('.fn-args-result')?.textContent})));console.error(error);throw error}finally{await browser?.close();server.kill()}
