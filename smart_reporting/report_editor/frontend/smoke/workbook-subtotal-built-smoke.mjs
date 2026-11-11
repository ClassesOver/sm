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
const port=Number(process.env.SUBTOTAL_SMOKE_PORT??4283),base=`http://127.0.0.1:${port}`,documentId='subtotal-built'
const checkpoint=process.env.SUBTOTAL_SMOKE_DIRECTORY??`/tmp/xlsx-subtotal-built-${Date.now()}`
await mkdir(checkpoint,{recursive:true})
await writeFile(join(checkpoint,'build-manifest.json'),await readFile(join(frontend,'../static/.vite/manifest.json')))
const sha=bytes=>createHash('sha256').update(bytes).digest('hex'),media='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
const quote=name=>"'"+name.replaceAll("'","''")+"'"
function python(payload){const result=spawnSync(join(repo,'.venv/bin/python'),['-c',`
import base64,json,sys
from io import BytesIO
from zipfile import ZipFile
from lxml import etree
from openpyxl import Workbook,load_workbook
from openpyxl.workbook.defined_name import DefinedName
from smart_reporting.report_editor.native_office import patch_office
p=json.load(sys.stdin)
if p['mode']=='fixture':
 b=Workbook();s=b.active;s.title=p['sheet'];o=p['offset'];c=1 if o==0 else 3
 for r,row in enumerate([['Group','Value','Other'],['A',10,'a'],['A',20,'b'],['B',30,'c'],['B',40,'d'],['Tail',99,'keep']],o+1):
  for col,value in enumerate(row,c):s.cell(r,col,value)
 s.sheet_properties.outlinePr.summaryBelow=False
 d=b.create_sheet('Dependent');v='B' if o==0 else 'D';g='A' if o==0 else 'C';q="'"+s.title.replace("'","''")+"'"
 d['A1']=f'={q}!$'+v+'$'+str(o+4);d['A2']=f'=SUM({q}!{v}{o+2}:{v}{o+5})'
 b.defined_names.add(DefinedName('Body',attr_text=f'{q}!$'+g+'$'+str(o+2)+':$'+v+'$'+str(o+5)))
 f=BytesIO();b.save(f);print(base64.b64encode(f.getvalue()).decode())
elif p['mode']=='patch':print(base64.b64encode(patch_office('xlsx',base64.b64decode(p['bytes']),p['operations'])).decode())
else:
 data=base64.b64decode(p['bytes']);o=p['offset'];g,v=('A','B') if o==0 else ('C','D');code={'sum':9,'count':3,'average':1}[p['agg']]
 with ZipFile(BytesIO(data)) as z:
  assert z.testzip() is None
  for name in z.namelist():
   if name.endswith(('.xml','.rels')):etree.fromstring(z.read(name))
 b=load_workbook(BytesIO(data));s=b[p['sheet']];q="'"+s.title.replace("'","''")+"'"
 for r,label,start,end in [(o+4,'A Total',o+2,o+3),(o+7,'B Total',o+5,o+6),(o+8,'Grand Total',o+2,o+7)]:
  assert s[f'{g}{r}'].value==label
  assert s[f'{v}{r}'].value==f'=SUBTOTAL({code},$'+v+'$'+str(start)+':$'+v+'$'+str(end)+')'
  assert s[f'{g}{r}'].font.bold and s[f'{v}{r}'].font.bold
 assert s[f'{g}{o+9}'].value=='Tail' and s[f'{v}{o+9}'].value==99
 assert s.cell(o+9,3 if o==0 else 5).value=='keep'
 assert [s.row_dimensions[r].outlineLevel for r in range(o+1,o+10)]==[0,2,2,1,2,2,1,0,0]
 assert s.sheet_properties.outlinePr.summaryBelow is True
 assert b['Dependent']['A1'].value==f'={q}!$'+v+'$'+str(o+5)
 assert b['Dependent']['A2'].value==f'=SUM({q}!{v}{o+2}:{v}{o+6})'
 assert b.defined_names['Body'].attr_text==f'{q}!$'+g+'$'+str(o+2)+':$'+v+'$'+str(o+6)
 print(json.dumps({'zipXmlOpenpyxl':True,'tail':s[f'{g}{o+9}'].value,'summaryBelow':True,'grandFormula':s[f'{v}{o+8}'].value,'cache':load_workbook(BytesIO(data),data_only=True)[p['sheet']][f'{v}{o+8}'].value}))
`],{cwd:repo,env:{...process.env,PYTHONPATH:repo},input:JSON.stringify(payload),encoding:'utf8',maxBuffer:30*1024*1024});assert.equal(result.status,0,result.stderr);return result.stdout.trim()}
const cases=[{agg:'sum',sheet:'Sum Data',offset:0,revision:1,expected:100},{agg:'count',sheet:'Count 数据',offset:4,revision:10,expected:4},{agg:'average',sheet:"Average's Data",offset:4,revision:20,expected:25}].filter(item=>!process.env.SUBTOTAL_SMOKE_AGG||item.agg===process.env.SUBTOTAL_SMOKE_AGG).map(item=>({...item,revision:item.revision+Number(process.env.SUBTOTAL_SMOKE_REVISION_OFFSET??0)}))
const revisions=new Map(),downloads=new Map(),savedSources=new Set(),results=[],assets=new Map(),assetChecks=[],errors=[]
for(const item of cases){const path=join(checkpoint,`source-${item.revision}.xlsx`);let bytes;try{bytes=await readFile(path)}catch(error){if(error.code!=='ENOENT')throw error;bytes=Buffer.from(python({mode:'fixture',...item}),'base64');await writeFile(path,bytes)}revisions.set(item.revision,bytes)}
let preview,browser,page,stage='setup',routeError,saveCount=0
const http=createServer(async(req,res)=>{try{
 const file=/^\/reports\/v1\/native\/subtotal-built\/(\d+)\/api\/file$/.exec(req.url??''),context=/^\/reports\/v1\/native\/subtotal-built\/(\d+)\/api\/context$/.exec(req.url??''),download=/^\/download\/(\d+)\.xlsx$/.exec(req.url??'')
 if(file||download){const bytes=(file?revisions:downloads).get(Number((file??download)[1]));assert(bytes);res.writeHead(200,{'Content-Type':media,'Content-Disposition':'attachment; filename=subtotal.xlsx'});res.end(bytes);return}
 if(context){const revision=Number(context[1]),bytes=revisions.get(revision);assert(bytes);res.writeHead(200,{'Content-Type':'application/json'});res.end(JSON.stringify({context:{documentId,format:'xlsx',revision,parentRevision:revision-1,scope:{database:'f',companyId:'f',userId:'f',threadId:'f'},sourceFile:{path:`subtotal-${revision}.xlsx`,size:bytes.length,sha256:sha(bytes),mediaType:media},origin:'upload'},csrfToken:'csrf',capabilities:{xlsx_editor:true},editingEnabled:true}));return}
 const path=/^\/reports\/v1\/native\/subtotal-built\/\d+$/.test(req.url??'')?'/reports/v1/editor/assets/native.html':req.url,r=await fetch(base+path);res.writeHead(r.status,Object.fromEntries([...r.headers].filter(([key])=>!['content-encoding','content-length','transfer-encoding'].includes(key))));res.end(Buffer.from(await r.arrayBuffer()))
 }catch(error){res.writeHead(500);res.end(String(error))}})
