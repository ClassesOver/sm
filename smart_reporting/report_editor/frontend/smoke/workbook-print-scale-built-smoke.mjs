import assert from 'node:assert/strict'
import {createServer} from 'node:http'
import {spawn,spawnSync} from 'node:child_process'
import {createHash} from 'node:crypto'
import {mkdtemp,readFile,writeFile} from 'node:fs/promises'
import {tmpdir} from 'node:os'
import {join} from 'node:path'
import {fileURLToPath} from 'node:url'
import {setTimeout as delay} from 'node:timers/promises'
import {chromium} from 'playwright'
const frontend=fileURLToPath(new URL('../',import.meta.url)),repo=fileURLToPath(new URL('../../../../',import.meta.url)),port=Number(process.env.PRINT_SCALE_SMOKE_PORT??4271),base=`http://127.0.0.1:${port}`
const temporary=await mkdtemp(join(tmpdir(),'print-scale-built-')),sha=b=>createHash('sha256').update(b).digest('hex'),media='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',documentId='print-scale-built'
const python=input=>{const r=spawnSync(join(repo,'.venv/bin/python'),['-c',String.raw`
import base64,json,re,sys
from io import BytesIO
from zipfile import ZipFile
from hashlib import sha256
from lxml import etree
from openpyxl import Workbook,load_workbook
p=json.load(sys.stdin)
if p['mode']=='fixture':
 b=Workbook();b.active.title='Scale'
 for s in [b.active,b.create_sheet('Other')]:
  for r in range(1,31):
   for c in range(1,5):s.cell(r,c,f'{r}:{c}')
  s['F1']='=1+2';s.row_dimensions[1].height=30;s.column_dimensions['A'].width=18
  s.print_area='A1:D30';s.page_setup.scale=85;s.page_setup.fitToWidth=2;s.page_setup.fitToHeight=3;s.sheet_properties.pageSetUpPr.fitToPage=True
  s.page_setup.orientation='landscape';s.page_setup.paperSize='9';s.page_setup.copies=2
  s.page_margins.left=0.31;s.page_margins.right=0.42;s.page_margins.top=0.53;s.page_margins.bottom=0.64;s.page_margins.header=0.17;s.page_margins.footer=0.18
 f=BytesIO();b.save(f);print(base64.b64encode(f.getvalue()).decode())
elif p['mode']=='patch':
 from smart_reporting.report_editor.native_office import patch_office
 print(base64.b64encode(patch_office('xlsx',base64.b64decode(p['bytes']),p['operations'])).decode())
else:
 data=base64.b64decode(p['bytes']);b=load_workbook(BytesIO(data));s=b['Scale']
 with ZipFile(BytesIO(data)) as z:
  xml=z.read('xl/worksheets/sheet1.xml').decode();root=etree.fromstring(xml.encode());ns={'m':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'};setup=root.find('m:pageSetup',ns);pr=root.find('m:sheetPr/m:pageSetUpPr',ns)
  masked=re.sub(r'\s(?:scale|fitToPage)="[^"]*"','',xml)
  print(json.dumps({'scale':s.page_setup.scale or 100,'rawScale':None if setup is None else setup.get('scale'),'fitToPage':bool(s.sheet_properties.pageSetUpPr.fitToPage),'rawFit':None if pr is None else pr.get('fitToPage'),'fit':[s.page_setup.fitToWidth,s.page_setup.fitToHeight],'orientation':s.page_setup.orientation,'copies':s.page_setup.copies,'margins':dict(s.page_margins),'a1':s['A1'].value,'formula':s['F1'].value,'maskedXml':masked,'parts':{n:sha256(z.read(n)).hexdigest() for n in z.namelist() if n!='xl/worksheets/sheet1.xml'}}))
`],{cwd:repo,env:{...process.env,PYTHONPATH:repo},input:JSON.stringify(input),encoding:'utf8',maxBuffer:30*1024*1024});assert.equal(r.status,0,r.stderr);return r.stdout.trim()}
const revisions=new Map(),payloads=[],downloads=new Map(),assets=new Map(),checks=[],errors=[],results=[]
const fixture=Buffer.from(python({mode:'fixture'}),'base64');for(const revision of [1,10,20])revisions.set(revision,fixture)
let server,browser,page,stage='setup',routeError
const http=createServer(async(req,res)=>{try{
 const file=/^\/reports\/v1\/native\/print-scale-built\/(\d+)\/api\/file$/.exec(req.url??''),context=/^\/reports\/v1\/native\/print-scale-built\/(\d+)\/api\/context$/.exec(req.url??''),download=/^\/download\/(\d+)\.xlsx$/.exec(req.url??'')
 if(file||download){const bytes=(file?revisions:downloads).get(Number((file??download)[1]));assert(bytes);res.writeHead(200,{'Content-Type':media,'Content-Disposition':'attachment; filename=print-scale.xlsx','Content-Length':bytes.length});res.end(bytes);return}
 if(context){const revision=Number(context[1]),bytes=revisions.get(revision);res.writeHead(200,{'Content-Type':'application/json'});res.end(JSON.stringify({context:{documentId,format:'xlsx',revision,parentRevision:revision-1,scope:{database:'f',companyId:'f',userId:'f',threadId:'f'},sourceFile:{path:`revision-${revision}.xlsx`,size:bytes.length,sha256:sha(bytes),mediaType:media},origin:'upload'},csrfToken:'csrf',capabilities:{xlsx_editor:true},editingEnabled:true}));return}
 const path=/^\/reports\/v1\/native\/print-scale-built\/\d+$/.test(req.url??'')?'/reports/v1/editor/assets/native.html':req.url,r=await fetch(base+path);res.writeHead(r.status,Object.fromEntries([...r.headers].filter(([k])=>!['content-encoding','content-length','transfer-encoding'].includes(k))));res.end(Buffer.from(await r.arrayBuffer()))
 }catch(e){res.writeHead(500);res.end(String(e))}})
