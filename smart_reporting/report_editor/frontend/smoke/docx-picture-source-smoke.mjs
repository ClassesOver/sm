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
const output = resolve(process.env.DOCX_EVIDENCE_DIR ?? '/home/junge/codex-evidence/smart_reporting/office-image-links-measure-20261113/word/source-browser')
await mkdir(output, { recursive: true })
const sha = value => createHash('sha256').update(value).digest('hex')
const staticRoot = process.env.DOCX_TEST_DIST ? resolve(process.env.DOCX_TEST_DIST) : null
const identityFrontend = process.env.DOCX_FROZEN_FRONTEND ? resolve(process.env.DOCX_FROZEN_FRONTEND) : frontend
const manifestSha256 = staticRoot ? sha(await readFile(join(staticRoot, '.vite/manifest.json'))) : null
if (staticRoot) assert.equal(manifestSha256, process.env.DOCX_EXPECTED_MANIFEST_SHA256)
const watched = ['docx-picture-dialogs-source.tsx','docx-picture-controls.tsx','docx-pictures.ts','docx-picture-cutout.ts','docx-ribbon.ts','docx-main.tsx']
const sourceHashes = Object.fromEntries(await Promise.all(watched.map(async name => [name, sha(await readFile(join(identityFrontend,'src',name)))])))
const backendFiles = ['smart_reporting/reporting/delivery/docx_native.py','smart_reporting/reporting/delivery/office_engine.py','smart_reporting/report_editor/native.py','smart_reporting/report_editor/native_api.py','smart_reporting/report_editor/native_publication.py','smart_reporting/reporting/doc_engine/bridge/edit-docx.ts','smart_reporting/reporting/doc_engine/bridge/docx-picture.ts']
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
    from smart_reporting.reporting.tests.test_docx_picture_dialogs import source
    path.write_bytes(source())
    image=Image.new('RGB',(120,80),'white');image.paste('blue',(30,20,90,60));image.save(path.parent/'replacement.png')
