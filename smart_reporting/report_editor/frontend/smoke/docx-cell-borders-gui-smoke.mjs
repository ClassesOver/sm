import assert from 'node:assert/strict'
import { spawn, spawnSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import { fileURLToPath } from 'node:url'
import { setTimeout as delay } from 'node:timers/promises'
import { chromium } from 'playwright'
const frontend=fileURLToPath(new URL('../',import.meta.url)),repo=fileURLToPath(new URL('../../../../',import.meta.url)),base='http://127.0.0.1:4195'
const mime='application/vnd.openxmlformats-officedocument.wordprocessingml.document',sha=bytes=>createHash('sha256').update(bytes).digest('hex')
function python(input){
 const result=spawnSync(`${repo}/.venv/bin/python`,['-c',`
import base64,json,sys
from io import BytesIO
from zipfile import ZipFile
from lxml import etree
import re
from docx import Document
from docx.enum.style import WD_STYLE_TYPE
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.opc.constants import RELATIONSHIP_TYPE as RT
from smart_reporting.reporting.delivery.docx_native import inspect_docx,patch_docx
p=json.load(sys.stdin)
if p['mode']=='create':
 d=Document();d.add_paragraph('Untouched before');style=d.styles.add_style('CellShadeSmoke',WD_STYLE_TYPE.TABLE)
 prop=OxmlElement('w:tcPr');shd=OxmlElement('w:shd');shd.set(qn('w:val'),'clear');shd.set(qn('w:fill'),'DEEBF7');prop.append(shd);style.element.append(prop)
 t=d.add_table(rows=2,cols=2);t.style=style
 borders=OxmlElement('w:tblBorders')
 for name in ['insideH','insideV']:
  edge=OxmlElement('w:'+name);edge.set(qn('w:val'),'single');edge.set(qn('w:sz'),'4');edge.set(qn('w:color'),'000000');borders.append(edge)
 t._tbl.tblPr.append(borders)
 diagonal=OxmlElement('w:tcBorders');edge=OxmlElement('w:tl2br');edge.set(qn('w:val'),'single');edge.set(qn('w:themeColor'),'accent2');diagonal.append(edge);t.cell(1,1)._tc.get_or_add_tcPr().append(diagonal)
 for r,row in enumerate(t.rows):
  for c,cell in enumerate(row.cells):cell.text=f'Cell {r},{c}'
 cell=t.cell(0,0);cell.paragraphs[0].add_run(' rich').bold=True
 link=OxmlElement('w:hyperlink');link.set(qn('r:id'),cell.part.relate_to('https://example.org',RT.HYPERLINK,is_external=True));run=OxmlElement('w:r');text=OxmlElement('w:t');text.text=' link';run.append(text);link.append(run);cell.paragraphs[0]._p.append(link)
 shd=OxmlElement('w:shd');shd.set(qn('w:val'),'clear');shd.set(qn('w:fill'),'FFC000');cell._tc.get_or_add_tcPr().append(shd)
 d.add_paragraph('Untouched after');d.sections[0].header.paragraphs[0].text='Untouched header'
 out=BytesIO();d.save(out);print(base64.b64encode(out.getvalue()).decode())
elif p['mode']=='inspect':print(json.dumps(inspect_docx(base64.b64decode(p['bytes']))))
elif p['mode']=='patch':print(base64.b64encode(patch_docx(base64.b64decode(p['bytes']),p['operations'])).decode())
else:
 a=ZipFile(BytesIO(base64.b64decode(p['before'])));b=ZipFile(BytesIO(base64.b64decode(p['after'])))
 names={name for name in a.namelist() if not name.endswith('/')}
 assert names=={name for name in b.namelist() if not name.endswith('/')}
 for name in names:
  if name!='word/document.xml':assert a.read(name)==b.read(name),name
 original=a.read('word/document.xml');actual=b.read('word/document.xml')
 strip=lambda value:re.sub(rb'<w:(?:tcBorders|tblBorders)\\b[^>]*(?:/>|>[\\s\\S]*?</w:(?:tcBorders|tblBorders)>)',b'',value)
 assert strip(original)==strip(actual),'unrelated document XML changed'
 before=Document(BytesIO(base64.b64decode(p['before']))).tables[0];after=Document(BytesIO(base64.b64decode(p['after']))).tables[0]
 for r,row in enumerate(before.rows):
  for c,cell in enumerate(row.cells):
   assert [etree.tostring(p._p) for p in cell.paragraphs]==[etree.tostring(p._p) for p in after.cell(r,c).paragraphs]
 for c in range(2):
  borders=after.cell(0,c)._tc.tcPr.find(qn('w:tcBorders'))
  for name in ['top','left','bottom','right','tl2br','tr2bl']:assert borders.find(qn('w:'+name)).get(qn('w:val'))=='none'
 for c in range(2):
  edge=after.cell(1,c)._tc.tcPr.find(qn('w:tcBorders')).find(qn('w:bottom'));assert edge.get(qn('w:color'))=='FF0000' and edge.get(qn('w:sz'))=='12'
 borders=after._tbl.tblPr.find(qn('w:tblBorders'));assert all(borders.find(qn('w:'+name)) is None for name in ['insideH','insideV'])
 assert after.cell(1,1)._tc.tcPr.find(qn('w:tcBorders')).find(qn('w:tl2br')).get(qn('w:themeColor'))=='accent2'
 print(json.dumps({'otherZipPartsExact':True,'onlyTargetBorderXmlChanged':True,'tableStyleShadingRichRunsAndUnhitThemeExact':True,'noneClearsTableInside':True}))
`],{cwd:repo,env:{...process.env,PYTHONPATH:repo},input:JSON.stringify(input),encoding:'utf8',maxBuffer:20*1024*1024})
 if(result.status)throw Error(result.stderr||result.stdout)
 return result.stdout.trim()
}
const source=Buffer.from(python({mode:'create'}),'base64'),sourceModel=JSON.parse(python({mode:'inspect',bytes:source.toString('base64')}))
let saved,savedModel,payload,browser,page
const errors=[]
const preview=process.env.NATIVE_GUI_PREVIEW==='1'
const server=spawn('./node_modules/.bin/vite',[...(preview?['preview']:[]),'--host','127.0.0.1','--port','4195','--strictPort'],{cwd:frontend,stdio:'ignore'})
try{
 for(let i=0;i<120;i++){try{if((await fetch(`${base}/reports/v1/editor/assets/native.html`)).ok)break}catch{}await delay(250)}
 browser=await chromium.launch({headless:true,args:['--disable-features=LocalNetworkAccessChecks']})
 page=await browser.newPage({viewport:{width:1600,height:1100}})
 page.on('pageerror',error=>errors.push(error.message))
 const revision=route=>Number(route.request().url().match(/cell-borders\/(\d+)\/api/)[1]),active=route=>revision(route)===1?source:saved
 await page.route('**/reports/v1/native/cell-borders/*/api/context',route=>route.fulfill({json:{context:{documentId:'cell-borders',format:'docx',revision:revision(route),parentRevision:revision(route)===1?null:1,scope:{database:'fixture',companyId:'fixture',userId:'fixture',threadId:'fixture'},sourceFile:{path:'source.docx',size:active(route).length,sha256:sha(active(route)),mediaType:mime},origin:'upload'},editingEnabled:true,csrfToken:'fixture',capabilities:{docx_editor:true}}}))
 await page.route('**/reports/v1/native/cell-borders/*/api/file',route=>route.fulfill({body:active(route),contentType:mime}))
 await page.route('**/reports/v1/native/cell-borders/*/api/preview',route=>{assert.deepEqual(route.request().postDataJSON().operations,[]);const model=revision(route)===1?sourceModel:savedModel;return route.fulfill({json:{sourceSha256:model.sourceSha256,draftSha256:model.sourceSha256,model}})})
 await page.route('**/reports/v1/native/cell-borders/1/api/save',route=>{
  payload=route.request().postDataJSON();assert.equal(payload.expectedSha256,sha(source));saved=Buffer.from(python({mode:'patch',bytes:source.toString('base64'),operations:payload.operations}),'base64');savedModel=JSON.parse(python({mode:'inspect',bytes:saved.toString('base64')}))
  return route.fulfill({json:{documentId:'cell-borders',revision:2,parentRevision:1,revisionRegistered:true,validation:{ok:false,issues:[{code:'fixture_review',message:'GUI fixture soft warning'}]},artifacts:{word:{downloadUrl:'/cell-borders.docx',sha256:sha(saved),size:saved.length}},editor:{openUrl:'/reports/v1/native/cell-borders/2'}}})
 })
 await page.route(/\/reports\/v1\/native\/cell-borders\/[12]$/,async route=>route.fulfill({response:await route.fetch({url:`${base}/reports/v1/editor/assets/native.html`})}))
 const ready=async()=>{await page.locator('.docx-source-home').waitFor({timeout:60000});await page.getByRole('textbox',{name:'Word 文档编辑区'}).locator('table').waitFor()}
 const table=()=>page.getByRole('textbox',{name:'Word 文档编辑区'}).locator('table').first(),cells=()=>table().locator('td,th')
 const borders=()=>cells().evaluateAll(nodes=>nodes.map(node=>{const css=getComputedStyle(node);return {top:[css.borderTopStyle,css.borderTopColor,css.borderTopWidth],bottom:[css.borderBottomStyle,css.borderBottomColor,css.borderBottomWidth],left:[css.borderLeftStyle,css.borderLeftColor,css.borderLeftWidth],right:[css.borderRightStyle,css.borderRightColor,css.borderRightWidth]}}))
 const tab=()=>page.locator('[data-tab-id="tableDesign"]').click()
 const apply=async mode=>{await tab();const control=page.locator('[data-action="table-border-menu"]');assert(await control.isEnabled(),await control.getAttribute('title'));await control.click();await page.locator(`[data-action="table-border-${mode}"]`).click();await delay(150)}
 const caret=async()=>{await cells().first().getByText('Cell 0,0',{exact:false}).first().click()}
 const open=async n=>{await page.goto(`${base}/reports/v1/native/cell-borders/${n}`);await ready()}
 const model=()=>page.evaluate(()=>document.querySelector('.tiptap').editor.getJSON())
 await open(1);await caret();const initial=await model();await tab()
 await page.locator('[data-action="table-border-width"]').selectOption('12');await page.locator('[data-action="table-border-color"]').fill('#ff0000');assert.deepEqual(await model(),initial)
 await apply('outer');let lines=await borders();assert.deepEqual(lines[0].top,['solid','rgb(255, 0, 0)','2px']);assert.deepEqual(lines[3].bottom,['solid','rgb(255, 0, 0)','2px']);console.log(JSON.stringify({phase:'caret-whole-table',lines}))
 await page.keyboard.press('Control+z');assert.deepEqual(await model(),initial)
 await page.evaluate(()=>{const editor=document.querySelector('.tiptap').editor;let pos;editor.state.doc.forEach((node,offset)=>{if(node.type.name==='docTable'&&pos===undefined)pos=offset});editor.commands.setNodeSelection(pos)})
 await apply('outer');console.log(JSON.stringify({phase:'whole-table-selection',lines:await borders()}))
 // 已由真实命令把NodeSelection规范为CellSelection；只用其原生constructor搭建首行选区。
 await page.evaluate(()=>{const editor=document.querySelector('.tiptap').editor,positions=[];editor.state.doc.descendants((node,pos)=>{if(['docTableCell','docTableHeader'].includes(node.type.name))positions.push(pos)});editor.view.dispatch(editor.state.tr.setSelection(editor.state.selection.constructor.create(editor.state.doc,positions[0],positions[1])))})
 await page.locator('[data-action="table-border-style"]').selectOption('dashed');await page.locator('[data-action="table-border-width"]').selectOption('18');await page.locator('[data-action="table-border-color"]').fill('#00b050')
 console.log(JSON.stringify({phase:'before-selected-bottom',selection:await page.evaluate(()=>{const selection=document.querySelector('.tiptap').editor.state.selection;return {name:selection.constructor.name,from:selection.from,to:selection.to,anchorCell:selection.$anchorCell?.pos,headCell:selection.$headCell?.pos}}),pen:await page.locator('[data-action=table-border-style]').inputValue(),width:await page.locator('[data-action=table-border-width]').inputValue()}));await apply('bottom');console.log(JSON.stringify({phase:'after-selected-bottom',notice:await page.locator('.docx-notice').innerText()}));lines=await borders();assert.deepEqual(lines[0].bottom,['dashed','rgb(0, 176, 80)','3px']);assert.deepEqual(lines[1].bottom,['dashed','rgb(0, 176, 80)','3px']);assert.deepEqual(lines[2].bottom,['solid','rgb(255, 0, 0)','2px']);await page.screenshot({path:'/tmp/docx-cell-borders-pen.png'});console.log(JSON.stringify({phase:'selected-row-pen',lines}))
 await page.keyboard.press('Control+z');assert.notDeepEqual((await borders())[0].bottom,lines[0].bottom);await page.keyboard.press('Control+Shift+z');assert.deepEqual((await borders())[0].bottom,lines[0].bottom)
 await apply('none');lines=await borders();assert.equal(lines[0].top[0],'none');assert.equal(lines[1].top[0],'none');assert.deepEqual(lines[2].bottom,['solid','rgb(255, 0, 0)','2px']);console.log(JSON.stringify({phase:'none-selected-row',lines}))
 await page.reload();await ready();assert.deepEqual(await borders(),lines);console.log(JSON.stringify({phase:'draft-restored',lines:await borders()}))
 await page.locator('[data-action="save"]').click();await page.getByRole('link',{name:'下载 Word',exact:true}).waitFor({timeout:60000})
 assert.equal(payload.operations.length,1);assert.equal(payload.operations[0].kind,'setTableCellBorders');assert.deepEqual(payload.operations[0].steps.map(step=>step.mode),['outer','bottom','none'])
 const readback=JSON.parse(python({mode:'verify',before:source.toString('base64'),after:saved.toString('base64')}))
 await open(2);assert.deepEqual(await borders(),lines);await page.screenshot({path:'/tmp/docx-cell-borders-reopened.png'});assert.deepEqual(errors,[])
 console.log(JSON.stringify({ok:true,preview,browser:browser.version(),sourceSha256:sha(source),savedSha256:sha(saved),operations:payload.operations,readback,caretWholeTable:true,selectedRow:true,undoRedo:true,draftRestored:true,revision2Reopened:true,pageErrors:errors,provenance:'HTTP routes substitute authorization/revisions; preview uses real inspect_docx and save real patch_docx. PM selection setup only; all border changes use visible ribbon controls.'}))
}catch(error){await page?.screenshot({path:'/tmp/docx-cell-borders-failed.png'}).catch(()=>{});console.error(JSON.stringify({failed:true,message:String(error),pageErrors:errors}));throw error}finally{await browser?.close();server.kill()}
