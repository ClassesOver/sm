import assert from 'node:assert/strict'
import {createServer} from 'node:http'
import {spawn,spawnSync} from 'node:child_process'
import {createHash} from 'node:crypto'
import {mkdir,readFile,writeFile} from 'node:fs/promises'
import {join} from 'node:path'
import {fileURLToPath} from 'node:url'
import {setTimeout as delay} from 'node:timers/promises'
import {chromium} from 'playwright'
const frontend=fileURLToPath(new URL('../',import.meta.url)),repo=fileURLToPath(new URL('../../../../',import.meta.url))
const port=Number(process.env.PIVOT_REFRESH_SMOKE_PORT??4295),base=`http://127.0.0.1:${port}`,documentId='pivot-refresh-built'
const checkpoint=process.env.PIVOT_REFRESH_SMOKE_DIRECTORY??`/tmp/xlsx-pivot-refresh-built-${Date.now()}`
const sourceFieldRename=process.argv.includes('--source-field-rename'),sourceFieldGuard=process.argv.includes('--source-field-guard'),tableRename=sourceFieldRename||sourceFieldGuard||process.argv.includes('--table-rename-source'),tableCase=tableRename||process.argv.includes('--table-case-source')
await mkdir(checkpoint,{recursive:true})
await writeFile(join(checkpoint,'build-manifest.json'),await readFile(join(frontend,'../static/.vite/manifest.json')))
const sha=bytes=>createHash('sha256').update(bytes).digest('hex'),media='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
function python(payload){const result=spawnSync(join(repo,'.venv/bin/python'),['-c',`
import base64,json,sys
from io import BytesIO
from openpyxl import Workbook,load_workbook
from openpyxl.pivot.table import TableDefinition,Location,RowColField,DataField
from openpyxl.pivot.cache import CacheDefinition,CacheSource,WorksheetSource,CacheField,SharedItems
from openpyxl.pivot.record import RecordList
from openpyxl.worksheet.table import Table
from smart_reporting.report_editor.native_office import patch_office
p=json.load(sys.stdin)
if p['mode']=='fixture':
 b=Workbook();s=b.active;s.title='Data'
 for row in [['Category','Amount'],['East',10],['East',20],['West',30],['West',40]]:s.append(row)
 if p['tableCase']:s.add_table(Table(displayName='Sales',ref='A1:B5'))
 if p['sourceFieldGuard']:
  for row,values in enumerate([['Category','Amount'],['Other',5],['Other',6]],1):
   for col,value in enumerate(values,5):s.cell(row,col,value)
  s.add_table(Table(displayName='Other',ref='E1:F3'))
 s['D1']='original';s['Z100']='extent';o=b.create_sheet('Pivot')
 for row in [['Category','Amount'],['East',30],['West',70],['Grand Total',100]]:o.append(row)
 table=TableDefinition(name='Report',cacheId=1,dataCaption='Values',location=Location(ref='A1:B4',firstHeaderRow=1,firstDataRow=1,firstDataCol=1),rowFields=[RowColField(x=0)],dataFields=[DataField(name='Sum Amount',fld=1,subtotal='sum')])
 table.cache=CacheDefinition(cacheSource=CacheSource(type='worksheet',worksheetSource=WorksheetSource(ref=None if p['tableCase'] else 'A1:B5',name='sAlEs' if p['tableCase'] else None,sheet='Data')),cacheFields=[CacheField(name='Category',sharedItems=SharedItems()),CacheField(name='Amount',sharedItems=SharedItems())])
 table.cache.records=RecordList();o.add_pivot(table);f=BytesIO();b.save(f);print(base64.b64encode(f.getvalue()).decode())
elif p['mode']=='patch':print(base64.b64encode(patch_office('xlsx',base64.b64decode(p['bytes']),p['operations'])).decode())
else:
 b=load_workbook(BytesIO(base64.b64decode(p['bytes'])));s=b['Data'];o=b['Pivot']
 assert s['D1'].value=='manual draft' and s['B2'].value==90
 assert s['A3'].value=='South' and s['A4'].value==s['A5'].value=='East'
 assert o['B4'].value==180 and o['A5'].value is None and o['B5'].value is None
 assert o._pivots[0].location.ref=='A1:B4'
 if p['tableCase']:
  name='CurrentSales' if p['tableRename'] else 'Sales'
  assert o._pivots[0].cache.cacheSource.worksheetSource.name==name
  assert s.tables[name].ref=='A1:B5'
  field='Revenue' if p['sourceFieldRename'] else 'Amount'
  assert s.tables[name].headerRowCount==1 and s['A1'].value=='Category' and s['B1'].value==field
  assert o._pivots[0].cache.cacheFields[1].name==field
 if p['sourceFieldGuard']:
  assert s.tables['Other'].ref=='E1:F3' and s['E1'].value=='Category' and s['F1'].value=='Amount'
 print(json.dumps({'openpyxl':True,'actualResult':180,'manualDraft':True,'location':'A1:B4','clearedTail':True,**({'sourceTable':name} if p['tableCase'] else {})}))
`],{cwd:repo,env:{...process.env,PYTHONPATH:repo},input:JSON.stringify({...payload,tableCase,tableRename,sourceFieldGuard,sourceFieldRename}),encoding:'utf8',maxBuffer:30*1024*1024});assert.equal(result.status,0,result.stderr);return result.stdout.trim()}
const cases=[{revision:1}]
const revisions=new Map(),downloads=new Map(),savedSources=new Set(),results=[],assets=new Map(),assetChecks=[],errors=[]
for(const item of cases){const path=join(checkpoint,`source-${item.revision}.xlsx`);let bytes;try{bytes=await readFile(path)}catch(error){if(error.code!=='ENOENT')throw error;bytes=Buffer.from(python({mode:'fixture',...item}),'base64');await writeFile(path,bytes)}revisions.set(item.revision,bytes)}
let preview,browser,page,stage='setup',routeError,saveCount=0
const http=createServer(async(req,res)=>{try{
 const file=/^\/reports\/v1\/native\/pivot-refresh-built\/(\d+)\/api\/file$/.exec(req.url??''),context=/^\/reports\/v1\/native\/pivot-refresh-built\/(\d+)\/api\/context$/.exec(req.url??''),download=/^\/download\/(\d+)\.xlsx$/.exec(req.url??'')
 if(file||download){const bytes=(file?revisions:downloads).get(Number((file??download)[1]));assert(bytes);res.writeHead(200,{'Content-Type':media,'Content-Disposition':'attachment; filename=subtotal.xlsx'});res.end(bytes);return}
 if(context){const revision=Number(context[1]),bytes=revisions.get(revision);assert(bytes);res.writeHead(200,{'Content-Type':'application/json'});res.end(JSON.stringify({context:{documentId,format:'xlsx',revision,parentRevision:revision-1,scope:{database:'f',companyId:'f',userId:'f',threadId:'f'},sourceFile:{path:`subtotal-${revision}.xlsx`,size:bytes.length,sha256:sha(bytes),mediaType:media},origin:'upload'},csrfToken:'csrf',capabilities:{xlsx_editor:true},editingEnabled:true}));return}
 const path=/^\/reports\/v1\/native\/pivot-refresh-built\/\d+$/.test(req.url??'')?'/reports/v1/editor/assets/native.html':req.url,r=await fetch(base+path);res.writeHead(r.status,Object.fromEntries([...r.headers].filter(([key])=>!['content-encoding','content-length','transfer-encoding'].includes(key))));res.end(Buffer.from(await r.arrayBuffer()))
 }catch(error){res.writeHead(500);res.end(String(error))}})
