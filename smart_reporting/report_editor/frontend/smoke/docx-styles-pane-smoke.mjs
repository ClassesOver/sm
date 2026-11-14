// GenOffice f8c17004 源组件族验收：授权/修订API为fixture，实际DOCX预览、保存、下载与独立ZIP回读。
import assert from 'node:assert/strict'
import { createServer } from 'node:http'
import { spawnSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import { readFile, writeFile, mkdir } from 'node:fs/promises'
import { resolve, join, extname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { chromium } from 'playwright'

const frontend = fileURLToPath(new URL('../', import.meta.url)), repo = resolve(frontend, '../../..')
const output = resolve(process.env.DOCX_EVIDENCE_DIR ?? '/home/junge/codex-evidence/smart_reporting/office-styles-20261113-recovery/native')
await mkdir(output, { recursive: true })
const sha = value => createHash('sha256').update(value).digest('hex')
const staticRoot = process.env.DOCX_TEST_DIST ? resolve(process.env.DOCX_TEST_DIST) : null
const identityFrontend = process.env.DOCX_FROZEN_FRONTEND ? resolve(process.env.DOCX_FROZEN_FRONTEND) : frontend
const manifestSha256 = staticRoot ? sha(await readFile(join(staticRoot, '.vite/manifest.json'))) : null
if (staticRoot) assert.equal(manifestSha256, process.env.DOCX_EXPECTED_MANIFEST_SHA256)
const watched = ['docx-styles-pane.tsx','docx-styles-pane-source.tsx','docx-style-dialog.tsx','docx-style-gallery.ts','docx-styles-pane-adapter.ts','docx-styles-pane-operations.ts','docx-styles-modal-keys.ts','docx-native-history.ts','docx-operations.ts','docx-note-paragraph-runs.ts','docx-main.tsx']
const sourceHashes = Object.fromEntries(await Promise.all(watched.map(async name => [name, sha(await readFile(join(identityFrontend,'src',name)))])))
const backendFiles = ['smart_reporting/reporting/delivery/docx_native.py','smart_reporting/reporting/delivery/office_engine.py','smart_reporting/report_editor/native.py','smart_reporting/report_editor/native_api.py','smart_reporting/report_editor/native_publication.py','smart_reporting/reporting/doc_engine/bridge/edit-docx.ts','smart_reporting/reporting/doc_engine/bridge/docx-styles-pane.ts']
const backendHashes = async () => Object.fromEntries(await Promise.all(backendFiles.map(async name => [name, sha(await readFile(join(repo,name)))])))
const backendBefore = await backendHashes()
const python = String.raw`
import json,sys
from io import BytesIO
from pathlib import Path
from hashlib import sha256
from zipfile import ZipFile
from docx import Document
from docx.shared import Pt
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from lxml import etree
from smart_reporting.reporting.delivery.docx_native import inspect_docx,patch_docx
from smart_reporting.reporting.delivery.office_engine import bridge_execution
p=json.load(sys.stdin);path=Path(p['path'])
if p['mode']=='fixture':
    doc=Document();doc.sections[0].header.paragraphs[0].text='页眉保留';target=doc.add_paragraph()
    for text,latin,asian,bold in [('Latin','Cambria','宋体',True),(' 中文','Arial','楷体',False)]:
        run=target.add_run(text);run.bold=bold;run.font.size=Pt(12)
        fonts=OxmlElement('w:rFonts')
        for key,value in {'ascii':latin,'hAnsi':latin,'eastAsia':asian,'cs':'Arial'}.items():fonts.set(qn('w:'+key),value)
        run._r.get_or_add_rPr().append(fonts)
        for tag,attrs in [('lang',{'val':'en-US','eastAsia':'zh-CN'}),('bdr',{'val':'single','sz':'4','color':'778899'})]:
            child=OxmlElement('w:'+tag)
            for key,value in attrs.items():child.set(qn('w:'+key),value)
            run._r.rPr.append(child)
    doc.add_paragraph('光标输入');doc.add_paragraph('邻段保留');doc.add_table(rows=1,cols=1).cell(0,0).text='表格保留';doc.save(path)
elif p['mode']=='patch':path.write_bytes(patch_docx(Path(p['source']).read_bytes(),p['operations']))
data=path.read_bytes();doc=Document(BytesIO(data))
with ZipFile(BytesIO(data)) as package:parts={name:sha256(package.read(name)).hexdigest() for name in package.namelist() if not name.endswith('/')}
if p['mode']=='verify':
    original=Path(p['source']).read_bytes();old=Document(BytesIO(original))
    assert doc.paragraphs[0].style.style_id=='ReportBody'
    style=doc.styles['Report Body'];assert style.font.name=='Calibri' and style.font.size.pt==13.5 and style.font.italic
    assert style.element.rPr.rFonts.get(qn('w:eastAsia'))=='仿宋';assert style.paragraph_format.space_after.pt==8
    assert doc.paragraphs[0].text=='Latin 中文' and doc.paragraphs[1].text=='光标Z输入'
    typed=[run for run in doc.paragraphs[1].runs if run.text=='Z'];assert len(typed)==1 and typed[0].style.style_id=='ReportChar'
    assert doc.styles['Report Char'].font.italic
    assert [item.xml for item in list(doc._element.body)[2:]]==[item.xml for item in list(old._element.body)[2:]]
    with ZipFile(BytesIO(original)) as before,ZipFile(BytesIO(data)) as after:
        for name in before.namelist():
            if name not in ('word/document.xml','word/styles.xml','docProps/core.xml'):assert before.read(name)==after.read(name),name
        ns={'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
        a=etree.fromstring(before.read('word/styles.xml'));b=etree.fromstring(after.read('word/styles.xml'))
        for item in a.findall('w:style',ns):
            target=b.xpath('./w:style[@w:styleId=$id]',namespaces=ns,id=item.get(qn('w:styleId')))
            assert len(target)==1 and etree.tostring(item)==etree.tostring(target[0])
engine,command=bridge_execution('doc','edit-docx');entry=Path(command[-1]).resolve()
print(json.dumps({'sha256':sha256(data).hexdigest(),'model':inspect_docx(data),'parts':parts,'execution':{'root':str(engine),'command':command,'entryRealpath':str(entry),'entrySha256':sha256(entry.read_bytes()).hexdigest()}},ensure_ascii=False))
`
const runPython = payload => {
  const result=spawnSync(join(repo,'.venv/bin/python'),['-c',python],{cwd:repo,input:JSON.stringify(payload),encoding:'utf8',timeout:120000,maxBuffer:20*1024*1024,env:{...process.env,PYTHONPATH:repo}})
  assert.equal(result.status,0,result.stderr);return JSON.parse(result.stdout)
}
const pathOf = revision => join(output, `revision-${revision}.docx`)
const revisions = new Map([[1,runPython({mode:'fixture',path:pathOf(1)})]])
const prefix='/reports/v1/editor/assets/',mediaType='application/vnd.openxmlformats-officedocument.wordprocessingml.document'
const { createServer:createViteServer }=await import('vite')
const vite=staticRoot?null:await createViteServer({root:frontend,configFile:join(frontend,'vite.config.ts'),cacheDir:process.env.DOCX_VITE_CACHE??'/dev/shm/office-styles-vite-cache',optimizeDeps:{entries:[join(frontend,'native.html')]},server:{middlewareMode:true,hmr:false},appType:'custom'})
const server=createServer(async(req,res)=>{
  try{
    const path=new URL(req.url,'http://127.0.0.1').pathname
    if(path==='/favicon.ico'){res.writeHead(204);res.end();return}
    if(path.startsWith('/download/')){const revision=Number(path.split('/').at(-1));res.writeHead(200,{'Content-Type':mediaType,'Content-Disposition':'attachment; filename=styles.docx'});res.end(await readFile(pathOf(revision)));return}
    if(staticRoot){const file=path.startsWith(prefix)?resolve(staticRoot,path.slice(prefix.length)):join(staticRoot,'native.html');assert.ok(file.startsWith(staticRoot+'/'));res.writeHead(200,{'Content-Type':({'.js':'application/javascript','.css':'text/css','.html':'text/html','.woff2':'font/woff2'})[extname(file)]??'application/octet-stream'});res.end(await readFile(file));return}
    if(path.startsWith(prefix)||path.startsWith('/src/')||path.startsWith('/@')||path.startsWith('/node_modules/')){vite.middlewares(req,res,()=>{res.writeHead(404);res.end()});return}
    res.writeHead(200,{'Content-Type':'text/html'});res.end(await vite.transformIndexHtml('/native.html',await readFile(join(frontend,'native.html'),'utf8')))
  }catch(error){if(!res.headersSent)res.writeHead(404);res.end(String(error))}
})
await new Promise(ok=>server.listen(0,'127.0.0.1',ok));const base=`http://127.0.0.1:${server.address().port}`
let browser,page,writable=true
const errors=[],checks=[],saves=[],sourceIdentities=[],chunks={},requests=[]
const recordCheck=checks.push.bind(checks);checks.push=(...items)=>{for(const item of items)process.stdout.write(item+'\n');return recordCheck(...items)}
try{
  browser=await chromium.launch({headless:true});page=await browser.newPage({viewport:{width:1440,height:900}})
  page.on('pageerror',error=>errors.push(error.message));page.on('console',message=>{if(message.type()==='error')errors.push(message.text())})
  page.on('response',response=>{
    const path=new URL(response.url()).pathname
    if(staticRoot&&path.startsWith(prefix)&&/\.(js|css)$/.test(path))sourceIdentities.push((async()=>{assert.equal(response.status(),200);const bytes=await response.body();assert.equal(sha(bytes),sha(await readFile(resolve(staticRoot,path.slice(prefix.length)))));chunks[path]=sha(bytes)})())
    else if(!staticRoot&&watched.some(file=>path.endsWith('/'+file)))sourceIdentities.push((async()=>{const bytes=await response.body(),map=/sourceMappingURL=data:application\/json;base64,([^\s]+)/.exec(bytes.toString());assert.ok(map);const decoded=JSON.parse(Buffer.from(map[1],'base64'));const file=watched.find(file=>path.endsWith('/'+file));assert.ok(decoded.sourcesContent.some(text=>sha(Buffer.from(text))===sourceHashes[file]),file);chunks[path]=sha(bytes)})())
  })
  await page.route('**/reports/v1/native/styles-pane/*/api/**',async route=>{
    try{
      const req=route.request(),path=new URL(req.url()).pathname,revision=Number(path.split('/')[5]),current=revisions.get(revision);requests.push({method:req.method(),path})
      if(path.endsWith('/context'))return route.fulfill({json:{context:{documentId:'styles-pane',revision,parentRevision:revision>1?revision-1:null,format:'docx',scope:{database:'f',companyId:'f',userId:'f',threadId:'f'},sourceFile:{path:pathOf(revision),sha256:current.sha256,size:(await readFile(pathOf(revision))).length,mediaType},origin:'report'},editingEnabled:writable,csrfToken:'fixture',capabilities:{docx_editor:true}}})
      if(path.endsWith('/file'))return route.fulfill({body:await readFile(pathOf(revision)),contentType:mediaType})
      if(path.endsWith('/preview'))return route.fulfill({json:{sourceSha256:current.sha256,draftSha256:current.sha256,model:current.model}})
      assert.ok(path.endsWith('/save'));const payload=req.postDataJSON();assert.equal(payload.expectedSha256,current.sha256)
      const next=revision+1,result=runPython({mode:'patch',source:pathOf(revision),path:pathOf(next),operations:payload.operations});revisions.set(next,result);saves.push(payload)
      return route.fulfill({json:{documentId:'styles-pane',revision:next,parentRevision:revision,revisionRegistered:true,validation:{ok:false,issues:['fixture_validation_warning']},artifacts:{word:{downloadUrl:`${base}/download/${next}`,sha256:result.sha256}},editor:{openUrl:`/reports/v1/native/styles-pane/${next}`}}})
    }catch(error){errors.push(String(error));return route.fulfill({status:500,json:{detail:String(error)}})}
  })
  const open=async revision=>{await page.goto(`${base}/reports/v1/native/styles-pane/${revision}`);await page.locator('.docx-source-home').waitFor({timeout:45000})}
  const body=()=>page.getByRole('textbox',{name:'Word 文档编辑区',exact:true})
  const select=async(index,caret=false)=>{await body().focus();await page.evaluate(({index,caret})=>{const editor=document.querySelector('[aria-label="Word 文档编辑区"]'),p=editor.querySelectorAll('p')[index],range=document.createRange();if(caret){const walker=document.createTreeWalker(p,NodeFilter.SHOW_TEXT),text=walker.nextNode();range.setStart(text,2);range.collapse(true)}else range.selectNodeContents(p);const selected=window.getSelection();selected.removeAllRanges();selected.addRange(range);document.dispatchEvent(new Event('selectionchange'))},{index,caret});await page.waitForTimeout(100)}
  const pane=()=>page.locator('.styles-pane'),dialog=()=>page.getByRole('dialog')
  const showPane=async()=>{if(!await pane().isVisible())await page.locator('[data-action=styles-pane]').click();await pane().waitFor()}
  const draft=()=>page.evaluate(()=>Object.values(localStorage).filter(value=>value.includes('styles-pane')).map(value=>JSON.parse(value)).flatMap(value=>value.operations??[]))
  const all=async()=>pane().locator('.styles-pane-foot select').selectOption('all')
  const context=async(id,label)=>{await all();await pane().locator(`[data-style-id="${id}"]`).click({button:'right'});await pane().getByRole('button',{name:label,exact:true}).click()}
  const newStyle=async()=>{await showPane();await pane().getByRole('button',{name:'新建样式…',exact:true}).click();await dialog().waitFor()}
  await open(1);await select(0);await showPane();await all();assert.ok(await pane().locator('[data-style-id]').count()>2);checks.push('source-pane-gallery')
  await pane().getByRole('searchbox').fill('Heading1');assert.equal(await pane().locator('[data-style-id]').count(),1);await pane().getByRole('searchbox').fill('');checks.push('search-filters')
  await body().locator('table').first().click();assert.equal(await pane().getByRole('button',{name:'新建样式…',exact:true}).isDisabled(),true);await select(0);checks.push('table-scope-disabled')
  await pane().locator('.styles-pane-clear').click();assert.ok((await draft()).some(op=>op.kind==='clearParagraphFormatting'));await body().focus();await page.keyboard.press('Control+z');assert.deepEqual(await draft(),[]);checks.push('source-clear-formatting-and-undo')
  await pane().locator('[data-style-id="Heading1"]').click();assert.equal((await draft()).find(op=>op.kind==='applyDocumentStyle').actions[0].styleId,'Heading1');await body().focus();await page.keyboard.press('Control+z');assert.deepEqual(await draft(),[]);checks.push('existing-heading-apply-and-undo')
  await pane().locator('[data-style-id="Emphasis"]').click();assert.equal((await draft()).find(op=>op.kind==='applyDocumentStyle').actions[0].type,'character');await pane().locator('[data-style-id="Emphasis"]').click();assert.equal((await draft()).find(op=>op.kind==='applyDocumentStyle').actions.at(-1).styleId,null);await body().focus();await page.keyboard.press('Control+z');await page.keyboard.press('Control+z');assert.deepEqual(await draft(),[]);checks.push('existing-character-apply-toggle-and-undo')
  await newStyle();await dialog().getByLabel('名称',{exact:true}).fill('cancelled');await dialog().getByRole('button',{name:'取消',exact:true}).click();assert.deepEqual(await draft(),[]);checks.push('new-cancel')
  await context('Normal','修改…');await dialog().getByRole('button',{name:'确定',exact:true}).click();assert.deepEqual(await draft(),[]);checks.push('modify-noop')
  await newStyle();await dialog().getByLabel('名称',{exact:true}).fill('Report Body');await dialog().getByLabel('西文字体',{exact:true}).selectOption('Calibri');await dialog().getByLabel('东亚字体',{exact:true}).selectOption('仿宋');await dialog().locator('input[type=number]').nth(0).fill('13.5');await dialog().locator('input[type=number]').nth(2).fill('8')
  for(const viewport of [{width:1440,height:900},{width:390,height:640},{width:640,height:320}]){await page.setViewportSize(viewport);await dialog().getByRole('button',{name:'确定',exact:true}).scrollIntoViewIfNeeded();const hit=await dialog().getByRole('button',{name:'确定',exact:true}).evaluate(e=>{const r=e.getBoundingClientRect();return{y:r.y,bottom:r.bottom,hit:document.elementFromPoint(r.x+r.width/2,r.y+r.height/2)===e}});assert.ok(hit.hit&&hit.y>=0&&hit.bottom<=viewport.height);await page.screenshot({path:join(output,`dialog-${viewport.width}x${viewport.height}.png`)});checks.push(`footer-button-hit-${viewport.width}x${viewport.height}`)}
  await page.setViewportSize({width:1440,height:900});await dialog().getByRole('button',{name:'确定',exact:true}).click();await page.waitForFunction(()=>Object.values(localStorage).some(value=>value.includes('ReportBody')));let operations=await draft();assert.equal(operations.filter(op=>op.kind==='upsertStyle').length,1);assert.equal(operations.filter(op=>op.kind==='applyDocumentStyle').length,1);checks.push('new-and-immediate-paragraph-apply')
  await context('ReportBody','修改…');await dialog().getByLabel('倾斜',{exact:true}).check();await dialog().getByRole('button',{name:'确定',exact:true}).click();checks.push('modify-definition')
  await context('ReportBody','更新以匹配所选内容');checks.push('update-from-selection')
  await context('ReportBody','修改…');await dialog().getByLabel('倾斜',{exact:true}).check();await dialog().getByLabel('东亚字体',{exact:true}).selectOption('仿宋');await dialog().getByRole('button',{name:'确定',exact:true}).click()
  await context('ReportBody','选择所有 1 个实例');checks.push('select-all-instances')
  const before=await draft();await body().focus();await page.keyboard.press('Control+z');await page.keyboard.press('Control+y');assert.deepEqual(await draft(),before);checks.push('undo-redo')
  await open(1);await showPane();assert.deepEqual(await draft(),before);checks.push('draft-reload')
  await select(1,true);await newStyle();await dialog().getByLabel('名称',{exact:true}).fill('Report Char');await dialog().locator('select').nth(0).selectOption('character');await dialog().getByLabel('倾斜',{exact:true}).check();await dialog().getByRole('button',{name:'确定',exact:true}).click();await body().focus();await page.keyboard.insertText('Z');await page.waitForFunction(()=>Object.values(localStorage).some(value=>value.includes('patchParagraphRuns')));operations=await draft();assert.equal(operations.filter(op=>op.kind==='upsertStyle').length,2);checks.push('new-character-caret-and-typed-run-plan')
  await open(1);assert.deepEqual(await draft(),operations);checks.push('typed-draft-reload')
  await page.getByRole('button',{name:'保存',exact:true}).click();await page.getByRole('link',{name:'下载 Word',exact:true}).waitFor();assert.equal(saves.length,1);assert.deepEqual(saves[0].operations,operations)
  const result=runPython({mode:'verify',path:pathOf(2),source:pathOf(1)}),download=await page.request.get(await page.getByRole('link',{name:'下载 Word',exact:true}).getAttribute('href'));assert.equal(download.status(),200);assert.equal(sha(await download.body()),result.sha256);checks.push('actual-save-download-independent-zip-and-style-readback-nonblocking-link')
  if(staticRoot)assert.equal(result.execution.entrySha256,process.env.DOCX_EXPECTED_BRIDGE_SHA256,'frozen bridge execution identity')
  writable=false;await open(2);await showPane();assert.equal(await pane().getByRole('button',{name:'新建样式…',exact:true}).isDisabled(),true);checks.push('readonly')
  await Promise.all(sourceIdentities);assert.deepEqual(errors,[])
  if(!staticRoot){for(const file of watched)assert.equal(sha(await readFile(join(identityFrontend,'src',file))),sourceHashes[file]);assert.equal(Object.keys(chunks).length,watched.length)}
  const backendAfter=await backendHashes();assert.deepEqual(backendAfter,backendBefore)
  await writeFile(join(output,'result.json'),JSON.stringify({mode:staticRoot?'frozen':'source',manifestSha256,checks,errors,saves,sourceHashes,chunks,backendBefore,backendAfter,execution:result.execution,sha256:result.sha256,parts:result.parts,requests},null,2))
}catch(error){await writeFile(join(output,'failure.json'),JSON.stringify({error:String(error),checks,errors,requests},null,2));await page?.screenshot({path:join(output,'failure.png')});throw error}finally{await browser?.close();await new Promise(ok=>server.close(ok));await vite?.close()}
