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
const port=Number(process.env.CSV_IMPORT_SMOKE_PORT??4293),base=`http://127.0.0.1:${port}`,documentId='csv-import-built'
const checkpoint=process.env.CSV_IMPORT_SMOKE_DIRECTORY??`/tmp/xlsx-csv-import-built-${Date.now()}`
await mkdir(checkpoint,{recursive:true})
await writeFile(join(checkpoint,'build-manifest.json'),await readFile(join(frontend,'../static/.vite/manifest.json')))
const sha=bytes=>createHash('sha256').update(bytes).digest('hex'),media='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
function python(payload){const result=spawnSync(join(repo,'.venv/bin/python'),['-c',`
import base64,json,sys
from io import BytesIO
from openpyxl import Workbook,load_workbook
from openpyxl.styles import Font,PatternFill
from smart_reporting.report_editor.native_office import patch_office
p=json.load(sys.stdin)
if p['mode']=='fixture':
 b=Workbook();s=b.active;s.title='Data';s['A1']='original';s['C5']='before';s['C5'].font=Font(bold=True);s['C5'].fill=PatternFill('solid',fgColor='FFFF00');s['Z100']='extent'
 f=BytesIO();b.save(f);print(base64.b64encode(f.getvalue()).decode())
elif p['mode']=='patch':print(base64.b64encode(patch_office('xlsx',base64.b64decode(p['bytes']),p['operations'])).decode())
else:
 b=load_workbook(BytesIO(base64.b64decode(p['bytes'])));s=b['Data']
 assert s['A1'].value=='manual draft'
 assert [[s.cell(r,c).value for c in range(3,7)] for r in range(5,7)]==[['中文',12.5,'007','=1+1'],['TRUE','1234567890123456','+86','@SUM(A1)']]
 assert s['F5'].data_type=='s' and s['F6'].data_type=='s'
 assert s['C5'].font.bold and s['C5'].fill.fgColor.rgb=='00FFFF00'
 assert s['J10'].value=='中' and s['K10'].value==1
 print(json.dumps({'openpyxl':True,'literalFormula':True,'manualDraft':True,'format':True,'gb18030':True}))
`],{cwd:repo,env:{...process.env,PYTHONPATH:repo},input:JSON.stringify(payload),encoding:'utf8',maxBuffer:30*1024*1024});assert.equal(result.status,0,result.stderr);return result.stdout.trim()}
const cases=[{revision:1}]
const revisions=new Map(),downloads=new Map(),savedSources=new Set(),results=[],assets=new Map(),assetChecks=[],errors=[]
for(const item of cases){const path=join(checkpoint,`source-${item.revision}.xlsx`);let bytes;try{bytes=await readFile(path)}catch(error){if(error.code!=='ENOENT')throw error;bytes=Buffer.from(python({mode:'fixture',...item}),'base64');await writeFile(path,bytes)}revisions.set(item.revision,bytes)}
let preview,browser,page,stage='setup',routeError,saveCount=0
const http=createServer(async(req,res)=>{try{
 const file=/^\/reports\/v1\/native\/csv-import-built\/(\d+)\/api\/file$/.exec(req.url??''),context=/^\/reports\/v1\/native\/csv-import-built\/(\d+)\/api\/context$/.exec(req.url??''),download=/^\/download\/(\d+)\.xlsx$/.exec(req.url??'')
 if(file||download){const bytes=(file?revisions:downloads).get(Number((file??download)[1]));assert(bytes);res.writeHead(200,{'Content-Type':media,'Content-Disposition':'attachment; filename=subtotal.xlsx'});res.end(bytes);return}
 if(context){const revision=Number(context[1]),bytes=revisions.get(revision);assert(bytes);res.writeHead(200,{'Content-Type':'application/json'});res.end(JSON.stringify({context:{documentId,format:'xlsx',revision,parentRevision:revision-1,scope:{database:'f',companyId:'f',userId:'f',threadId:'f'},sourceFile:{path:`subtotal-${revision}.xlsx`,size:bytes.length,sha256:sha(bytes),mediaType:media},origin:'upload'},csrfToken:'csrf',capabilities:{xlsx_editor:true},editingEnabled:true}));return}
 const path=/^\/reports\/v1\/native\/csv-import-built\/\d+$/.test(req.url??'')?'/reports/v1/editor/assets/native.html':req.url,r=await fetch(base+path);res.writeHead(r.status,Object.fromEntries([...r.headers].filter(([key])=>!['content-encoding','content-length','transfer-encoding'].includes(key))));res.end(Buffer.from(await r.arrayBuffer()))
 }catch(error){res.writeHead(500);res.end(String(error))}})