await new Promise(resolve=>http.listen(0,'127.0.0.1',resolve));const app=`http://127.0.0.1:${http.address().port}`
try{
 preview=spawn('./node_modules/.bin/vite',['preview','--host','127.0.0.1','--port',String(port),'--strictPort'],{cwd:frontend,stdio:'pipe'})
 for(let i=0;;i++){assert.equal(preview.exitCode,null);try{if((await fetch(base+'/reports/v1/editor/assets/native.html')).ok)break}catch{}assert(i<120);await delay(250)}
 browser=await chromium.launch({headless:true});page=await browser.newPage({viewport:{width:1500,height:1100},acceptDownloads:true,permissions:['clipboard-read','clipboard-write']})
 page.on('pageerror',error=>{errors.push(error.message);const detail={stage,message:error.message,stack:error.stack};console.error(JSON.stringify({pageerror:detail}));void writeFile(join(checkpoint,`page-error-${errors.length}.json`),JSON.stringify(detail,null,2))});page.on('dialog',dialog=>dialog.type()==='beforeunload'||tableRename&&dialog.message().startsWith('转换后')?dialog.accept():dialog.dismiss())
 page.on('response',response=>{const path=new URL(response.url()).pathname;if(!path.startsWith('/reports/v1/editor/assets/')||!path.endsWith('.js'))return;assetChecks.push((async()=>{assert.equal(response.status(),200);const bytes=await response.body();assert.equal(sha(bytes),sha(await readFile(join(frontend,'../static',path.slice('/reports/v1/editor/assets/'.length)))));assets.set(path,sha(bytes));await writeFile(join(checkpoint,'assets.json'),JSON.stringify(Object.fromEntries(assets),null,2))})())})
 await page.route('**/reports/v1/native/pivot-refresh-built/*/api/save',async route=>{try{
  const revision=Number(new URL(route.request().url()).pathname.split('/')[5]),payload=route.request().postDataJSON();assert(!savedSources.has(revision),'禁止重复保存已成功的来源修订')
  const bytes=Buffer.from(python({mode:'patch',bytes:revisions.get(revision).toString('base64'),operations:payload.operations}),'base64')
  revisions.set(revision+1,bytes);downloads.set(revision+1,bytes);savedSources.add(revision);saveCount++
  await writeFile(join(checkpoint,`revision-${revision+1}.xlsx`),bytes)
  await writeFile(join(checkpoint,`saved-source-${revision}.json`),JSON.stringify({revision:revision+1,sourceRevision:revision,sha256:sha(bytes),operations:payload.operations},null,2))
  await route.fulfill({json:{documentId,revision:revision+1,parentRevision:revision,revisionRegistered:true,artifacts:{xlsx:{downloadUrl:`${app}/download/${revision+1}.xlsx`,size:bytes.length,sha256:sha(bytes)}},editor:{openUrl:`/reports/v1/native/${documentId}/${revision+1}`},validation:{ok:true,issues:[]}}})
 }catch(error){routeError=String(error);await route.fulfill({status:500,json:{detail:routeError}})}})
 const ready=()=>page.waitForFunction(()=>document.querySelector('#report-editor')?.getAttribute('aria-busy')==='false',null,{timeout:60000})
 const open=async revision=>{await page.goto(`${app}/reports/v1/native/${documentId}/${revision}`);await ready()}
 const command=async(tab,id)=>{await page.locator(`[data-ribbon-tab="${tab}"]`).click();await page.locator(`[data-ribbon-command="${id}"]`).click()}
 const goto=async reference=>{await command('Home','goto-open');await page.locator('[data-goto-reference]').fill(reference);await page.locator('.workbook-ribbon-goto-dialog button[type="submit"]').click();await page.locator('.workbook-ribbon-goto-dialog').waitFor({state:'hidden'})}
 const copy=async reference=>{
  await goto(reference);await delay(250)
  const sentinel='csv-copy-'+Date.now()+'-'+Math.random();await page.evaluate(text=>navigator.clipboard.writeText(text),sentinel)
  await page.keyboard.press('Control+c')
  for(let attempt=0;attempt<40;attempt++){const actual=await page.evaluate(()=>navigator.clipboard.readText());if(actual!==sentinel)return actual.trimEnd();await delay(100)}
  throw new Error('真实网格复制超时: '+reference)
 }
 const computed=async(reference,expected)=>{let actual;for(let attempt=0;attempt<20;attempt++){actual=Number(await copy(reference));if(actual===expected)return actual;await delay(150)}assert.equal(actual,expected)}
 const drafts=()=>page.evaluate(()=>Object.fromEntries(Object.keys(localStorage).filter(key=>key.startsWith('native-editor-draft:')).map(key=>[key,JSON.parse(localStorage.getItem(key))])))
 const edit=async(reference,value)=>{await goto(reference);await page.keyboard.type(value);await page.keyboard.press('Enter');await delay(700)}
 const refresh=async()=>{await command('Data','refresh-all');await page.waitForFunction(()=>!document.querySelector('#report-editor')?.inert&&(document.querySelector('.workbook-feedback')?.textContent??'').includes('已刷新'),null,{timeout:60000})}
 const checkTableSource=async(label,name='Sales',field='Amount')=>{
  await goto('Pivot!A1');await command('Data','pivot-edit')
  const dialog=page.locator('[role="dialog"][aria-label="数据透视表"]');await dialog.waitFor()
  const selection=dialog.getByLabel('来源表',{exact:true});assert.equal(await selection.inputValue(),'0');assert.equal(await selection.locator('option:checked').textContent(),name+' · Data')
  assert.equal(await dialog.getByLabel(field+' 聚合方式',{exact:true}).count(),1)
  await page.screenshot({path:join(checkpoint,`${label}-table-source.png`),fullPage:true})
  await dialog.locator('[data-action="cancel"]').click();await dialog.waitFor({state:'hidden'})
 }
 stage='initial';await open(1)
 if(tableCase)await checkTableSource('initial')
 if(tableRename){
  stage='rename-source';await goto('Data!A2');await page.locator('[data-ribbon-tab="Table Design"]').click()
  await page.getByLabel('表格名称',{exact:true}).fill('CurrentSales');await page.getByLabel('表格名称',{exact:true}).press('Tab')
  await page.waitForFunction(()=>(document.querySelector('.workbook-feedback')?.textContent??'').includes('表格名称已更新'))
  await checkTableSource('renamed','CurrentSales')
  stage='undo-source-rename';await command('File','undo');await checkTableSource('undo-rename','Sales')
  stage='redo-source-rename';await command('File','redo');await checkTableSource('redo-rename','CurrentSales')
  if(sourceFieldGuard){
   stage='reuse-source-old-name';await goto('Data!E2');await page.locator('[data-ribbon-tab="Table Design"]').click()
   await page.getByLabel('表格名称',{exact:true}).fill('Sales');await page.getByLabel('表格名称',{exact:true}).press('Tab');await edit('Data!F1','Revenue');assert.equal(await copy('Data!F1'),'Revenue')
   await command('File','undo');assert.equal(await copy('Data!F1'),'Amount');await command('File','undo')
   const beforeFields=await drafts()
   const rejectedField=async()=>{
    await page.waitForFunction(()=>(document.querySelector('.workbook-feedback')?.textContent??'').includes('透视缓存仍引用'),null,{timeout:15000})
    assert.equal(await copy('Data!A1:B1'),'Category\tAmount');assert.deepEqual(await drafts(),beforeFields)
   }
   stage='reject-source-field-input';await edit('Data!B1','Revenue');await rejectedField()
   stage='reject-source-field-paste';await goto('Data!B1');await page.evaluate(()=>navigator.clipboard.writeText('Revenue'));await page.keyboard.press('Control+v');await delay(700);await rejectedField()
   stage='reject-source-field-swap';await goto('Data!A1');await page.evaluate(()=>navigator.clipboard.writeText('Amount\tCategory'));await page.keyboard.press('Control+v');await delay(700);await rejectedField()
   stage='reject-source-field-clear';await goto('Data!B1');await page.keyboard.press('Delete');await delay(700);await rejectedField()
   stage='reject-source-column-shrink';await goto('Data!A2');await page.locator('[data-ribbon-tab="Table Design"]').click();await page.getByRole('button',{name:'调整表格范围',exact:true}).click()
   const resize=page.getByRole('dialog',{name:'调整表格范围',exact:true});await resize.getByLabel('新的表格范围',{exact:true}).fill('A1:A5');await resize.getByRole('button',{name:'确定',exact:true}).click()
   assert.match(await resize.getByRole('alert').textContent(),/透视缓存仍引用/);assert.deepEqual(await drafts(),beforeFields)
   await page.screenshot({path:join(checkpoint,'rejected-source-column-shrink.png'),fullPage:true});await resize.locator('[data-action="cancel"]').click()
   await command('File','undo');await checkTableSource('undo-after-field-rejection','Sales');await command('File','redo');await checkTableSource('redo-after-field-rejection','CurrentSales')
   stage='add-uncached-source-column';await goto('Data!A2');await page.locator('[data-ribbon-tab="Table Design"]').click();await page.getByRole('button',{name:'调整表格范围',exact:true}).click()
   await resize.getByLabel('新的表格范围',{exact:true}).fill('A1:C5');await resize.getByRole('button',{name:'确定',exact:true}).click();await resize.waitFor({state:'hidden'})
   assert.equal(await copy('Data!C1'),'Column3');await command('File','undo');assert.equal(await copy('Data!C1'),'');await command('File','redo');assert.equal(await copy('Data!C1'),'Column3');await command('File','undo');assert.equal(await copy('Data!C1'),'')
   assert.deepEqual(await drafts(),beforeFields)
  }
  stage='reject-source-header-removal';await goto('Data!A2');await page.locator('[data-ribbon-tab="Table Design"]').click()
  const beforeHeader=await drafts();await page.getByLabel('标题行',{exact:true}).uncheck()
  await page.waitForFunction(()=>!document.querySelector('#report-editor')?.inert&&(document.querySelector('.workbook-feedback')?.textContent??'').includes('不能关闭标题行'),null,{timeout:60000})
  assert.equal(await page.getByLabel('标题行',{exact:true}).isChecked(),true);assert.deepEqual(await drafts(),beforeHeader)
  await page.screenshot({path:join(checkpoint,'rejected-source-header.png'),fullPage:true})
  assert.equal(await copy('Data!A1:B1'),'Category\tAmount')
  // 被拒绝的操作没有占用撤销记录，上一条表名修改仍可直接撤销/重做。
  await command('File','undo');await checkTableSource('undo-after-header-rejection','Sales')
  await command('File','redo');await checkTableSource('redo-after-header-rejection','CurrentSales')
  stage='reject-source-conversion';await goto('Data!A2');await page.locator('[data-ribbon-tab="Table Design"]').click()
  const before=await drafts();await page.getByRole('button',{name:'转换为区域',exact:true}).click()
  await page.waitForFunction(()=>!document.querySelector('#report-editor')?.inert&&(document.querySelector('.workbook-feedback')?.textContent??'').includes('仍被透视表'),null,{timeout:60000})
  assert.equal(await page.getByLabel('表格名称',{exact:true}).inputValue(),'CurrentSales');assert.deepEqual(await drafts(),before)
 }
 if(sourceFieldRename){
  // 标准导入首次刷新后取得完整自有状态，才开放固定形状字段迁移。
  stage='adopt-source-state';await refresh()
  stage='rename-source-field';await edit('Data!B1','Revenue');assert.equal(await copy('Data!B1'),'Revenue');assert.equal(await copy('Pivot!B4'),'100');await checkTableSource('renamed-field','CurrentSales','Revenue')
  stage='undo-source-field';await command('File','undo');assert.equal(await copy('Data!B1'),'Amount');await checkTableSource('undo-field','CurrentSales')
  stage='redo-source-field';await command('File','redo');assert.equal(await copy('Data!B1'),'Revenue');await checkTableSource('redo-field','CurrentSales','Revenue')
  stage='consecutive-source-field';await edit('Data!B1','FinalRevenue');assert.equal(await copy('Data!B1'),'FinalRevenue');await checkTableSource('consecutive-field','CurrentSales','FinalRevenue')
  await command('File','undo');assert.equal(await copy('Data!B1'),'Revenue');await checkTableSource('undo-consecutive-field','CurrentSales','Revenue')
 }
 await edit('Data!D1','manual draft');await edit('Data!B2','90');await edit('Data!A3','South')
 assert.equal(await copy('Pivot!B4'),'100')
 stage='growth';await refresh();assert.equal(await copy('Pivot!B5'),'180');assert.match(await copy('Pivot!A1:B5'),/South/)
 stage='undo-growth';await command('File','undo');assert.equal(await copy('Pivot!B4'),'100');assert.equal(await copy('Pivot!B5'),'');assert.equal(await copy('Data!B2'),'90');assert.equal(await copy('Data!D1'),'manual draft')
 stage='redo-growth';await command('File','redo');assert.equal(await copy('Pivot!B5'),'180')
 stage='shrink';await edit('Data!A4','East');await edit('Data!A5','East');await refresh();assert.equal(await copy('Pivot!B4'),'180');assert.equal(await copy('Pivot!A5:B5'),'')
 stage='undo-shrink';await command('File','undo');assert.equal(await copy('Pivot!B5'),'180');assert.equal(await copy('Data!A5'),'East')
 stage='redo-shrink';await command('File','redo');assert.equal(await copy('Pivot!B4'),'180');assert.equal(await copy('Pivot!A5:B5'),'')
 const beforeRefresh=await drafts();stage='draft-reload';await page.reload();await ready();assert.equal(await copy('Pivot!B4'),'180');assert.equal(await copy('Data!D1'),'manual draft');assert.deepEqual(await drafts(),beforeRefresh)
 stage='save';await page.locator('[data-action="save"]').click();await page.waitForFunction(()=>(document.querySelector('.save-state-label')?.textContent??'').includes('已保存修订 2'),null,{timeout:60000});assert.equal(routeError,undefined);assert.equal(saveCount,1)
 const saved=JSON.parse(await readFile(join(checkpoint,'saved-source-1.json'),'utf8'));const [download]=await Promise.all([page.waitForEvent('download'),page.locator('[data-action="xlsx-download"]').click()]);const bytes=await readFile(await download.path());assert.equal(sha(bytes),saved.sha256);await writeFile(join(checkpoint,'downloaded-2.xlsx'),bytes)
 const independent=JSON.parse(python({mode:'inspect',bytes:bytes.toString('base64')}));stage='revision-2-reopen';await open(2);assert.equal(await copy('Pivot!B4'),'180');assert.equal(await copy('Pivot!A5:B5'),'');assert.equal(await copy('Data!D1'),'manual draft');assert.equal(saveCount,1)
 if(tableCase)await checkTableSource('reopened',tableRename?'CurrentSales':'Sales',sourceFieldRename?'Revenue':'Amount')
 await page.screenshot({path:join(checkpoint,'reopened.png'),fullPage:true});results.push({revision:2,sha256:sha(bytes),independent,operations:saved.operations,undoRedo:true,growth:true,shrink:true,draftReload:true,download:true,reopened:true})
 await Promise.all(assetChecks);assert.deepEqual(errors,[]);const summary={ok:true,checkpoint,tableCaseSource:tableCase,tableRenameSource:tableRename,sourceFieldGuard,sourceFieldRename,browserVersion:browser.version(),saveCount,resourceCount:assets.size,results,assets:Object.fromEntries(assets),errors};await writeFile(join(checkpoint,'summary.json'),JSON.stringify(summary,null,2));console.log(JSON.stringify({ok:true,checkpoint,cases:results.length,assets:assets.size}))
}catch(error){if(page){await writeFile(join(checkpoint,'failure.html'),await page.content()).catch(()=>{});await page.screenshot({path:join(checkpoint,'failure.png'),fullPage:true}).catch(()=>{})}console.error(JSON.stringify({stage,checkpoint}));throw error}
finally{await browser?.close();preview?.kill();await new Promise(resolve=>http.close(resolve))}
