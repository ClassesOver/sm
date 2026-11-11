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
const port=Number(process.env.ADVANCED_FILTER_SMOKE_PORT??4284),base=`http://127.0.0.1:${port}`,documentId='advanced-filter-built'
const checkpoint=process.env.ADVANCED_FILTER_SMOKE_DIRECTORY??`/tmp/xlsx-advanced-filter-built-${Date.now()}`
await mkdir(checkpoint,{recursive:true})
const manifest=await readFile(join(frontend,'../static/.vite/manifest.json'));try{assert.deepEqual(await readFile(join(checkpoint,'build-manifest.json')),manifest,'checkpoint构建身份已变化，必须新建目录')}catch(error){if(error.code!=='ENOENT')throw error;await writeFile(join(checkpoint,'build-manifest.json'),manifest)}
const sha=bytes=>createHash('sha256').update(bytes).digest('hex'),media='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
function python(payload){const result=spawnSync(join(repo,'.venv/bin/python'),['-c',`
import base64,json,sys
from io import BytesIO
from zipfile import ZipFile
from lxml import etree
from openpyxl import Workbook,load_workbook
from openpyxl.worksheet.filters import FilterColumn,Filters
from smart_reporting.report_editor.native_office import patch_office
p=json.load(sys.stdin)
if p['mode']=='fixture':
 b=Workbook();s=b.active;s.title='Data'
 rows=[['Group','Value','Other'],['A',5,'keep'],['A',10,'keep'],['B',20,'drop'],['A',40,'keep']]
 for r,row in enumerate(rows,5):
  for c,v in enumerate(row,3):s.cell(r,c,v)
 s['C12']='Tail';s['D12']=99;s['E12']='outside'
 if p['existing']:
  s.auto_filter.ref='C5:E9';s.auto_filter.filterColumn=[FilterColumn(colId=2,filters=Filters(filter=['keep']))];s.row_dimensions[8].hidden=True
 if p['manual']:s.row_dimensions[7].hidden=True
 f=BytesIO();b.save(f);print(base64.b64encode(f.getvalue()).decode())
elif p['mode']=='patch':print(base64.b64encode(patch_office('xlsx',base64.b64decode(p['bytes']),p['operations'])).decode())
else:
 data=base64.b64decode(p['bytes']);source=base64.b64decode(p['source'])
 with ZipFile(BytesIO(data)) as z:
  assert z.testzip() is None
  for n in z.namelist():
   if n.endswith(('.xml','.rels')):etree.fromstring(z.read(n))
  root=etree.fromstring(z.read('xl/worksheets/sheet1.xml'));ns={'m':root.nsmap[None]};af=root.find('m:autoFilter',ns);assert af.get('ref')=='C5:E9'
  cf=af.find('m:filterColumn[@colId="'+str(p['column'])+'"]/m:customFilters',ns)
  assert (cf.get('and')=='1')==p['and']
  assert [dict(x.attrib) for x in cf]==p['filters']
  if p['existing']:assert af.find('m:filterColumn[@colId="2"]/m:filters/m:filter',ns).get('val')=='keep'
 s=load_workbook(BytesIO(data))['Data'];original=load_workbook(BytesIO(source))['Data']
 assert [[c.value for c in row] for row in s]==[[c.value for c in row] for row in original]
 hidden=sorted(r for r,d in s.row_dimensions.items() if d.hidden);assert hidden==p['hidden'],(hidden,p['hidden'])
 assert not s.row_dimensions[5].hidden and s['C12'].value=='Tail'
 print(json.dumps({'zipXmlOpenpyxl':True,'ref':s.auto_filter.ref,'hidden':hidden,'dataUnchanged':True,'filters':p['filters']}))
`],{cwd:repo,env:{...process.env,PYTHONPATH:repo},input:JSON.stringify(payload),encoding:'utf8',maxBuffer:30*1024*1024});assert.equal(result.status,0,result.stderr);return result.stdout.trim()}
const cases=[
 {name:'and',revision:1,existing:true,manual:false,column:1,first:['greaterThanOrEqual','10'],second:['lessThan','30'],and:true,hidden:[6,8,9],filters:[{operator:'greaterThanOrEqual',val:'10'},{operator:'lessThan',val:'30'}]},
 {name:'or-create',revision:10,existing:false,manual:false,column:1,first:['lessThan','10'],second:['greaterThan','30'],and:false,hidden:[7,8],filters:[{operator:'lessThan',val:'10'},{operator:'greaterThan',val:'30'}]},
 {name:'text-equal-manual',revision:20,existing:true,manual:true,column:0,first:['equal','A'],and:false,hidden:[7,8],filters:[{val:'A'}]},
].filter(item=>!process.env.ADVANCED_FILTER_SMOKE_CASE||item.name===process.env.ADVANCED_FILTER_SMOKE_CASE)
const revisions=new Map(),downloads=new Map(),savedSources=new Set(),results=[],assets=new Map(),assetChecks=[],errors=[]
for(const item of cases){const path=join(checkpoint,`source-${item.revision}.xlsx`);let bytes;try{bytes=await readFile(path)}catch(error){if(error.code!=='ENOENT')throw error;bytes=Buffer.from(python({mode:'fixture',...item}),'base64');await writeFile(path,bytes)}revisions.set(item.revision,bytes)}
let preview,browser,page,stage='setup',routeError,saveCount=0
const http=createServer(async(req,res)=>{try{
 const file=/^\/reports\/v1\/native\/advanced-filter-built\/(\d+)\/api\/file$/.exec(req.url??''),context=/^\/reports\/v1\/native\/advanced-filter-built\/(\d+)\/api\/context$/.exec(req.url??''),download=/^\/download\/(\d+)\.xlsx$/.exec(req.url??'')
 if(file||download){const bytes=(file?revisions:downloads).get(Number((file??download)[1]));assert(bytes);res.writeHead(200,{'Content-Type':media,'Content-Disposition':'attachment; filename=advanced-filter.xlsx'});res.end(bytes);return}
 if(context){const revision=Number(context[1]),bytes=revisions.get(revision);assert(bytes);res.writeHead(200,{'Content-Type':'application/json'});res.end(JSON.stringify({context:{documentId,format:'xlsx',revision,parentRevision:revision-1,scope:{database:'f',companyId:'f',userId:'f',threadId:'f'},sourceFile:{path:`advanced-filter-${revision}.xlsx`,size:bytes.length,sha256:sha(bytes),mediaType:media},origin:'upload'},csrfToken:'csrf',capabilities:{xlsx_editor:true},editingEnabled:true}));return}
 const path=/^\/reports\/v1\/native\/advanced-filter-built\/\d+$/.test(req.url??'')?'/reports/v1/editor/assets/native.html':req.url,r=await fetch(base+path);res.writeHead(r.status,Object.fromEntries([...r.headers].filter(([key])=>!['content-encoding','content-length','transfer-encoding'].includes(key))));res.end(Buffer.from(await r.arrayBuffer()))
 }catch(error){res.writeHead(500);res.end(String(error))}})
