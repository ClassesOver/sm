// 原生 XLSX 产品 UI/PNG 导入/撤销重做/CLI 持久化；HTTP授权和修订仓储为明确夹具。
import assert from 'node:assert/strict'
import {spawn,spawnSync} from 'node:child_process'
import {createHash} from 'node:crypto'
import {mkdir,writeFile,symlink} from 'node:fs/promises'
import {join} from 'node:path'
import {fileURLToPath} from 'node:url'
import {setTimeout as delay} from 'node:timers/promises'
import {chromium} from 'playwright'
const frontend=fileURLToPath(new URL('../',import.meta.url)),repo=fileURLToPath(new URL('../../../../',import.meta.url)),directory=process.env.XLSX_THREADS_OUTPUT,port=Number(process.env.XLSX_THREADS_PORT??4514),base='http://127.0.0.1:'+port
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
elif p['mode']=='patch':print(base64.b64encode(patch_office('xlsx',base64.b64decode(p['bytes']),p['operations'],thread_actor=actor)).decode())
else:
 import xml.etree.ElementTree as E
 data=base64.b64decode(p['bytes']);b=load_workbook(BytesIO(data));z=zipfile.ZipFile(BytesIO(data));ns={'t':'http://schemas.microsoft.com/office/spreadsheetml/2018/threadedcomments'};parts=[n for n in z.namelist() if n.startswith('xl/threadedComments/') and n.endswith('.xml')];entries=[dict(e.attrib,text=e.find('t:text',ns).text) for part in parts for e in E.fromstring(z.read(part))];print(json.dumps(dict(value=b['Report']['A1'].value,text=b['Report']['C3'].comment.text,author=b['Report']['C3'].comment.author,other=b['Other']['B2'].value,entries=entries,persons=z.read('xl/persons/person.xml').decode(),parts=parts)))
