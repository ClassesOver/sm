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
const port=Number(process.env.QUERIES_SMOKE_PORT??4294),base=`http://127.0.0.1:${port}`,documentId='queries-built'
const checkpoint=process.env.QUERIES_SMOKE_DIRECTORY??`/tmp/xlsx-queries-built-${Date.now()}`
await mkdir(checkpoint,{recursive:true})
await writeFile(join(checkpoint,'build-manifest.json'),await readFile(join(frontend,'../static/.vite/manifest.json')))
const sha=bytes=>createHash('sha256').update(bytes).digest('hex'),media='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
function fixture(revision){const result=spawnSync(join(repo,'.venv/bin/python'),['-c',`
import base64,sys
from io import BytesIO
from zipfile import ZipFile,ZIP_DEFLATED
from openpyxl import Workbook
from openpyxl.worksheet.table import Table
b=Workbook();s=b.active;s.title='Data';s['A1']='original';s['Z100']='extent'
r=b.create_sheet('Rates 数据')
for row in [['Name','Value'],['A',10],['B',20],['C',30],['D',40]]:r.append(row)
r.add_table(Table(displayName='LoadedRates',ref='A1:B5'))
f=BytesIO();b.save(f)
with ZipFile(BytesIO(f.getvalue())) as z:parts={n:z.read(n) for n in z.namelist()}
ns='http://schemas.openxmlformats.org/spreadsheetml/2006/main';rel='http://schemas.openxmlformats.org/package/2006/relationships';office='http://schemas.openxmlformats.org/officeDocument/2006/relationships'
rev=int(sys.argv[1])
if rev!=2:
 parts['xl/connections.xml']=('<connections xmlns="'+ns+'"><connection id="1" name="Web Rates"><webPr url="https://user:password@external.invalid/rates?token=web-secret#private"/></connection><connection id="2" name="SQL Source"><dbPr connection="Provider=SQL;Password=db-secret;User ID=admin" command="SELECT secret FROM private"/></connection><connection id="3" name="Query - Rates"><dbPr connection="Provider=Microsoft.Mashup.OleDb.1;Location=Rates;Password=pq-secret"/></connection><connection id="4" name="Text File"><textPr sourceFile="C:/private/values.csv"/></connection></connections>').encode()
 parts['xl/tables/_rels/table1.xml.rels']=('<Relationships xmlns="'+rel+'"><Relationship Id="q" Type="'+office+'/queryTable" Target="../queryTables/queryTable1.xml"/></Relationships>').encode()
 parts['xl/queryTables/queryTable1.xml']=('<queryTable xmlns="'+ns+'" name="LoadedRates" connectionId="1"/>').encode()
 if rev==3:parts['xl/connections.xml']=b'<connections><connection id="1"></connections>'
out=BytesIO()
with ZipFile(out,'w',ZIP_DEFLATED) as z:
 for n,v in parts.items():z.writestr(n,v)
print(base64.b64encode(out.getvalue()).decode())
`,String(revision)],{cwd:repo,encoding:'utf8',timeout:30000,maxBuffer:30*1024*1024});assert.equal(result.status,0,result.stderr);assert.equal(result.error,undefined);return Buffer.from(result.stdout.trim(),'base64')}
const cases=[1,2,3].map(revision=>({revision}))
const revisions=new Map(),downloads=new Map(),savedSources=new Set(),results=[],assets=new Map(),assetChecks=[],errors=[]
for(const item of cases){const path=join(checkpoint,`source-${item.revision}.xlsx`);let bytes;try{bytes=await readFile(path)}catch(error){if(error.code!=='ENOENT')throw error;bytes=fixture(item.revision);await writeFile(path,bytes)}revisions.set(item.revision,bytes)}
let preview,browser,page,stage='setup',routeError,saveCount=0
const http=createServer(async(req,res)=>{try{
 const file=/^\/reports\/v1\/native\/queries-built\/(\d+)\/api\/file$/.exec(req.url??''),context=/^\/reports\/v1\/native\/queries-built\/(\d+)\/api\/context$/.exec(req.url??''),download=/^\/download\/(\d+)\.xlsx$/.exec(req.url??'')
 if(file||download){const bytes=(file?revisions:downloads).get(Number((file??download)[1]));assert(bytes);res.writeHead(200,{'Content-Type':media,'Content-Disposition':'attachment; filename=subtotal.xlsx'});res.end(bytes);return}
 if(context){const revision=Number(context[1]),bytes=revisions.get(revision);assert(bytes);res.writeHead(200,{'Content-Type':'application/json'});res.end(JSON.stringify({context:{documentId,format:'xlsx',revision,parentRevision:revision-1,scope:{database:'f',companyId:'f',userId:'f',threadId:'f'},sourceFile:{path:`subtotal-${revision}.xlsx`,size:bytes.length,sha256:sha(bytes),mediaType:media},origin:'upload'},csrfToken:'csrf',capabilities:{xlsx_editor:true},editingEnabled:true}));return}
 const path=/^\/reports\/v1\/native\/queries-built\/\d+$/.test(req.url??'')?'/reports/v1/editor/assets/native.html':req.url,r=await fetch(base+path);res.writeHead(r.status,Object.fromEntries([...r.headers].filter(([key])=>!['content-encoding','content-length','transfer-encoding'].includes(key))));res.end(Buffer.from(await r.arrayBuffer()))
 }catch(error){res.writeHead(500);res.end(String(error))}})