elif p['mode']=='patch':path.write_bytes(patch_docx(Path(p['source']).read_bytes(),p['operations']))
data=path.read_bytes();doc=Document(BytesIO(data))
with ZipFile(BytesIO(data)) as package:parts={name:sha256(package.read(name)).hexdigest() for name in package.namelist() if not name.endswith('/')}
if p['mode']=='verify':
    original=Path(p['source']).read_bytes();old=Document(BytesIO(original))
    assert [item.text for item in doc.paragraphs]==[item.text for item in old.paragraphs]
    assert doc.paragraphs[0].runs[0].bold and doc.tables[0].cell(0,0).text=='表格保持'
    with ZipFile(BytesIO(data)) as package:
        root=etree.fromstring(package.read('word/document.xml'));ns={'a':'http://schemas.openxmlformats.org/drawingml/2006/main','r':'http://schemas.openxmlformats.org/officeDocument/2006/relationships'}
        rid=root.xpath('//a:blip',namespaces=ns)[0].get('{'+ns['r']+'}embed');rels=etree.fromstring(package.read('word/_rels/document.xml.rels'))
        target=next(x.get('Target') for x in rels if x.get('Id')==rid);saved=package.read(posixpath.normpath(posixpath.join('word',target)))
        image=Image.open(BytesIO(saved));assert image.mode=='RGBA';assert image.getextrema()[3]==(0,255)
        image.save(path.parent/'actual-result.png')
    with ZipFile(BytesIO(original)) as before,ZipFile(BytesIO(data)) as after:
        for name in before.namelist():
            if name not in ['[Content_Types].xml','docProps/core.xml','word/document.xml','word/_rels/document.xml.rels','word/media/image1.png']:assert before.read(name)==after.read(name),name
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
    if(path==='/favicon.ico'||/favicon(?:-32)?\.(?:svg|png)$/.test(path)){res.writeHead(204);res.end();return}
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
  browser=await chromium.launch({headless:true,args:['--disable-features=LocalNetworkAccessChecks,LocalNetworkAccessPermissionCheck,BlockInsecurePrivateNetworkRequests'],executablePath:process.env.DOCX_BROWSER_EXECUTABLE ?? '/snap/chromium/current/usr/lib/chromium-browser/chrome'});page=await browser.newPage({viewport:{width:1440,height:900}})
  if(process.env.DOCX_DEBUG_EXCEPTIONS){const cdp=await page.context().newCDPSession(page);await cdp.send('Debugger.enable');await cdp.send('Debugger.setPauseOnExceptions',{state:'all'});cdp.on('Debugger.paused',async event=>{if(String(event.data?.description??'').includes("reading 'open'"))process.stdout.write('EXCEPTION '+JSON.stringify(event.callFrames.map(frame=>({name:frame.functionName,url:frame.url,location:frame.location})))+'\n');await cdp.send('Debugger.resume')})}
  page.on('pageerror',error=>errors.push(error.message));page.on('console',message=>{if(message.type()==='error')errors.push(message.text())})
  page.on('response',response=>{
    const path=new URL(response.url()).pathname
    if(response.status()>=400)process.stdout.write('HTTP '+response.status()+' '+path+'\n')
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
  const open=async revision=>{await page.goto(`${base}/reports/v1/native/styles-pane/${revision}`);await Promise.race([page.locator('.docx-source-home').waitFor({timeout:45000}),page.getByText('预览不可用，请下载原件查看。',{exact:true}).waitFor().then(async()=>{throw new Error(await page.locator('body').innerText()+' TITLES '+JSON.stringify(await page.locator('[title]').evaluateAll(nodes=>nodes.map(n=>n.title))))})])}
  const body=()=>page.getByRole('textbox',{name:'Word 文档编辑区',exact:true})
  const select=async(index,caret=false)=>{await body().focus();await page.evaluate(({index,caret})=>{const editor=document.querySelector('[aria-label="Word 文档编辑区"]'),p=editor.querySelectorAll('p')[index],range=document.createRange();if(caret){const walker=document.createTreeWalker(p,NodeFilter.SHOW_TEXT),text=walker.nextNode();range.setStart(text,2);range.collapse(true)}else range.selectNodeContents(p);const selected=window.getSelection();selected.removeAllRanges();selected.addRange(range);document.dispatchEvent(new Event('selectionchange'))},{index,caret});await page.waitForTimeout(150)}

  const draft=()=>page.evaluate(()=>Object.values(localStorage).filter(value=>value.includes('styles-pane')).map(value=>JSON.parse(value)).flatMap(value=>value.operations??[]))
  const selectImage=async()=>{await body().locator('.doc-protected[data-doc-protected=image] img').first().click();await page.locator('[data-tab-id=pictureFormat]').click()}
  const d=()=>page.locator('.docx-picture-dialog-host [role=dialog]')
  const openDialog=async action=>{await selectImage();await page.locator('[data-action=picture-'+action+']').click();await d().waitFor()}
  const apply=async()=>{await d().getByRole('button',{name:'应用',exact:true}).click();await d().waitFor({state:'detached'});await page.waitForTimeout(100)}
  await open(1);await selectImage();const picker=page.waitForEvent('filechooser');await page.locator('[data-action=picture-replace]').click();await(await picker).setFiles(join(output,'replacement.png'));await page.waitForFunction(()=>Object.values(localStorage).some(value=>value.includes('replaceImage')));checks.push('authorized-file-replacement-native-preview')
  const replaced=await draft();assert.equal(replaced.length,1);assert.equal(replaced[0].kind,'replaceImage');assert.equal(replaced[0].image.widthPx,120)
  await openDialog('crop');await d().getByRole('button',{name:'取消',exact:true}).click();assert.deepEqual(await draft(),replaced);checks.push('crop-cancel-keeps-replacement')
  await openDialog('crop');await d().evaluate(e=>e.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',isComposing:true,bubbles:true,cancelable:true})));assert.equal(await d().count(),1);assert.deepEqual(await draft(),replaced)
  await page.keyboard.press('Escape');await d().waitFor({state:'detached'});checks.push('ime-enter-and-escape-no-apply');await openDialog('crop');await body().locator('.doc-protected[data-doc-protected=image] img').nth(1).dispatchEvent('mousedown',{button:0,bubbles:true});await d().getByRole('button',{name:'应用',exact:true}).click();await page.waitForTimeout(100);assert.deepEqual(await draft(),replaced);await page.keyboard.press('Escape');checks.push('stale-selected-image-apply-rejected')
  await openDialog('crop');await page.screenshot({path:join(output,'crop-dialog.png')});
  const handles=await d().locator('[style*="cursor"]').evaluateAll(nodes=>nodes.map(n=>({cursor:n.style.cursor,rect:n.getBoundingClientRect().toJSON()})));assert.equal(handles.filter(item=>item.cursor.endsWith('resize')).length,8);assert.equal(handles.filter(item=>item.cursor==='move').length,1);await writeFile(join(output,'crop-handles.json'),JSON.stringify(handles,null,2))
  const southeast=d().locator('[style*="nwse-resize"]').last();const r=await southeast.boundingBox();assert.ok(r);await page.mouse.move(r.x+r.width/2,r.y+r.height/2);await page.mouse.down();await page.mouse.move(r.x+r.width/2-20,r.y+r.height/2-10,{steps:4});await page.mouse.up();const move=d().locator('[style*="cursor: move"]');const m=await move.boundingBox();await page.mouse.move(m.x+m.width/2,m.y+m.height/2);await page.mouse.down();await page.mouse.move(m.x+m.width/2+5,m.y+m.height/2+3,{steps:3});await page.mouse.up();await apply();const cropped=await draft();assert.ok(cropped[0].image.widthPx<120&&cropped[0].image.heightPx<80);checks.push('source-eight-handles-drag-crop-original-pixels')
  await body().focus();await page.keyboard.press('Control+z');assert.deepEqual(await draft(),replaced);await page.keyboard.press('Control+y');assert.deepEqual(await draft(),cropped);checks.push('native-image-undo-redo')
  await open(1);assert.deepEqual(await draft(),cropped);checks.push('picture-native-draft-reload')
  await openDialog('cutout');for(const viewport of [{width:390,height:640},{width:640,height:320}]){await page.setViewportSize(viewport);await d().getByRole('button',{name:'应用',exact:true}).scrollIntoViewIfNeeded();const hit=await d().getByRole('button',{name:'应用',exact:true}).evaluate(e=>{const r=e.getBoundingClientRect();return document.elementFromPoint(r.x+r.width/2,r.y+r.height/2)===e});assert.ok(hit);await page.screenshot({path:join(output,'cutout-'+viewport.width+'x'+viewport.height+'.png')})};await page.setViewportSize({width:1440,height:900});checks.push('narrow-and-low-height-footer-reachable');await d().locator('input[type=range]').fill('30');await page.screenshot({path:join(output,'cutout-dialog.png')});await apply();const before=await draft();assert.equal(before.length,1);assert.equal(before[0].image.mime,'image/png');checks.push('source-tolerance-preview-full-resolution-transparent-apply')
  await page.getByRole('button',{name:'保存',exact:true}).click();await page.getByRole('link',{name:'下载 Word',exact:true}).waitFor();assert.equal(saves.length,1);assert.deepEqual(saves[0].operations,before)
  const result=runPython({mode:'verify',path:pathOf(2),source:pathOf(1)}),download=await page.request.get(await page.getByRole('link',{name:'下载 Word',exact:true}).getAttribute('href'));assert.equal(download.status(),200);const downloadedBytes=await download.body();assert.equal(sha(downloadedBytes),result.sha256);await writeFile(join(output,'downloaded-revision-2.docx'),downloadedBytes);checks.push('actual-download-native-media-alpha-body-readback-nonblocking-link')
  if(staticRoot)assert.equal(result.execution.entrySha256,process.env.DOCX_EXPECTED_BRIDGE_SHA256,'frozen bridge execution identity')
  await open(2);await openDialog('cutout');await page.screenshot({path:join(output,'reopened-revision-2.png')});await page.keyboard.press('Escape');assert.equal(saves.length,1);checks.push('explicit-revision-two-picture-reopen');writable=false;await open(2);await selectImage();assert.equal(await page.locator('[data-action=picture-crop]').isDisabled(),true);assert.equal(await page.locator('[data-action=picture-cutout]').isDisabled(),true);assert.equal(await page.locator('[data-action=picture-replace]').isDisabled(),true);checks.push('readonly-picture-actions-disabled')
  await Promise.all(sourceIdentities);assert.deepEqual(errors,[])
  if(!staticRoot){for(const file of watched)assert.equal(sha(await readFile(join(identityFrontend,'src',file))),sourceHashes[file]);assert.equal(Object.keys(chunks).length,watched.length)}
  const backendAfter=await backendHashes();assert.deepEqual(backendAfter,backendBefore)
  await writeFile(join(output,'result.json'),JSON.stringify({mode:staticRoot?'frozen':'source',manifestSha256,checks,errors,saves,sourceHashes,chunks,backendBefore,backendAfter,execution:result.execution,sha256:result.sha256,parts:result.parts,requests},null,2))
}catch(error){await writeFile(join(output,'failure.json'),JSON.stringify({error:String(error),checks,errors,requests},null,2));await page?.screenshot({path:join(output,'failure.png')});throw error}finally{await browser?.close();await new Promise(ok=>server.close(ok));await vite?.close()}
