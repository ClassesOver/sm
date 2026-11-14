// 原生 XLSX 产品 UI/PNG 导入/撤销重做/CLI 持久化；HTTP授权和修订仓储为明确夹具。
import assert from 'node:assert/strict'
import {spawn,spawnSync} from 'node:child_process'
import {createHash} from 'node:crypto'
import {mkdir,writeFile,symlink} from 'node:fs/promises'
import {join} from 'node:path'
import {fileURLToPath} from 'node:url'
import {setTimeout as delay} from 'node:timers/promises'
import {chromium} from 'playwright'
const frontend=fileURLToPath(new URL('../',import.meta.url)),repo=fileURLToPath(new URL('../../../../',import.meta.url)),directory=process.env.XLSX_PICTURES_OUTPUT,port=Number(process.env.XLSX_PICTURES_PORT??4517),base='http://127.0.0.1:'+port
assert.ok(directory);await mkdir(directory,{recursive:true})
const engine=join(directory,'engine');await mkdir(engine,{recursive:true});for(const name of ['bridge','packages','node_modules','package.json','tsconfig.json','tsconfig.base.json'])await symlink(join(repo,'smart_reporting/reporting/workbook_engine',name),join(engine,name)).catch(e=>{if(e.code!=='EEXIST')throw e})
function python(payload){const result=spawnSync(join(repo,'.venv/bin/python'),['-c',`
import base64,json,sys,zipfile
from io import BytesIO
from openpyxl import Workbook,load_workbook
from openpyxl.comments import Comment
from openpyxl.drawing.image import Image as XLImage
from openpyxl.chart import BarChart, Reference
from PIL import Image
from smart_reporting.report_editor.native_office import patch_office
from smart_reporting.report_editor.native_xlsx_threads import xlsx_thread_actor
from smart_reporting.report_editor.native_models import NativeScope
actor=xlsx_thread_actor(NativeScope(database='fixture',companyId='fixture',userId='fixture',threadId='fixture'))
p=json.load(sys.stdin)
if p['mode']=='create':
 b=Workbook();b.active.title='Report';b.active['A1']='正文保留';b.active['C3'].comment=Comment('另一批注','作者乙');b.create_sheet('Other')['B2']='=2+3';img=BytesIO();Image.new('RGB',(8,6),(30,90,160)).save(img,format='PNG');img.seek(0);b.active.add_image(XLImage(img),'E6');b.active['A3']=2;b.active['A4']=4;c=BarChart();c.add_data(Reference(b.active,min_col=1,min_row=3,max_row=4));b.active.add_chart(c,'H5');f=BytesIO();b.save(f);print(base64.b64encode(f.getvalue()).decode())
elif p['mode']=='actor':print(json.dumps(actor))
elif p['mode']=='patch':print(base64.b64encode(patch_office('xlsx',base64.b64decode(p['bytes']),p['operations'],thread_actor=actor)).decode())
else:
 import xml.etree.ElementTree as E,hashlib
 data=base64.b64decode(p['bytes']);b=load_workbook(BytesIO(data));z=zipfile.ZipFile(BytesIO(data));ns={'x':'http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing','a':'http://schemas.openxmlformats.org/drawingml/2006/main'};drawings=[n for n in z.namelist() if n.startswith('xl/drawings/drawing') and n.endswith('.xml')];pics=[e for n in drawings for e in E.fromstring(z.read(n)).findall('.//x:pic',ns)];media=[dict(path=n,sha256=hashlib.sha256(z.read(n)).hexdigest(),size=len(z.read(n))) for n in z.namelist() if n.startswith('xl/media/')];print(json.dumps(dict(value=b['Report']['A1'].value,text=b['Report']['C3'].comment.text,other=b['Other']['B2'].value,pictures=len(pics),charts=len(b['Report']._charts),media=media,parts=z.namelist())))
`],{input:JSON.stringify(payload),cwd:repo,env:{...process.env,AGENT_REPORTING_WORKBOOK_ENGINE_DIR:engine},encoding:'utf8'});assert.equal(result.status,0,result.stderr);return result.stdout.trim()}
const actor=JSON.parse(python({mode:'actor'}))
const bytes=Buffer.from(python({mode:'create'}),'base64'),sha=b=>createHash('sha256').update(b).digest('hex'),mediaType='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
await writeFile(join(directory,'source.xlsx'),bytes)
const context={documentId:'xlsx-pictures',format:'xlsx',revision:1,parentRevision:null,scope:{database:'fixture',companyId:'fixture',userId:'fixture',threadId:'fixture'},sourceFile:{path:'source.xlsx',size:bytes.length,sha256:sha(bytes),mediaType},origin:'upload'}
const server=spawn('./node_modules/.bin/vite',[...(process.env.XLSX_PICTURES_VITE_CONFIG?['--config',process.env.XLSX_PICTURES_VITE_CONFIG]:[]),'--host','127.0.0.1','--port',String(port),'--strictPort'],{cwd:frontend,stdio:'pipe'});let log='',browser,page,payload,saved,stage='server';console.log('stage:'+stage);server.stdout.on('data',b=>log+=b);server.stderr.on('data',b=>log+=b)
const errors=[],layout=[],navigations=[]
try{
 for(let n=0;;n++){assert.equal(server.exitCode,null,log);try{if((await fetch(base+'/reports/v1/editor/assets/native.html')).ok)break}catch{}assert(n<120,log);await delay(250)}
 browser=await chromium.launch({headless:true,executablePath:process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE??'/snap/bin/chromium'});page=await browser.newPage({viewport:{width:1440,height:900}});page.on('pageerror',e=>errors.push(e.message));page.on('request',request=>{if(request.isNavigationRequest())navigations.push({url:request.url(),method:request.method(),resourceType:request.resourceType()})})
 await page.route(/\/reports\/v1\/native\/xlsx-pictures\/[12]$/,async route=>{const response=await fetch(base+'/reports/v1/editor/assets/native.html');await route.fulfill({body:await response.text(),contentType:'text/html'})})
 const ready=()=>page.waitForFunction(()=>document.querySelector('#report-editor')?.getAttribute('aria-busy')==='false',null,{timeout:90000})
 const routeRevision=async(revision,file)=>{await page.route(`**/reports/v1/native/xlsx-pictures/${revision}/api/context`,route=>route.fulfill({json:{context:{...context,revision,sourceFile:{...context.sourceFile,size:file.length,sha256:sha(file)}},threadActor:actor,csrfToken:'fixture',capabilities:{xlsx_editor:true},editingEnabled:true}}));await page.route(`**/reports/v1/native/xlsx-pictures/${revision}/api/file`,route=>route.fulfill({contentType:mediaType,body:file}))}
 await routeRevision(1,bytes)
 await page.route('**/reports/v1/native/xlsx-pictures/1/api/save',async route=>{payload=route.request().postDataJSON();saved=Buffer.from(python({mode:'patch',bytes:bytes.toString('base64'),operations:payload.operations}),'base64');await writeFile(join(directory,'saved.xlsx'),saved);await route.fulfill({json:{documentId:'xlsx-pictures',revision:2,parentRevision:1,revisionRegistered:true,artifacts:{xlsx:{downloadUrl:'/xlsx-pictures.xlsx',size:saved.length,sha256:sha(saved)}},editor:null,validation:{ok:false,issues:[{message:'夹具：业务事实未重新验收'}]}}})})
 await page.addInitScript(()=>history.replaceState(null,'','/reports/v1/native/xlsx-pictures/'+(sessionStorage.getItem('picture-revision')??'1')))
 await page.goto(base+'/reports/v1/editor/assets/native.html');await ready()
 const insertTab=()=>page.locator('[data-ribbon-tab=Insert]').click(),command=name=>page.locator(`[data-ribbon-command=${name}]`),dialog=()=>page.locator('.workbook-picture-dialog [role=dialog]')
 const imageCount=()=>page.evaluate(async()=>{const runtime=(await import('/src/workbook-vendor/grid/create-univer.ts'));return document.querySelectorAll('.workbook-picture-dialog').length})
 stage='equation';console.log('stage:'+stage);await insertTab();await command('insert-equation').click();await dialog().getByRole('button',{name:'A = \\pi r^2',exact:true}).click();await dialog().getByRole('button',{name:'插入',exact:true}).click();await dialog().waitFor({state:'detached',timeout:60000})
 stage='icons';console.log('stage:'+stage);await command('insert-icons').click();assert.equal(await dialog().locator('.dialog-tabs button').count(),9);await dialog().getByPlaceholder('搜索图标（英文）').fill('airplane');await dialog().getByRole('radio',{name:'#c00000',exact:true}).click();await dialog().locator('.icons-grid button').first().click();await dialog().waitFor({state:'detached',timeout:60000})
 stage='ordinary';console.log('stage:'+stage);const picker=page.waitForEvent('filechooser');await command('insert-picture').click();await (await picker).setFiles({name:'普通照片.png',mimeType:'image/png',buffer:Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGP4z8AAAAMBAQDJ/pLvAAAAAElFTkSuQmCC','base64')});await page.locator('input[data-workbook-picture]').waitFor({state:'detached',timeout:60000})
 stage='history';console.log('stage:'+stage);await page.locator('[data-ribbon-tab=File]').click();await command('undo').click();await page.waitForTimeout(600);await command('redo').click();await page.waitForTimeout(600)
 stage='layout';console.log('stage:'+stage);await insertTab();await command('insert-equation').click();for(const [width,height] of [[1440,900],[640,360],[390,320]]){await page.setViewportSize({width,height});const geometry=await dialog().evaluate(n=>{const r=n.getBoundingClientRect();return {x:r.x,y:r.y,right:r.right,bottom:r.bottom}});assert.ok(geometry.x>=0&&geometry.y>=0&&geometry.right<=width+1&&geometry.bottom<=height+1,JSON.stringify(geometry));await page.screenshot({path:join(directory,`dialog-${width}x${height}.png`)});layout.push({width,height,geometry})}await dialog().getByRole('button',{name:'取消',exact:true}).click();await page.setViewportSize({width:1440,height:900})
 stage='save';console.log('stage:'+stage);await page.locator('[data-action=save]').click();await page.locator('a[href="/xlsx-pictures.xlsx"]').waitFor({timeout:60000});assert.ok(saved);const actual=JSON.parse(python({mode:'inspect',bytes:saved.toString('base64')}));assert.equal(actual.value,'正文保留');assert.equal(actual.text,'另一批注');assert.equal(actual.other,'=2+3');assert.equal(actual.pictures,4);assert.equal(actual.charts,1);assert.equal(actual.media.length,4);
 stage='reopen';console.log('stage:'+stage);await routeRevision(2,saved);await page.evaluate(()=>sessionStorage.setItem('picture-revision','2'));await page.goto(base+'/reports/v1/editor/assets/native.html');await ready();await page.screenshot({path:join(directory,'reopened.png')});assert.deepEqual(errors,[])
 await writeFile(join(directory,'evidence.json'),JSON.stringify({ok:true,scope:'source-Vite ordinary picture/equation/icon UI, actual native_office→source CLI and independent openpyxl/ZIP; HTTP auth/revision repository mocked; no production download claim',sourceSha256:sha(bytes),outputSha256:sha(saved),payload,actual,layout,errors,navigations},null,2));console.log(JSON.stringify({ok:true,directory,outputSha256:sha(saved),layoutCases:layout.length}))
}catch(error){await page?.screenshot({path:join(directory,'failure.png'),fullPage:true}).catch(()=>{});await writeFile(join(directory,'failure.json'),JSON.stringify({stage,error:String(error),stack:error.stack,errors,payload,navigations,layout},null,2));throw error}
finally{await browser?.close();server.kill();await writeFile(join(directory,'server.log'),log)}
