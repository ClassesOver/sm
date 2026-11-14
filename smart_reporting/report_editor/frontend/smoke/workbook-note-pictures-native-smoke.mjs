// 原生 XLSX 产品 UI/PNG 导入/撤销重做/CLI 持久化；HTTP授权和修订仓储为明确夹具。
import assert from 'node:assert/strict'
import {spawn,spawnSync} from 'node:child_process'
import {createHash} from 'node:crypto'
import {mkdir,writeFile,symlink} from 'node:fs/promises'
import {join} from 'node:path'
import {fileURLToPath} from 'node:url'
import {setTimeout as delay} from 'node:timers/promises'
import {chromium} from 'playwright'
const frontend=fileURLToPath(new URL('../',import.meta.url)),repo=fileURLToPath(new URL('../../../../',import.meta.url)),directory=process.env.NOTE_PICTURES_OUTPUT,port=Number(process.env.NOTE_PICTURES_PORT??4504),base='http://127.0.0.1:'+port
assert.ok(directory);await mkdir(directory)
const engine=join(directory,'engine');await mkdir(engine);for(const name of ['bridge','packages','node_modules','package.json','tsconfig.json','tsconfig.base.json'])await symlink(join(repo,'smart_reporting/reporting/workbook_engine',name),join(engine,name))
function python(payload){const result=spawnSync(join(repo,'.venv/bin/python'),['-c',`
import base64,json,sys,zipfile
from io import BytesIO
from openpyxl import Workbook,load_workbook
from openpyxl.comments import Comment
from smart_reporting.report_editor.native_office import patch_office
p=json.load(sys.stdin)
if p['mode']=='create':
 b=Workbook();b.active.title='Report';b.active['A1']='正文保留';b.active['A1'].comment=Comment('保留批注文字','作者甲');b.active['C3'].comment=Comment('另一批注','作者乙');b.create_sheet('Other')['B2']='=2+3';f=BytesIO();b.save(f);print(base64.b64encode(f.getvalue()).decode())
elif p['mode']=='patch':print(base64.b64encode(patch_office('xlsx',base64.b64decode(p['bytes']),p['operations'])).decode())
else:
 data=base64.b64decode(p['bytes']);b=load_workbook(BytesIO(data));z=zipfile.ZipFile(BytesIO(data));print(json.dumps(dict(value=b['Report']['A1'].value,text=b['Report']['A1'].comment.text,author=b['Report']['A1'].comment.author,other=b['Other']['B2'].value,media=[n for n in z.namelist() if n.startswith('xl/media/')],vml=[z.read(n).decode() for n in z.namelist() if n.endswith('.vml')])))
`],{input:JSON.stringify(payload),cwd:repo,env:{...process.env,AGENT_REPORTING_WORKBOOK_ENGINE_DIR:engine},encoding:'utf8'});assert.equal(result.status,0,result.stderr);return result.stdout.trim()}
const bytes=Buffer.from(python({mode:'create'}),'base64'),sha=b=>createHash('sha256').update(b).digest('hex'),mediaType='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
await writeFile(join(directory,'source.xlsx'),bytes)
const context={documentId:'note-pictures',format:'xlsx',revision:1,parentRevision:null,scope:{database:'fixture',companyId:'fixture',userId:'fixture',threadId:'fixture'},sourceFile:{path:'source.xlsx',size:bytes.length,sha256:sha(bytes),mediaType},origin:'upload'}
const server=spawn('./node_modules/.bin/vite',['--host','127.0.0.1','--port',String(port),'--strictPort'],{cwd:frontend,stdio:'pipe'});let log='',browser,page,payload,saved,stage='server';server.stdout.on('data',b=>log+=b);server.stderr.on('data',b=>log+=b)
const errors=[],layout=[],navigations=[]
try{
 for(let n=0;;n++){assert.equal(server.exitCode,null,log);try{if((await fetch(base+'/reports/v1/editor/assets/native.html')).ok)break}catch{}assert(n<120,log);await delay(250)}
 browser=await chromium.launch({headless:true,executablePath:process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE??'/snap/bin/chromium'});page=await browser.newPage({viewport:{width:1440,height:900}});page.on('pageerror',e=>errors.push(e.message));page.on('request',request=>{if(request.isNavigationRequest())navigations.push({url:request.url(),method:request.method(),resourceType:request.resourceType()})})
 const ready=()=>page.waitForFunction(()=>document.querySelector('#report-editor')?.getAttribute('aria-busy')==='false',null,{timeout:90000})
 const routeRevision=async(revision,file)=>{await page.route(`**/reports/v1/native/note-pictures/${revision}/api/context`,route=>route.fulfill({json:{context:{...context,revision,sourceFile:{...context.sourceFile,size:file.length,sha256:sha(file)}},csrfToken:'fixture',capabilities:{xlsx_editor:true},editingEnabled:true}}));await page.route(`**/reports/v1/native/note-pictures/${revision}/api/file`,route=>route.fulfill({contentType:mediaType,body:file}))}
 await routeRevision(1,bytes)
 await page.route('**/reports/v1/native/note-pictures/1/api/save',async route=>{payload=route.request().postDataJSON();saved=Buffer.from(python({mode:'patch',bytes:bytes.toString('base64'),operations:payload.operations}),'base64');await writeFile(join(directory,'saved.xlsx'),saved);await route.fulfill({json:{documentId:'note-pictures',revision:2,parentRevision:1,revisionRegistered:true,artifacts:{xlsx:{downloadUrl:'/note-pictures.xlsx',size:saved.length,sha256:sha(saved)}},editor:{openUrl:'/reports/v1/native/note-pictures/2'},validation:{ok:false,issues:[{message:'夹具：业务事实未重新验收'}]}}})})
 await page.addInitScript(()=>history.replaceState(null,'','/reports/v1/native/note-pictures/'+(sessionStorage.getItem('note-revision')??'1')))
 await page.goto(base+'/reports/v1/editor/assets/native.html');await ready()
 stage='insert';await page.locator('.workbook-note-pictures-toggle').click();await page.locator('.note-pictures-pane').waitFor()
 const png=await page.evaluate(()=>{const c=document.createElement('canvas');c.width=80;c.height=30;const x=c.getContext('2d');x.fillStyle='#115588';x.fillRect(0,0,80,30);return c.toDataURL('image/png').split(',')[1]})
 const choosing=page.waitForEvent('filechooser');await page.locator('[data-note-picture-insert]').click();const chooser=await choosing;await chooser.setFiles({name:'note.png',mimeType:'image/png',buffer:Buffer.from(png,'base64')});await page.locator('.note-pictures-pane .np-card img').waitFor({timeout:60000});assert.equal(await page.locator('.np-card').count(),1)
 const draft=()=>page.evaluate(()=>Object.entries(localStorage).filter(([k])=>k.startsWith('native-editor-draft:')).flatMap(([,v])=>JSON.parse(v).operations))
 const applied=await draft();assert.ok(applied.some(o=>o.kind==='setNotePicture'&&o.picture))
 stage='layout';for(const [width,height] of [[1440,900],[640,360],[390,320]]){await page.setViewportSize({width,height});const geometry=await page.locator('.note-pictures-pane').evaluate(n=>{const r=n.getBoundingClientRect();return {x:r.x,y:r.y,right:r.right,bottom:r.bottom,background:getComputedStyle(n).backgroundColor}});assert.ok(geometry.x>=0&&geometry.y>=0&&geometry.right<=width+1&&geometry.bottom<=height+1,JSON.stringify(geometry));await page.locator('[data-note-pictures-close]').click({trial:true});await page.locator('[data-note-picture-insert]').scrollIntoViewIfNeeded();await page.locator('[data-note-picture-insert]').click({trial:true});await page.locator('[data-note-picture-remove]').scrollIntoViewIfNeeded();await page.locator('[data-note-picture-remove]').click({trial:true});await page.locator('[data-note-pictures-close]').focus();await page.screenshot({path:join(directory,`pane-${width}x${height}.png`)});layout.push({width,height,geometry})}
 await page.setViewportSize({width:1440,height:900});await page.locator('[data-note-pictures-close]').click();stage='history';await page.locator('[data-ribbon-tab=File]').click();await page.locator('[data-ribbon-command=undo]').click();await page.locator('.workbook-note-pictures-toggle').click();await page.getByText('此工作簿没有包含图片的批注',{exact:true}).waitFor();await page.locator('[data-note-pictures-close]').click();await page.locator('[data-ribbon-command=redo]').click();await page.locator('.workbook-note-pictures-toggle').click();await page.locator('.np-card img').waitFor();await page.locator('[data-note-pictures-close]').click()
 stage='save';await page.locator('[data-action=save]').click();await page.locator('a[href="/note-pictures.xlsx"]').waitFor({timeout:60000});await writeFile(join(directory,'saved-ui.html'),await page.content());assert.ok(saved);const actual=JSON.parse(python({mode:'inspect',bytes:saved.toString('base64')}));assert.equal(actual.value,'正文保留');assert.equal(actual.text,'保留批注文字');assert.equal(actual.author,'作者甲');assert.equal(actual.other,'=2+3');assert.equal(actual.media.length,1);assert.ok(actual.vml.some(v=>v.includes('notePicture')))
 stage='reopen';await routeRevision(2,saved);await page.evaluate(()=>sessionStorage.setItem('note-revision','2'));await page.goto(base+'/reports/v1/editor/assets/native.html');await ready();await page.locator('.workbook-note-pictures-toggle').click();await page.locator('.np-card img').waitFor();assert.equal(await page.locator('.np-card').count(),1);assert.deepEqual(errors,[])
 await writeFile(join(directory,'evidence.json'),JSON.stringify({ok:true,scope:'source-Vite native main UI, actual native_office→source CLI and independent openpyxl/ZIP; HTTP auth/revision repository mocked; no production download claim',sourceSha256:sha(bytes),outputSha256:sha(saved),payload,actual,layout,errors,navigations},null,2));console.log(JSON.stringify({ok:true,directory,outputSha256:sha(saved),layoutCases:layout.length}))
}catch(error){await page?.screenshot({path:join(directory,'failure.png'),fullPage:true}).catch(()=>{});await writeFile(join(directory,'failure.json'),JSON.stringify({stage,error:String(error),stack:error.stack,errors,payload,navigations,layout},null,2));throw error}
finally{await browser?.close();server.kill();await writeFile(join(directory,'server.log'),log)}
