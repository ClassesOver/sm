import assert from 'node:assert/strict'
import {spawn,spawnSync} from 'node:child_process'
import {createHash} from 'node:crypto'
import {readFileSync} from 'node:fs'
import {setTimeout as delay} from 'node:timers/promises'
import {chromium} from 'playwright'
const frontend=process.cwd(),repo=new URL('../../../',`file://${frontend}/`).pathname,base='http://127.0.0.1:4238'
const namespace=process.env.PIVOT_RENAME_NAMESPACE??'default',newName="财务 O'Brien & 数据"
assert(['default','alias'].includes(namespace))
const sha=bytes=>createHash('sha256').update(bytes).digest('hex')
function python(payload){const result=spawnSync(`${repo}/.venv/bin/python`,['-c',`
import json,sys,base64,re
from io import BytesIO
from zipfile import ZipFile,ZIP_DEFLATED
from xml.etree import ElementTree as ET
from xml.sax.saxutils import quoteattr
from openpyxl import Workbook,load_workbook
from openpyxl.pivot.table import TableDefinition,Location
from openpyxl.pivot.cache import CacheDefinition,CacheSource,WorksheetSource,CacheField,SharedItems
from smart_reporting.report_editor.native_office import patch_office
p=json.load(sys.stdin)
if p['mode']=='create':
 b=Workbook();s=b.active;s.title='Source';s.append(['Category','Amount']);s.append(['A',10]);pivot=b.create_sheet('Pivot')
 table=TableDefinition(name='Report',cacheId=1,dataCaption='Values',location=Location(ref='A1:B3',firstHeaderRow=1,firstDataRow=1,firstDataCol=1))
 table.cache=CacheDefinition(cacheSource=CacheSource(type='worksheet',worksheetSource=WorksheetSource(ref='A1:B2',sheet=s.title)),cacheFields=[CacheField(name='Category',sharedItems=SharedItems()),CacheField(name='Amount',sharedItems=SharedItems())])
 pivot.add_pivot(table)
 f=BytesIO();b.save(f);out=BytesIO()
 with ZipFile(BytesIO(f.getvalue())) as before,ZipFile(out,'w',ZIP_DEFLATED) as after:
  for entry in before.infolist():
   raw=before.read(entry.filename)
   if entry.filename.startswith('xl/pivotCache/pivotCacheDefinition') and p['namespace']=='alias':
    xml=raw.decode().replace('xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"','xmlns:q="http://schemas.openxmlformats.org/spreadsheetml/2006/main"')
    raw=re.sub(r'<(/?)([A-Za-z][\\w]*)(?=[\\s/>])',r'<\\1q:\\2',xml).encode()
   after.writestr(entry,raw)
 print(base64.b64encode(out.getvalue()).decode())
elif p['mode']=='patch':print(base64.b64encode(patch_office('xlsx',base64.b64decode(p['bytes']),p['operations'])).decode())
else:
 raw=base64.b64decode(p['bytes']);b=load_workbook(BytesIO(raw));before=ZipFile(BytesIO(base64.b64decode(p['original'])));after=ZipFile(BytesIO(raw))
 cacheParts=sorted(n for n in before.namelist() if n.startswith('xl/pivotCache/pivotCacheDefinition') and n.endswith('.xml'))
 assert len(cacheParts)==1
 cachePart=cacheParts[0];old=before.read(cachePart).decode();new=after.read(cachePart).decode();name=p['newName']
 expected=old.replace('sheet="Source"','sheet='+quoteattr(name,{"'":'&apos;'}))
 if p['namespace']=='alias':
  expected=re.sub(r'<(/?)q:',r'<\\1',expected).replace('xmlns:q="http://schemas.openxmlformats.org/spreadsheetml/2006/main"','xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"')
 source=ET.fromstring(new).find('{*}cacheSource/{*}worksheetSource')
 assert source is not None
 unchanged=[n for n in before.namelist() if n not in ('xl/workbook.xml',cachePart)]
 pivotParts=sorted(n for n in before.namelist() if n.startswith(('xl/pivotCache/','xl/pivotTables/')) and n!=cachePart)
 assert any('pivotTable1.xml' in n for n in pivotParts)
 print(json.dumps({'sheetNames':b.sheetnames,'sourceValues':list(b[name].values),'pivotCount':len(b['Pivot']._pivots),'cacheSource':b['Pivot']._pivots[0].cache.cacheSource.worksheetSource.sheet,'cacheXmlSource':source.attrib['sheet'],'cacheXml':new,'cacheOnlySheetChanged':new==old.replace('sheet="Source"','sheet='+quoteattr(name,{"'":'&apos;'})),'cacheOnlyExpectedSheetAndNamespaceChanged':new==expected,'namespaceNormalization':p['namespace']=='alias','partSetUnchanged':set(before.namelist())==set(after.namelist()),'allOtherPartBytesUnchanged':all(before.read(n)==after.read(n) for n in unchanged),'pivotPartsUnchanged':all(before.read(n)==after.read(n) for n in pivotParts),'pivotSheetBytesUnchanged':before.read('xl/worksheets/sheet2.xml')==after.read('xl/worksheets/sheet2.xml'),'stylesUnchanged':before.read('xl/styles.xml')==after.read('xl/styles.xml'),'changedParts':[n for n in before.namelist() if before.read(n)!=after.read(n)]},ensure_ascii=False))
`],{input:JSON.stringify(payload),encoding:'utf8',cwd:repo});assert.equal(result.status,0,result.stderr);return result.stdout.trim()}
const bytes=Buffer.from(python({mode:'create',namespace}),'base64'),media='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
const context={documentId:'pivot-rename',format:'xlsx',revision:1,parentRevision:null,scope:{database:'f',companyId:'f',userId:'f',threadId:'f'},sourceFile:{path:'pivot.xlsx',size:bytes.length,sha256:sha(bytes),mediaType:media},origin:'upload'}
const server=spawn('./node_modules/.bin/vite',['preview','--host','127.0.0.1','--port','4238','--strictPort'],{cwd:frontend,stdio:'ignore'})
let browser,saved,payload,saveCount=0
try{
 for(let i=0;i<120;i++){try{if((await fetch(`${base}/reports/v1/editor/assets/native.html`)).ok)break}catch{}await delay(250)}
 browser=await chromium.launch({headless:true});const page=await browser.newPage({viewport:{width:1500,height:1100}}),errors=[],scriptProof=[]
 page.on('pageerror',error=>errors.push(error.message))
 page.on('response',response=>{const url=new URL(response.url());if(url.pathname.startsWith('/reports/v1/editor/assets/')&&url.pathname.endsWith('.js'))scriptProof.push((async()=>{assert.equal(response.status(),200);const body=await response.body();assert.equal(sha(body),sha(readFileSync(`../static/${url.pathname.slice('/reports/v1/editor/assets/'.length)}`)));return url.pathname})())})
 for(const revision of [1,2]){
  await page.route(`**/reports/v1/native/pivot-rename/${revision}/api/context`,route=>route.fulfill({json:{context:revision===1?context:{...context,revision:2,parentRevision:1,sourceFile:{...context.sourceFile,size:saved.length,sha256:sha(saved)}},csrfToken:'csrf',capabilities:{xlsx_editor:true},editingEnabled:true}}))
  await page.route(`**/reports/v1/native/pivot-rename/${revision}/api/file`,route=>route.fulfill({body:revision===1?bytes:saved,contentType:media}))
 }
 await page.route('**/reports/v1/native/pivot-rename/1/api/save',async route=>{saveCount++;payload=route.request().postDataJSON();saved=Buffer.from(python({mode:'patch',bytes:bytes.toString('base64'),operations:payload.operations}),'base64');await route.fulfill({json:{documentId:'pivot-rename',revision:2,parentRevision:1,revisionRegistered:true,artifacts:{xlsx:{downloadUrl:'/pivot.xlsx'}},editor:{openUrl:'/reports/v1/native/pivot-rename/2'},validation:{issues:[]}}})})
 await page.route(/\/reports\/v1\/native\/pivot-rename\/[12]$/,async route=>route.fulfill({response:await route.fetch({url:`${base}/reports/v1/editor/assets/native.html`})}))
 await page.addInitScript(()=>history.replaceState(null,'','/reports/v1/native/pivot-rename/1'))
 const ready=async()=>{await page.waitForFunction(()=>document.querySelector('#report-editor')?.getAttribute('aria-busy')==='false',null,{timeout:60000});await page.locator('[data-ribbon-tab="Home"]').waitFor()}
 const tab=name=>page.locator('[data-u-comp="slide-tab-item"]').filter({hasText:name})
 const history=async action=>{await page.locator('[data-ribbon-tab="File"]').click();await page.locator(`[data-ribbon-command="${action}"]`).click()}
 await page.goto(`${base}/reports/v1/editor/assets/native.html`);await ready()
 await tab('Source').click();await tab('Source').dblclick();const editor=page.locator('[data-u-comp="slide-tab-item"] [contenteditable="true"]');await editor.fill(newName);await editor.press('Enter');await tab(newName).waitFor()
 await history('undo');await tab('Source').waitFor();await history('redo');await tab(newName).waitFor()
 await page.waitForFunction(()=>Object.keys(localStorage).filter(key=>key.startsWith('native-editor-draft:')).some(key=>{try{return JSON.parse(localStorage.getItem(key)).operations.some(op=>op.kind==='applySheetEdits'&&op.plan.renames.length)}catch{return false}}),null,{timeout:30000})
 await page.reload();await ready();await tab(newName).waitFor();assert.equal(await tab('Source').count(),0)
 await page.locator('[data-action="save"]').click();await page.waitForFunction(()=>document.querySelector('.save-state-label')?.textContent==='已保存修订 2',null,{timeout:60000})
 assert.deepEqual(payload.operations,[{kind:'applySheetEdits',plan:{renames:[{sheetName:'Source',newName}],additions:[],removals:[],order:[newName,'Pivot']}}])
 const actual=JSON.parse(python({mode:'inspect',bytes:saved.toString('base64'),original:bytes.toString('base64'),newName,namespace}))
 assert.deepEqual(actual.sheetNames,[newName,'Pivot']);assert.deepEqual(actual.sourceValues,[['Category','Amount'],['A',10]]);assert.equal(actual.pivotCount,1);assert.equal(actual.cacheSource,newName);assert.equal(actual.cacheXmlSource,newName);assert.equal(actual.cacheOnlyExpectedSheetAndNamespaceChanged,true);if(namespace==='default')assert.equal(actual.cacheOnlySheetChanged,true);assert.equal(actual.partSetUnchanged,true);assert.equal(actual.allOtherPartBytesUnchanged,true);assert.equal(actual.pivotPartsUnchanged,true);assert.equal(actual.pivotSheetBytesUnchanged,true);assert.equal(actual.stylesUnchanged,true);assert.deepEqual(actual.changedParts.sort(),['xl/pivotCache/pivotCacheDefinition1.xml','xl/workbook.xml'])
 await page.addInitScript(()=>history.replaceState(null,'','/reports/v1/native/pivot-rename/2'));await page.goto(`${base}/reports/v1/native/pivot-rename/2`);await ready();await tab(newName).waitFor();assert.equal(await tab('Source').count(),0)
 await page.waitForTimeout(500)
 const beforeDraft=await page.evaluate(()=>Object.fromEntries(Object.entries(localStorage))),beforeSaveLabel=await page.locator('.save-state-label').textContent(),beforeTabs=await page.locator('[data-u-comp="slide-tab-item"]').allTextContents()
 await tab(newName).click({button:'right'});await page.getByText('删除',{exact:true}).last().click();await page.getByRole('button',{name:'确定',exact:true}).click()
 await page.getByText(`仍有透视表读取工作表 "${newName}" 的来源数据，已拒绝删除。`,{exact:true}).waitFor()
 await tab(newName).waitFor();await history('undo');await tab(newName).waitFor();await history('redo');await tab(newName).waitFor()
 assert.deepEqual(await page.locator('[data-u-comp="slide-tab-item"]').allTextContents(),beforeTabs)
 assert.deepEqual(await page.evaluate(()=>Object.fromEntries(Object.entries(localStorage))),beforeDraft);assert.equal(await page.locator('.save-state-label').textContent(),beforeSaveLabel);assert.equal(saveCount,1)
 const scripts=await Promise.all(scriptProof);assert(scripts.some(path=>/workbook-main-/.test(path)));assert.deepEqual(errors,[])
 console.log(JSON.stringify({ok:true,namespace,pureUiRename:true,undoRedo:true,draftReload:true,pythonPivotCacheAndParts:actual,revision2Reopen:true,renamedPivotSourceDeletionAtomicRefusal:true,saveCount,js200AndHashMatch:scripts.length,assets:[...new Set(scripts.filter(path=>/workbook-(main|engine-|structure|pivot-references|xml-parser)/.test(path)))],pageErrors:errors}))
}finally{await browser?.close();server.kill()}
