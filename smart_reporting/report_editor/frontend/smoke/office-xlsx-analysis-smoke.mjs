// 冻结生产资源、真实Univer计算和Python原生保存；鉴权/context/修订登记为显式fixture。
import assert from 'node:assert/strict'
import {createHash} from 'node:crypto'
import {mkdir,readFile,writeFile,access} from 'node:fs/promises'
import {createServer} from 'node:http'
import {spawnSync} from 'node:child_process'
import {join,resolve,extname} from 'node:path'
import {fileURLToPath} from 'node:url'
import {setTimeout as delay} from 'node:timers/promises'
import {isDeepStrictEqual} from 'node:util'
import {chromium} from 'playwright'
import {inspectAnalysisLayout} from './office-xlsx-analysis-layout.mjs'
const frontend=fileURLToPath(new URL('../',import.meta.url)),repo=resolve(frontend,'../../..'),staticRoot=resolve(frontend,'../static')
const directory=process.env.XLSX_ANALYSIS_OUTPUT,port=Number(process.env.XLSX_ANALYSIS_PORT??4396),base='http://127.0.0.1:'+port,prefix='/reports/v1/editor/assets/',pathBase='/reports/v1/native/analysis-pc/'
assert.ok(directory);await mkdir(directory,{recursive:true});let prior=false;try{await access(join(directory,'save.json'));prior=true}catch{}assert.equal(prior,false,'never repeat a successful save')
const sha=b=>createHash('sha256').update(b).digest('hex'),manifest=await readFile(join(staticRoot,'.vite/manifest.json'))
assert.equal(sha(manifest),process.env.WORKBOOK_EXPECTED_MANIFEST_SHA256);await writeFile(join(directory,'build-manifest.json'),manifest)
function engine(mode,extra={}){const r=spawnSync(join(repo,'.venv/bin/python'),[join(frontend,'smoke/office-xlsx-analysis-fixture.py')],{cwd:repo,env:{...process.env,PYTHONPATH:repo},input:JSON.stringify({mode,directory,...extra}),encoding:'utf8',timeout:120000,maxBuffer:20*1024*1024});assert.equal(r.status,0,r.stderr);return JSON.parse(r.stdout)}
engine('create');const source=await readFile(join(directory,'source.xlsx')),revisions={1:source},media='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',layout={cases:[],failures:[]},errors=[],requests=[],checks=[],resources=new Map()
let browser,page,saved=false,stage='start',routeError
const server=createServer(async(req,res)=>{try{const path=new URL(req.url,base).pathname
 if(path==='/favicon.ico'){res.writeHead(200,{'Content-Type':'image/svg+xml'});res.end('<svg xmlns="http://www.w3.org/2000/svg"/>');return}
 if(path==='/analysis-download.xlsx'){assert.ok(revisions[2]);res.writeHead(200,{'Content-Type':media,'Content-Disposition':'attachment; filename=analysis.xlsx','Content-Length':revisions[2].length});res.end(revisions[2]);requests.push({method:req.method,path:'download-http'});return}
 const native=new RegExp('^'+pathBase+'[0-9]+$').test(path)
 assert.ok(native||path.startsWith(prefix));const target=native?join(staticRoot,'native.html'):resolve(staticRoot,path.slice(prefix.length));assert.ok(target.startsWith(staticRoot+'/'));const data=await readFile(target)
 res.writeHead(200,{'Content-Type':{'.js':'application/javascript','.css':'text/css','.html':'text/html','.woff2':'font/woff2','.ttf':'font/ttf'}[extname(target)]??'application/octet-stream'});res.end(data)
 }catch{res.writeHead(404);res.end('not found')}})
