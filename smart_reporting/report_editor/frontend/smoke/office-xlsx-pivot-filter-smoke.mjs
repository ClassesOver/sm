// 当前生产构建 + 真实 Chromium/Node/Python 文件链；HTTP鉴权/context/保存登记为显式fixture。
import assert from 'node:assert/strict'
import {spawn,spawnSync} from 'node:child_process'
import {createHash} from 'node:crypto'
import {createServer} from 'node:http'
import {mkdir,readFile,writeFile} from 'node:fs/promises'
import {resolve,join,dirname} from 'node:path'
import {fileURLToPath} from 'node:url'
import {setTimeout as delay} from 'node:timers/promises'
import {build} from 'esbuild'
import {chromium} from 'playwright'
import {inspectPivotFilter} from './office-xlsx-pivot-filter-layout.mjs'
const frontend=resolve(dirname(fileURLToPath(import.meta.url)),'..'),repo=resolve(frontend,'../../..'),staticRoot=resolve(frontend,'../static')
const output=process.env.OFFICE_PIVOT_FILTER_OUTPUT,port=Number(process.env.OFFICE_PIVOT_FILTER_PORT??4321),base='http://127.0.0.1:'+port
const resume=process.env.OFFICE_PIVOT_FILTER_RESUME==='1'
assert.ok(output,'specify fresh OFFICE_PIVOT_FILTER_OUTPUT');await mkdir(output,{recursive:true})
const sha=b=>createHash('sha256').update(b).digest('hex'),manifest=sha(await readFile(join(staticRoot,'.vite/manifest.json')))
assert.equal(manifest,process.env.WORKBOOK_EXPECTED_MANIFEST_SHA256,'wrong production build')
const fixture=join(output,'fixture.mjs')
await build({entryPoints:[resolve(frontend,'smoke/office-xlsx-pivot-filter-fixture.mjs')],outfile:fixture,bundle:true,platform:'node',format:'esm',banner:{js:"import {createRequire} from 'node:module';const require=createRequire(import.meta.url);"}})
const pySource=`
import json,sys,base64
from io import BytesIO
from pathlib import Path
from datetime import datetime
from zipfile import ZipFile
from openpyxl import Workbook,load_workbook
from smart_reporting.report_editor.native_office import patch_office
p=json.load(sys.stdin)
if p['mode']=='source':
 b=Workbook();s=b.active;s.title='Data';s.append(['Date','Region','Amount'])
 for i in range(1,19):s.append([datetime(2026,1,i),'Region_'+str(i).zfill(2)+'_'+'长成员名称'*12,i*10])
 b.create_sheet('Pivot');s=b.create_sheet('Preserved');s['A1']='unchanged formula';s['B1']='=SUM(1,2)';b.save(p['output']);print('{}')
elif p['mode']=='patch':
 data=patch_office('xlsx',Path(p['source']).read_bytes(),p['operations']);Path(p['output']).write_bytes(data);print('{}')
else:
 b=load_workbook(p['source']);assert b['Preserved']['B1'].value=='=SUM(1,2)';assert b['Data'].max_row==19
 with ZipFile(p['source']) as z:assert z.testzip() is None
 print(json.dumps({'sheets':b.sheetnames,'dataRows':18,'preservedFormula':b['Preserved']['B1'].value,'pivotNames':[t.name for t in b['Pivot']._pivots]}))
`
function python(payload){const r=spawnSync(resolve(repo,'.venv/bin/python'),['-c',pySource],{cwd:repo,env:{...process.env,PYTHONPATH:repo},input:JSON.stringify(payload),encoding:'utf8',maxBuffer:20*1024*1024,timeout:120000});assert.equal(r.status,0,r.stderr);return JSON.parse(r.stdout)}
function node(mode,path,destination){const r=spawnSync(process.execPath,[fixture,mode,path,...(destination?[destination]:[])],{encoding:'utf8',timeout:120000,maxBuffer:20*1024*1024});assert.equal(r.status,0,r.stderr);return r.stdout?JSON.parse(r.stdout):undefined}
if(!resume){python({mode:'source',output:join(output,'raw.xlsx')});node('create',join(output,'raw.xlsx'),join(output,'revision-1.xlsx'))}
const prior=resume?JSON.parse(await readFile(join(output,'request.json'),'utf8')):undefined
const source=await readFile(join(output,'revision-1.xlsx')),sourceSha256=sha(source),revisions={1:source,...(resume?{2:await readFile(join(output,'revision-2.xlsx'))}:{})},layout=resume?JSON.parse(await readFile(join(output,'layout.json'),'utf8')):{cases:[],failures:[]},errors=[],resources=new Map(),checks=[],requests=[]
let browser,page,saved=resume,replayed=false,preview
const downloadServer=createServer((_req,res)=>{const bytes=revisions[2];if(!bytes){res.writeHead(404);res.end();return}res.writeHead(200,{'Content-Type':'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet','Content-Disposition':'attachment; filename=pivot-filter.xlsx','Content-Length':bytes.length});res.end(bytes)})
await new Promise((done,reject)=>{downloadServer.once('error',reject);downloadServer.listen(0,'127.0.0.1',done)})
const downloadUrl='http://127.0.0.1:'+downloadServer.address().port+'/pivot-filter-download.xlsx'
try{
 preview=spawn('./node_modules/.bin/vite',['preview','--host','127.0.0.1','--port',String(port),'--strictPort'],{cwd:frontend,stdio:'ignore'})
 for(let i=0;i<120;i++){try{if((await fetch(base+'/reports/v1/editor/assets/native.html')).ok)break}catch{}await delay(250);assert.ok(i<119,'preview not ready')}
 browser=await chromium.launch({headless:true,...(process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE?{executablePath:process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE}:{})});page=await browser.newPage({viewport:{width:1500,height:1000}})
 page.on('pageerror',e=>errors.push(e.message));page.on('console',m=>{if(m.type()==='error')errors.push(m.text())});page.on('crash',()=>errors.push('Chromium renderer crashed'))
 page.on('response',r=>{const path=new URL(r.url()).pathname;if(r.status()>=400)errors.push(`${r.status()} ${path}`);if(path.startsWith('/reports/v1/editor/assets/')&&/\.(js|css)$/.test(path))checks.push(r.body().then(async bytes=>{assert.equal(r.status(),200);assert.equal(sha(bytes),sha(await readFile(join(staticRoot,path.slice('/reports/v1/editor/assets/'.length)))));resources.set(path,{size:bytes.length,sha256:sha(bytes)})}).catch(e=>errors.push(String(e))))})
 const media='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
 await page.route('**/reports/v1/native/pivot-filter-pc/**',async route=>{
  const req=route.request(),match=new URL(req.url()).pathname.match(/\/pivot-filter-pc\/(\d+)(.*)$/),revision=Number(match[1]),suffix=match[2],bytes=revisions[revision]
  if(!suffix)return route.fulfill({response:await route.fetch({url:base+'/reports/v1/editor/assets/native.html'})})
  requests.push({method:req.method(),path:suffix})
  if(suffix==='/api/context')return route.fulfill({json:{context:{documentId:'pivot-filter-pc',format:'xlsx',revision,parentRevision:revision>1?revision-1:null,scope:{database:'fixture',companyId:'fixture',userId:'fixture',threadId:'fixture'},sourceFile:{path:'revision-'+revision+'.xlsx',size:bytes.length,sha256:sha(bytes),mediaType:media},origin:'upload'},csrfToken:'fixture',capabilities:{xlsx_editor:true},editingEnabled:true}})
  if(suffix==='/api/file')return route.fulfill({body:bytes,contentType:media})
  if(suffix==='/api/save'){
   const payload=req.postDataJSON();assert.equal(payload.expectedSha256,sourceSha256)
   if(resume){assert.equal(replayed,false);assert.deepEqual(payload,prior);replayed=true}
   else{assert.equal(saved,false,'never repeat a successful save');python({mode:'patch',source:join(output,'revision-1.xlsx'),output:join(output,'revision-2.xlsx'),operations:payload.operations});revisions[2]=await readFile(join(output,'revision-2.xlsx'));saved=true;await writeFile(join(output,'request.json'),JSON.stringify(payload,null,2))}
   return route.fulfill({json:{documentId:'pivot-filter-pc',revision:2,parentRevision:1,revisionRegistered:true,artifacts:{xlsx:{downloadUrl,size:revisions[2].length,sha256:sha(revisions[2])}},editor:{openUrl:'/reports/v1/native/pivot-filter-pc/2'},validation:{ok:false,issues:[{code:'fixture_review_pending',message:'透视筛选版式验收待复核'}]}}})
  }
  throw new Error('unexpected fixture route '+suffix)
 })
 const ready=()=>page.waitForFunction(()=>document.querySelector('#report-editor')?.getAttribute('aria-busy')==='false',null,{timeout:60000})
 const command=async(tab,id)=>{await page.locator(`[data-ribbon-tab="${tab}"]`).click();await page.locator(`[data-ribbon-command="${id}"]`).click()}
 const draft=()=>page.evaluate(()=>Object.entries(localStorage).filter(([key])=>key.startsWith('native-editor-draft:')).map(([key,value])=>[key,JSON.parse(value).operations]))
 const dialog=page.locator('[role=dialog][aria-label="透视表筛选"]'),card=dialog.locator('.modal-card')
 const open=async mode=>{await command('Insert',mode==='slicer'?'slicer-open':'timeline-open');await dialog.waitFor();await dialog.locator('[aria-label="筛选字段"] option').first().waitFor({state:'attached'});await page.waitForFunction(()=>!document.querySelector('[aria-label="筛选字段"]')?.disabled)}
 const cancel=async mode=>{await dialog.locator('[data-action=cancel]').click();assert.equal(await page.locator(`[data-ribbon-command="${mode==='slicer'?'slicer-open':'timeline-open'}"]`).evaluate(node=>document.activeElement===node),true)}
 let excluded
 if(resume){
  await page.goto(base+'/reports/v1/native/pivot-filter-pc/1');await ready()
  const identity={documentId:'pivot-filter-pc',revision:1,sourceSha256,scope:{database:'fixture',companyId:'fixture',userId:'fixture',threadId:'fixture'}}
  const key='native-editor-draft:v1:'+JSON.stringify(['fixture','fixture','fixture','fixture','pivot-filter-pc',1,sourceSha256])
  await page.evaluate(({key,identity,prior})=>localStorage.setItem(key,JSON.stringify({version:1,identity,operations:prior.operations,pending:{action:'save',request:prior}})),{key,identity,prior})
  await page.reload();await ready()
  excluded=node('inspect',join(output,'revision-2.xlsx')).pivots[0].hiddenMembers.column[0][0]
 }else{
 await page.goto(base+'/reports/v1/native/pivot-filter-pc/1');await ready();assert.deepEqual(await draft(),[])
 await open('slicer');await dialog.getByLabel('筛选字段',{exact:true}).selectOption('Region')
 await inspectPivotFilter(page,{output,phase:'slicer',evidence:layout,draft})
 if(process.env.OFFICE_PIVOT_FILTER_BASELINE)throw new Error('expected baseline defects: '+layout.failures.join('; '))
 assert.deepEqual(layout.failures,[]);await cancel('slicer');assert.deepEqual(await draft(),[])
 await open('timeline');await dialog.getByLabel('筛选字段',{exact:true}).selectOption('Date');await dialog.getByLabel('开始日期',{exact:true}).fill('2026-01-18');await dialog.getByLabel('结束日期',{exact:true}).fill('2026-01-01');await dialog.locator('[type=submit]').click();assert.ok((await dialog.locator('[role=alert]').textContent()).includes('开始日期'));assert.deepEqual(await draft(),[])
 await inspectPivotFilter(page,{output,phase:'timeline-error',evidence:layout,draft});assert.deepEqual(layout.failures,[]);await page.keyboard.press('Escape');await dialog.waitFor({state:'hidden'})
 await open('slicer');await dialog.getByLabel('筛选字段',{exact:true}).selectOption('Region');await dialog.locator('[data-native-control]').check()
 const member=dialog.locator('[data-members] input').first();excluded=await member.inputValue();await member.uncheck()
 await dialog.getByLabel('控件名称',{exact:true}).fill('PC_Slicer');await dialog.getByLabel('控件标题',{exact:true}).fill('经营收入 · 按地区筛选');await dialog.getByLabel('控件左上角单元格',{exact:true}).fill('AZ2');await dialog.getByLabel('控件宽度（像素）',{exact:true}).fill('240')
 await dialog.locator('summary').click()
 await inspectPivotFilter(page,{output,phase:'native-slicer',evidence:layout,draft});assert.deepEqual(layout.failures,[]);await dialog.locator('summary').click()
 await dialog.locator('[type=submit]').click();await dialog.waitFor({state:'hidden'});await ready();const slicerDraft=await draft();assert.ok(slicerDraft.flatMap(([,ops])=>ops).some(op=>op.kind==='upsertPivotControl'))
 await command('File','undo');await ready();assert.deepEqual((await draft()).flatMap(([,operations])=>operations),[]);await command('File','redo');await ready();assert.deepEqual(await draft(),slicerDraft)
 await page.reload();await ready();assert.deepEqual(await draft(),slicerDraft)
 await open('timeline');await dialog.getByLabel('筛选字段',{exact:true}).selectOption('Date');await dialog.locator('[data-native-control]').check();await dialog.getByLabel('控件名称',{exact:true}).fill('PC_Timeline');await dialog.getByLabel('控件左上角单元格',{exact:true}).fill('AZ18');await dialog.getByLabel('结束日期',{exact:true}).fill('2026-01-15')
 await inspectPivotFilter(page,{output,phase:'native-timeline',evidence:layout,draft});assert.deepEqual(layout.failures,[])
 await dialog.locator('[type=submit]').click();await dialog.waitFor({state:'hidden'});await ready()
 }
 await page.locator('[data-action=save]').click();await page.waitForFunction(()=>document.querySelector('.save-state-label')?.textContent.includes('已保存修订 2'),null,{timeout:120000});await page.locator('.workbook-feedback').filter({hasText:'透视筛选版式验收待复核'}).waitFor({state:'visible'})
 const [download]=await Promise.all([page.waitForEvent('download'),page.locator('[data-action=xlsx-download]').click()]);await download.saveAs(join(output,'downloaded.xlsx'));assert.equal(sha(await readFile(join(output,'downloaded.xlsx'))),sha(revisions[2]))
 const inspected=node('inspect',join(output,'downloaded.xlsx')),independent=python({mode:'inspect',source:join(output,'downloaded.xlsx')});assert.equal(inspected.controls.length,2);assert.ok(inspected.controls.some(c=>c.name==='PC_Slicer'&&c.kind==='slicer'));assert.ok(inspected.controls.some(c=>c.name==='PC_Timeline'&&c.kind==='timeline'))
 await page.goto(base+'/reports/v1/native/pivot-filter-pc/2');await ready();await open('slicer');await dialog.getByLabel('筛选字段',{exact:true}).selectOption('Region');assert.equal(await dialog.getByLabel('控件名称',{exact:true}).inputValue(),'PC_Slicer');assert.equal(await dialog.locator('[data-native-control]').isDisabled(),true);assert.equal(await dialog.locator('[data-members] input').first().isChecked(),false)
 await inspectPivotFilter(page,{output,phase:'reopened-slicer',evidence:layout,draft});assert.deepEqual(layout.failures,[]);await cancel('slicer')
 await page.waitForLoadState('networkidle');await Promise.all(checks);assert.deepEqual(errors,[]);assert.equal(sha(await readFile(join(staticRoot,'.vite/manifest.json'))),manifest);assert.equal(sha(await readFile(join(output,'revision-1.xlsx'))),sourceSha256)
 const result={ok:true,apiRoutesAreFixtures:true,realPythonNodeBridge:true,actualBrowserDownload:true,resumedSavedResponse:resume,replayed,manifest,sourceSha256,outputSha256:sha(revisions[2]),excluded,layout,inspected,independent,requests,resources:Object.fromEntries(resources),errors}
 await writeFile(join(output,'evidence.json'),JSON.stringify(result,null,2));console.log(JSON.stringify({ok:true,output,cases:layout.cases.length,resources:resources.size}))
}catch(error){await page?.screenshot({path:join(output,'failure.png'),fullPage:true}).catch(()=>{});await writeFile(join(output,'failure.json'),JSON.stringify({error:String(error),stack:error.stack,saved,errors},null,2));throw error}
finally{await browser?.close();preview?.kill();await new Promise(done=>downloadServer.close(done))}
