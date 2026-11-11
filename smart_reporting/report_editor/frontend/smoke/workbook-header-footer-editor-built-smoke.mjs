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
const frontend=fileURLToPath(new URL('../',import.meta.url)),repo=fileURLToPath(new URL('../../../../',import.meta.url)),port=Number(process.env.HEADER_FOOTER_EDITOR_SMOKE_PORT??4296),base=`http://127.0.0.1:${port}`
const temporary=await mkdtemp(join(tmpdir(),'header-footer-editor-built-')),sha=b=>createHash('sha256').update(b).digest('hex'),media='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',documentId='header-footer-editor-built'
const python=input=>{const r=spawnSync(join(repo,'.venv/bin/python'),['-c',String.raw`
import base64,json,re,sys
from io import BytesIO
from zipfile import ZipFile
from hashlib import sha256
from lxml import etree
from openpyxl import Workbook,load_workbook
p=json.load(sys.stdin)
if p['mode']=='fixture':
 b=Workbook();s=b.active;s.title='Headers'
 for r in range(1,4):s.cell(r,1,f'Body {r}')
 s.oddHeader.left.text='Left &P';s.oddHeader.center.text='Before &N';s.oddHeader.right.text='&G &Q'
 s.oddFooter.right.text='Footer &A'
 s.firstHeader.center.text='First';s.evenFooter.center.text='Even'
 s.HeaderFooter.differentFirst=True;s.HeaderFooter.differentOddEven=True
 s.print_area='A1:B3'
 f=BytesIO();b.save(f);print(base64.b64encode(f.getvalue()).decode())
elif p['mode']=='patch':
 from smart_reporting.report_editor.native_office import patch_office
 print(base64.b64encode(patch_office('xlsx',base64.b64decode(p['bytes']),p['operations'])).decode())
else:
 data=base64.b64decode(p['bytes'])
 with ZipFile(BytesIO(data)) as z:
  xml=z.read('xl/worksheets/sheet1.xml').decode();root=etree.fromstring(xml.encode());ns={'m':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'};hf=root.find('m:headerFooter',ns)
  print(json.dumps({'header':None if hf is None else hf.findtext('m:oddHeader',namespaces=ns),'footer':None if hf is None else hf.findtext('m:oddFooter',namespaces=ns),'first':None if hf is None else hf.findtext('m:firstHeader',namespaces=ns),'even':None if hf is None else hf.findtext('m:evenFooter',namespaces=ns),'flags':{} if hf is None else dict(hf.attrib),'masked':re.sub(r'<oddHeader.*?</oddHeader>|<oddFooter.*?</oddFooter>','',xml),'parts':{n:sha256(z.read(n)).hexdigest() for n in z.namelist() if n!='xl/worksheets/sheet1.xml'}}))
`],{cwd:repo,env:{...process.env,PYTHONPATH:repo},input:JSON.stringify(input),encoding:'utf8',maxBuffer:30*1024*1024});assert.equal(r.status,0,r.stderr);return r.stdout.trim()}
const revisions=new Map(),payloads=[],downloads=new Map(),assets=new Map(),checks=[],errors=[],results=[]
const fixture=Buffer.from(python({mode:'fixture'}),'base64');for(const revision of [1,10,20])revisions.set(revision,fixture)
let server,browser,page,stage='setup',routeError
const http=createServer(async(req,res)=>{try{
 const file=/^\/reports\/v1\/native\/header-footer-editor-built\/(\d+)\/api\/file$/.exec(req.url??''),context=/^\/reports\/v1\/native\/header-footer-editor-built\/(\d+)\/api\/context$/.exec(req.url??''),download=/^\/download\/(\d+)\.xlsx$/.exec(req.url??'')
 if(file||download){const bytes=(file?revisions:downloads).get(Number((file??download)[1]));assert(bytes);res.writeHead(200,{'Content-Type':media,'Content-Disposition':'attachment; filename=print-scale.xlsx','Content-Length':bytes.length});res.end(bytes);return}
 if(context){const revision=Number(context[1]),bytes=revisions.get(revision);res.writeHead(200,{'Content-Type':'application/json'});res.end(JSON.stringify({context:{documentId,format:'xlsx',revision,parentRevision:revision-1,scope:{database:'f',companyId:'f',userId:'f',threadId:'f'},sourceFile:{path:`revision-${revision}.xlsx`,size:bytes.length,sha256:sha(bytes),mediaType:media},origin:'upload'},csrfToken:'csrf',capabilities:{xlsx_editor:true},editingEnabled:true}));return}
 const path=/^\/reports\/v1\/native\/header-footer-editor-built\/\d+$/.test(req.url??'')?'/reports/v1/editor/assets/native.html':req.url,r=await fetch(base+path,{signal:AbortSignal.timeout(15000)});res.writeHead(r.status,Object.fromEntries([...r.headers].filter(([k])=>!['content-encoding','content-length','transfer-encoding'].includes(k))));res.end(Buffer.from(await r.arrayBuffer()))
 }catch(e){res.writeHead(500);res.end(String(e))}})
