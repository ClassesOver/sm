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
const output = resolve(process.env.DOCX_EVIDENCE_DIR ?? '/home/junge/codex-evidence/smart_reporting/office-component-inventory-20261113/word/watermark/source-browser')
await mkdir(output, { recursive: true })
const sha = value => createHash('sha256').update(value).digest('hex')
const staticRoot = process.env.DOCX_TEST_DIST ? resolve(process.env.DOCX_TEST_DIST) : null
const identityFrontend = process.env.DOCX_FROZEN_FRONTEND ? resolve(process.env.DOCX_FROZEN_FRONTEND) : frontend
const manifestSha256 = staticRoot ? sha(await readFile(join(staticRoot, '.vite/manifest.json'))) : null
if (staticRoot) assert.equal(manifestSha256, process.env.DOCX_EXPECTED_MANIFEST_SHA256)
const watched = ['docx-watermark-dialog-source.tsx','docx-ribbon.ts','docx-main.tsx','docx-watermark.ts']
const sourceHashes = Object.fromEntries(await Promise.all(watched.map(async name => [name, sha(await readFile(join(identityFrontend,'src',name)))])))
const backendFiles = ['smart_reporting/reporting/delivery/docx_native.py','smart_reporting/reporting/delivery/office_engine.py','smart_reporting/report_editor/native.py','smart_reporting/report_editor/native_api.py','smart_reporting/report_editor/native_publication.py','smart_reporting/reporting/doc_engine/bridge/edit-docx.ts','smart_reporting/reporting/doc_engine/bridge/docx-watermark.ts']
const backendHashes = async () => Object.fromEntries(await Promise.all(backendFiles.map(async name => [name, sha(await readFile(join(repo,name)))])))
const backendBefore = await backendHashes()
const python = String.raw`
import json,sys,posixpath
from io import BytesIO
from pathlib import Path
from hashlib import sha256
from zipfile import ZipFile
from docx import Document
from docx.shared import Pt
from PIL import Image
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from lxml import etree
from smart_reporting.reporting.delivery.docx_native import inspect_docx,patch_docx
from smart_reporting.reporting.delivery.office_engine import bridge_execution
p=json.load(sys.stdin);path=Path(p['path'])
if p['mode']=='fixture':
    source=Document();source.add_paragraph('水印正文').runs[0].bold=True;source.add_paragraph('Second paragraph');source.add_table(rows=1,cols=1).cell(0,0).text='Untouched table';source.add_paragraph('Trailing paragraph');source.sections[0].header.paragraphs[0].text='页眉原文';source.save(path)
    Image.new('RGB',(120,80),'blue').save(path.parent/'watermark.png')
elif p['mode']=='patch':path.write_bytes(patch_docx(Path(p['source']).read_bytes(),p['operations']))
data=path.read_bytes();doc=Document(BytesIO(data))
with ZipFile(BytesIO(data)) as package:parts={name:sha256(package.read(name)).hexdigest() for name in package.namelist() if not name.endswith('/')}
if p['mode']=='verify':
    original=Path(p['source']).read_bytes();old=Document(BytesIO(original))
    assert [item.text for item in doc.paragraphs]==[item.text for item in old.paragraphs]
    assert doc.paragraphs[0].runs[0].bold and doc.tables[0].cell(0,0).text=='Untouched table'
    assert doc.sections[0].header.paragraphs[0].text=='页眉原文'
    with ZipFile(BytesIO(original)) as before,ZipFile(BytesIO(data)) as after:
        assert before.read('word/document.xml')==after.read('word/document.xml')
        assert any(after.read(name)==(path.parent/'watermark.png').read_bytes() for name in after.namelist() if name.startswith('word/media/'))
        for name in before.namelist():
            if name not in ['[Content_Types].xml','docProps/core.xml','word/_rels/document.xml.rels'] and not name.startswith('word/header'):
                assert before.read(name)==after.read(name),name
        for name in after.namelist():
            if name.startswith('word/header') and name.endswith('.xml'):
                xml=after.read(name).decode();assert 'WordPictureWatermark1' in xml and 'width:135pt;height:90pt' in xml and 'gain=' not in xml
                root=etree.fromstring(after.read(name));image=root.find('.//{urn:schemas-microsoft-com:vml}imagedata');rid=image.get('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id')
                rels=etree.fromstring(after.read(posixpath.join(posixpath.dirname(name),'_rels',posixpath.basename(name)+'.rels')))
                target=next(item.get('Target') for item in rels if item.get('Id')==rid);media=posixpath.normpath(posixpath.join(posixpath.dirname(name),target))
                assert after.read(media)==(path.parent/'watermark.png').read_bytes()
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
  const select=async(index,caret=false)=>{await body().focus();await page.evaluate(({index,caret})=>{const editor=document.querySelector('[aria-label="Word 文档编辑区"]'),p=editor.querySelectorAll('p')[index],range=document.createRange();if(caret){const walker=document.createTreeWalker(p,NodeFilter.SHOW_TEXT),text=walker.nextNode();range.setStart(text,2);range.collapse(true)}else range.selectNodeContents(p);const selected=window.getSelection();selected.removeAllRanges();selected.addRange(range);document.dispatchEvent(new Event('selectionchange'))},{index,caret});await page.waitForTimeout(150)}

  const d=()=>page.locator('.watermark-dialog')
  const openWatermark=async()=>{await page.locator('[data-tab-label="设计"]').click();await page.locator('[data-action=watermark]').click();await page.locator('[data-action=watermark-custom]').click();await d().waitFor()}
  const draft=()=>page.evaluate(()=>Object.values(localStorage).filter(value=>value.includes('styles-pane')).map(value=>JSON.parse(value)).flatMap(value=>value.operations??[]))
  const apply=async()=>{await d().getByRole('button',{name:'确定',exact:true}).click();await d().waitFor({state:'detached'});await page.waitForTimeout(80)}
  await open(1);await openWatermark();assert.equal(await d().locator('.wm-mode').count(),3);assert.equal(await d().locator('.wm-size option').count(),15);checks.push('complete-pinned-none-picture-text-family')
  await d().getByRole('button',{name:'取消',exact:true}).click();assert.deepEqual(await draft(),[]);await openWatermark();await page.keyboard.press('Escape');await d().waitFor({state:'detached'});assert.deepEqual(await draft(),[]);checks.push('cancel-and-escape-no-operations')
  await openWatermark();await page.keyboard.press('Shift+Tab');assert.ok(await page.locator('.docx-watermark-source-host').evaluate(host=>host.contains(document.activeElement)));await d().locator('.wm-mode input').nth(2).check();await d().locator('input[type=text]').evaluate(e=>e.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',isComposing:true,bubbles:true,cancelable:true})));assert.equal(await d().count(),1);assert.deepEqual(await draft(),[]);checks.push('focus-trap-and-ime-enter-no-apply')
  await d().locator('.wm-mode input').nth(1).check();const chooser=page.waitForEvent('filechooser');await d().locator('.wm-pick').click();await(await chooser).setFiles(join(output,'watermark.png'));await d().locator('.wm-pick-name').getByText('120 × 80 px').waitFor();await d().getByLabel('缩放:',{exact:true}).selectOption('150');await d().locator('.wm-check input[type=checkbox]').first().uncheck();assert.equal(await d().locator('img.wm-preview-mark').count(),1);checks.push('authorized-local-picture-scale-washout-preview')
  for(const viewport of [{width:1440,height:900},{width:390,height:640},{width:640,height:320}]){await page.setViewportSize(viewport);await d().evaluate(e=>e.scrollTop=0);await page.screenshot({path:join(output,'dialog-top-'+viewport.width+'x'+viewport.height+'.png')});await d().getByRole('button',{name:'确定',exact:true}).scrollIntoViewIfNeeded();const hit=await d().getByRole('button',{name:'确定',exact:true}).evaluate(e=>{const r=e.getBoundingClientRect();return{top:r.top,bottom:r.bottom,hit:document.elementFromPoint(r.x+r.width/2,r.y+r.height/2)===e}});assert.ok(hit.hit&&hit.top>=0&&hit.bottom<=viewport.height);await page.screenshot({path:join(output,'dialog-'+viewport.width+'x'+viewport.height+'.png')});checks.push('source-footer-hit-'+viewport.width+'x'+viewport.height)}
  await page.setViewportSize({width:1440,height:900});await apply();const before=await draft();assert.equal(before.length,1);assert.equal(before[0].kind,'setWatermark');assert.equal(before[0].watermark.scale,150);assert.equal(before[0].watermark.washout,false);assert.equal(await page.locator('.docx-picture-watermark-preview').count()>0,true);checks.push('one-native-picture-operation-canvas-preview')
  await body().focus();await page.keyboard.press('Control+z');assert.deepEqual(await draft(),[]);await page.keyboard.press('Control+y');assert.deepEqual(await draft(),before);checks.push('native-undo-redo')
  await open(1);assert.deepEqual(await draft(),before);checks.push('native-draft-reload')
  await page.getByRole('button',{name:'保存',exact:true}).click();await page.getByRole('link',{name:'下载 Word',exact:true}).waitFor();assert.equal(saves.length,1);assert.deepEqual(saves[0].operations,before)
  const result=runPython({mode:'verify',path:pathOf(2),source:pathOf(1)}),download=await page.request.get(await page.getByRole('link',{name:'下载 Word',exact:true}).getAttribute('href'));assert.equal(download.status(),200);const downloadedBytes=await download.body();assert.equal(sha(downloadedBytes),result.sha256);await writeFile(join(output,'downloaded-revision-2.docx'),downloadedBytes);checks.push('actual-download-native-media-and-body-readback-nonblocking-link')
  if(staticRoot)assert.equal(result.execution.entrySha256,process.env.DOCX_EXPECTED_BRIDGE_SHA256,'frozen bridge execution identity')
  await open(2);await openWatermark();assert.equal(await d().locator('.wm-mode input').nth(1).isChecked(),true);assert.equal(await d().getByLabel('缩放:',{exact:true}).inputValue(),'150');assert.equal(await d().locator('.wm-check input[type=checkbox]').first().isChecked(),false);assert.equal(await d().locator('img.wm-preview-mark').count(),1);await page.screenshot({path:join(output,'reopened-revision-2.png')});await page.keyboard.press('Escape');assert.equal(saves.length,1);checks.push('explicit-revision-two-picture-reopen')
  writable=false;await open(2);await page.locator('[data-tab-label="设计"]').click();assert.equal(await page.locator('[data-action=watermark]').isDisabled(),true);checks.push('readonly-disabled')
  await Promise.all(sourceIdentities);assert.deepEqual(errors,[])
  if(!staticRoot){for(const file of watched)assert.equal(sha(await readFile(join(identityFrontend,'src',file))),sourceHashes[file]);assert.equal(Object.keys(chunks).length,watched.length)}
  const backendAfter=await backendHashes();assert.deepEqual(backendAfter,backendBefore)
  await writeFile(join(output,'result.json'),JSON.stringify({mode:staticRoot?'frozen':'source',manifestSha256,checks,errors,saves,sourceHashes,chunks,backendBefore,backendAfter,execution:result.execution,sha256:result.sha256,parts:result.parts,requests},null,2))
}catch(error){await writeFile(join(output,'failure.json'),JSON.stringify({error:String(error),checks,errors,requests},null,2));await page?.screenshot({path:join(output,'failure.png')});throw error}finally{await browser?.close();await new Promise(ok=>server.close(ok));await vite?.close()}