await new Promise(resolve=>http.listen(0,'127.0.0.1',resolve));const app=`http://127.0.0.1:${http.address().port}`
try{
 preview=spawn('./node_modules/.bin/vite',['preview','--host','127.0.0.1','--port',String(port),'--strictPort'],{cwd:frontend,stdio:'pipe'})
 for(let i=0;;i++){assert.equal(preview.exitCode,null);try{if((await fetch(base+'/reports/v1/editor/assets/native.html')).ok)break}catch{}assert(i<120);await delay(250)}
 browser=await chromium.launch({headless:true});page=await browser.newPage({viewport:{width:1500,height:1100},acceptDownloads:true,permissions:['clipboard-read','clipboard-write']})
 page.on('pageerror',error=>{errors.push(error.message);const detail={stage,message:error.message,stack:error.stack};console.error(JSON.stringify({pageerror:detail}));void writeFile(join(checkpoint,`page-error-${errors.length}.json`),JSON.stringify(detail,null,2))});page.on('dialog',dialog=>dialog.type()==='beforeunload'?dialog.accept():dialog.dismiss())
 page.on('response',response=>{const path=new URL(response.url()).pathname;if(!path.startsWith('/reports/v1/editor/assets/')||!path.endsWith('.js'))return;assetChecks.push((async()=>{assert.equal(response.status(),200);const bytes=await response.body();assert.equal(sha(bytes),sha(await readFile(join(frontend,'../static',path.slice('/reports/v1/editor/assets/'.length)))));assets.set(path,sha(bytes));await writeFile(join(checkpoint,'assets.json'),JSON.stringify(Object.fromEntries(assets),null,2))})())})
 await page.route('**/reports/v1/native/advanced-filter-built/*/api/save',async route=>{try{
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
 const copyActive=async expected=>{const marker=`advanced-${Date.now()}-${Math.random()}`;await page.evaluate(text=>navigator.clipboard.writeText(text),marker);await page.keyboard.press('Control+c');const until=Date.now()+10000;let copied;do{copied=(await page.evaluate(()=>navigator.clipboard.readText())).trimEnd();if(copied===expected)return copied;await delay(100)}while(Date.now()<until);assert.equal(copied,expected,'公开 Ctrl+C 未在 10 秒内返回预期可见单元格');return copied}
 const visibleRows=async item=>{await goto("'Data'!D5");await page.keyboard.press('ArrowDown');const expected=item.name==='and'?'10':'5';assert.equal(await copyActive(expected),expected);if(item.name!=='and'){await page.keyboard.press('Escape');await page.keyboard.press('ArrowDown');assert.equal(await copyActive('40'),'40')}}
 const drafts=()=>page.evaluate(()=>Object.fromEntries(Object.keys(localStorage).filter(key=>key.startsWith('native-editor-draft:')).map(key=>[key,JSON.parse(localStorage.getItem(key))])))
 for(const item of cases){stage=`${item.name}-setup`;let saved;try{saved=JSON.parse(await readFile(join(checkpoint,`saved-source-${item.revision}.json`),'utf8'))}catch(error){if(error.code!=='ENOENT')throw error}
  let bytes,operations
  const currentOp=async()=>Object.values(await drafts()).flatMap(draft=>draft.operations).find(op=>op.kind==='applySheetFilter')
  const modal=page.getByRole('dialog',{name:'高级筛选',exact:true})
  const openDialog=async()=>{await goto("'Data'!C5:E9");await command('Data','filter-advanced');await modal.waitFor({state:'visible'})}
  const assertDraft=async()=>{await page.waitForFunction(expected=>Object.keys(localStorage).some(key=>key.startsWith('native-editor-draft:')&&JSON.parse(localStorage.getItem(key)).operations.some(op=>op.kind==='applySheetFilter'&&JSON.stringify(op.hiddenRows)===JSON.stringify(expected))),item.hidden.map(row=>row-1));const op=await currentOp();assert.deepEqual(op.filter.range,{startRow:4,endRow:8,startColumn:2,endColumn:4});assert.deepEqual(op.hiddenRows,item.hidden.map(row=>row-1));assert.deepEqual(op.filter.columns.find(column=>column.colId===item.column).customs.filters,item.filters)}
  if(saved){bytes=await readFile(join(checkpoint,`revision-${saved.revision}.xlsx`));assert.equal(sha(bytes),saved.sha256);revisions.set(saved.revision,bytes);downloads.set(saved.revision,bytes);savedSources.add(item.revision);operations=saved.operations}
  else{
   try{await readFile(join(checkpoint,`revision-${item.revision+1}.xlsx`));throw Error('已有产物缺少回执，禁止重复保存')}catch(error){if(error.code!=='ENOENT')throw error}
   await open(item.revision);const before=await drafts();await openDialog();await modal.getByRole('button',{name:'取消',exact:true}).click();assert.deepEqual(await drafts(),before)
   await openDialog();await modal.getByLabel('高级筛选字段',{exact:true}).selectOption(String(item.column));await modal.getByLabel('第一条件运算符',{exact:true}).selectOption(item.first[0]);await modal.getByLabel('第一条件值',{exact:true}).fill(item.first[1])
   if(item.second){await modal.getByLabel('第二条件运算符',{exact:true}).selectOption(item.second[0]);await modal.getByLabel('第二条件值',{exact:true}).fill(item.second[1]);await modal.getByLabel('条件连接',{exact:true}).selectOption(item.and?'and':'or')}
   await page.screenshot({path:join(checkpoint,`${item.name}-dialog.png`),fullPage:true});await modal.getByRole('button',{name:'确定',exact:true}).click();await modal.waitFor({state:'hidden'});await assertDraft();await visibleRows(item)
   stage=`${item.name}-undo`;await command('File','undo');await page.waitForFunction(()=>Object.values(localStorage).filter(value=>value.startsWith('{')).every(value=>{try{const d=JSON.parse(value);return!d.operations?.some(op=>op.kind==='applySheetFilter')}catch{return true}}))
   stage=`${item.name}-redo`;await command('File','redo');await assertDraft()
   const beforeRefresh=await drafts();stage=`${item.name}-refresh`;await page.reload();await ready();await assertDraft();assert.deepEqual(await drafts(),beforeRefresh)
   stage=`${item.name}-save`;await page.locator('[data-action="save"]').click();await page.waitForFunction(revision=>(document.querySelector('.save-state-label')?.textContent??'').includes(`已保存修订 ${revision}`),item.revision+1,{timeout:60000});assert.equal(routeError,undefined)
   saved=JSON.parse(await readFile(join(checkpoint,`saved-source-${item.revision}.json`),'utf8'));operations=saved.operations
   const [download]=await Promise.all([page.waitForEvent('download'),page.locator('[data-action="xlsx-download"]').click()]);bytes=await readFile(await download.path());assert.equal(sha(bytes),saved.sha256);await writeFile(join(checkpoint,`downloaded-${item.revision+1}.xlsx`),bytes)
  }
  assert.equal(operations.filter(op=>op.kind==='applySheetFilter').length,1)
  const independent=JSON.parse(python({mode:'inspect',bytes:bytes.toString('base64'),source:revisions.get(item.revision).toString('base64'),...item}));stage=`${item.name}-new-revision`;await open(item.revision+1);const reopenedDraft=await page.evaluate(async()=>({url:location.pathname,context:(await(await fetch(`${location.pathname}/api/context`)).json()).context,status:document.querySelector('.save-state-label')?.textContent,drafts:Object.keys(localStorage).filter(key=>key.startsWith('native-editor-draft:')).map(key=>({key,value:JSON.parse(localStorage.getItem(key))}))}));await writeFile(join(checkpoint,`${item.name}-reopened-draft.json`),JSON.stringify(reopenedDraft,null,2));await visibleRows(item)
  await openDialog();await modal.getByRole('button',{name:'取消',exact:true}).click()
  assert.equal(reopenedDraft.status,'已保存');assert.equal(reopenedDraft.context.revision,item.revision+1);assert.equal(reopenedDraft.context.sourceFile.sha256,sha(bytes));assert.deepEqual(reopenedDraft.drafts.filter(entry=>entry.value.identity.revision===item.revision+1).flatMap(entry=>entry.value.operations),[])
  let reopenedCriteriaCopy,reopenedCriteriaDraft,reopenedUndoDraft,reopenedRedoDraft,reopenedFinalUndoDraft
  if(item.name==='and'){
   await openDialog();await modal.getByLabel('高级筛选字段',{exact:true}).selectOption('1');await modal.getByLabel('第一条件运算符',{exact:true}).selectOption('lessThan');await modal.getByLabel('第一条件值',{exact:true}).fill('10');await modal.getByLabel('第二条件值',{exact:true}).fill('');await modal.getByRole('button',{name:'确定',exact:true}).click();await modal.waitFor({state:'hidden'})
   await page.waitForFunction(()=>Object.values(localStorage).some(value=>{try{return JSON.parse(value).operations?.some(op=>op.kind==='applySheetFilter')}catch{return false}}));reopenedCriteriaDraft=await page.evaluate(()=>({status:document.querySelector('.save-state-label')?.textContent,drafts:Object.keys(localStorage).filter(key=>key.startsWith('native-editor-draft:')).map(key=>({key,value:JSON.parse(localStorage.getItem(key))}))}));await writeFile(join(checkpoint,'and-reopened-criteria-draft.json'),JSON.stringify(reopenedCriteriaDraft,null,2))
   await goto("'Data'!D5");await page.keyboard.press('ArrowDown');const copied=await copyActive('5');reopenedCriteriaCopy={value:copied,expected:'5',ok:copied==='5',formulaBar:await page.locator('[data-u-comp="formula-bar"]').innerText()}
   await command('File','undo');await page.waitForFunction(()=>Object.keys(localStorage).some(key=>key.startsWith('native-editor-draft:'))&&Object.keys(localStorage).filter(key=>key.startsWith('native-editor-draft:')).every(key=>JSON.parse(localStorage.getItem(key)).operations.length===0));reopenedUndoDraft=await page.evaluate(()=>({status:document.querySelector('.save-state-label')?.textContent,drafts:Object.keys(localStorage).filter(key=>key.startsWith('native-editor-draft:')).map(key=>({key,value:JSON.parse(localStorage.getItem(key))}))}));await writeFile(join(checkpoint,'and-reopened-undo-draft.json'),JSON.stringify(reopenedUndoDraft,null,2));assert.equal(reopenedUndoDraft.status,'已保存');await visibleRows(item)
   await command('File','redo');await page.waitForFunction(()=>Object.keys(localStorage).filter(key=>key.startsWith('native-editor-draft:')).some(key=>JSON.parse(localStorage.getItem(key)).operations.some(op=>op.kind==='applySheetFilter'&&JSON.stringify(op.hiddenRows)==='[6,7,8]')));reopenedRedoDraft=await page.evaluate(()=>({status:document.querySelector('.save-state-label')?.textContent,drafts:Object.keys(localStorage).filter(key=>key.startsWith('native-editor-draft:')).map(key=>({key,value:JSON.parse(localStorage.getItem(key))}))}));await writeFile(join(checkpoint,'and-reopened-redo-draft.json'),JSON.stringify(reopenedRedoDraft,null,2));assert.equal(reopenedRedoDraft.status,'有未保存修改');assert.deepEqual(reopenedRedoDraft.drafts,reopenedCriteriaDraft.drafts);await goto("'Data'!D5");await page.keyboard.press('ArrowDown');assert.equal(await copyActive('5'),'5')
   await command('File','undo');await page.waitForFunction(()=>document.querySelector('.save-state-label')?.textContent==='已保存'&&Object.keys(localStorage).some(key=>key.startsWith('native-editor-draft:'))&&Object.keys(localStorage).filter(key=>key.startsWith('native-editor-draft:')).every(key=>JSON.parse(localStorage.getItem(key)).operations.length===0));reopenedFinalUndoDraft=await page.evaluate(()=>({status:document.querySelector('.save-state-label')?.textContent,drafts:Object.keys(localStorage).filter(key=>key.startsWith('native-editor-draft:')).map(key=>({key,value:JSON.parse(localStorage.getItem(key))}))}));await writeFile(join(checkpoint,'and-reopened-final-undo-draft.json'),JSON.stringify(reopenedFinalUndoDraft,null,2));assert.equal(reopenedFinalUndoDraft.status,'已保存');assert.deepEqual(reopenedFinalUndoDraft.drafts,reopenedUndoDraft.drafts);await visibleRows(item)
  }
  const response=await page.request.get(`${app}/download/${item.revision+1}.xlsx`);assert.equal(response.status(),200);assert.equal(sha(await response.body()),sha(bytes))
  await page.screenshot({path:join(checkpoint,`${item.name}-reopened.png`),fullPage:true});results.push({...item,sha256:sha(bytes),operations,independent,reopenedDraft,reopenedCriteriaCopy,reopenedCriteriaDraft,reopenedUndoDraft,reopenedRedoDraft,reopenedFinalUndoDraft,download:true,newRevisionReopen:true,publicKeyboardVisibility:true,reopenedCriteriaChange:item.name==='and'});await writeFile(join(checkpoint,`${item.name}-result.json`),JSON.stringify(results.at(-1),null,2))
 }
 await Promise.all(assetChecks);assert.deepEqual(errors,[]);const ok=results.every(result=>result.reopenedCriteriaCopy?.ok!==false);const summary={ok,checkpoint,browserVersion:browser.version(),saveCount,resourceCount:assets.size,results,assets:Object.fromEntries(assets),errors};await writeFile(join(checkpoint,'summary.json'),JSON.stringify(summary,null,2));console.log(JSON.stringify({ok,checkpoint,cases:results.length,assets:assets.size}))
}catch(error){if(page){await writeFile(join(checkpoint,'failure.html'),await page.content()).catch(()=>{});await page.screenshot({path:join(checkpoint,'failure.png'),fullPage:true}).catch(()=>{})}console.error(JSON.stringify({stage,checkpoint}));throw error}
finally{await browser?.close();preview?.kill();await new Promise(resolve=>http.close(resolve))}