await new Promise(resolve=>http.listen(0,'127.0.0.1',resolve));const app=`http://127.0.0.1:${http.address().port}`
try{
 preview=spawn('./node_modules/.bin/vite',['preview','--host','127.0.0.1','--port',String(port),'--strictPort'],{cwd:frontend,stdio:'pipe'})
 for(let i=0;;i++){assert.equal(preview.exitCode,null);try{if((await fetch(base+'/reports/v1/editor/assets/native.html')).ok)break}catch{}assert(i<120);await delay(250)}
 browser=await chromium.launch({headless:true});page=await browser.newPage({viewport:{width:1500,height:1100},acceptDownloads:true,permissions:['clipboard-read','clipboard-write']})
 page.on('pageerror',error=>{errors.push(error.message);const detail={stage,message:error.message,stack:error.stack};console.error(JSON.stringify({pageerror:detail}));void writeFile(join(checkpoint,`page-error-${errors.length}.json`),JSON.stringify(detail,null,2))});page.on('dialog',dialog=>dialog.type()==='beforeunload'?dialog.accept():dialog.dismiss())
 page.on('response',response=>{const path=new URL(response.url()).pathname;if(!path.startsWith('/reports/v1/editor/assets/')||!path.endsWith('.js'))return;assetChecks.push((async()=>{assert.equal(response.status(),200);const bytes=await response.body();assert.equal(sha(bytes),sha(await readFile(join(frontend,'../static',path.slice('/reports/v1/editor/assets/'.length)))));assets.set(path,sha(bytes));await writeFile(join(checkpoint,'assets.json'),JSON.stringify(Object.fromEntries(assets),null,2))})())})
 await page.route('**/reports/v1/native/subtotal-built/*/api/save',async route=>{try{
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
 const copy=async reference=>{await goto(reference);const sentinel=`subtotal-${Date.now()}-${Math.random()}`;await page.evaluate(text=>navigator.clipboard.writeText(text),sentinel);await page.keyboard.press('Control+c');await page.waitForFunction(async text=>(await navigator.clipboard.readText())!==text,sentinel,{timeout:10000});return(await page.evaluate(()=>navigator.clipboard.readText())).trimEnd()}
 const computed=async(reference,expected)=>{let actual;for(let attempt=0;attempt<20;attempt++){actual=Number(await copy(reference));if(actual===expected)return actual;await delay(150)}assert.equal(actual,expected)}
 const drafts=()=>page.evaluate(()=>Object.fromEntries(Object.keys(localStorage).filter(key=>key.startsWith('native-editor-draft:')).map(key=>[key,JSON.parse(localStorage.getItem(key))])))
 for(const item of cases){stage=`${item.agg}-setup`;let saved;try{saved=JSON.parse(await readFile(join(checkpoint,`saved-source-${item.revision}.json`),'utf8'))}catch(error){if(error.code!=='ENOENT')throw error}
  const q=quote(item.sheet),g=item.offset===0?'A':'C',v=item.offset===0?'B':'D',grand=`${q}!${v}${item.offset+8}`,selection=`${q}!${g}${item.offset+1}:${v}${item.offset+5}`
  let bytes,operations
  if(saved){bytes=await readFile(join(checkpoint,`revision-${saved.revision}.xlsx`));assert.equal(sha(bytes),saved.sha256);revisions.set(saved.revision,bytes);downloads.set(saved.revision,bytes);savedSources.add(item.revision);operations=saved.operations}
  else{
   try{await readFile(join(checkpoint,`revision-${item.revision+1}.xlsx`));throw Error('已有产物缺少回执，禁止重复保存')}catch(error){if(error.code!=='ENOENT')throw error}
   await open(item.revision);await goto(selection);const before=await drafts();await command('Data','subtotal-open')
   const modal=page.getByRole('dialog',{name:'分类汇总',exact:true});await modal.getByRole('button',{name:'取消',exact:true}).click();assert.deepEqual(await drafts(),before)
   await goto(selection);await command('Data','subtotal-open');await modal.getByLabel('汇总方式',{exact:true}).selectOption(item.agg);await page.screenshot({path:join(checkpoint,`${item.agg}-dialog.png`),fullPage:true});await modal.getByRole('button',{name:'确定',exact:true}).click();await modal.waitFor({state:'hidden'})
   stage=`${item.agg}-calculated`;await computed(grand,item.expected)
   stage=`${item.agg}-undo`;await command('File','undo');assert.equal(await copy(`${q}!${g}${item.offset+6}:${v}${item.offset+6}`),'Tail\t99')
   stage=`${item.agg}-redo`;await command('File','redo');await computed(grand,item.expected)
   await page.waitForFunction(()=>Object.keys(localStorage).some(key=>key.startsWith('native-editor-draft:')&&JSON.parse(localStorage.getItem(key)).operations.filter(op=>op.kind==='applyRowColumnOps').length===3))
   const beforeRefresh=await drafts();stage=`${item.agg}-refresh`;await page.reload();await ready();await computed(grand,item.expected);assert.deepEqual(await drafts(),beforeRefresh)
   if(process.env.SUBTOTAL_SMOKE_STOP_BEFORE_SAVE==='1')throw Error('诊断按要求在保存前停止')
   stage=`${item.agg}-save`;await page.locator('[data-action="save"]').click();await page.waitForFunction(revision=>(document.querySelector('.save-state-label')?.textContent??'').includes(`已保存修订 ${revision}`),item.revision+1,{timeout:60000});assert.equal(routeError,undefined)
   saved=JSON.parse(await readFile(join(checkpoint,`saved-source-${item.revision}.json`),'utf8'));operations=saved.operations
   const [download]=await Promise.all([page.waitForEvent('download'),page.locator('[data-action="xlsx-download"]').click()]);bytes=await readFile(await download.path());assert.equal(sha(bytes),saved.sha256)
   await writeFile(join(checkpoint,`downloaded-${item.revision+1}.xlsx`),bytes)
  }
  assert.equal(operations.filter(op=>op.kind==='applyRowColumnOps').length,3)
  const independent=JSON.parse(python({mode:'inspect',bytes:bytes.toString('base64'),...item}));stage=`${item.agg}-new-revision`;await open(item.revision+1);await computed(grand,item.expected)
  const response=await page.request.get(`${app}/download/${item.revision+1}.xlsx`);assert.equal(response.status(),200);assert.equal(sha(await response.body()),sha(bytes))
  await page.screenshot({path:join(checkpoint,`${item.agg}-reopened.png`),fullPage:true});results.push({...item,sha256:sha(bytes),operations,independent,computed:true,download:true,newRevisionReopen:true});await writeFile(join(checkpoint,`${item.agg}-result.json`),JSON.stringify(results.at(-1),null,2))
 }
 await Promise.all(assetChecks);assert.deepEqual(errors,[]);const summary={ok:true,checkpoint,browserVersion:browser.version(),saveCount,resourceCount:assets.size,results,assets:Object.fromEntries(assets),errors};await writeFile(join(checkpoint,'summary.json'),JSON.stringify(summary,null,2));console.log(JSON.stringify({ok:true,checkpoint,cases:results.length,assets:assets.size}))
}catch(error){if(page){await writeFile(join(checkpoint,'failure.html'),await page.content()).catch(()=>{});await page.screenshot({path:join(checkpoint,'failure.png'),fullPage:true}).catch(()=>{})}console.error(JSON.stringify({stage,checkpoint}));throw error}
finally{await browser?.close();preview?.kill();await new Promise(resolve=>http.close(resolve))}