await new Promise(resolve=>http.listen(0,'127.0.0.1',resolve));const app=`http://127.0.0.1:${http.address().port}`
try{
 server=spawn('./node_modules/.bin/vite',['preview','--host','127.0.0.1','--port',String(port),'--strictPort'],{cwd:frontend,stdio:'pipe'})
 for(let i=0;;i++){assert.equal(server.exitCode,null);try{if((await fetch(base+'/reports/v1/editor/assets/native.html')).ok)break}catch{}assert(i<120);await delay(250)}
 browser=await chromium.launch({headless:true});page=await browser.newPage({viewport:{width:1500,height:1100},acceptDownloads:true})
 page.on('pageerror',e=>errors.push(e.message));page.on('console',m=>{if(m.type()==='error')errors.push(m.text())});page.on('dialog',d=>d.type()==='beforeunload'?d.accept():d.dismiss())
 page.on('response',r=>{const path=new URL(r.url()).pathname;if(!path.startsWith('/reports/v1/editor/assets/')||!path.endsWith('.js'))return;checks.push((async()=>{assert.equal(r.status(),200);const body=await r.body();assert.equal(sha(body),sha(await readFile(join(frontend,'../static',path.slice('/reports/v1/editor/assets/'.length)))));assets.set(path,sha(body));await writeFile(join(temporary,'assets.json'),JSON.stringify(Object.fromEntries(assets),null,2))})())})
 await page.route('**/reports/v1/native/print-scale-built/*/api/save',async route=>{try{const revision=Number(new URL(route.request().url()).pathname.split('/')[5]),payload=route.request().postDataJSON();payloads.push(payload);const bytes=Buffer.from(python({mode:'patch',bytes:revisions.get(revision).toString('base64'),operations:payload.operations}),'base64');revisions.set(revision+1,bytes);downloads.set(revision+1,bytes);await writeFile(join(temporary,`revision-${revision+1}.xlsx`),bytes);await route.fulfill({json:{documentId,revision:revision+1,parentRevision:revision,revisionRegistered:true,artifacts:{xlsx:{downloadUrl:`${app}/download/${revision+1}.xlsx`,size:bytes.length,sha256:sha(bytes)}},editor:{openUrl:`/reports/v1/native/${documentId}/${revision+1}`},validation:{ok:true,issues:[]}}})}catch(e){routeError=String(e);await route.fulfill({status:500,json:{detail:routeError}})}})
 await page.addInitScript(()=>{const append=Element.prototype.append;Element.prototype.append=function(...nodes){append.apply(this,nodes);for(const node of nodes)if(node instanceof HTMLIFrameElement&&node.contentWindow)node.contentWindow.print=()=>{window.__printScaleHtml=node.contentDocument.documentElement.outerHTML}}})
 const ready=async()=>{await page.waitForFunction(()=>document.querySelector('#report-editor')?.getAttribute('aria-busy')==='false',null,{timeout:60000});await page.locator('[data-ribbon-tab="Home"]').waitFor()}
 const open=async revision=>{await page.goto(`${app}/reports/v1/native/${documentId}/${revision}`);await ready()}
 const tab=name=>page.locator('[data-u-comp="slide-tab-item"]').filter({hasText:name})
 const command=async(group,id)=>{await page.locator(`[data-ribbon-tab="${group}"]`).click();await page.locator(`[data-ribbon-command="${id}"]`).click()}
 const dialog=()=>page.getByRole('dialog',{name:'打印缩放比例',exact:true}),input=()=>dialog().locator('[data-print-scale-input]')
 const openScale=async()=>{await command('Page Layout','print-scale-open');await dialog().waitFor()}
 const set=async scale=>{await openScale();await input().fill(String(scale));await dialog().locator('[data-print-scale-apply]').click();await dialog().waitFor({state:'hidden'})}
 const value=async()=>{await openScale();const v={scale:Number(await input().inputValue()),mode:await dialog().locator('[data-print-scale-mode]').textContent()};await dialog().locator('[data-print-scale-cancel]').click();return v}
 const storage=()=>page.evaluate(()=>Object.fromEntries(Object.keys(localStorage).filter(k=>k.startsWith('native-editor-draft:')).sort().map(k=>[k,localStorage.getItem(k)])))
 const print=async label=>{await page.evaluate(()=>{window.__printScaleHtml=undefined});await command('File','print');await page.waitForFunction(()=>!!window.__printScaleHtml);const html=await page.evaluate(()=>window.__printScaleHtml);await writeFile(join(temporary,`${label}-print.html`),html);return page.evaluate(html=>{const d=new DOMParser().parseFromString(html,'text/html');return{pages:d.querySelectorAll('.page').length,rowHeight:d.querySelector('.page tr')?.style.height,columnWidth:d.querySelector('.page col')?.style.width}},html)}
 for(const [revision,scale]of [[1,10],[10,100],[20,400]]){
  const name=`scale-${scale}`,resume=process.env.PRINT_SCALE_RESUME_DIRECTORY
  if(resume){let prior;try{prior=JSON.parse(await readFile(join(resume,`${name}-result.json`),'utf8'))}catch(e){if(e.code!=='ENOENT')throw e}if(prior){const bytes=await readFile(join(resume,`downloaded-revision-${prior.revision}.xlsx`));assert.equal(sha(bytes),prior.downloadSha256);await writeFile(join(temporary,`downloaded-revision-${prior.revision}.xlsx`),bytes);await writeFile(join(temporary,`${name}-result.json`),JSON.stringify(prior,null,2));results.push(prior);continue}}
  if(revision<Number(process.env.PRINT_SCALE_START_REVISION??1))continue
  stage=`source-${name}`;await open(revision);await tab('Scale').click();const before=JSON.parse(python({mode:'inspect',bytes:fixture.toString('base64')}));assert.deepEqual(await value(),{scale:85,mode:'当前按页数调整为合适大小；此比例暂未生效。'})
  const initial=await storage();await openScale();for(const invalid of ['9','401','12.5','']){await input().fill(invalid);await dialog().locator('[data-print-scale-apply]').click();assert.match(await dialog().getByRole('alert').textContent(),/10–400/)}await input().fill('123');await dialog().locator('[data-print-scale-cancel]').click();assert.deepEqual(await storage(),initial,'invalid和取消不写草稿')
  stage=`same-value-disables-fit-${name}`;await set(85);assert.deepEqual(await value(),{scale:85,mode:''});const same=await storage();await set(85);assert.deepEqual(await storage(),same,'fit关闭后的同值不写')
  // 通过公开sheet tab Enter键事件模拟modal打开期间外部激活变化，不注入运行时或工作簿状态。
  stage=`stale-${name}`;await openScale();await input().fill('200');await tab('Other').dispatchEvent('keydown',{key:'Enter',code:'Enter',bubbles:true});await page.waitForFunction(()=>[...document.querySelectorAll('[data-u-comp="slide-tab-item"]')].some(el=>el.textContent==='Other'&&el.getAttribute('aria-selected')==='true'));await dialog().locator('[data-print-scale-apply]').click();assert.match(await dialog().getByRole('alert').textContent(),/改变|重新|切换/);await dialog().locator('[data-print-scale-cancel]').click();await tab('Scale').click();assert.deepEqual(await value(),{scale:85,mode:''})
  stage=`rename-${name}`;await tab('Scale').dblclick();const edit=page.locator('[data-u-comp="slide-tab-item"] [contenteditable="true"]');await edit.fill('Renamed');await edit.press('Enter');await tab('Renamed').waitFor();assert.deepEqual(await value(),{scale:85,mode:''});await command('File','undo');await tab('Scale').waitFor();assert.deepEqual(await value(),{scale:85,mode:''})
  stage=`scale-${scale}`;await set(scale);assert.deepEqual(await value(),{scale,mode:''});const geometry=await print(name);assert.equal(geometry.rowHeight,`${30*scale/100}pt`,'实际File Print HTML按比例缩放，不套用源200上限')
  await page.reload();await ready();await tab('Scale').click();assert.deepEqual(await value(),{scale,mode:''});assert.deepEqual(await print(`${name}-draft`),geometry)
  stage=`save-${name}`;await page.locator('[data-action="save"]').click();await page.waitForFunction(n=>(document.querySelector('.save-state-label')?.textContent??'').includes(`已保存修订 ${n}`),revision+1,{timeout:60000});assert.equal(routeError,undefined);const operations=payloads.at(-1).operations;assert.deepEqual(operations.map(o=>o.kind),['applyPageSetups']);const [download]=await Promise.all([page.waitForEvent('download'),page.locator('[data-action="xlsx-download"]').click()]);const bytes=await readFile(await download.path());assert.equal(sha(bytes),sha(revisions.get(revision+1)));await writeFile(join(temporary,`downloaded-revision-${revision+1}.xlsx`),bytes)
  const after=JSON.parse(python({mode:'inspect',bytes:bytes.toString('base64')}));assert.equal(after.scale,scale);assert.equal(after.fitToPage,false);if(scale===100)assert.equal(after.rawScale,null);assert([null,'0','false'].includes(after.rawFit));for(const key of ['fit','orientation','copies','margins','a1','formula','maskedXml','parts'])assert.deepEqual(after[key],before[key],`只改比例/fit:${key}`)
  stage=`reopen-${name}`;await open(revision+1);await tab('Scale').click();assert.deepEqual(await value(),{scale,mode:''});assert.deepEqual(await print(`${name}-reopen`),geometry);const screenshot=join(temporary,`${name}-reopened.png`);await page.screenshot({path:screenshot,fullPage:true});const result={name,revision:revision+1,scale,operations,geometry,downloadSha256:sha(bytes),screenshot,rawScale:after.rawScale,rawFit:after.rawFit};results.push(result);await writeFile(join(temporary,`${name}-result.json`),JSON.stringify(result,null,2));console.log(JSON.stringify(result))
 }
 await Promise.all(checks);assert.deepEqual(errors,[]);console.log(JSON.stringify({ok:true,temporary,browserVersion:browser.version(),results,saveCount:payloads.length,assets:Object.fromEntries(assets),errors}))
}catch(e){if(page){await writeFile(join(temporary,'failure.html'),await page.content()).catch(()=>{});await page.screenshot({path:join(temporary,'failure.png'),fullPage:true}).catch(()=>{})}console.error(JSON.stringify({stage,temporary}));throw e}finally{await browser?.close();server?.kill();await new Promise(resolve=>http.close(resolve))}
