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
const seed=resume?JSON.parse(await readFile(resolve(resume,'evidence.json'),'utf8')).operations:[]
const output=process.env.PDF_PENDING_TEXT_OUTPUT??'/tmp/pdf-form-batch-browser',runtime=process.env.AGENT_REPORTING_PDF_ENGINE_DIR??'/tmp/pdf-form-batch-runtime'
await mkdir(output,{recursive:true})
const python=resolve(repo,'.venv/bin/python'),input=resolve(output,'source.pdf'),cli=resolve(runtime,'dist/cli.mjs')
if(resume)await writeFile(input,await readFile(resolve(resume,'source.pdf')))
else execFileSync(python,['-c',"from reportlab.pdfgen import canvas;import sys;c=canvas.Canvas(sys.argv[1],pagesize=(400,500));c.drawString(40,450,'Original preserved');c.save()",input])
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
 if(resume){
  await page.locator('[data-pdf-ribbon-tab="formDesign"]').click()
  const field=page.locator('[data-field-id="pending:Field2"]'),card=page.locator('.pdf-formdesign-props')
  await field.press('Enter');await field.press('Control+c');await card.getByRole('button',{name:'完成',exact:true}).click()
  await page.locator('#report-editor').press('Control+v');await page.waitForFunction(()=>window.smoke.draft.operations.length===7)
  assert.equal(await page.evaluate(()=>window.smoke.draft.operations[6].fieldName),'Field2_copy3')
  await page.setViewportSize({width:390,height:700});await page.screenshot({path:resolve(output,'unselected-paste-narrow.png')})
  layout=await card.evaluate(node=>({left:node.getBoundingClientRect().left,right:node.getBoundingClientRect().right,width:node.clientWidth,scrollWidth:node.scrollWidth}))
  assert.ok(layout.left>=0&&layout.right<=390&&layout.scrollWidth<=layout.width,JSON.stringify(layout))
  await card.getByRole('button',{name:'完成',exact:true}).click();await page.setViewportSize({width:1440,height:1000})
 }else{
 await page.locator('[data-pdf-ribbon-tab="formDesign"]').click()
 await page.locator('[data-source-command-id="genoffice.pdf.formDesign.addTextField"]').click()
 const layer=page.locator('.pdf-formdesign-layer').first()
 await layer.click({position:{x:40,y:70},modifiers:['Control']});await page.waitForFunction(()=>window.smoke.draft.operations.length===1)
 await page.locator('.pdf-formdesign-props').getByRole('button',{name:'完成',exact:true}).click()
 await layer.click({position:{x:40,y:200}});await page.waitForFunction(()=>window.smoke.draft.operations.length===2)
 assert.deepEqual(await page.evaluate(()=>window.smoke.draft.operations.map(op=>op.fieldName)),['Field1','Field2'])
 const card=page.locator('.pdf-formdesign-props')
 await card.getByLabel('必填',{exact:true}).check();await page.waitForFunction(()=>window.smoke.draft.operations[1].required===true)
 await card.getByLabel('默认值',{exact:true}).fill('Second field');await page.waitForFunction(()=>window.smoke.draft.operations[1].value==='Second field')
 await card.getByRole('button',{name:'完成',exact:true}).click()
 await page.locator('[data-source-command-id="genoffice.pdf.formDesign.addCheckBox"]').click()
 await layer.click({position:{x:250,y:120}});await page.waitForFunction(()=>window.smoke.draft.operations.length===3)
 await card.getByLabel('默认勾选',{exact:true}).check();await page.waitForFunction(()=>window.smoke.draft.operations[2].checked===true)
 await card.getByRole('button',{name:'完成',exact:true}).click()
 const before=await page.evaluate(()=>window.smoke.draft.operations)
 const second=page.locator('[data-field-id="pending:Field2"]');await second.press('Enter');await second.press('ArrowRight')
 await page.waitForFunction(original=>window.smoke.draft.operations[1].rect[0]===original+1,before[1].rect[0])
 assert.deepEqual(await page.evaluate(()=>window.smoke.draft.operations[0]),before[0]);assert.deepEqual(await page.evaluate(()=>window.smoke.draft.operations[2]),before[2])
 await card.getByRole('button',{name:'删除字段',exact:true}).click();await page.waitForFunction(()=>window.smoke.draft.operations.length===2)
 assert.deepEqual(await page.evaluate(()=>window.smoke.draft.operations.map(op=>op.fieldName)),['Field1','Field3'])
 await page.locator('[data-pdf-ribbon-tab="home"]').click();await page.locator('[data-source-command-id="genoffice.pdf.home.edit.undo"]').click();await page.waitForFunction(()=>window.smoke.draft.operations.length===3)
 await page.reload();await page.waitForFunction(()=>window.smoke?.ready);assert.equal(await page.evaluate(()=>window.smoke.draft.operations.length),3)
 await page.locator('[data-pdf-ribbon-tab="formDesign"]').click();await page.locator('[data-field-id="pending:Field2"]').press('Enter')
 await page.setViewportSize({width:390,height:700});await page.screenshot({path:resolve(output,'fields-narrow.png')})
 layout=await card.evaluate(node=>({left:node.getBoundingClientRect().left,right:node.getBoundingClientRect().right,width:node.clientWidth,scrollWidth:node.scrollWidth}))
 assert.ok(layout.left>=0&&layout.right<=390&&layout.scrollWidth<=layout.width,JSON.stringify(layout))
 await card.getByRole('button',{name:'完成',exact:true}).click();await page.setViewportSize({width:1440,height:1000})
 if(clipboardMode){
  const original=page.locator('[data-field-id="pending:Field2"]');await original.press('Enter');await original.press('Control+c');await original.press('Control+d')
  await page.waitForFunction(()=>window.smoke.draft.operations.length===4)
  await page.locator('[data-field-id="pending:Field2_copy1"]').press('Control+v');await page.waitForFunction(()=>window.smoke.draft.operations.length===5)
  const count=await page.evaluate(()=>window.smoke.draft.operations.length)
  await card.getByLabel('默认值',{exact:true}).press('Control+d');assert.equal(await page.evaluate(()=>window.smoke.draft.operations.length),count)
  await card.getByRole('button',{name:'完成',exact:true}).click()
  await page.locator('[data-field-id="pending:Field1"]').click({button:'right'})
  await page.getByRole('menuitem',{name:'复制字段',exact:true}).click()
  await page.locator('.pdf-formdesign-layer').first().click({button:'right',position:{x:300,y:400}})
  await page.getByRole('menuitem',{name:'粘贴字段',exact:true}).click();await page.waitForFunction(()=>window.smoke.draft.operations.length===6)
  await card.getByRole('button',{name:'完成',exact:true}).click()
  await page.screenshot({path:resolve(output,'clipboard-fields.png')})
 }
 }
 const operations=await page.evaluate(()=>window.smoke.draft.operations)
 const confirmation=await page.evaluate(async()=>{try{await window.smoke.view.prepareSave();return null}catch(error){return error.message}});assert.match(confirmation,/请核对实际 PDF 预览/)
 await page.waitForFunction(()=>document.querySelector('#report-editor').dataset.pdfPreview==='true')
 await page.locator('.pdf-page-content').first().scrollIntoViewIfNeeded();await page.screenshot({path:resolve(output,'actual-preview.png')})
 assert.deepEqual(latest.receipt.appliedOperationIndices,Array.from({length:resume?7:clipboardMode?6:3},(_,index)=>index));assert.deepEqual(latest.receipt.skippedOperations,[])
 await writeFile(resolve(output,'fields.pdf'),await readFile(latest.path))
 const independent=JSON.parse(execFileSync(python,['-c',`import json,sys
from pypdf import PdfReader
r=PdfReader(sys.argv[1]);fields=r.get_fields()
expected={'Field1','Field2','Field3'}
if sys.argv[2] in ('clipboard','resume'):
 expected|={'Field2_copy1','Field2_copy2','Field1_copy1'}
 for name in ['Field2_copy1','Field2_copy2']:
  assert fields[name]['/V']=='Second field' and int(fields[name].get('/Ff',0))&2
if sys.argv[2]=='resume':
 expected.add('Field2_copy3');assert fields['Field2_copy3']['/V']=='Second field'
assert set(fields)==expected,fields
assert fields['Field2']['/V']=='Second field' and int(fields['Field2'].get('/Ff',0))&2
assert fields['Field3'].get('/V') not in (None,'/Off')
assert 'Original preserved' in r.pages[0].extract_text()
assert len(r.pages[0]['/Annots'])==len(expected)
assert all(annot.get_object().get('/AP') for annot in r.pages[0]['/Annots'])
print(json.dumps({'ok':True,'names':list(fields),'textValue':str(fields['Field2']['/V']),'checkbox':str(fields['Field3']['/V'])}))`,resolve(output,'fields.pdf'),resume?'resume':clipboardMode?'clipboard':'batch'],{encoding:'utf8'}))
 assert.deepEqual(errors,[]);assert.deepEqual(httpErrors,[]);assert.equal(createHash('sha256').update(await readFile(input)).digest('hex'),sha)
 await writeFile(resolve(output,'evidence.json'),JSON.stringify({ok:true,sourceSha256:sha,operations,receipt:latest.receipt,independent,layout,errors,httpErrors,scope:'Actual source host/FormDesignLayer/PDF.js/CLI preview and pypdf; no HTTP save/publication'},null,2))
 console.log(JSON.stringify({ok:true,output,independent,layout}))
}finally{await browser?.close();await server?.close()}
