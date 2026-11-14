import assert from 'node:assert/strict'
import {createHash} from 'node:crypto'
import {execFileSync} from 'node:child_process'
import {mkdir,readFile,writeFile} from 'node:fs/promises'
import {resolve} from 'node:path'
import {fileURLToPath} from 'node:url'
import {createServer} from 'vite'
import {chromium} from 'playwright'
const frontend=fileURLToPath(new URL('../',import.meta.url)),repo=resolve(frontend,'../../..')
const clipboardMode=process.env.PDF_FORM_CLIPBOARD==='1',resume=process.env.PDF_FORM_CLIPBOARD_RESUME
const seed=resume?JSON.parse(await readFile(resolve(resume,'request-1.json'),'utf8')).operations:[]
const output=process.env.PDF_PENDING_TEXT_OUTPUT??'/tmp/pdf-image-delete-browser',runtime=process.env.AGENT_REPORTING_PDF_ENGINE_DIR??'/tmp/pdf-image-delete-runtime'
await mkdir(output,{recursive:true})
const python=resolve(repo,'.venv/bin/python'),input=resolve(output,'source.pdf'),cli=resolve(runtime,'dist/cli.mjs')
if(resume)await writeFile(input,await readFile(resolve(resume,'source.pdf')))
else execFileSync('node',['--input-type=module','-e',`import {writeFileSync} from 'node:fs';import {PDFDocument,PDFName,PDFString,StandardFonts} from 'pdf-lib';
const d=await PDFDocument.create(),p=d.addPage([400,500]);p.drawText('Original preserved',{x:40,y:450});const second=d.addPage([400,500]);second.setCropBox(20,30,380,470);const font=await d.embedFont(StandardFonts.TimesRomanBoldItalic);
const image=await d.embedPng(Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==','base64'));p.drawImage(image,{x:60,y:90,width:100,height:80});p.drawImage(image,{x:240,y:300,width:80,height:60});second.drawImage(image,{x:40,y:40,width:60,height:60});
writeFileSync(process.argv[1],await d.save({useObjectStreams:false,updateFieldAppearances:false}));`,input],{cwd:resolve(repo,'smart_reporting/reporting/pdf_engine')})
const bytes=await readFile(input),sha=createHash('sha256').update(bytes).digest('hex');let serial=0
async function bridge(request){const path=resolve(output,`request-${serial++}.json`);await writeFile(path,JSON.stringify(request));return JSON.parse(execFileSync('node',[cli,path],{cwd:runtime,encoding:'utf8'}))}
const model=await bridge({kind:'inspect',input,includeText:true}),errors=[],httpErrors=[]
assert.equal(model.capabilities.editExistingImage,true);assert.equal(model.existingImages[0].removable,true)
let server,browser,latest
try{
 server=await createServer({root:frontend,configFile:resolve(frontend,'vite.config.ts'),cacheDir:resolve(output,'vite-cache'),server:{host:'127.0.0.1',port:4317,strictPort:true},plugins:[{name:'pending-text-smoke',configureServer(vite){vite.middlewares.use(async(req,res,next)=>{
  if(req.url==='/__pending__/source'){res.setHeader('Content-Type','application/pdf');res.end(bytes);return}
  if(req.url==='/__pending__/model'){res.setHeader('Content-Type','application/json');res.end(JSON.stringify({sourceSha256:sha,model}));return}
  if(req.url==='/__pending__/preview'||req.url==='/__pending__/preview-file'){
   try{
    const chunks=[];for await(const chunk of req)chunks.push(chunk);const payload=JSON.parse(Buffer.concat(chunks).toString())
    assert.equal(payload.expectedSha256,sha)
    if(req.url.endsWith('preview-file')){assert.equal(payload.expectedPreviewDigest,latest.receipt.previewDigest);res.setHeader('Content-Type','application/pdf');res.end(await readFile(latest.path));return}
    const path=resolve(output,`preview-output-${serial}.pdf`),receipt=await bridge({kind:'patch',input,output:path,sourceSha256:sha,operations:payload.operations}),actualModel=await bridge({kind:'inspect',input:path,includeText:true})
    latest={path,receipt};res.setHeader('Content-Type','application/json');res.end(JSON.stringify({...receipt,model:actualModel}));return
   }catch(error){res.statusCode=500;res.end(String(error));return}
  }
  if(req.url!=='/__pending__/')return next()
  const html=`<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head><body><button id="save">保存</button><div id="report-editor"></div><script type="module">
import {createPdfEditorView} from '/src/pdf-main.ts';import {NativeDraft} from '/src/native-draft.ts';import '/src/style.css';import '/src/office-theme.css';import '/src/pdf.css';
const identity={documentId:'pending-smoke',revision:1,sourceSha256:'${sha}',scope:{database:'db',companyId:'c',userId:'u',threadId:'t'}};
const draft=new NativeDraft(identity,localStorage);if('${resume?'yes':''}')draft.setOperations(JSON.parse(atob('${Buffer.from(JSON.stringify(seed)).toString('base64')}')));const api={file:async()=>await (await fetch('/__pending__/source')).arrayBuffer(),preview:async payload=>payload.operations.length?await(await fetch('/__pending__/preview',{method:'POST',body:JSON.stringify(payload)})).json():await (await fetch('/__pending__/model')).json(),previewFile:async payload=>await(await fetch('/__pending__/preview-file',{method:'POST',body:JSON.stringify(payload)})).arrayBuffer()};
const context={context:{...identity,format:'pdf',sourceFile:{sha256:identity.sourceSha256,path:'source.pdf',size:${bytes.length}}},editingEnabled:true,pdfTextEnabled:false};
window.smoke={draft};window.smoke.view=await createPdfEditorView({editor:document.querySelector('#report-editor'),save:document.querySelector('#save')},{api,context,draft});window.smoke.ready=true;
</script></body></html>`
  res.setHeader('Content-Type','text/html');res.end(await vite.transformIndexHtml('/__pending__/',html))
 })}}]})
 await server.listen();browser=await chromium.launch({headless:true,executablePath:process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE??'/usr/bin/chromium',args:['--no-sandbox']})
 const page=await browser.newPage({viewport:{width:1440,height:1000}})
 page.on('pageerror',error=>errors.push(error.message));page.on('response',response=>{if(response.status()>=400)httpErrors.push({url:response.url(),status:response.status()})})
 await page.goto('http://127.0.0.1:4317/__pending__/');await page.waitForFunction(()=>window.smoke?.ready,{timeout:60000})
 assert.equal(await page.locator('html').getAttribute('lang'),'zh-CN')
 assert.deepEqual(await page.locator('[data-pdf-ribbon-tab]').allTextContents(),['开始','注释','编辑','页面','视图','填写表单','表单设计'])
 let layout
 if(!resume){
  await page.locator('[data-pdf-ribbon-tab="edit"]').click();await page.locator('[data-source-command-id="genoffice.pdf.edit.objects.editImage"]').click()
  const dialog=page.getByRole('dialog',{name:'编辑已有图像',exact:true});await dialog.waitFor();const remove=dialog.getByRole('button',{name:'删除选中图像',exact:true});assert.equal(await remove.isEnabled(),true)
  await page.setViewportSize({width:390,height:700});await page.screenshot({path:resolve(output,'image-delete-narrow.png')});layout=await dialog.evaluate(node=>({left:node.getBoundingClientRect().left,right:node.getBoundingClientRect().right,width:node.clientWidth,scrollWidth:node.scrollWidth}));assert.ok(layout.left>=0&&layout.right<=390&&layout.scrollWidth<=layout.width,JSON.stringify(layout));await page.setViewportSize({width:1440,height:1000})
  await remove.click();await page.waitForFunction(()=>window.smoke.draft.operations.length===1);assert.equal(await page.evaluate(()=>window.smoke.draft.operations[0].remove),true)
  await page.locator('[data-pdf-ribbon-tab="home"]').click();await page.locator('[data-source-command-id="genoffice.pdf.home.edit.undo"]').click();await page.waitForFunction(()=>window.smoke.draft.operations.length===0);await page.locator('[data-source-command-id="genoffice.pdf.home.edit.redo"]').click();await page.waitForFunction(()=>window.smoke.draft.operations.length===1)
  const before=await page.evaluate(()=>window.smoke.draft.operations);await page.reload();await page.waitForFunction(()=>window.smoke?.ready);assert.deepEqual(await page.evaluate(()=>window.smoke.draft.operations),before)
 }
 const operations=await page.evaluate(()=>window.smoke.draft.operations)
 const confirmation=await page.evaluate(async()=>{try{await window.smoke.view.prepareSave();return null}catch(error){return error.message}});assert.match(confirmation,/请核对实际 PDF 预览/)
 await page.waitForFunction(()=>document.querySelector('#report-editor').dataset.pdfPreview==='true')
 await page.locator('.pdf-page-content').first().scrollIntoViewIfNeeded();await page.screenshot({path:resolve(output,'actual-preview.png')})
 assert.deepEqual(latest.receipt.appliedOperationIndices,Array.from({length:1},(_,index)=>index));assert.deepEqual(latest.receipt.skippedOperations,[])
 assert.match(await page.locator('.pdf-preview-review').textContent().catch(()=>''),/删除已有图像/)
 await writeFile(resolve(output,'fields.pdf'),await readFile(latest.path))
 await writeFile(resolve(output,'ui-evidence.json'),JSON.stringify({sourceSha256:sha,operations,receipt:latest.receipt,layout,errors,httpErrors,resume,scope:'actual UI and CLI preview completed before independent verifier'},null,2))
 const independent=JSON.parse(execFileSync(python,['-c',`import json,sys
import pymupdf as fitz
from pypdf import PdfReader
before=fitz.open(sys.argv[2]);after=fitz.open(sys.argv[1])
def images(doc):
 return [(p.number,tuple(row['bbox']),row['digest']) for p in doc for row in p.get_image_info(hashes=True)]
assert images(after)==images(before)[1:]
assert [len(p.get_image_info()) for p in after]==[1,1]
assert 'Original preserved' in PdfReader(sys.argv[1]).pages[0].extract_text()
print(json.dumps({'ok':True,'drawnImagesBefore':3,'drawnImagesAfter':2,'perPageImages':[1,1],'survivorPixelsAndRectsPreserved':True}))`,resolve(output,'fields.pdf'),input],{encoding:'utf8'}))
 assert.deepEqual(errors,[]);assert.deepEqual(httpErrors,[]);assert.equal(createHash('sha256').update(await readFile(input)).digest('hex'),sha)
 await writeFile(resolve(output,'evidence.json'),JSON.stringify({ok:true,sourceSha256:sha,operations,receipt:latest.receipt,independent,layout,errors,httpErrors,scope:'Actual source host/FormDesignLayer/PDF.js/CLI preview and pypdf; no HTTP save/publication'},null,2))
 console.log(JSON.stringify({ok:true,output,independent,layout}))
}finally{await browser?.close();await server?.close()}