`],{input:JSON.stringify(payload),cwd:repo,env:{...process.env,AGENT_REPORTING_WORKBOOK_ENGINE_DIR:engine},encoding:'utf8'});assert.equal(result.status,0,result.stderr);return result.stdout.trim()}
const actor=JSON.parse(python({mode:'actor'}))
const bytes=Buffer.from(python({mode:'create'}),'base64'),sha=b=>createHash('sha256').update(b).digest('hex'),mediaType='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
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
 stage='root';await page.getByRole('button',{name:'新建批注',exact:true}).click();await page.getByPlaceholder('开始对话').fill('真实线程根帖 <&');await page.getByRole('button',{name:'发布',exact:true}).click();await page.locator('.tc-text').filter({hasText:'真实线程根帖 <&'}).waitFor({timeout:60000})
 const pane=()=>page.locator('.threaded-comments-pane'),button=(name)=>pane().getByRole('button',{name,exact:true}),waitIdle=()=>page.waitForFunction(()=>{const b=[...document.querySelectorAll('.threaded-comments-pane button')].find(n=>n.textContent==='解决'||n.textContent==='重新打开');return b&&!b.disabled},{},{timeout:60000})
 await waitIdle();stage='reply';await page.getByPlaceholder('回复…').fill('第一条回复');await button('回复').click();await page.locator('.tc-text').filter({hasText:'第一条回复'}).waitFor();await waitIdle()
 stage='edit';await button('编辑').first().click();await pane().locator('textarea').first().fill('根帖已编辑 <&');await button('保存').click();await page.locator('.tc-text').filter({hasText:'根帖已编辑 <&'}).waitFor();await waitIdle();await button('编辑').nth(1).click();await pane().locator('textarea').first().fill('回复已编辑');await button('保存').click();await page.locator('.tc-text').filter({hasText:'回复已编辑'}).waitFor();await waitIdle()
 stage='delete-reply';await button('删除').nth(1).click();await page.locator('.tc-text').filter({hasText:'回复已编辑'}).waitFor({state:'detached'});await waitIdle();await page.getByPlaceholder('回复…').fill('最终保留回复');await button('回复').click();await page.locator('.tc-text').filter({hasText:'最终保留回复'}).waitFor();await waitIdle()
 stage='resolve';await button('解决').click();await pane().locator('.tc-badge').waitFor();await waitIdle();assert.equal(await page.getByPlaceholder('回复…').count(),0);await button('重新打开').click();await page.getByPlaceholder('回复…').waitFor();await waitIdle()
 stage='layout';for(const [width,height] of [[1440,900],[640,360],[390,320]]){await page.setViewportSize({width,height});const geometry=await pane().evaluate(n=>{const r=n.getBoundingClientRect();return {x:r.x,y:r.y,right:r.right,bottom:r.bottom,background:getComputedStyle(n).backgroundColor}});assert.ok(geometry.x>=0&&geometry.y>=0&&geometry.right<=width+1&&geometry.bottom<=height+1,JSON.stringify(geometry));await pane().locator('.tc-close').click({trial:true});await button('删除会话').scrollIntoViewIfNeeded();await button('删除会话').click({trial:true});await page.screenshot({path:join(directory,`pane-${width}x${height}.png`)});layout.push({width,height,geometry})}
 await page.setViewportSize({width:1440,height:900});stage='history';await button('删除会话').click();await pane().locator('.tc-empty').waitFor();await pane().locator('.tc-close').click();await page.locator('[data-ribbon-tab=File]').click();await page.locator('[data-ribbon-command=undo]').click();await page.getByRole('button',{name:'显示批注',exact:true}).click();await page.locator('.tc-text').filter({hasText:'根帖已编辑 <&'}).waitFor();await pane().locator('.tc-close').click();await page.locator('[data-ribbon-command=redo]').click();await page.getByRole('button',{name:'显示批注',exact:true}).click();await pane().locator('.tc-empty').waitFor();await pane().locator('.tc-close').click();await page.locator('[data-ribbon-command=undo]').click()
 stage='save';await page.locator('[data-action=save]').click();await page.locator('a[href="/xlsx-threads.xlsx"]').waitFor({timeout:60000});assert.ok(saved);const actual=JSON.parse(python({mode:'inspect',bytes:saved.toString('base64')}));assert.equal(actual.value,'正文保留');assert.equal(actual.text,'另一批注');assert.equal(actual.author,'作者乙');assert.equal(actual.other,'=2+3');assert.equal(actual.entries.length,2);assert.equal(actual.entries[0].text,'根帖已编辑 <&');assert.equal(actual.entries[1].text,'最终保留回复');assert.equal(actual.entries[1].parentId,actual.entries[0].id);assert.equal(actual.entries[0].personId,actor.personId);assert.ok(actual.persons.includes('fixture'))
 stage='reopen';await routeRevision(2,saved);await page.evaluate(()=>sessionStorage.setItem('note-revision','2'));await page.goto(base+'/reports/v1/editor/assets/native.html');await ready();await page.getByRole('button',{name:'显示批注',exact:true}).click();await page.locator('.tc-text').filter({hasText:'根帖已编辑 <&'}).waitFor();await page.locator('.tc-text').filter({hasText:'最终保留回复'}).waitFor();assert.deepEqual(errors,[])
 await writeFile(join(directory,'evidence.json'),JSON.stringify({ok:true,scope:'source-Vite native main UI, actual native_office→source CLI and independent openpyxl/ZIP; HTTP auth/revision repository mocked; no production download claim',sourceSha256:sha(bytes),outputSha256:sha(saved),payload,actual,layout,errors,navigations},null,2));console.log(JSON.stringify({ok:true,directory,outputSha256:sha(saved),layoutCases:layout.length}))
}catch(error){await page?.screenshot({path:join(directory,'failure.png'),fullPage:true}).catch(()=>{});await writeFile(join(directory,'failure.json'),JSON.stringify({stage,error:String(error),stack:error.stack,errors,payload,navigations,layout},null,2));throw error}
finally{await browser?.close();server.kill();await writeFile(join(directory,'server.log'),log)}
