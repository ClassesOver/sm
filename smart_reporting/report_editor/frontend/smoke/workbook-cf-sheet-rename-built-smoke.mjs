import assert from 'node:assert/strict'
import { spawn, spawnSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import { readFileSync } from 'node:fs'
import { setTimeout as delay } from 'node:timers/promises'
import { chromium } from 'playwright'

const frontend=process.cwd(),repo=new URL('../../../',`file://${frontend}/`).pathname,base='http://127.0.0.1:4222',newName="财务 O'Brien"
function python(payload){const result=spawnSync(`${repo}/.venv/bin/python`,['-c',`
import json,sys,base64,xml.etree.ElementTree as ET
from io import BytesIO
from zipfile import ZipFile,ZIP_DEFLATED
from openpyxl import Workbook,load_workbook
from openpyxl.formatting.rule import FormulaRule,DataBarRule
from openpyxl.styles import PatternFill
from smart_reporting.report_editor.native_office import patch_office
p=json.load(sys.stdin)
if p['mode']=='create':
 b=Workbook();s=b.active;s.title='Source';other=b.create_sheet('Other')
 for i in range(1,6):s.cell(i,1,i);other.cell(i,2,i)
 other.conditional_formatting.add('B1:B4',FormulaRule(formula=['TRUE'],stopIfTrue=True,fill=PatternFill('solid',fgColor='FFFF0000')))
 other.conditional_formatting.add('B1:B4',FormulaRule(formula=['IF(source!a1>0,"Source!A1",0)>0'],fill=PatternFill('solid',fgColor='FF00FF00')))
 other.conditional_formatting.add('C1:C4',DataBarRule(start_type='formula',start_value='source!a1',end_type='num',end_value=100,color='FF638EC6'))
 f=BytesIO();b.save(f);zin=ZipFile(BytesIO(f.getvalue()));out=BytesIO();ns='http://schemas.microsoft.com/office/spreadsheetml/2009/9/main'
 base='<conditionalFormatting sqref="D1:D4"><cfRule type="dataBar" priority="4"><dataBar><cfvo type="formula" val="Source!A1"/><cfvo type="max"/><color rgb="FF638EC6"/></dataBar><extLst><ext uri="{B025F937-C7B1-47D3-B67F-A62EFF666E3E}" xmlns:x14="'+ns+'"><x14:id>linked-rename-id</x14:id></ext></extLst></cfRule></conditionalFormatting>'
 twin='<extLst><ext uri="{78C0D931-6437-407D-A8EE-F0AAD7539E65}" xmlns:x14="'+ns+'"><x14:conditionalFormattings><x14:conditionalFormatting xmlns:xm="http://schemas.microsoft.com/office/excel/2006/main"><x14:cfRule type="dataBar" priority="4" id="linked-rename-id"><x14:dataBar minLength="0" maxLength="100" gradient="0"><x14:cfvo type="formula"><xm:f>Source!A1</xm:f></x14:cfvo><x14:cfvo type="autoMax"/><x14:negativeFillColor rgb="FFFF0000"/></x14:dataBar></x14:cfRule><xm:sqref>D1:D4</xm:sqref></x14:conditionalFormatting></x14:conditionalFormattings></ext></extLst>'
 with ZipFile(out,'w',ZIP_DEFLATED) as zout:
  for name in zin.namelist():
   part=zin.read(name)
   if name=='xl/worksheets/sheet2.xml':part=part.decode().replace('</worksheet>',base+twin+'</worksheet>').encode()
   zout.writestr(name,part)
 print(base64.b64encode(out.getvalue()).decode())
elif p['mode']=='patch':print(base64.b64encode(patch_office('xlsx',base64.b64decode(p['bytes']),p['operations'])).decode())
else:
 raw=base64.b64decode(p['bytes']);b=load_workbook(BytesIO(raw));other=b['Other'];before=ZipFile(BytesIO(base64.b64decode(p['original'])));after=ZipFile(BytesIO(raw));xml=ET.fromstring(after.read('xl/worksheets/sheet2.xml'));ns={'s':'http://schemas.openxmlformats.org/spreadsheetml/2006/main','x14':'http://schemas.microsoft.com/office/spreadsheetml/2009/9/main','xm':'http://schemas.microsoft.com/office/excel/2006/main'}
 print(json.dumps({'sheetNames':b.sheetnames,'rules':[{'range':str(key.sqref),'type':r.type,'formula':r.formula,'stop':r.stopIfTrue,'priority':r.priority} for key,value in other.conditional_formatting._cf_rules.items() for r in value],'baseFormulaThresholds':[node.get('val') for node in xml.findall('.//s:cfvo[@type="formula"]',ns)],'twinFormulas':[node.text for node in xml.findall('.//xm:f',ns)],'baseIds':[node.text for node in xml.findall('.//x14:id',ns)],'twinIds':[node.get('id') for node in xml.findall('.//x14:cfRule',ns)],'negativeColors':[node.get('rgb') for node in xml.findall('.//x14:negativeFillColor',ns)],'gradient':[node.get('gradient') for node in xml.findall('.//x14:dataBar',ns)],'sourceXmlUnchanged':before.read('xl/worksheets/sheet1.xml')==after.read('xl/worksheets/sheet1.xml'),'stylesUnchanged':before.read('xl/styles.xml')==after.read('xl/styles.xml'),'otherValues':[other.cell(i,2).value for i in range(1,6)],'changedParts':[name for name in before.namelist() if before.read(name)!=after.read(name)]}))
`],{input:JSON.stringify(payload),encoding:'utf8',cwd:repo});assert.equal(result.status,0,result.stderr);return result.stdout.trim()}
const bytes=Buffer.from(python({mode:'create'}),'base64'),media='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
const context=(source,revision=1)=>({documentId:'cf-rename',format:'xlsx',revision,parentRevision:revision===1?null:1,scope:{database:'f',companyId:'f',userId:'f',threadId:'f'},sourceFile:{path:'cf.xlsx',size:source.length,sha256:createHash('sha256').update(source).digest('hex'),mediaType:media},origin:'upload'})
const server=spawn('./node_modules/.bin/vite',['preview','--host','127.0.0.1','--port','4222','--strictPort'],{cwd:frontend,stdio:'ignore'})
let browser,saved,payload
try{
 for(let i=0;i<120;i++){try{if((await fetch(`${base}/reports/v1/editor/assets/native.html`)).ok)break}catch{}await delay(250)}
 browser=await chromium.launch({headless:true});const page=await browser.newPage({viewport:{width:1500,height:1100}}),errors=[],scriptProof=[]
 page.on('pageerror',error=>{errors.push(error.message);console.log(error.stack)})
 page.on('response',response=>{const url=new URL(response.url());if(url.pathname.startsWith('/reports/v1/editor/assets/')&&url.pathname.endsWith('.js'))scriptProof.push((async()=>{assert.equal(response.status(),200);const body=await response.body(),path=`../static/${url.pathname.slice('/reports/v1/editor/assets/'.length)}`;assert.equal(createHash('sha256').update(body).digest('hex'),createHash('sha256').update(readFileSync(path)).digest('hex'));return url.pathname})())})
 for(const revision of [1,2]){
  await page.route(`**/reports/v1/native/cf-rename/${revision}/api/context`,route=>route.fulfill({json:{context:context(revision===1?bytes:saved,revision),csrfToken:'csrf',capabilities:{xlsx_editor:true},editingEnabled:true}}))
  await page.route(`**/reports/v1/native/cf-rename/${revision}/api/file`,route=>route.fulfill({body:revision===1?bytes:saved,contentType:media}))
 }
 await page.route('**/reports/v1/native/cf-rename/1/api/save',async route=>{payload=route.request().postDataJSON();saved=Buffer.from(python({mode:'patch',bytes:bytes.toString('base64'),operations:payload.operations}),'base64');await route.fulfill({json:{documentId:'cf-rename',revision:2,parentRevision:1,revisionRegistered:true,artifacts:{xlsx:{downloadUrl:'/cf.xlsx'}},editor:{openUrl:'/reports/v1/native/cf-rename/2'},validation:{issues:[]}}})})
 await page.route(/\/reports\/v1\/native\/cf-rename\/[12]$/,async route=>route.fulfill({response:await route.fetch({url:`${base}/reports/v1/editor/assets/native.html`})}))
 await page.addInitScript(()=>history.replaceState(null,'','/reports/v1/native/cf-rename/1'))
 const ready=async()=>{await page.waitForFunction(()=>document.querySelector('#report-editor')?.getAttribute('aria-busy')==='false',null,{timeout:60000});await page.locator('[data-ribbon-tab="Home"]').waitFor()}
 const tab=name=>page.locator('[data-u-comp="slide-tab-item"]').filter({hasText:name})
 const manager=async renamed=>{await tab(renamed?newName:'Source').waitFor();await tab('Other').click();await page.locator('[data-ribbon-tab="Home"]').click();await page.locator('[data-ribbon-command="cf-open"]').click();await page.getByText('B1:B4',{exact:true}).first().waitFor();assert.equal(await page.getByText('B1:B4',{exact:true}).count(),2);await page.getByText('C1:C4',{exact:true}).waitFor();await page.getByText('D1:D4',{exact:true}).waitFor();await page.getByText('自定义公式',{exact:true}).first().waitFor()}
 const history=async action=>{await page.locator('[data-ribbon-tab="File"]').click();await page.locator(`[data-ribbon-command="${action}"]`).click()}
 await page.goto(`${base}/reports/v1/editor/assets/native.html`);await ready();await manager(false)
 await tab('Source').click();await tab('Source').dblclick();const editor=page.locator('[data-u-comp="slide-tab-item"] [contenteditable="true"]');await editor.fill(newName);await editor.press('Enter');await tab(newName).waitFor();await manager(true)
 await history('undo');await tab('Source').waitFor();await manager(false)
 await history('redo');await tab(newName).waitFor();await manager(true)
 await page.waitForFunction(()=>Object.keys(localStorage).filter(key=>key.startsWith('native-editor-draft:')).some(key=>{try{return JSON.parse(localStorage.getItem(key)).operations.some(op=>op.kind==='applySheetEdits'&&op.plan.renames.length)}catch{return false}}),null,{timeout:30000})
 await page.reload();await ready();await manager(true)
 await page.locator('[data-action="save"]').click();await page.waitForFunction(()=>document.querySelector('.save-state-label')?.textContent==='已保存修订 2',null,{timeout:60000}).catch(async error=>{console.log(JSON.stringify({phase:'save-failed',body:(await page.locator('body').innerText()).slice(-3000)}));throw error})
 assert.deepEqual(payload.operations,[{kind:'applySheetEdits',plan:{renames:[{sheetName:'Source',newName}],additions:[],removals:[],order:[newName,'Other']}}])
 const actual=JSON.parse(python({mode:'inspect',bytes:saved.toString('base64'),original:bytes.toString('base64')}));console.log(JSON.stringify({phase:'python-save',actual,operations:payload.operations}))
 assert.deepEqual(actual.sheetNames,[newName,'Other']);assert.equal(actual.rules[1].formula[0],`IF('财务 O''Brien'!a1>0,"Source!A1",0)>0`);assert.deepEqual(actual.rules.map(rule=>rule.priority),[1,2,3,4]);assert.deepEqual(actual.baseFormulaThresholds,["'财务 O''Brien'!a1","'财务 O''Brien'!A1"]);assert.deepEqual(actual.twinFormulas,["'财务 O''Brien'!A1"]);assert.deepEqual(actual.baseIds,['linked-rename-id']);assert.deepEqual(actual.twinIds,['linked-rename-id']);assert.deepEqual(actual.negativeColors,['FFFF0000']);assert.deepEqual(actual.gradient,['0']);assert.equal(actual.sourceXmlUnchanged,true);assert.equal(actual.stylesUnchanged,true);assert.deepEqual(actual.otherValues,[1,2,3,4,5]);assert.deepEqual(actual.changedParts.sort(),['xl/workbook.xml','xl/worksheets/sheet2.xml'])
 await page.addInitScript(()=>history.replaceState(null,'','/reports/v1/native/cf-rename/2'));await page.goto(`${base}/reports/v1/native/cf-rename/2`);await ready();await manager(true);assert.deepEqual(errors,[])
 const scripts=await Promise.all(scriptProof);assert(scripts.some(path=>/workbook-main-/.test(path)));console.log(JSON.stringify({ok:true,preview:true,renameFormulaAndThresholds:true,linkedBaseTwinIdentity:true,parentPriority:true,nativeUndoRedo:true,draftRecovery:true,pythonPatchOpenpyxl:true,revisionReopen:true,operations:payload.operations,actual,js200AndHashMatch:scripts.length,assets:[...new Set(scripts.filter(path=>/workbook-(main|engine-|structure)/.test(path)))],pageErrors:errors}))
}finally{await browser?.close();server.kill()}