await new Promise((done,reject)=>{server.once('error',reject);server.listen(port,'127.0.0.1',done)})
try{
 browser=await chromium.launch({headless:true,...(process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE?{executablePath:process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE}:{})});page=await browser.newPage({viewport:{width:1440,height:900}})
 page.on('pageerror',e=>errors.push(e.message));page.on('console',m=>{if(m.type()==='error')errors.push(m.text())});page.on('crash',()=>errors.push('renderer crashed'))
 page.on('response',r=>{const path=new URL(r.url()).pathname;if(r.status()>=400)errors.push(r.status()+' '+path);if(r.status()===200&&path.startsWith(prefix)&&/\.(?:m?js|css)$/.test(path))checks.push(r.body().then(async b=>{assert.equal(sha(b),sha(await readFile(join(staticRoot,path.slice(prefix.length)))));resources.set(path,{sha256:sha(b),size:b.length})}).catch(e=>errors.push(String(e))))})
 await page.route(new RegExp(pathBase+'[0-9]+/api/'),async route=>{try{
  const request=route.request(),path=new URL(request.url()).pathname,match=path.match(/\/analysis-pc\/(\d+)\/api\/(.*)$/),revision=Number(match[1]),suffix=match[2],bytes=revisions[revision];requests.push({method:request.method(),path:suffix})
  if(suffix==='context')return route.fulfill({json:{context:{documentId:'analysis-pc',format:'xlsx',revision,parentRevision:revision>1?revision-1:null,scope:{database:'fixture',companyId:'fixture',userId:'fixture',threadId:'fixture'},sourceFile:{path:'analysis.xlsx',size:bytes.length,sha256:sha(bytes),mediaType:media},origin:'upload'},csrfToken:'fixture',capabilities:{xlsx_editor:true},editingEnabled:true}})
  if(suffix==='file')return route.fulfill({body:bytes,contentType:media})
  assert.equal(suffix,'save');assert.equal(saved,false);const input=request.postDataJSON();assert.equal(input.expectedSha256,sha(source));const artifact=engine('patch',{operations:input.operations});revisions[2]=await readFile(join(directory,'revision-2.xlsx'));saved=true
  const result={documentId:'analysis-pc',revision:2,parentRevision:1,revisionRegistered:true,artifacts:{xlsx:{downloadUrl:base+'/analysis-download.xlsx',...artifact}},editor:{openUrl:base+pathBase+'2'},validation:{ok:false,issues:[{code:'manual_review',message:'模拟分析结果版式待复核，文件已生成。'}]}}
  await writeFile(join(directory,'save.json'),JSON.stringify({request:input,result},null,2));return route.fulfill({json:result})
 }catch(error){routeError=error;await route.fulfill({status:500,json:{detail:String(error)}})}})
 const ready=()=>page.waitForFunction(()=>document.querySelector('#report-editor')?.getAttribute('aria-busy')==='false',null,{timeout:90000})
 const draft=()=>page.evaluate(()=>Object.entries(localStorage).filter(([k])=>k.startsWith('native-editor-draft:')).map(([k,v])=>[k,JSON.parse(v).operations]))
 const operations=async()=>(await draft()).flatMap(([,ops])=>ops)
 const waitOperations=async expected=>{for(let i=0;i<150;i++){if(isDeepStrictEqual(await operations(),expected))return;await delay(100)}assert.deepEqual(await operations(),expected)}
 const go=async ref=>{const input=page.locator('[data-u-comp="defined-name"] input');await input.fill(ref);await input.press('Enter');await delay(150)}
 const history=async command=>{await page.locator('[data-ribbon-tab=File]').click();await page.locator(`[data-ribbon-command=${command}]`).click()}
 const labels={goal:'单变量求解',table:'模拟运算表'},commands={goal:'goal-seek-open',table:'data-table-open'}
 const dialog=kind=>page.getByRole('dialog',{name:labels[kind],exact:true}),entry=kind=>page.locator(`[data-ribbon-command=${commands[kind]}]`)
 const open=async kind=>{await page.locator('[data-ribbon-tab=Data]').click();await entry(kind).click();await dialog(kind).waitFor()}
 const inspect=async(kind,phase)=>{await inspectAnalysisLayout(page,{directory,label:labels[kind],phase:kind+'-'+phase,layout,draft});assert.deepEqual(layout.failures,[])}
 const close=async kind=>{await page.keyboard.press('Escape');await dialog(kind).waitFor({state:'hidden'});assert.equal(await entry(kind).evaluate(n=>n===document.activeElement),true)}
 await page.goto(base+pathBase+'1');await ready();await go('B1');await open('goal');stage='goal-initial';await inspect('goal','initial');assert.equal(await dialog('goal').locator('[type=submit]').isDisabled(),true)
 await dialog('goal').getByLabel('目标值',{exact:true}).fill('Infinity');await dialog('goal').getByLabel('可变单元格',{exact:true}).fill('A1');await dialog('goal').locator('[type=submit]').click();assert.match(await dialog('goal').getByRole('alert').innerText(),/有限数值/);assert.deepEqual(await operations(),[]);stage='goal-error';await inspect('goal','error')
 stage='goal-solve';await dialog('goal').getByLabel('目标值',{exact:true}).fill('30');await dialog('goal').locator('[type=submit]').click();await page.waitForFunction(()=>document.querySelector('[role=dialog][aria-label="单变量求解"]')?.getAttribute('aria-busy')==='false',null,{timeout:60000});assert.match(await dialog('goal').getByRole('status').innerText(),/找到解：15/,await dialog('goal').innerText());stage='goal-success';await inspect('goal','success');await close('goal')
 const goalEdits=[{kind:'applyCellEdits',edits:[{sheetName:'Analysis',row:0,column:0,cell:{value:15},writeValue:true}]}];await waitOperations(goalEdits)
 await go('D2:E5');await open('table');stage='table-initial';await inspect('table','initial')
 await dialog('table').getByLabel('行输入单元格',{exact:true}).fill('A1');await dialog('table').getByLabel('列输入单元格',{exact:true}).fill('A1');await dialog('table').locator('[type=submit]').click();await dialog('table').getByRole('alert').getByText('行和列输入单元格不能相同',{exact:true}).waitFor();stage='table-error';await inspect('table','error');assert.deepEqual(await operations(),goalEdits)
 stage='table-calculate';await dialog('table').getByLabel('行输入单元格',{exact:true}).fill('');await dialog('table').locator('[type=submit]').click();await page.waitForFunction(()=>document.querySelector('[role=dialog][aria-label="模拟运算表"]')?.getAttribute('aria-busy')==='false',null,{timeout:60000});assert.match(await dialog('table').getByRole('status').innerText(),/已生成 3 个结果/,await dialog('table').innerText());stage='table-success';await inspect('table','success');await close('table')
 const expected=structuredClone(goalEdits);expected[0].edits.push(...[20,40,60].map((value,index)=>({sheetName:'Analysis',row:index+2,column:4,cell:{value},writeValue:true})));await waitOperations(expected)
 await history('undo');await waitOperations(goalEdits);await history('redo');await waitOperations(expected);await page.reload();await ready();await waitOperations(expected)
 stage='save';await page.locator('[data-action=save]').click();await page.waitForFunction(()=>document.querySelector('.save-state-label')?.textContent?.includes('已保存修订 2'),null,{timeout:90000});if(routeError)throw routeError
 assert.match(await page.locator('.workbook-feedback').innerText(),/模拟分析结果版式待复核/);const downloading=page.waitForEvent('download');await page.locator('[data-action=xlsx-download]').click();const download=await downloading;assert.equal(await download.failure(),null);await download.saveAs(join(directory,'downloaded.xlsx'));assert.deepEqual(await readFile(join(directory,'downloaded.xlsx')),revisions[2]);const independent=engine('verify')
 stage='reopen';await page.goto(base+pathBase+'2');await ready();for(const kind of ['goal','table']){await go(kind==='goal'?'B1':'D2:E5');await open(kind);await inspect(kind,'reopened');await close(kind)}await page.screenshot({path:join(directory,'reopened-file.png'),fullPage:true})
 await Promise.all(checks);assert.deepEqual(errors,[]);assert.deepEqual(await readFile(join(staticRoot,'.vite/manifest.json')),manifest)
 await writeFile(join(directory,'evidence.json'),JSON.stringify({ok:true,manifest:sha(manifest),realUniverCalculation:true,routeIsFixture:true,realPythonSave:true,actualBrowserDownload:true,savedRevisions:1,layout,applied:expected,independent,requests,resources:Object.fromEntries(resources),errors},null,2));console.log(JSON.stringify({ok:true,cases:layout.cases.length,resources:resources.size,directory}))
}catch(error){await page?.screenshot({path:join(directory,'failure.png'),fullPage:true}).catch(()=>{});const diagnostics=await page?.evaluate(()=>({dialogs:[...document.querySelectorAll('[role=dialog]:not([hidden])')].map(n=>({label:n.getAttribute('aria-label'),busy:n.getAttribute('aria-busy'),text:n.textContent})),drafts:Object.entries(localStorage).filter(([k])=>k.startsWith('native-editor-draft:'))})).catch(()=>undefined);await writeFile(join(directory,'failure.json'),JSON.stringify({stage,saved,error:String(error),stack:error.stack,routeError:String(routeError??''),errors,diagnostics},null,2));throw error}
finally{await browser?.close();await new Promise(done=>server.close(done))}