await new Promise(resolve=>http.listen(0,'127.0.0.1',resolve));const app=`http://127.0.0.1:${http.address().port}`
try{
 preview=spawn('./node_modules/.bin/vite',['preview','--host','127.0.0.1','--port',String(port),'--strictPort'],{cwd:frontend,stdio:'pipe'})
 for(let i=0;;i++){assert.equal(preview.exitCode,null);try{if((await fetch(base+'/reports/v1/editor/assets/native.html')).ok)break}catch{}assert(i<120);await delay(250)}
 browser=await chromium.launch({headless:true});page=await browser.newPage({viewport:{width:1500,height:1100},acceptDownloads:true,permissions:['clipboard-read','clipboard-write']})
 page.on('pageerror',error=>{errors.push(error.message);const detail={stage,message:error.message,stack:error.stack};console.error(JSON.stringify({pageerror:detail}));void writeFile(join(checkpoint,`page-error-${errors.length}.json`),JSON.stringify(detail,null,2))});page.on('dialog',dialog=>dialog.type()==='beforeunload'?dialog.accept():dialog.dismiss())
 page.on('response',response=>{const path=new URL(response.url()).pathname;if(!path.startsWith('/reports/v1/editor/assets/')||!path.endsWith('.js'))return;assetChecks.push((async()=>{assert.equal(response.status(),200);const bytes=await response.body();assert.equal(sha(bytes),sha(await readFile(join(frontend,'../static',path.slice('/reports/v1/editor/assets/'.length)))));assets.set(path,sha(bytes));await writeFile(join(checkpoint,'assets.json'),JSON.stringify(Object.fromEntries(assets),null,2))})())})
 await page.route('**/reports/v1/native/csv-import-built/*/api/save',async route=>{try{
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
 const choose=async()=>{const [chooser]=await Promise.all([page.waitForEvent('filechooser'),command('Data','import-csv')]);return chooser}
 const upload=async(buffer,name='input.csv')=>{await(await choose()).setFiles({name,mimeType:'text/csv',buffer});await page.waitForFunction(()=>!document.querySelector('input[type=file]'));await delay(300)}
 stage='initial';await open(1)
 await goto('Data!A1');await page.keyboard.type('manual draft');await page.keyboard.press('Enter');await delay(800)
 await goto('Data!C5');const baseline=await drafts()
 stage='cancel';await(await choose()).setFiles([]);await page.waitForFunction(()=>!document.querySelector('input[type=file]'));assert.deepEqual(await drafts(),baseline)
 stage='stale';const stale=await choose();await goto('Data!D6');await stale.setFiles({name:'stale.csv',mimeType:'text/csv',buffer:Buffer.from('wrong,target')});await page.waitForFunction(()=>!document.querySelector('input[type=file]'));assert.deepEqual(await drafts(),baseline);assert.equal(await copy('Data!C5'),'before')
 stage='utf8';await goto('Data!C5');await upload(Buffer.from('中文;12.5;007;=1+1'+String.fromCharCode(13,10)+'TRUE;1234567890123456;+86;@SUM(A1)'))
 assert.equal((await copy('Data!C5:F6')).replaceAll(String.fromCharCode(13),''),[['中文','12.5','007','=1+1'],['TRUE','1234567890123456','+86','@SUM(A1)']].map(row=>row.join(String.fromCharCode(9))).join(String.fromCharCode(10)))
 stage='undo';await command('File','undo');assert.equal(await copy('Data!C5'),'before');assert.equal(await copy('Data!A1'),'manual draft')
 stage='redo';await command('File','redo');assert.equal(await copy('Data!F5'),'=1+1')
 stage='gb18030';await goto('Data!J10');await upload(Buffer.from([0xd6,0xd0,44,49]),'gb18030.csv');assert.equal(await copy('Data!J10:K10'),'中'+String.fromCharCode(9)+'1')
 const beforeRefresh=await drafts();stage='refresh';await page.reload();await ready();assert.equal(await copy('Data!F5'),'=1+1');assert.equal(await copy('Data!A1'),'manual draft');assert.deepEqual(await drafts(),beforeRefresh)
 stage='save';await page.locator('[data-action="save"]').click();await page.waitForFunction(()=>(document.querySelector('.save-state-label')?.textContent??'').includes('已保存修订 2'),null,{timeout:60000});assert.equal(routeError,undefined);assert.equal(saveCount,1)
 const saved=JSON.parse(await readFile(join(checkpoint,'saved-source-1.json'),'utf8'));const [download]=await Promise.all([page.waitForEvent('download'),page.locator('[data-action="xlsx-download"]').click()]);const bytes=await readFile(await download.path());assert.equal(sha(bytes),saved.sha256);await writeFile(join(checkpoint,'downloaded-2.xlsx'),bytes)
 const independent=JSON.parse(python({mode:'inspect',bytes:bytes.toString('base64')}));stage='revision-2-reopen';await open(2);assert.equal(await copy('Data!F5'),'=1+1');assert.equal(await copy('Data!J10:K10'),'中'+String.fromCharCode(9)+'1');assert.equal(await copy('Data!A1'),'manual draft');assert.equal(saveCount,1)
 await page.screenshot({path:join(checkpoint,'reopened.png'),fullPage:true});results.push({revision:2,sha256:sha(bytes),independent,operations:saved.operations,cancel:true,stale:true,undoRedo:true,refresh:true,download:true,reopened:true})
 await Promise.all(assetChecks);assert.deepEqual(errors,[]);const summary={ok:true,checkpoint,browserVersion:browser.version(),saveCount,resourceCount:assets.size,results,assets:Object.fromEntries(assets),errors};await writeFile(join(checkpoint,'summary.json'),JSON.stringify(summary,null,2));console.log(JSON.stringify({ok:true,checkpoint,cases:results.length,assets:assets.size}))
}catch(error){if(page){await writeFile(join(checkpoint,'failure.html'),await page.content()).catch(()=>{});await page.screenshot({path:join(checkpoint,'failure.png'),fullPage:true}).catch(()=>{})}console.error(JSON.stringify({stage,checkpoint}));throw error}
finally{await browser?.close();preview?.kill();await new Promise(resolve=>http.close(resolve))}
