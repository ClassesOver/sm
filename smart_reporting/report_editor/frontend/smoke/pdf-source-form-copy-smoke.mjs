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
const output=process.env.PDF_PENDING_TEXT_OUTPUT??'/tmp/pdf-source-copy-browser',runtime=process.env.AGENT_REPORTING_PDF_ENGINE_DIR??'/tmp/pdf-source-copy-runtime'
await mkdir(output,{recursive:true})
const python=resolve(repo,'.venv/bin/python'),input=resolve(output,'source.pdf'),cli=resolve(runtime,'dist/cli.mjs')
if(resume)await writeFile(input,await readFile(resolve(resume,'source.pdf')))
else execFileSync('node',['--input-type=module','-e',`import {writeFileSync} from 'node:fs';import {PDFDocument,PDFName,PDFString,StandardFonts} from 'pdf-lib';
const d=await PDFDocument.create(),p=d.addPage([400,500]);p.drawText('Original preserved',{x:40,y:450});const second=d.addPage([400,500]);second.setCropBox(20,30,380,470);const font=await d.embedFont(StandardFonts.TimesRomanBoldItalic),f=d.getForm();
const t=f.createTextField('OriginalText');t.setText('Alice');t.enableRequired();t.addToPage(p,{x:40,y:320,width:160,height:24,font});t.acroField.dict.set(PDFName.of('DV'),PDFString.of('Default name'));
const c=f.createCheckBox('OriginalCheck');c.addToPage(p,{x:40,y:260,width:20,height:20});c.check();
const choice=f.createDropdown('OriginalChoice');choice.addOptions(['A','B']);choice.select('B');choice.addToPage(p,{x:40,y:200,width:160,height:24,font});choice.acroField.dict.set(PDFName.of('DV'),PDFString.of('A'));
writeFileSync(process.argv[1],await d.save({useObjectStreams:false}));`,input],{cwd:resolve(repo,'smart_reporting/reporting/pdf_engine')})
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
 let layout
 if(!resume){
 await page.locator('[data-pdf-ribbon-tab="formDesign"]').click()
 const original=name=>page.locator('[data-field-id="widget:'+model.formDesignWidgets.find(w=>w.fieldName===name).widgetId+'"]')
 const card=page.locator('.pdf-formdesign-props')
 await original('OriginalText').press('Enter');await original('OriginalText').press('Control+c');await original('OriginalText').press('Control+d')
 await page.waitForFunction(()=>window.smoke.draft.operations.length===1)
 assert.equal(await page.evaluate(()=>window.smoke.draft.operations[0].copyFrom.fieldName),'OriginalText')
 assert.equal(await card.locator('input').count(),0)
 await page.setViewportSize({width:390,height:700});await page.screenshot({path:resolve(output,'source-copy-narrow.png')})
 layout=await card.evaluate(node=>({left:node.getBoundingClientRect().left,right:node.getBoundingClientRect().right,width:node.clientWidth,scrollWidth:node.scrollWidth}))
 assert.ok(layout.left>=0&&layout.right<=390&&layout.scrollWidth<=layout.width,JSON.stringify(layout))
 await card.getByRole('button',{name:'完成',exact:true}).click();await page.setViewportSize({width:1440,height:1000})
 const second=page.locator('.pdf-formdesign-layer').nth(1);await second.scrollIntoViewIfNeeded();await second.click({button:'right',position:{x:250,y:100}});await page.getByRole('menuitem',{name:'粘贴字段',exact:true}).click()
 await page.waitForFunction(()=>window.smoke.draft.operations.length===2);await card.getByRole('button',{name:'完成',exact:true}).click()
 await original('OriginalCheck').scrollIntoViewIfNeeded();await original('OriginalCheck').click({button:'right'});await page.getByRole('menuitem',{name:'复制字段',exact:true}).click()
 await second.scrollIntoViewIfNeeded();await second.click({button:'right',position:{x:250,y:100}});await page.getByRole('menuitem',{name:'粘贴字段',exact:true}).click();await page.waitForFunction(()=>window.smoke.draft.operations.length===3);await card.getByRole('button',{name:'完成',exact:true}).click()
 await original('OriginalChoice').scrollIntoViewIfNeeded();await original('OriginalChoice').click({button:'right'});await page.getByRole('menuitem',{name:'重复字段',exact:true}).click();await page.waitForFunction(()=>window.smoke.draft.operations.length===4);await card.getByRole('button',{name:'完成',exact:true}).click()
 const before=await page.evaluate(()=>window.smoke.draft.operations)
 await page.locator('[data-pdf-ribbon-tab="home"]').click();await page.locator('[data-source-command-id="genoffice.pdf.home.edit.undo"]').click();await page.waitForFunction(()=>window.smoke.draft.operations.length===3)
 await page.locator('[data-source-command-id="genoffice.pdf.home.edit.redo"]').click();await page.waitForFunction(()=>window.smoke.draft.operations.length===4);assert.deepEqual(await page.evaluate(()=>window.smoke.draft.operations),before)
 await page.reload();await page.waitForFunction(()=>window.smoke?.ready);assert.deepEqual(await page.evaluate(()=>window.smoke.draft.operations),before)
 }else{
  await page.locator('[data-pdf-ribbon-tab="formDesign"]').click();await page.locator('[data-field-id="pending:OriginalText_copy1"]').press('Enter');await page.setViewportSize({width:390,height:700});const card=page.locator('.pdf-formdesign-props');await page.screenshot({path:resolve(output,'source-copy-narrow.png')});layout=await card.evaluate(node=>({left:node.getBoundingClientRect().left,right:node.getBoundingClientRect().right,width:node.clientWidth,scrollWidth:node.scrollWidth}));assert.ok(layout.left>=0&&layout.right<=390&&layout.scrollWidth<=layout.width,JSON.stringify(layout));await card.getByRole('button',{name:'完成',exact:true}).click();await page.setViewportSize({width:1440,height:1000})
 }
 const operations=await page.evaluate(()=>window.smoke.draft.operations)
 const confirmation=await page.evaluate(async()=>{try{await window.smoke.view.prepareSave();return null}catch(error){return error.message}});assert.match(confirmation,/请核对实际 PDF 预览/)
 await page.waitForFunction(()=>document.querySelector('#report-editor').dataset.pdfPreview==='true')
 await page.locator('.pdf-page-content').first().scrollIntoViewIfNeeded();await page.screenshot({path:resolve(output,'actual-preview.png')})
 assert.deepEqual(latest.receipt.appliedOperationIndices,Array.from({length:4},(_,index)=>index));assert.deepEqual(latest.receipt.skippedOperations,[])
 await writeFile(resolve(output,'fields.pdf'),await readFile(latest.path))
 await writeFile(resolve(output,'ui-evidence.json'),JSON.stringify({sourceSha256:sha,operations,receipt:latest.receipt,layout,errors,httpErrors,resume,scope:'actual UI and CLI preview completed before independent verifier'},null,2))
 const independent=JSON.parse(execFileSync(python,['-c',`import json,sys
from pypdf import PdfReader
r=PdfReader(sys.argv[1]);fields=r.get_fields()
expected={'OriginalText','OriginalCheck','OriginalChoice','OriginalText_copy1','OriginalText_copy2','OriginalCheck_copy1','OriginalChoice_copy1'}
assert set(fields)==expected,fields
for name in ['OriginalText','OriginalText_copy1','OriginalText_copy2']:
 assert fields[name]['/V']=='Alice' and fields[name]['/DV']=='Default name' and int(fields[name].get('/Ff',0))&2
for name in ['OriginalCheck','OriginalCheck_copy1']:
 assert fields[name]['/V'] not in ('/Off',None)
for name in ['OriginalChoice','OriginalChoice_copy1']:
 assert fields[name]['/V']=='B' and fields[name]['/DV']=='A' and [list(option) for option in fields[name]['/Opt']]==[['A','A'],['B','B']]
assert 'Original preserved' in r.pages[0].extract_text()
assert len(r.pages)==2 and len(r.pages[0]['/Annots'])==5 and len(r.pages[1]['/Annots'])==2
assert all(a.get_object().get('/AP') for p in r.pages for a in p.get('/Annots',[]))
print(json.dumps({'ok':True,'names':list(fields),'perPageWidgets':[len(p.get('/Annots',[])) for p in r.pages]}))`,resolve(output,'fields.pdf')],{encoding:'utf8'}))
 assert.deepEqual(errors,[]);assert.deepEqual(httpErrors,[]);assert.equal(createHash('sha256').update(await readFile(input)).digest('hex'),sha)
 await writeFile(resolve(output,'evidence.json'),JSON.stringify({ok:true,sourceSha256:sha,operations,receipt:latest.receipt,independent,layout,errors,httpErrors,scope:'Actual source host/FormDesignLayer/PDF.js/CLI preview and pypdf; no HTTP save/publication'},null,2))
 console.log(JSON.stringify({ok:true,output,independent,layout}))
}finally{await browser?.close();await server?.close()}
