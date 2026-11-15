import assert from 'node:assert/strict'
import {createHash} from 'node:crypto'
import {execFileSync} from 'node:child_process'
import {mkdir,readFile,writeFile} from 'node:fs/promises'
import {resolve} from 'node:path'
import {fileURLToPath} from 'node:url'
import {createServer} from 'vite'
import {chromium} from 'playwright'
const frontend=fileURLToPath(new URL('../',import.meta.url)),repo=resolve(frontend,'../../..')
const output=process.env.PDF_PENDING_TEXT_OUTPUT??'/tmp/pdf-move-text-browser',runtime=process.env.AGENT_REPORTING_PDF_ENGINE_DIR??'/tmp/pdf-move-text-runtime'
await mkdir(output,{recursive:true})
const python=resolve(repo,'.venv/bin/python'),input=resolve(output,'source.pdf'),cli=resolve(runtime,'dist/cli.mjs')
execFileSync(python,['-c',"from reportlab.pdfgen import canvas;import sys;c=canvas.Canvas(sys.argv[1],pagesize=(400,500));c.drawString(40,450,'Original preserved');c.save()",input])
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
const draft=new NativeDraft(identity,localStorage);const api={file:async()=>await (await fetch('/__pending__/source')).arrayBuffer(),preview:async payload=>payload.operations.length?await(await fetch('/__pending__/preview',{method:'POST',body:JSON.stringify(payload)})).json():await (await fetch('/__pending__/model')).json(),previewFile:async payload=>await(await fetch('/__pending__/preview-file',{method:'POST',body:JSON.stringify(payload)})).arrayBuffer()};
const context={context:{...identity,format:'pdf',sourceFile:{sha256:identity.sourceSha256,path:'source.pdf',size:${bytes.length}}},editingEnabled:true,pdfTextEnabled:true};
window.smoke={draft};window.smoke.view=await createPdfEditorView({editor:document.querySelector('#report-editor'),save:document.querySelector('#save')},{api,context,draft});window.smoke.ready=true;
</script></body></html>`
  res.setHeader('Content-Type','text/html');res.end(await vite.transformIndexHtml('/__pending__/',html))
 })}}]})
 await server.listen();browser=await chromium.launch({headless:true,executablePath:process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE??'/usr/bin/chromium',args:['--no-sandbox']})
 const page=await browser.newPage({viewport:{width:1440,height:1000}})
 page.on('pageerror',error=>errors.push(error.message));page.on('response',response=>{if(response.status()>=400)httpErrors.push({url:response.url(),status:response.status()})})
 await page.goto('http://127.0.0.1:4317/__pending__/');await page.waitForFunction(()=>window.smoke?.ready,{timeout:60000})
 const edit=page.locator('[data-source-command-id="genoffice.pdf.home.edit.editText"]')
 await edit.click();await page.getByLabel('原文位移 X',{exact:true}).fill('40');await page.getByLabel('原文位移 Y',{exact:true}).fill('-40')
 const incomplete=await page.evaluate(async()=>{try{await window.smoke.view.prepareSave();return null}catch(error){return error.message}});assert.match(incomplete,/先暂存原文移动/)
 await page.locator('[data-pdf-move-text]').click();await page.waitForFunction(()=>window.smoke.draft.operations[0]?.kind==='moveText')
 await page.waitForFunction(()=>document.querySelector('[data-source-command-id="genoffice.pdf.home.edit.insertText"]').disabled===true)
 assert.equal(await page.locator('[data-source-command-id="genoffice.pdf.home.edit.insertText"]').isDisabled(),true)
 await page.locator('[data-source-command-id="genoffice.pdf.home.edit.undo"]').click();await page.waitForFunction(()=>window.smoke.draft.operations.length===0)
 await page.locator('[data-source-command-id="genoffice.pdf.home.edit.redo"]').click();await page.waitForFunction(()=>window.smoke.draft.operations[0]?.kind==='moveText')
 await page.reload();await page.waitForFunction(()=>window.smoke?.ready);await edit.click()
 assert.equal(await page.getByLabel('原文位移 X',{exact:true}).inputValue(),'40');assert.equal(await page.getByLabel('原文位移 Y',{exact:true}).inputValue(),'-40')
 await page.setViewportSize({width:390,height:700});await page.locator('[data-pdf-move-text]').scrollIntoViewIfNeeded();await page.screenshot({path:resolve(output,'move-narrow.png')})
 const operations=await page.evaluate(()=>window.smoke.draft.operations);assert.equal(operations.length,1);assert.deepEqual(operations[0].delta,[40,-40])
 await page.setViewportSize({width:1440,height:1000})
 const confirmation=await page.evaluate(async()=>{try{await window.smoke.view.prepareSave();return null}catch(error){return error.message}});assert.match(confirmation,/请核对实际 PDF 预览/)
 await page.waitForFunction(()=>document.querySelector('#report-editor').dataset.pdfPreview==='true')
 await page.locator('.pdf-page-content').first().scrollIntoViewIfNeeded();await page.screenshot({path:resolve(output,'actual-preview.png')})
 assert.deepEqual(latest.receipt.appliedOperationIndices,[0]);assert.deepEqual(latest.receipt.skippedOperations,[])
 const actual=await readFile(latest.path);await writeFile(resolve(output,'moved.pdf'),actual)
 const independent=JSON.parse(execFileSync(python,['-c',`import sys,json
from pypdf import PdfReader
def info(path):
 rows=[];p=PdfReader(path).pages[0]
 p.extract_text(visitor_text=lambda text,cm,tm,font,size:rows.append((text,cm,tm,font,size)))
 text,cm,tm,font,size=next(item for item in rows if 'Original preserved' in item[0])
 return {'text':text,'x':tm[4]*cm[0]+tm[5]*cm[2]+cm[4],'y':tm[4]*cm[1]+tm[5]*cm[3]+cm[5],'font':str(font.get('/BaseFont')),'size':size}
before=info(sys.argv[1]);after=info(sys.argv[2])
assert abs(after['x']-before['x']-40)<.05 and abs(after['y']-before['y']+40)<.05,(before,after)
assert after['font']==before['font'] and after['size']==before['size']
print(json.dumps({'ok':True,'before':before,'after':after}))`,input,resolve(output,'moved.pdf')],{encoding:'utf8'}))
 assert.deepEqual(errors,[]);assert.deepEqual(httpErrors,[]);assert.equal(createHash('sha256').update(await readFile(input)).digest('hex'),sha)
 await writeFile(resolve(output,'evidence.json'),JSON.stringify({ok:true,sourceSha256:sha,operations,receipt:latest.receipt,independent,errors,httpErrors,scope:'Actual source PDF host/PDF.js/CLI preview and independent pypdf, no HTTP save or publication'},null,2))
 console.log(JSON.stringify({ok:true,output,independent}))
}finally{await browser?.close();await server?.close()}
