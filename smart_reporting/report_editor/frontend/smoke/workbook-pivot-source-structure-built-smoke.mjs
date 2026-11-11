import assert from 'node:assert/strict'
import { createServer } from 'node:http'
import { spawn, spawnSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import { readFileSync, writeFileSync, mkdtempSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { setTimeout as delay } from 'node:timers/promises'
import { chromium } from 'playwright'
const frontend=fileURLToPath(new URL('../',import.meta.url)),repo=fileURLToPath(new URL('../../../../',import.meta.url)),port=Number(process.env.PIVOT_STRUCTURE_SMOKE_PORT??4240),base=`http://127.0.0.1:${port}`,temporary=mkdtempSync(join(tmpdir(),'pivot-source-structure-built-'))
const sha=bytes=>createHash('sha256').update(bytes).digest('hex')
function python(payload){const r=spawnSync(`${repo}/.venv/bin/python`,['-c',`
import json,sys,base64
from io import BytesIO
from zipfile import ZipFile
from openpyxl import Workbook,load_workbook
from openpyxl.pivot.table import TableDefinition, Location
from openpyxl.pivot.cache import CacheDefinition, CacheSource, WorksheetSource, CacheField, SharedItems
from smart_reporting.report_editor.native_office import patch_office
p=json.load(sys.stdin)
if p['mode']=='create':
 b=Workbook();s=b.active;s.title='Source';s.append(['Category','Amount']);s.append(['A',10])
 pivot=b.create_sheet('Pivot');unused=b.create_sheet('Unused');unused.append(['Head','Count']);unused.append(['U-A',21]);unused.append(['U-B',32])
 table=TableDefinition(name='Report',cacheId=1,dataCaption='Values',location=Location(ref='A1:B3',firstHeaderRow=1,firstDataRow=1,firstDataCol=1))
 table.cache=CacheDefinition(cacheSource=CacheSource(type='worksheet',worksheetSource=WorksheetSource(ref='A1:B2',sheet=s.title)),cacheFields=[CacheField(name='Category',sharedItems=SharedItems()),CacheField(name='Amount',sharedItems=SharedItems())])
 pivot.add_pivot(table)
 f=BytesIO();b.save(f);print(base64.b64encode(f.getvalue()).decode())
elif p['mode']=='patch':print(base64.b64encode(patch_office('xlsx',base64.b64decode(p['bytes']),p['operations'])).decode())
else:
 raw=base64.b64decode(p['bytes']);b=load_workbook(BytesIO(raw));before=ZipFile(BytesIO(base64.b64decode(p['original'])));after=ZipFile(BytesIO(raw))
 parts=sorted(n for n in before.namelist() if n.startswith(('xl/pivotCache/','xl/pivotTables/')))
 assert parts and any('pivotCacheDefinition' in n for n in parts) and any('pivotTable1.xml' in n for n in parts)
 print(json.dumps({'sheetNames':b.sheetnames,'sourceValues':list(b['Source'].values),'pivotCount':len(b['Pivot']._pivots),'cacheSource':b['Pivot']._pivots[0].cache.cacheSource.worksheetSource.sheet,'pivotParts':parts,'pivotPartSetUnchanged':parts==sorted(n for n in after.namelist() if n.startswith(('xl/pivotCache/','xl/pivotTables/'))),'pivotBytesUnchanged':all(before.read(n)==after.read(n) for n in parts),'pivotSheetBytesUnchanged':before.read('xl/worksheets/sheet2.xml')==after.read('xl/worksheets/sheet2.xml'),'stylesUnchanged':before.read('xl/styles.xml')==after.read('xl/styles.xml'),'unusedValues':list(b['Unused'].values),'partSetUnchanged':set(before.namelist())==set(after.namelist()),'allOtherPartBytesUnchanged':all(before.read(n)==after.read(n) for n in before.namelist() if n!='xl/worksheets/sheet3.xml'),'changedParts':[n for n in before.namelist() if before.read(n)!=after.read(n)]}))
`],{input:JSON.stringify(payload),encoding:'utf8',cwd:repo});assert.equal(r.status,0,r.stderr);return r.stdout.trim()}
const bytes=Buffer.from(python({mode:'create'}),'base64'),media='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',context={documentId:'pivot-structure-guard',format:'xlsx',revision:1,parentRevision:null,scope:{database:'f',companyId:'f',userId:'f',threadId:'f'},sourceFile:{path:'pivot.xlsx',size:bytes.length,sha256:createHash('sha256').update(bytes).digest('hex'),mediaType:media},origin:'upload'}
const server=spawn('./node_modules/.bin/vite',['preview','--host','127.0.0.1','--port',String(port),'--strictPort'],{cwd:frontend,stdio:'ignore'})
let browser,saved,payload,page,stage='setup',routeError,saveCount=0
const downloadServer=createServer((request,response)=>{if(request.url!=='/pivot-structure-guard.xlsx'||!saved){response.writeHead(404);response.end();return}response.writeHead(200,{'Content-Type':media,'Content-Disposition':'attachment; filename=pivot-structure-guard.xlsx','Content-Length':saved.length});response.end(saved)})
await new Promise(resolve=>downloadServer.listen(0,'127.0.0.1',resolve))
const downloadUrl=`http://127.0.0.1:${downloadServer.address().port}/pivot-structure-guard.xlsx`
try{
 for(let i=0;i<120;i++){try{if((await fetch(`${base}/reports/v1/editor/assets/native.html`)).ok)break}catch{}await delay(250)}
 browser=await chromium.launch({headless:true});page=await browser.newPage({viewport:{width:1500,height:1100},acceptDownloads:true,permissions:['clipboard-read','clipboard-write']});const errors=[],scriptProof=[]
 page.on('pageerror',e=>errors.push(e.message));page.on('console',message=>{if(message.type()==='error')errors.push(message.text())})
 page.on('response',response=>{const url=new URL(response.url());if(url.pathname.startsWith('/reports/v1/editor/assets/')&&url.pathname.endsWith('.js'))scriptProof.push((async()=>{assert.equal(response.status(),200);const body=await response.body(),path=`../static/${url.pathname.slice('/reports/v1/editor/assets/'.length)}`;assert.equal(createHash('sha256').update(body).digest('hex'),createHash('sha256').update(readFileSync(join(frontend,path))).digest('hex'));return url.pathname})())})
 await page.route('**/reports/v1/native/pivot-structure-guard/1/api/context',r=>r.fulfill({json:{context,csrfToken:'csrf',capabilities:{xlsx_editor:true},editingEnabled:true}}))
 await page.route('**/reports/v1/native/pivot-structure-guard/1/api/file',r=>r.fulfill({body:bytes,contentType:media}))
 await page.route('**/reports/v1/native/pivot-structure-guard/1/api/save',async r=>{
  saveCount++;payload=r.request().postDataJSON()
  try{saved=Buffer.from(python({mode:'patch',bytes:bytes.toString('base64'),operations:payload.operations}),'base64');writeFileSync(join(temporary,'revision-2.xlsx'),saved);await r.fulfill({json:{documentId:'pivot-structure-guard',revision:2,parentRevision:1,revisionRegistered:true,artifacts:{xlsx:{downloadUrl,size:saved.length,sha256:sha(saved)}},editor:{openUrl:'/reports/v1/native/pivot-structure-guard/2'},validation:{issues:[]}}})}
  catch(error){routeError=String(error);await r.fulfill({status:500,json:{detail:routeError}})}
 })
 await page.route('**/pivot-structure-guard.xlsx',r=>r.fulfill({body:saved,contentType:media,headers:{'Content-Disposition':'attachment; filename=pivot-structure-guard.xlsx'}}))
 await page.route(/\/reports\/v1\/native\/pivot-structure-guard\/[12]$/,async r=>r.fulfill({response:await r.fetch({url:`${base}/reports/v1/editor/assets/native.html`})}))
 await page.addInitScript(()=>history.replaceState(null,'','/reports/v1/native/pivot-structure-guard/1'))
 const ready=async()=>{await page.waitForFunction(()=>document.querySelector('#report-editor')?.getAttribute('aria-busy')==='false',null,{timeout:60000});await page.locator('[data-ribbon-tab="Home"]').waitFor()}
 const goto=async ref=>{await page.locator('[data-ribbon-tab="Home"]').click();await page.locator('[data-ribbon-command="goto-open"]').click();await page.locator('[data-goto-reference]').fill(ref);await page.locator('.workbook-ribbon-goto-dialog button[type="submit"]').click()}
 const history=async action=>{await page.locator('[data-ribbon-tab="File"]').click();const control=page.locator(`[data-ribbon-command="${action}"]`);if(await control.isEnabled())await control.click()}
 const historyState=async()=>{await page.locator('[data-ribbon-tab="File"]').click();return {undo:await page.locator('[data-ribbon-command="undo"]').isDisabled(),redo:await page.locator('[data-ribbon-command="redo"]').isDisabled()}}
 const state=async()=>({draft:await page.evaluate(()=>Object.fromEntries(Object.entries(localStorage))),label:await page.locator('.save-state-label').textContent(),history:await historyState()})
 let copyId=0
 const matrix=async ref=>{
  await goto(ref);const sentinel=`pivot-snapshot-${++copyId}`;await page.evaluate(value=>navigator.clipboard.writeText(value),sentinel);await page.keyboard.press('Control+c')
  for(let i=0;i<40;i++){const value=await page.evaluate(()=>navigator.clipboard.readText());if(value!==sentinel)return value.replace(/\r\n/g,'\n');await delay(50)}throw Error('原生复制未覆盖snapshot sentinel')
 }
 const tab=name=>page.locator('[data-u-comp="slide-tab-item"]').filter({hasText:name})
 const structural=async action=>{await page.locator('[data-ribbon-tab="Home"]').click();const control=page.locator(`[data-ribbon-command="${action}"]`);assert.equal(await control.isEnabled(),true,'必须真实提交结构命令，不能以disabled当拒绝');await control.click()}
 const guarded=['insert-row-here','delete-row-here','insert-col-here','delete-col-here']
 stage='open';await page.goto(`${base}/reports/v1/editor/assets/native.html`);await ready();writeFileSync(join(temporary,'source.xlsx'),bytes)
 const sourceSnapshot=await matrix('Source!A1:C5')
 await delay(500)
 const before=await state()
 for(const action of guarded){
  stage=`refuse-${action}`;await goto('Source!A2');await structural(action)
  await page.getByText('仍有透视表读取工作表 "Source" 的来源数据，已拒绝插入/删除行列。',{exact:true}).waitFor()
  assert.equal(await matrix('Source!A1:C5'),sourceSnapshot,`${action}不改变原生复制矩阵`)
  assert.deepEqual(await state(),before,`${action}不改变草稿、保存态和history可用性`);assert.equal(saveCount,0)
 }
 stage='refused-history';await history('undo');await history('redo');assert.equal(await matrix('Source!A1:C5'),sourceSnapshot);assert.deepEqual(await state(),before)
 // 非来源表确实可以修改；用原生复制数据作为可见结果，不通过私有runtime或后门。
 stage='allowed-unused';const unusedBefore=await matrix('Unused!A1:C6')
 await goto('Unused!A2');await structural('insert-row-here');const rowInserted=await matrix('Unused!A1:C6');assert.notEqual(rowInserted,unusedBefore)
 await history('undo');assert.equal(await matrix('Unused!A1:C6'),unusedBefore)
 await history('redo');assert.equal(await matrix('Unused!A1:C6'),rowInserted)
 await goto('Unused!B1');await structural('insert-col-here');const bothInserted=await matrix('Unused!A1:D6');assert.ok(bothInserted.includes('U-A'))
 await page.waitForFunction(()=>Object.keys(localStorage).filter(key=>key.startsWith('native-editor-draft:')).some(key=>{try{return JSON.parse(localStorage.getItem(key)).operations.some(op=>op.kind==='applyRowColumnOps')}catch{return false}}),null,{timeout:30000})
 stage='draft-reload';await page.reload();await ready();assert.equal(await matrix('Unused!A1:D6'),bothInserted);assert.equal(await matrix('Source!A1:C5'),sourceSnapshot)
 stage='public-save';await page.locator('[data-action="save"]').click();await page.waitForFunction(()=>document.querySelector('.save-state-label')?.textContent==='已保存修订 2',null,{timeout:60000}).catch(error=>{throw Error(`${error};route=${routeError}`)})
 assert.equal(saveCount,1);assert.equal(routeError,undefined)
 assert.equal(payload.operations.length,2);for(const op of payload.operations){assert.equal(op.kind,'applyRowColumnOps');assert.equal(op.sheetName,'Unused');assert.equal(op.ops.length,1)}
 const actual=JSON.parse(python({mode:'inspect',bytes:saved.toString('base64'),original:bytes.toString('base64')}))
 assert.deepEqual(actual.sheetNames,['Source','Pivot','Unused']);assert.deepEqual(actual.sourceValues,[['Category','Amount'],['A',10]])
 assert.deepEqual(actual.unusedValues,[['Head',null,'Count'],[null,null,null],['U-A',null,21],['U-B',null,32]])
 for(const key of ['pivotPartSetUnchanged','pivotBytesUnchanged','pivotSheetBytesUnchanged','stylesUnchanged','partSetUnchanged','allOtherPartBytesUnchanged'])assert.equal(actual[key],true,key)
 assert.equal(actual.pivotCount,1);assert.equal(actual.cacheSource,'Source');assert.deepEqual(actual.changedParts,['xl/worksheets/sheet3.xml'])
 const downloadLink=page.getByRole('link',{name:/下载.*(?:XLSX|Excel|工作簿)/}).first()
 const [download]=await Promise.all([page.waitForEvent('download'),downloadLink.click()]);let downloadedPath;try{downloadedPath=await download.path()}catch(error){throw Error(`下载失败: ${await download.failure()};url=${download.url()};${error}`)}const downloaded=readFileSync(downloadedPath);assert.equal(sha(downloaded),sha(saved));writeFileSync(join(temporary,'downloaded-revision-2.xlsx'),downloaded)
 await page.route('**/reports/v1/native/pivot-structure-guard/2/api/context',r=>r.fulfill({json:{context:{...context,revision:2,parentRevision:1,sourceFile:{...context.sourceFile,size:saved.length,sha256:sha(saved)}},csrfToken:'csrf',capabilities:{xlsx_editor:true},editingEnabled:true}}))
 await page.route('**/reports/v1/native/pivot-structure-guard/2/api/file',r=>r.fulfill({body:saved,contentType:media}))
 stage='revision2-reopen';await page.addInitScript(()=>history.replaceState(null,'','/reports/v1/native/pivot-structure-guard/2'));await page.goto(`${base}/reports/v1/native/pivot-structure-guard/2`);await ready();await tab('Unused').waitFor();assert.equal(await matrix('Unused!A1:D6'),bothInserted);assert.equal(await matrix('Source!A1:C5'),sourceSnapshot)
 await page.screenshot({path:join(temporary,'revision-2-reopened.png'),fullPage:true});writeFileSync(join(temporary,'revision-2-reopened.html'),await page.content())
 const scripts=await Promise.all(scriptProof);assert(scripts.some(path=>/workbook-main-/.test(path)));assert.deepEqual(errors,[])
 console.log(JSON.stringify({ok:true,temporary,browserVersion:browser.version(),sourceSha256:sha(bytes),downloadedSha256:sha(downloaded),sourceRowColumnAtomicRefusals:guarded,uiCopiedSourceMatrixUnchanged:true,historyAndDraftSaveStateUnchanged:true,unusedStructureUndoRedo:true,draftReload:true,revision2Reopen:true,saveCount,operations:payload.operations,pythonPivotCacheAndOtherParts:actual,js200AndHashMatch:scripts.length,assets:[...new Set(scripts.filter(path=>/workbook-(main|engine-|structure|pivot-references)/.test(path)))],errors}))
} catch(error){if(page){writeFileSync(join(temporary,'failure.html'),await page.content());await page.screenshot({path:join(temporary,'failure.png'),fullPage:true}).catch(()=>{});console.error(JSON.stringify({stage,temporary,routeError,status:await page.locator('.save-state-label').textContent().catch(()=>null)}))}throw error}finally{await browser?.close();server.kill();await new Promise(resolve=>downloadServer.close(resolve))}
