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
 expected=a.read('word/document.xml').replace(b'<w:shd w:val="clear" w:fill="FFC000"/>',b'',1)
 assert b.read('word/document.xml')==expected
 print(json.dumps({'otherZipPartsExact':True,'documentXmlOnlySelectedShdRemoved':True,'tableStyleAndRichRunsExact':True}))
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
 const revision=route=>Number(route.request().url().match(/cell-shading\/(\d+)\/api/)[1]),active=route=>revision(route)===1?source:saved
 await page.route('**/reports/v1/native/cell-shading/*/api/context',route=>route.fulfill({json:{context:{documentId:'cell-shading',format:'docx',revision:revision(route),parentRevision:revision(route)===1?null:1,scope:{database:'fixture',companyId:'fixture',userId:'fixture',threadId:'fixture'},sourceFile:{path:'source.docx',size:active(route).length,sha256:sha(active(route)),mediaType:mime},origin:'upload'},editingEnabled:true,csrfToken:'fixture',capabilities:{docx_editor:true}}}))
 await page.route('**/reports/v1/native/cell-shading/*/api/file',route=>route.fulfill({body:active(route),contentType:mime}))
 await page.route('**/reports/v1/native/cell-shading/*/api/preview',route=>{assert.deepEqual(route.request().postDataJSON().operations,[]);const model=revision(route)===1?sourceModel:savedModel;return route.fulfill({json:{sourceSha256:model.sourceSha256,draftSha256:model.sourceSha256,model}})})
 await page.route('**/reports/v1/native/cell-shading/1/api/save',route=>{
  payload=route.request().postDataJSON();assert.equal(payload.expectedSha256,sha(source));saved=Buffer.from(python({mode:'patch',bytes:source.toString('base64'),operations:payload.operations}),'base64');savedModel=JSON.parse(python({mode:'inspect',bytes:saved.toString('base64')}))
  return route.fulfill({json:{documentId:'cell-shading',revision:2,parentRevision:1,revisionRegistered:true,validation:{ok:false,issues:[{code:'fixture_review',message:'GUI fixture soft warning'}]},artifacts:{word:{downloadUrl:'/cell-shading.docx',sha256:sha(saved),size:saved.length}},editor:{openUrl:'/reports/v1/native/cell-shading/2'}}})
 })
 await page.route(/\/reports\/v1\/native\/cell-shading\/[12]$/,async route=>route.fulfill({response:await route.fetch({url:`${base}/reports/v1/editor/assets/native.html`})}))
 const ready=async()=>{await page.locator('.docx-source-home').waitFor({timeout:60000});await page.getByRole('textbox',{name:'Word 文档编辑区'}).locator('table').waitFor()}
 const table=()=>page.getByRole('textbox',{name:'Word 文档编辑区'}).locator('table').first(),cells=()=>table().locator('td,th')
 const colors=()=>cells().evaluateAll(nodes=>nodes.map(node=>getComputedStyle(node).backgroundColor))
 const tab=()=>page.locator('[data-tab-id="tableDesign"]').click()
 const shade=async value=>{await tab();const control=page.locator('[data-action="table-cell-shading"]');assert(await control.isEnabled(),await control.getAttribute('title'));await control.click();await page.locator(`[data-action="table-cell-shading-${value}"]`).click();await delay(150)}
 const caret=async()=>{await cells().first().getByText('Cell 0,0',{exact:false}).first().click()}
 const open=async n=>{await page.goto(`${base}/reports/v1/native/cell-shading/${n}`);await ready()}
 await open(1);await caret();const initial=await colors();assert.equal(initial[0],'rgb(255, 192, 0)');assert.equal(initial[1],'rgb(222, 235, 247)');console.log(JSON.stringify({phase:'initial',colors:initial}))
 await shade('00B050');assert.deepEqual(await colors(),['rgb(0, 176, 80)',...initial.slice(1)]);await page.screenshot({path:'/tmp/docx-cell-shading-green.png'})
 await page.keyboard.press('Control+z');assert.deepEqual(await colors(),initial);await page.keyboard.press('Control+Shift+z');assert.equal((await colors())[0],'rgb(0, 176, 80)');console.log(JSON.stringify({phase:'caret',undoRedo:true,colors:await colors()}))
 // 只搭建真实PM整表选区；颜色修改仍必须通过用户可见色板及原生命令。
 await page.evaluate(()=>{const editor=document.querySelector('.tiptap').editor;let pos;editor.state.doc.forEach((node,offset)=>{if(node.type.name==='docTable'&&pos===undefined)pos=offset});editor.commands.setNodeSelection(pos)})
 await shade('7030A0');assert((await colors()).every(color=>color==='rgb(112, 48, 160)'));console.log(JSON.stringify({phase:'whole-table',colors:await colors()}))
 await page.keyboard.press('Control+z');assert.equal((await colors())[0],'rgb(0, 176, 80)');assert.equal((await colors())[1],initial[1])
 await caret();await shade('none');assert((await colors()).every(color=>color==='rgb(222, 235, 247)'));console.log(JSON.stringify({phase:'none-inherits',colors:await colors()}))
 await page.reload();await ready();assert((await colors()).every(color=>color==='rgb(222, 235, 247)'));console.log(JSON.stringify({phase:'draft-restored',colors:await colors()}))
 await page.locator('[data-action="save"]').click();await page.getByRole('link',{name:'下载 Word',exact:true}).waitFor({timeout:60000})
 assert.equal(payload.operations.length,1);assert.equal(payload.operations[0].kind,'setCellShading');assert.equal(payload.operations[0].fill,null)
 const readback=JSON.parse(python({mode:'verify',before:source.toString('base64'),after:saved.toString('base64')}))
 await open(2);assert((await colors()).every(color=>color==='rgb(222, 235, 247)'));await page.screenshot({path:'/tmp/docx-cell-shading-reopened.png'});assert.deepEqual(errors,[])
 console.log(JSON.stringify({ok:true,preview,browser:browser.version(),sourceSha256:sha(source),savedSha256:sha(saved),operations:payload.operations,readback,caret:true,wholeTable:true,undoRedo:true,draftRestored:true,revision2Reopened:true,pageErrors:errors,provenance:'HTTP routes substitute authorization/revisions; preview uses real inspect_docx and save uses real patch_docx. PM whole-table selection is test setup; all shading edits use visible ribbon palette.'}))
}catch(error){await page?.screenshot({path:'/tmp/docx-cell-shading-failed.png'}).catch(()=>{});console.error(JSON.stringify({failed:true,message:String(error),pageErrors:errors}));throw error}finally{await browser?.close();server.kill()}
