// 原生 XLSX 产品 UI/PNG 导入/撤销重做/CLI 持久化；HTTP授权和修订仓储为明确夹具。
import assert from 'node:assert/strict'
import {spawn,spawnSync} from 'node:child_process'
import {createHash} from 'node:crypto'
import {mkdir,writeFile,symlink,readFile} from 'node:fs/promises'
import {join} from 'node:path'
import {fileURLToPath} from 'node:url'
import {setTimeout as delay} from 'node:timers/promises'
import {chromium} from 'playwright'
const frontend=fileURLToPath(new URL('../',import.meta.url)),repo=fileURLToPath(new URL('../../../../',import.meta.url)),directory=process.env.XLSX_THREADS_OUTPUT,port=Number(process.env.XLSX_THREADS_PORT??4515),base='http://127.0.0.1:'+port
assert.ok(directory);await mkdir(directory,{recursive:true})
const engine=join(directory,'engine');await mkdir(engine,{recursive:true});for(const name of ['bridge','packages','node_modules','package.json','tsconfig.json','tsconfig.base.json'])await symlink(join(repo,'smart_reporting/reporting/workbook_engine',name),join(engine,name)).catch(e=>{if(e.code!=='EEXIST')throw e})
function python(payload){const result=spawnSync(join(repo,'.venv/bin/python'),['-c',`
import base64,json,sys,zipfile
from io import BytesIO
from openpyxl import Workbook,load_workbook
from openpyxl.comments import Comment
from smart_reporting.report_editor.native_office import patch_office
from smart_reporting.report_editor.native_xlsx_threads import xlsx_thread_actor
from smart_reporting.report_editor.native_models import NativeScope
actor=xlsx_thread_actor(NativeScope(database='fixture',companyId='fixture',userId='fixture',threadId='fixture'))
p=json.load(sys.stdin)
if p['mode']=='create':
 b=Workbook();b.active.title='Report';b.active['A1']='正文保留';b.active['C3'].comment=Comment('另一批注','作者乙');b.create_sheet('Other')['B2']='=2+3';f=BytesIO();b.save(f);print(base64.b64encode(f.getvalue()).decode())
elif p['mode']=='actor':print(json.dumps(actor))
elif p['mode']=='readonly':
 data=BytesIO();source=zipfile.ZipFile(BytesIO(base64.b64decode(p['bytes'])))
 with zipfile.ZipFile(data,'w') as out:
  for name in source.namelist():
   value=source.read(name)
   if name.startswith('xl/threadedComments/') and name.endswith('.xml'):value=value.replace(b'2018/threadedcomments',b'2018/foreign')
   out.writestr(name,value)
 print(base64.b64encode(data.getvalue()).decode())
elif p['mode']=='patch':print(base64.b64encode(patch_office('xlsx',base64.b64decode(p['bytes']),p['operations'],thread_actor=actor)).decode())
else:
 import xml.etree.ElementTree as E
 data=base64.b64decode(p['bytes']);b=load_workbook(BytesIO(data));z=zipfile.ZipFile(BytesIO(data));ns={'t':'http://schemas.microsoft.com/office/spreadsheetml/2018/threadedcomments'};parts=[n for n in z.namelist() if n.startswith('xl/threadedComments/') and n.endswith('.xml')];entries=[dict(e.attrib,text=e.find('t:text',ns).text) for part in parts for e in E.fromstring(z.read(part))];print(json.dumps(dict(value=b['Report']['A1'].value,text=b['Report']['C3'].comment.text,author=b['Report']['C3'].comment.author,other=b['Other']['B2'].value,entries=entries,persons=z.read('xl/persons/person.xml').decode(),parts=parts)))
`],{input:JSON.stringify(payload),cwd:repo,env:{...process.env,AGENT_REPORTING_WORKBOOK_ENGINE_DIR:engine},encoding:'utf8'});assert.equal(result.status,0,result.stderr);return result.stdout.trim()}
const actor=JSON.parse(python({mode:'actor'}))
const bytes=await readFile(join(process.env.XLSX_THREADS_INPUT,'saved.xlsx')),sha=b=>createHash('sha256').update(b).digest('hex'),mediaType='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
await writeFile(join(directory,'source.xlsx'),bytes)
const context={documentId:'xlsx-threads',format:'xlsx',revision:1,parentRevision:null,scope:{database:'fixture',companyId:'fixture',userId:'fixture',threadId:'fixture'},sourceFile:{path:'source.xlsx',size:bytes.length,sha256:sha(bytes),mediaType},origin:'upload'}
const server=spawn('./node_modules/.bin/vite',['--host','127.0.0.1','--port',String(port),'--strictPort'],{cwd:frontend,stdio:'pipe'});let log='',browser,page,payload,saved,stage='server';server.stdout.on('data',b=>log+=b);server.stderr.on('data',b=>log+=b)
const errors=[],layout=[],navigations=[]
try{
 for(let n=0;;n++){assert.equal(server.exitCode,null,log);try{if((await fetch(base+'/reports/v1/editor/assets/native.html')).ok)break}catch{}assert(n<120,log);await delay(250)}
 browser=await chromium.launch({headless:true,executablePath:process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE??'/snap/bin/chromium'});page=await browser.newPage({viewport:{width:1440,height:900}});page.on('pageerror',e=>errors.push(e.message));page.on('request',request=>{if(request.isNavigationRequest())navigations.push({url:request.url(),method:request.method(),resourceType:request.resourceType()})})
 const ready=()=>page.waitForFunction(()=>document.querySelector('#report-editor')?.getAttribute('aria-busy')==='false',null,{timeout:90000})
 const routeRevision=async(revision,file)=>{await page.route(`**/reports/v1/native/xlsx-threads/${revision}/api/context`,route=>route.fulfill({json:{context:{...context,revision,sourceFile:{...context.sourceFile,size:file.length,sha256:sha(file)}},threadActor:actor,csrfToken:'fixture',capabilities:{xlsx_editor:true},editingEnabled:true}}));await page.route(`**/reports/v1/native/xlsx-threads/${revision}/api/file`,route=>route.fulfill({contentType:mediaType,body:file}))}
 await routeRevision(1,bytes)
 await page.route('**/reports/v1/native/xlsx-threads/1/api/save',async route=>{payload=route.request().postDataJSON();saved=Buffer.from(python({mode:'patch',bytes:bytes.toString('base64'),operations:payload.operations}),'base64');await writeFile(join(directory,'saved.xlsx'),saved);await route.fulfill({json:{documentId:'xlsx-threads',revision:2,parentRevision:1,revisionRegistered:true,artifacts:{xlsx:{downloadUrl:'/xlsx-threads.xlsx',size:saved.length,sha256:sha(saved)}},editor:null,validation:{ok:false,issues:[{message:'夹具：业务事实未重新验收'}]}}})})
 await page.addInitScript(()=>history.replaceState(null,'','/reports/v1/native/xlsx-threads/'+(sessionStorage.getItem('note-revision')??'1')))
 await page.goto(base+'/reports/v1/editor/assets/native.html');await ready()
 stage='reveal';await page.getByRole('button',{name:'显示批注',exact:true}).click();await page.locator('.tc-text').filter({hasText:'根帖已编辑 <&'}).waitFor();await page.locator('.tc-cell').getByText('A1',{exact:true}).click().catch(async()=>page.getByRole('button',{name:'A1',exact:true}).click());await page.locator('.threaded-comments-pane .tc-close').click();const frame=await page.locator('.workbook-grid-frame').boundingBox();const overlay=await page.locator('.workbook-threads-host').boundingBox();assert.equal(Math.round(frame.height),Math.round(overlay.height));await page.mouse.move(85,272);await page.locator('.thread-hover-card').waitFor();await page.locator('.thread-hover-card').getByText('根帖已编辑 <&',{exact:true}).waitFor();await page.screenshot({path:join(directory,'reveal.png')})
 stage='readonly';const preserved=Buffer.from(python({mode:'readonly',bytes:bytes.toString('base64')}),'base64');await routeRevision(3,preserved);await page.evaluate(()=>sessionStorage.setItem('note-revision','3'));await page.goto(base+'/reports/v1/editor/assets/native.html');await ready();await page.getByRole('button',{name:'显示批注',exact:true}).click();await page.getByText(/此来源仅可保留：.*命名空间/).waitFor();assert.equal(await page.locator('.threaded-comments-pane button').filter({hasText:'解决'}).count(),0);await page.locator('.threaded-comments-pane .tc-close').click();await page.getByRole('button',{name:'新建批注',exact:true}).click();await page.getByText(/线程批注未应用：.*命名空间/).waitFor();await page.screenshot({path:join(directory,'readonly.png')});assert.deepEqual(errors,[]);await writeFile(join(directory,'evidence.json'),JSON.stringify({ok:true,scope:'narrow source UI reveal and unsupported namespace readonly; no repeat save',errors,navigations},null,2));console.log(JSON.stringify({ok:true,directory}))
}catch(error){await page?.screenshot({path:join(directory,'failure.png'),fullPage:true}).catch(()=>{});await writeFile(join(directory,'failure.json'),JSON.stringify({stage,error:String(error),stack:error.stack,errors,payload,navigations,layout},null,2));throw error}
finally{await browser?.close();server.kill();await writeFile(join(directory,'server.log'),log)}