await new Promise(resolve=>http.listen(0,'127.0.0.1',resolve));const app=`http://127.0.0.1:${http.address().port}`
try{
 server=spawn('./node_modules/.bin/vite',['preview','--host','127.0.0.1','--port',String(port),'--strictPort'],{cwd:frontend,stdio:'pipe'})
 for(let i=0;;i++){assert.equal(server.exitCode,null);try{if((await fetch(base+'/reports/v1/editor/assets/native.html')).ok)break}catch{}assert(i<120);await delay(250)}
 browser=await chromium.launch({headless:true});page=await browser.newPage({viewport:{width:1500,height:1100},acceptDownloads:true})
 page.on('pageerror',e=>errors.push(e.message));page.on('console',m=>{if(m.type()==='error')errors.push(m.text())});page.on('dialog',d=>d.type()==='beforeunload'?d.accept():d.dismiss())
 page.on('response',r=>{const path=new URL(r.url()).pathname;if(!path.startsWith('/reports/v1/editor/assets/')||!path.endsWith('.js'))return;checks.push((async()=>{assert.equal(r.status(),200);const body=await r.body();assert.equal(sha(body),sha(await readFile(join(frontend,'../static',path.slice('/reports/v1/editor/assets/'.length)))));assets.set(path,sha(body));await writeFile(join(temporary,'assets.json'),JSON.stringify(Object.fromEntries(assets),null,2))})())})
 await page.route('**/reports/v1/native/header-footer-editor-built/*/api/save',async route=>{try{const revision=Number(new URL(route.request().url()).pathname.split('/')[5]),payload=route.request().postDataJSON();payloads.push(payload);const bytes=Buffer.from(python({mode:'patch',bytes:revisions.get(revision).toString('base64'),operations:payload.operations}),'base64');revisions.set(revision+1,bytes);downloads.set(revision+1,bytes);await writeFile(join(temporary,`revision-${revision+1}.xlsx`),bytes);await route.fulfill({json:{documentId,revision:revision+1,parentRevision:revision,revisionRegistered:true,artifacts:{xlsx:{downloadUrl:`${app}/download/${revision+1}.xlsx`,size:bytes.length,sha256:sha(bytes)}},editor:{openUrl:`/reports/v1/native/${documentId}/${revision+1}`},validation:{ok:true,issues:[]}}})}catch(e){routeError=String(e);await route.fulfill({status:500,json:{detail:routeError}})}})
 await page.addInitScript(()=>{const append=Element.prototype.append;Element.prototype.append=function(...nodes){append.apply(this,nodes);for(const node of nodes)if(node instanceof HTMLIFrameElement&&node.contentWindow)node.contentWindow.print=()=>{window.__printScaleHtml=node.contentDocument.documentElement.outerHTML}}})
 const ready=async()=>{await page.waitForFunction(()=>document.querySelector('#report-editor')?.getAttribute('aria-busy')==='false',null,{timeout:60000});await page.locator('[data-ribbon-tab="Home"]').waitFor()}
 const open=async revision=>{await page.goto(`${app}/reports/v1/native/${documentId}/${revision}`);await ready()}
 const tab=name=>page.locator('[data-u-comp="slide-tab-item"]').filter({hasText:name})
 const command=async(group,id)=>{await page.locator(`[data-ribbon-tab="${group}"]`).click();await page.locator(`[data-ribbon-command="${id}"]`).click()}
 const dialog=()=>page.getByRole('dialog',{name:'页眉页脚',exact:true})
 const field=name=>dialog().locator('[data-header-footer-field="'+name+'"]')
 const openEditor=async()=>{await command('Insert','header-footer-open');await dialog().waitFor()}
 const storage=()=>page.evaluate(()=>Object.fromEntries(Object.keys(localStorage).filter(k=>k.startsWith('native-editor-draft:')).sort().map(k=>[k,localStorage.getItem(k)])))
 const before=JSON.parse(python({mode:'inspect',bytes:fixture.toString('base64')}))
 console.log(JSON.stringify({stage:'open',temporary}));await open(1);await openEditor()
 assert.equal(await field('header-center').inputValue(),'Before &N')
 if(process.env.HEADER_FOOTER_LAYOUT_ONLY==='1'){
  const geometry=await dialog().locator('fieldset').evaluateAll(groups=>groups.map(group=>[...group.querySelectorAll('textarea')].map(input=>{const r=input.getBoundingClientRect();return{x:r.x,y:r.y,width:r.width}})))
  for(const row of geometry){assert.equal(row.length,3);assert(Math.abs(row[0].y-row[1].y)<1);assert(Math.abs(row[1].y-row[2].y)<1);assert(row[0].x<row[1].x&&row[1].x<row[2].x);assert(row.every(cell=>cell.width>60))}
  await page.screenshot({path:join(temporary,'layout-verified.png'),fullPage:true});await Promise.all(checks);assert.deepEqual(errors,[]);await writeFile(join(temporary,'layout-result.json'),JSON.stringify({ok:true,temporary,geometry,assets:Object.fromEntries(assets),errors},null,2));console.log(JSON.stringify({ok:true,temporary,geometry,errors}));process.exitCode=0;await browser.close();browser=undefined;server.kill();server=undefined;await new Promise(resolve=>http.close(resolve));process.exit(0)
 }

 const initial=await storage();await field('header-center').fill('Discard');await dialog().locator('[data-header-footer-cancel]').click();assert.deepEqual(await storage(),initial)
 await openEditor();await field('header-center').fill('Edited &P/&N');await dialog().locator('[data-header-footer-apply]').click();await dialog().waitFor({state:'hidden'})
 await page.reload();await ready();await openEditor();assert.equal(await field('header-center').inputValue(),'Edited &P/&N');assert.equal(await field('header-right').inputValue(),'&G &Q');await dialog().locator('[data-header-footer-cancel]').click()
 console.log(JSON.stringify({stage:'draft-restored',temporary}))
 const save=async revision=>{await page.locator('[data-action=save]').click();await page.waitForFunction(n=>(document.querySelector('.save-state-label')?.textContent??'').includes('已保存修订 '+n),revision,{timeout:60000});assert.equal(routeError,undefined);const [download]=await Promise.all([page.waitForEvent('download'),page.locator('[data-action=xlsx-download]').click()]);const bytes=await readFile(await download.path());assert.equal(sha(bytes),sha(revisions.get(revision)));await writeFile(join(temporary,'downloaded-revision-'+revision+'.xlsx'),bytes);return JSON.parse(python({mode:'inspect',bytes:bytes.toString('base64')}))}
 const edited=await save(2);assert.match(edited.header,/Edited &P\/&N/);assert.equal(edited.footer,before.footer)
 for(const key of ['first','even','flags','masked','parts'])assert.deepEqual(edited[key],before[key],key)
 assert.deepEqual(payloads[0].operations.map(o=>o.kind),['applyPageSetups']);assert.equal(payloads[0].operations[0].setups[0].footer,undefined)
 await open(2);await openEditor();assert.equal(await field('header-center').inputValue(),'Edited &P/&N');for(const key of ['left','center','right'])await field('header-'+key).fill('');await dialog().locator('[data-header-footer-apply]').click();await dialog().waitFor({state:'hidden'})
 const cleared=await save(3);assert.equal(cleared.header,null);assert.equal(cleared.footer,before.footer);for(const key of ['first','even','flags','masked','parts'])assert.deepEqual(cleared[key],before[key],key)
 await open(3);await openEditor();assert.equal(await field('header-center').inputValue(),'');assert.equal(await field('footer-right').inputValue(),'Footer &A');await page.screenshot({path:join(temporary,'cleared-reopened.png'),fullPage:true})
 results.push({edited,cleared,operations:payloads.map(p=>p.operations)});await writeFile(join(temporary,'result.json'),JSON.stringify({ok:true,temporary,results,assets:Object.fromEntries(assets),errors},null,2))
 await Promise.all(checks);assert.deepEqual(errors,[]);console.log(JSON.stringify({ok:true,temporary,browserVersion:browser.version(),results,saveCount:payloads.length,assets:Object.fromEntries(assets),errors}))
}catch(e){if(page){await writeFile(join(temporary,'failure.html'),await page.content()).catch(()=>{});await page.screenshot({path:join(temporary,'failure.png'),fullPage:true}).catch(()=>{})}console.error(JSON.stringify({stage,temporary}));throw e}finally{await browser?.close();server?.kill();await new Promise(resolve=>http.close(resolve))}