await new Promise(resolve=>http.listen(0,'127.0.0.1',resolve));const app=`http://127.0.0.1:${http.address().port}`
try{
 preview=spawn('./node_modules/.bin/vite',['preview','--host','127.0.0.1','--port',String(port),'--strictPort'],{cwd:frontend,stdio:'pipe'})
 for(let i=0;;i++){assert.equal(preview.exitCode,null);try{if((await fetch(base+'/reports/v1/editor/assets/native.html')).ok)break}catch{}assert(i<120);await delay(250)}
 browser=await chromium.launch({headless:true});page=await browser.newPage({viewport:{width:1500,height:1100},acceptDownloads:true,permissions:['clipboard-read','clipboard-write']})
 page.on('pageerror',error=>{errors.push(error.message);const detail={stage,message:error.message,stack:error.stack};console.error(JSON.stringify({pageerror:detail}));void writeFile(join(checkpoint,`page-error-${errors.length}.json`),JSON.stringify(detail,null,2))});page.on('dialog',dialog=>dialog.type()==='beforeunload'?dialog.accept():dialog.dismiss())
 page.on('response',response=>{const path=new URL(response.url()).pathname;if(!path.startsWith('/reports/v1/editor/assets/')||!path.endsWith('.js'))return;assetChecks.push((async()=>{assert.equal(response.status(),200);const bytes=await response.body();assert.equal(sha(bytes),sha(await readFile(join(frontend,'../static',path.slice('/reports/v1/editor/assets/'.length)))));assets.set(path,sha(bytes));await writeFile(join(checkpoint,'assets.json'),JSON.stringify(Object.fromEntries(assets),null,2))})())})
 const external=[]
 await page.route('**/*',async route=>{const url=new URL(route.request().url());if(url.origin!==app){external.push(url.origin+url.pathname);await route.abort();return}if(url.pathname.endsWith('/api/save')){saveCount++;await route.fulfill({status:500,json:{detail:'只读面板不应保存'}});return}await route.continue()})
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
 const state=async()=>{await page.locator('[data-ribbon-tab="File"]').click();return {storage:await page.evaluate(()=>({...localStorage})),label:await page.locator('.save-state-label').textContent(),undo:await page.locator('[data-ribbon-command="undo"]').isDisabled(),redo:await page.locator('[data-ribbon-command="redo"]').isDisabled(),save:await page.locator('[data-action="save"]').isDisabled()}}
 const modal=()=>page.getByRole('dialog',{name:'查询与连接',exact:true})
 const queryOpen=async()=>{await command('Data','queries-open');await modal().waitFor();await modal().locator('[data-query-loading]').waitFor({state:'hidden'})}
 stage='loaded';await open(1);await goto('Data!A1');await page.keyboard.type('manual draft');await page.keyboard.press('Enter');await delay(1000);const baseline=await state();assert.equal(baseline.undo,false)
 await queryOpen();assert.equal(await modal().locator('[data-query-entry]').count(),4)
 const text=await modal().textContent(),titles=await modal().locator('[data-query-entry]').evaluateAll(nodes=>nodes.map(node=>node.title).join(' '));assert.match(text,/Web Rates/);assert.match(text,/Power Query/);assert.match(text,/LoadedRates/);assert.match(text,/4 行/);assert(text.includes('https://external.invalid/rates'));assert.match(text,/values.csv/);assert.doesNotMatch(text+titles,/password|web-secret|db-secret|pq-secret|User ID|SELECT|private|token=/i)
 assert.equal(await modal().locator('[data-query-entry="1"]').isDisabled(),true);await page.screenshot({path:join(checkpoint,'loaded-panel.png'),fullPage:true})
 await modal().locator('[data-query-close]').click();assert.deepEqual(await state(),baseline)
 await queryOpen();await modal().locator('[data-query-entry="0"]').click();await modal().waitFor({state:'hidden'});assert.equal(await page.locator('[data-u-comp="defined-name"] input').inputValue(),'A1:B5');assert.match(await page.locator('.workbook-feedback').textContent(),/Rates 数据/);assert.deepEqual(await state(),baseline)
 assert.equal((await copy("'Rates 数据'!A1:B5")).replaceAll(String.fromCharCode(13),''),[['Name','Value'],['A',10],['B',20],['C',30],['D',40]].map(row=>row.join(String.fromCharCode(9))).join(String.fromCharCode(10)))
 assert.equal(await copy('Data!A1'),'manual draft');await command('File','undo');assert.equal(await copy('Data!A1'),'original');await command('File','redo');assert.equal(await copy('Data!A1'),'manual draft');assert.deepEqual(await state(),baseline)
 results.push({case:'loaded',metadata:true,redacted:true,navigation:true,manualDraft:true,historyNeutral:true})
 stage='empty';await open(2);const emptyBefore=await state();await queryOpen();await modal().locator('[data-query-empty]').waitFor();assert.match(await modal().textContent(),/没有查询或数据连接/);assert.equal(await modal().locator('[data-query-entry]').count(),0);await page.screenshot({path:join(checkpoint,'empty-panel.png'),fullPage:true});await modal().locator('[data-query-close]').click();assert.deepEqual(await state(),emptyBefore);results.push({case:'empty',realSourceEmpty:true,neutral:true})
 stage='damaged';await open(3);const badBefore=await state();await queryOpen();await modal().getByRole('alert').waitFor();assert.match(await modal().getByRole('alert').textContent(),/无法读取查询与连接/);assert.equal(await modal().locator('[data-query-empty]').isVisible(),false);await page.screenshot({path:join(checkpoint,'damaged-panel.png'),fullPage:true});await modal().locator('[data-query-close]').click();assert.deepEqual(await state(),badBefore);results.push({case:'damaged',specificError:true,neutral:true})
 assert.equal(saveCount,0);assert.deepEqual(external,[])
 await Promise.all(assetChecks);assert.deepEqual(errors,[]);const summary={ok:true,checkpoint,browserVersion:browser.version(),saveCount,resourceCount:assets.size,results,externalRequests:external,assets:Object.fromEntries(assets),errors};await writeFile(join(checkpoint,'summary.json'),JSON.stringify(summary,null,2));console.log(JSON.stringify({ok:true,checkpoint,cases:results.length,assets:assets.size}))
}catch(error){if(page){await writeFile(join(checkpoint,'failure.html'),await page.content()).catch(()=>{});await page.screenshot({path:join(checkpoint,'failure.png'),fullPage:true}).catch(()=>{})}console.error(JSON.stringify({stage,checkpoint}));throw error}
finally{await browser?.close();preview?.kill();await new Promise(resolve=>http.close(resolve))}
