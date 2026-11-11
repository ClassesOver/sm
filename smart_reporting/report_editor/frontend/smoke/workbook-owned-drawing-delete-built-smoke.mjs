import assert from 'node:assert/strict'
import { spawn, spawnSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import { readFileSync } from 'node:fs'
import { setTimeout as delay } from 'node:timers/promises'
import { chromium } from 'playwright'
const frontend=process.cwd(), repo=new URL('../../../',`file://${frontend}/`).pathname,base='http://127.0.0.1:4234',mode=process.env.OWNED_DRAWING_MODE??'exclusive',allow=mode!=='shared-drawing'
function python(payload){const r=spawnSync(`${repo}/.venv/bin/python`,['-c',`
import json,sys,base64,posixpath
from io import BytesIO
from zipfile import ZipFile,ZIP_DEFLATED
from xml.etree import ElementTree as ET
from openpyxl import Workbook,load_workbook
from openpyxl.chart import BarChart,Reference
from openpyxl.drawing.image import Image
from smart_reporting.report_editor.native_office import patch_office
p=json.load(sys.stdin)
if p['mode']=='create':
 b=Workbook();s=b.active;s.title='Source';other=b.create_sheet('Other')
 for i in range(1,6):s.cell(i,1,i);other.cell(i,2,i)
 chart=BarChart();chart.add_data(Reference(s,min_col=1,min_row=1,max_row=5));s.add_chart(chart,'D2')
 png=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aV1cAAAAASUVORK5CYII=');s.add_image(Image(BytesIO(png)),'J2')
 if p['variant']=='shared-image':other.add_image(Image(BytesIO(png)),'D2')
 f=BytesIO();b.save(f);before=ZipFile(BytesIO(f.getvalue()));out=BytesIO()
 with ZipFile(out,'w',ZIP_DEFLATED) as target:
  for entry in before.infolist():
   if p['variant']=='shared-image' and entry.filename=='xl/media/image2.png':continue
   data=before.read(entry.filename)
   if p['variant']=='shared-image' and entry.filename=='xl/drawings/_rels/drawing2.xml.rels':data=data.replace(b'/xl/media/image2.png',b'/xl/media/image1.png')
   if p['variant']=='shared-drawing' and entry.filename=='xl/worksheets/sheet2.xml':data=data.replace(b'</worksheet>',b'<drawing xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" r:id="rId1"/></worksheet>')
   target.writestr(entry,data)
  target.writestr('customXml/foreign-owned-probe.xml','<foreign xmlns="urn:owned-delete-probe">外来独立内容</foreign>')
  if p['variant']=='shared-drawing':target.writestr('xl/worksheets/_rels/sheet2.xml.rels','<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/drawing" Target="/xl/drawings/drawing1.xml"/></Relationships>')
 print(base64.b64encode(out.getvalue()).decode())
elif p['mode']=='patch':print(base64.b64encode(patch_office('xlsx',base64.b64decode(p['bytes']),p['operations'])).decode())
else:
 raw=base64.b64decode(p['bytes']);before=ZipFile(BytesIO(base64.b64decode(p['original'])));after=ZipFile(BytesIO(raw));b=load_workbook(BytesIO(raw));paths=set(after.namelist());dangling=[]
 for path in paths:
  if not path.endswith('.rels'):continue
  owner=path.replace('/_rels/','/').removesuffix('.rels') if path!='_rels/.rels' else ''
  for rel in ET.fromstring(after.read(path)):
   if rel.attrib.get('TargetMode')=='External':continue
   target=rel.attrib['Target'].split('#')[0];resolved=posixpath.normpath(target.lstrip('/') if target.startswith('/') else posixpath.join(posixpath.dirname(owner),target))
   if resolved not in paths:dangling.append([path,resolved])
 overrides=[e.attrib['PartName'].lstrip('/') for e in ET.fromstring(after.read('[Content_Types].xml')) if e.tag.endswith('Override')];bad_types=[path for path in overrides if path not in paths]
 kept=['xl/worksheets/sheet2.xml','xl/styles.xml']+(['customXml/foreign-owned-probe.xml'] if 'customXml/foreign-owned-probe.xml' in before.namelist() else [])+(['xl/media/image1.png','xl/drawings/drawing2.xml','xl/drawings/_rels/drawing2.xml.rels','xl/worksheets/_rels/sheet2.xml.rels'] if p['variant']=='shared-image' else [])
 print(json.dumps({'sheetNames':b.sheetnames,'values':[b['Other'].cell(i,2).value for i in range(1,6)],'dangling':dangling,'badOverrides':bad_types,'preserved':{path:before.read(path)==after.read(path) for path in kept},'ownedPartsRemaining':[path for path in ['xl/drawings/drawing1.xml','xl/drawings/_rels/drawing1.xml.rels','xl/charts/chart1.xml'] if path in paths],'mediaPresent':'xl/media/image1.png' in paths}))
`],{input:JSON.stringify(payload),encoding:'utf8',cwd:repo});assert.equal(r.status,0,r.stderr);return r.stdout.trim()}

const bytes=Buffer.from(python({mode:'create',variant:mode}),'base64'),media='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',context={documentId:'cf-probe',format:'xlsx',revision:1,parentRevision:null,scope:{database:'f',companyId:'f',userId:'f',threadId:'f'},sourceFile:{path:'cf.xlsx',size:bytes.length,sha256:createHash('sha256').update(bytes).digest('hex'),mediaType:media},origin:'upload'}
const server=spawn('./node_modules/.bin/vite',['preview','--host','127.0.0.1','--port','4234','--strictPort'],{cwd:frontend,stdio:'ignore'})
let browser,saved,payload
try{
 for(let i=0;i<120;i++){try{if((await fetch(`${base}/reports/v1/editor/assets/native.html`)).ok)break}catch{}await delay(250)}
 browser=await chromium.launch({headless:true});const page=await browser.newPage({viewport:{width:1500,height:1100}}),errors=[],scriptProof=[]
 page.on('pageerror',e=>{errors.push(e.message);console.log(e.stack)})
 page.on('response',response=>{const url=new URL(response.url());if(url.pathname.startsWith('/reports/v1/editor/assets/')&&url.pathname.endsWith('.js'))scriptProof.push((async()=>{assert.equal(response.status(),200);const body=await response.body(),path=`../static/${url.pathname.slice('/reports/v1/editor/assets/'.length)}`;assert.equal(createHash('sha256').update(body).digest('hex'),createHash('sha256').update(readFileSync(path)).digest('hex'));return url.pathname})())})
 await page.route('**/reports/v1/native/cf-probe/1/api/context',r=>r.fulfill({json:{context,csrfToken:'csrf',capabilities:{xlsx_editor:true},editingEnabled:true}}))
 await page.route('**/reports/v1/native/cf-probe/1/api/file',r=>r.fulfill({body:bytes,contentType:media}))
 await page.route('**/reports/v1/native/cf-probe/1/api/save',async r=>{payload=r.request().postDataJSON();saved=Buffer.from(python({mode:'patch',bytes:bytes.toString('base64'),operations:payload.operations}),'base64');await r.fulfill({json:{documentId:'cf-probe',revision:2,parentRevision:1,revisionRegistered:true,artifacts:{xlsx:{downloadUrl:'/cf.xlsx'}},editor:{openUrl:'/reports/v1/native/cf-probe/2'},validation:{issues:[]}}})})
 await page.route(/\/reports\/v1\/native\/cf-probe\/[12]$/,async r=>r.fulfill({response:await r.fetch({url:`${base}/reports/v1/editor/assets/native.html`})}))
 await page.addInitScript(()=>history.replaceState(null,'','/reports/v1/native/cf-probe/1'))
 await page.goto(`${base}/reports/v1/editor/assets/native.html`);await page.waitForFunction(()=>document.querySelector('#report-editor')?.getAttribute('aria-busy')==='false',null,{timeout:60000}).catch(async error=>{console.log(JSON.stringify({phase:'chart-load-failure',body:(await page.locator('body').innerText()).slice(-4000)}));throw error});await page.locator('[data-ribbon-tab="Home"]').waitFor()
 await page.waitForTimeout(500)
 const beforeDraft=await page.evaluate(()=>Object.fromEntries(Object.entries(localStorage))),beforeSaveLabel=await page.locator('.save-state-label').textContent()
 const tab=name=>page.locator('[data-u-comp="slide-tab-item"]').filter({hasText:name})
 const history=async action=>{await page.locator('[data-ribbon-tab="File"]').click();await page.locator(`[data-ribbon-command="${action}"]`).click()}
 const remove=async()=>{await tab('Source').click({button:'right'});await page.getByText('删除',{exact:true}).last().click();await page.getByRole('button',{name:'确定',exact:true}).click()}
 await remove()
 if(!allow){await page.getByText(/工作表 "Other" 的图表 .* 仍引用 "Source"，已拒绝删除。/).waitFor();await tab('Source').waitFor();await history('undo');await tab('Source').waitFor();await history('redo');await tab('Source').waitFor();assert.deepEqual(await page.evaluate(()=>Object.fromEntries(Object.entries(localStorage))),beforeDraft);assert.equal(await page.locator('.save-state-label').textContent(),beforeSaveLabel);assert.equal(saved,undefined)}
 else {await tab('Source').waitFor({state:'detached'});await history('undo');await tab('Source').waitFor();await history('redo');await tab('Source').waitFor({state:'detached'})
 {  await page.waitForFunction(()=>Object.keys(localStorage).filter(key=>key.startsWith('native-editor-draft:')).some(key=>{try{return JSON.parse(localStorage.getItem(key)).operations.some(op=>op.kind==='applySheetEdits'&&op.plan.removals.length)}catch{return false}}),null,{timeout:30000})
  await page.reload();await page.waitForFunction(()=>document.querySelector('#report-editor')?.getAttribute('aria-busy')==='false',null,{timeout:60000});await tab('Other').waitFor();assert.equal(await tab('Source').count(),0)
  await page.locator('[data-action="save"]').click();await page.waitForFunction(()=>document.querySelector('.save-state-label')?.textContent==='已保存修订 2',null,{timeout:60000})
  const actual=JSON.parse(python({mode:'inspect',bytes:saved.toString('base64'),original:bytes.toString('base64'),variant:mode}));assert.deepEqual(actual.sheetNames,['Other']);assert.deepEqual(actual.dangling,[]);assert.deepEqual(actual.badOverrides,[]);assert.deepEqual(actual.ownedPartsRemaining,[]);assert.equal(actual.mediaPresent,mode==='shared-image');assert(Object.values(actual.preserved).every(Boolean));assert.deepEqual(actual.values,[1,2,3,4,5]);assert.deepEqual(payload.operations,[{kind:'applySheetEdits',plan:{renames:[],additions:[],removals:['Source'],order:['Other']}}])
  await page.route('**/reports/v1/native/cf-probe/2/api/context',route=>route.fulfill({json:{context:{...context,revision:2,parentRevision:1,sourceFile:{...context.sourceFile,size:saved.length,sha256:createHash('sha256').update(saved).digest('hex')}},csrfToken:'csrf',capabilities:{xlsx_editor:true},editingEnabled:true}}));await page.route('**/reports/v1/native/cf-probe/2/api/file',route=>route.fulfill({body:saved,contentType:media}));await page.addInitScript(()=>history.replaceState(null,'','/reports/v1/native/cf-probe/2'));await page.goto(`${base}/reports/v1/native/cf-probe/2`);await page.waitForFunction(()=>document.querySelector('#report-editor')?.getAttribute('aria-busy')==='false',null,{timeout:60000});await tab('Other').waitFor();assert.equal(await tab('Source').count(),0);console.log(JSON.stringify({phase:'allowed-remove-save',actual,operations:payload.operations}))
 }

 }
 await page.screenshot({path:`/tmp/workbook-owned-drawing-${mode}-built.png`,fullPage:true})
 const scripts=await Promise.all(scriptProof);assert(scripts.some(path=>/workbook-main-/.test(path)));console.log(JSON.stringify({ok:true,preview:true,phase:'owned-drawing-remove-contract',mode,allow,atomicRefusal:!allow,allowedHistoryDraftPythonRevision:allow,js200AndHashMatch:scripts.length,assets:[...new Set(scripts.filter(path=>/workbook-(main|engine-|structure|chart-references|xml-parser)/.test(path)))],pageErrors:errors}));assert.deepEqual(errors,[])
}finally{await browser?.close();server.kill()}
