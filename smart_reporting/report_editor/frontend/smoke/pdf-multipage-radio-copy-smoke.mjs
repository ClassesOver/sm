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
const output=process.env.PDF_PENDING_TEXT_OUTPUT??'/tmp/pdf-multipage-radio-browser',runtime=process.env.AGENT_REPORTING_PDF_ENGINE_DIR??'/tmp/pdf-multipage-radio-runtime'
await mkdir(output,{recursive:true})
const python=resolve(repo,'.venv/bin/python'),input=resolve(output,'source.pdf'),cli=resolve(runtime,'dist/cli.mjs')
if(resume)await writeFile(input,await readFile(resolve(resume,'source.pdf')))
else execFileSync('node',['--input-type=module','-e',`import {writeFileSync} from 'node:fs';import {PDFDocument,PDFName,PDFString,StandardFonts} from 'pdf-lib';
const d=await PDFDocument.create(),p=d.addPage([400,500]);p.drawText('Original preserved',{x:40,y:450});const second=d.addPage([400,500]);second.setCropBox(20,30,380,470);const third=d.addPage([400,500]);third.setCropBox(40,50,360,450);const font=await d.embedFont(StandardFonts.TimesRomanBoldItalic),f=d.getForm();
const group=f.createRadioGroup('OriginalAnswer');group.enableRequired();['Yes','No','Maybe'].forEach((value,i)=>group.addOptionToPage(value,i===0?p:second,{x:40+i*60,y:320,width:20,height:20}));group.select('No');group.acroField.dict.set(PDFName.of('DV'),group.acroField.getOnValues()[0]);
writeFileSync(process.argv[1],await d.save({useObjectStreams:false,updateFieldAppearances:false}));`,input],{cwd:resolve(repo,'smart_reporting/reporting/pdf_engine')})
const bytes=await readFile(input),sha=createHash('sha256').update(bytes).digest('hex');let serial=0
async function bridge(request){const path=resolve(output,`request-${serial++}.json`);await writeFile(path,JSON.stringify(request));return JSON.parse(execFileSync('node',[cli,path],{cwd:runtime,encoding:'utf8'}))}
const model=await bridge({kind:'inspect',input,includeText:true}),errors=[],httpErrors=[]
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
 await page.locator('[data-pdf-ribbon-tab="formDesign"]').click()
 const card=page.locator('.pdf-formdesign-props')
 if(!resume){
  const source=model.formDesignWidgets.filter(w=>w.fieldName==='OriginalAnswer'),member=page.locator('[data-field-id="widget:'+source[1].widgetId+'"]')
  await member.press('Enter');assert.match(await card.textContent(),/整个.*单选组/);await member.press('Control+c');await member.press('Control+d');await page.waitForFunction(()=>window.smoke.draft.operations.length===1)
  assert.equal(await page.evaluate(()=>window.smoke.draft.operations[0].copyFrom.widgetId),source[0].widgetId)
  const first=page.locator('[data-field-id="pending:OriginalAnswer_copy1:1"]');await first.press('Enter');const beforeMove=await page.evaluate(()=>window.smoke.draft.operations[0].radioWidgets.map(w=>w.rect));await first.press('ArrowRight')
  assert.deepEqual(await page.evaluate(()=>window.smoke.draft.operations[0].radioWidgets.map(w=>w.rect)),beforeMove.map((rect,index)=>index===0?rect:rect.map((v,i)=>v+(i%2===0?1:0))))
  assert.equal(await card.locator('input').count(),0);assert.match(await card.textContent(),/整个.*单选组/)
  await page.setViewportSize({width:390,height:700});await page.screenshot({path:resolve(output,'source-copy-narrow.png')});layout=await card.evaluate(node=>({left:node.getBoundingClientRect().left,right:node.getBoundingClientRect().right,width:node.clientWidth,scrollWidth:node.scrollWidth}));assert.ok(layout.left>=0&&layout.right<=390&&layout.scrollWidth<=layout.width,JSON.stringify(layout));await card.getByRole('button',{name:'完成',exact:true}).click();await page.setViewportSize({width:1440,height:1000})
  const second=page.locator('.pdf-formdesign-layer').nth(2);await second.scrollIntoViewIfNeeded();await second.click({button:'right',position:{x:250,y:100}});await page.getByRole('menuitem',{name:'粘贴字段',exact:true}).click();await page.waitForFunction(()=>window.smoke.draft.operations.length===2)
  const pasted=page.locator('[data-field-id="pending:OriginalAnswer_copy2:1"]');await pasted.press('Enter');await card.getByRole('button',{name:'删除整组字段',exact:true}).click();await page.waitForFunction(()=>window.smoke.draft.operations.length===1)
  await page.locator('[data-pdf-ribbon-tab="home"]').click();await page.locator('[data-source-command-id="genoffice.pdf.home.edit.undo"]').click();await page.waitForFunction(()=>window.smoke.draft.operations.length===2)
  const before=await page.evaluate(()=>window.smoke.draft.operations);await page.locator('[data-source-command-id="genoffice.pdf.home.edit.redo"]').click();await page.waitForFunction(()=>window.smoke.draft.operations.length===1);await page.locator('[data-source-command-id="genoffice.pdf.home.edit.undo"]').click();await page.waitForFunction(()=>window.smoke.draft.operations.length===2);assert.deepEqual(await page.evaluate(()=>window.smoke.draft.operations),before)
  await page.reload();await page.waitForFunction(()=>window.smoke?.ready);assert.deepEqual(await page.evaluate(()=>window.smoke.draft.operations),before)
 }else{
  await page.locator('[data-field-id="pending:OriginalAnswer_copy1:0"]').press('Enter');await page.setViewportSize({width:390,height:700});await page.screenshot({path:resolve(output,'source-copy-narrow.png')});layout=await card.evaluate(node=>({left:node.getBoundingClientRect().left,right:node.getBoundingClientRect().right,width:node.clientWidth,scrollWidth:node.scrollWidth}));assert.ok(layout.left>=0&&layout.right<=390&&layout.scrollWidth<=layout.width,JSON.stringify(layout));await card.getByRole('button',{name:'完成',exact:true}).click();await page.setViewportSize({width:1440,height:1000})
 }
 const operations=await page.evaluate(()=>window.smoke.draft.operations)
 const confirmation=await page.evaluate(async()=>{try{await window.smoke.view.prepareSave();return null}catch(error){return error.message}});assert.match(confirmation,/请核对实际 PDF 预览/)
 await page.waitForFunction(()=>document.querySelector('#report-editor').dataset.pdfPreview==='true')
 await page.locator('.pdf-page-content').first().scrollIntoViewIfNeeded();await page.screenshot({path:resolve(output,'actual-preview.png')})
 assert.deepEqual(latest.receipt.appliedOperationIndices,Array.from({length:2},(_,index)=>index));assert.deepEqual(latest.receipt.skippedOperations,[])
 await writeFile(resolve(output,'fields.pdf'),await readFile(latest.path))
 await writeFile(resolve(output,'ui-evidence.json'),JSON.stringify({sourceSha256:sha,operations,receipt:latest.receipt,layout,errors,httpErrors,resume,scope:'actual UI and CLI preview completed before independent verifier'},null,2))
 const independent=JSON.parse(execFileSync(python,['-c',`import json,sys
from pypdf import PdfReader
r=PdfReader(sys.argv[1]);fields=r.get_fields()
expected={'OriginalAnswer','OriginalAnswer_copy1','OriginalAnswer_copy2'}
assert set(fields)==expected,fields
source=fields['OriginalAnswer']
for name in expected:
 assert fields[name]['/V']==source['/V'] and fields[name]['/DV']==source['/DV'] and fields[name]['/Opt']==source['/Opt'] and int(fields[name].get('/Ff',0))&2
 assert len(fields[name]['/Kids'])==3
 original_states=[str(w.get_object().get('/AS')) for w in source['/Kids']]
 assert [str(w.get_object().get('/AS')) for w in fields[name]['/Kids']]==original_states
assert 'Original preserved' in r.pages[0].extract_text()
assert len(r.pages)==3 and [len(p['/Annots']) for p in r.pages]==[2,5,2]
page_by_widget={(ref.idnum,ref.generation):i for i,p in enumerate(r.pages) for ref in p.get('/Annots',[])}
for name,pages in [('OriginalAnswer',[0,1,1]),('OriginalAnswer_copy1',[0,1,1]),('OriginalAnswer_copy2',[1,2,2])]:
 assert [page_by_widget[(ref.idnum,ref.generation)] for ref in fields[name]['/Kids']]==pages
assert all(a.get_object().get('/AP') for p in r.pages for a in p.get('/Annots',[]))
print(json.dumps({'ok':True,'names':list(fields),'perPageWidgets':[len(p.get('/Annots',[])) for p in r.pages],'value':str(source['/V']),'defaultValue':str(source['/DV']),'states':original_states}))`,resolve(output,'fields.pdf')],{encoding:'utf8'}))
 assert.deepEqual(errors,[]);assert.deepEqual(httpErrors,[]);assert.equal(createHash('sha256').update(await readFile(input)).digest('hex'),sha)
 await writeFile(resolve(output,'evidence.json'),JSON.stringify({ok:true,sourceSha256:sha,operations,receipt:latest.receipt,independent,layout,errors,httpErrors,scope:'Actual source host/FormDesignLayer/PDF.js/CLI preview and pypdf; no HTTP save/publication'},null,2))
 console.log(JSON.stringify({ok:true,output,independent,layout}))
}finally{await browser?.close();await server?.close()}
