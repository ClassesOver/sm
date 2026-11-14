import assert from 'node:assert/strict'
import {createHash} from 'node:crypto'
import {execFileSync} from 'node:child_process'
import {mkdir,readFile,writeFile} from 'node:fs/promises'
import {resolve} from 'node:path'
import {fileURLToPath} from 'node:url'
import {createServer} from 'vite'
import {chromium} from 'playwright'
const frontend=fileURLToPath(new URL('../',import.meta.url)),repo=resolve(frontend,'../../..')
const mixed=process.env.PDF_TEXT_INSERT_MIXED==='1'
const output=process.env.PDF_PENDING_TEXT_OUTPUT??'/tmp/pdf-pending-text-browser',runtime=process.env.AGENT_REPORTING_PDF_ENGINE_DIR??'/tmp/pdf-multiple-text-runtime'
await mkdir(output,{recursive:true})
const python=resolve(repo,'.venv/bin/python'),input=resolve(output,'source.pdf'),cli=resolve(runtime,'dist/cli.mjs')
execFileSync(python,['-c',"from reportlab.pdfgen import canvas;import sys;c=canvas.Canvas(sys.argv[1],pagesize=(400,500));c.drawString(40,450,'Original preserved');c.save()",input])
const bytes=await readFile(input),sha=createHash('sha256').update(bytes).digest('hex');let serial=0
async function bridge(request){const path=resolve(output,`request-${serial++}.json`);await writeFile(path,JSON.stringify(request));return JSON.parse(execFileSync('node',[cli,path],{cwd:runtime,encoding:'utf8'}))}
const model=await bridge({kind:'inspect',input,includeText:true}),errors=[],httpErrors=[]
let server,browser
try{
 server=await createServer({root:frontend,configFile:resolve(frontend,'vite.config.ts'),cacheDir:resolve(output,'vite-cache'),server:{host:'127.0.0.1',port:4317,strictPort:true},plugins:[{name:'pending-text-smoke',configureServer(vite){vite.middlewares.use(async(req,res,next)=>{
  if(req.url==='/__pending__/source'){res.setHeader('Content-Type','application/pdf');res.end(bytes);return}
  if(req.url==='/__pending__/model'){res.setHeader('Content-Type','application/json');res.end(JSON.stringify({sourceSha256:sha,model}));return}
  if(req.url!=='/__pending__/')return next()
  const html=`<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head><body><button id="save">保存</button><div id="report-editor"></div><script type="module">
import {createPdfEditorView} from '/src/pdf-main.ts';import {NativeDraft} from '/src/native-draft.ts';import '/src/style.css';import '/src/office-theme.css';import '/src/pdf.css';
const identity={documentId:'pending-smoke',revision:1,sourceSha256:'${sha}',scope:{database:'db',companyId:'c',userId:'u',threadId:'t'}};
const draft=new NativeDraft(identity,localStorage);const api={file:async()=>await (await fetch('/__pending__/source')).arrayBuffer(),preview:async()=>await (await fetch('/__pending__/model')).json()};
const context={context:{...identity,format:'pdf',sourceFile:{sha256:identity.sourceSha256,path:'source.pdf',size:${bytes.length}}},editingEnabled:true,pdfTextEnabled:true};
window.smoke={draft};window.smoke.view=await createPdfEditorView({editor:document.querySelector('#report-editor'),save:document.querySelector('#save')},{api,context,draft});window.smoke.ready=true;
</script></body></html>`
  res.setHeader('Content-Type','text/html');res.end(await vite.transformIndexHtml('/__pending__/',html))
 })}}]})
 await server.listen();browser=await chromium.launch({headless:true,executablePath:process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE??'/usr/bin/chromium',args:['--no-sandbox']})
 const page=await browser.newPage({viewport:{width:1440,height:1000}})
 page.on('pageerror',error=>errors.push(error.message));page.on('response',response=>{if(response.status()>=400)httpErrors.push({url:response.url(),status:response.status()})})
 await page.goto('http://127.0.0.1:4317/__pending__/');await page.waitForFunction(()=>window.smoke?.ready,{timeout:60000})
 const insert=page.locator('[data-source-command-id="genoffice.pdf.home.edit.insertText"]'),manage=page.locator('[data-pdf-pending-text-manage]')
 async function add(text){await insert.click();const dialog=page.getByRole('dialog',{name:'插入文字',exact:true});await dialog.getByLabel('插入文字内容',{exact:true}).fill(text);await dialog.locator('[data-pdf-static-text-confirm]').click();await page.locator('.pdf-page-content').first().click({position:{x:180,y:250}});await page.waitForFunction(()=>window.smoke.draft.operations.length>0)}
 await add('First inserted');await page.waitForFunction(()=>!document.querySelector('[data-source-command-id="genoffice.pdf.home.edit.insertText"]').disabled)
 await add('Second inserted');await page.waitForFunction(()=>window.smoke.draft.operations.length===2)
 await manage.click();await page.locator('[data-pdf-pending-text-edit="1"]').click()
 const edit=page.getByRole('dialog',{name:'编辑待保存文字',exact:true});await edit.getByLabel('插入文字内容',{exact:true}).fill('Updated second')
 await edit.getByLabel('插入文字基线 X',{exact:true}).fill('160');await edit.getByLabel('插入文字基线 Y',{exact:true}).fill('220')
 await edit.getByLabel('插入文字粗体',{exact:true}).check();await edit.locator('[data-pdf-static-text-confirm]').click()
 await page.waitForFunction(()=>window.smoke.draft.operations[1]?.text==='Updated second')
 await manage.click();await page.locator('[data-pdf-pending-text-delete="0"]').click();await page.waitForFunction(()=>window.smoke.draft.operations.length===1)
 await page.getByRole('dialog',{name:'管理插入文字',exact:true}).getByRole('button',{name:'关闭',exact:true}).click()
 await page.locator('[data-source-command-id="genoffice.pdf.home.edit.undo"]').click();await page.waitForFunction(()=>window.smoke.draft.operations.length===2)
 await page.locator('[data-source-command-id="genoffice.pdf.home.edit.redo"]').click();await page.waitForFunction(()=>window.smoke.draft.operations.length===1)
 await page.reload();await page.waitForFunction(()=>window.smoke?.ready);assert.equal(await page.evaluate(()=>window.smoke.draft.operations[0].text),'Updated second')
 if(mixed){
  await page.locator('[data-pdf-ribbon-tab="edit"]').click()
  await page.getByRole('button',{name:'原位改字',exact:true}).last().click()
  const panel=page.locator('.pdf-text-editor')
  await panel.getByLabel('替换后的文字',{exact:true}).fill('Changed original')
  await panel.getByLabel('替换文字字体',{exact:true}).selectOption('courier')
  await panel.getByLabel('替换文字字号',{exact:true}).fill('12')
  await panel.getByRole('button',{name:'加入文字修改',exact:true}).click()
  await page.waitForFunction(()=>window.smoke.draft.operations.length===2)
  const insertFirst=await page.evaluate(()=>window.smoke.draft.operations)
  assert.deepEqual(insertFirst.map(op=>op.kind),['insertText','replaceText'])
  await writeFile(resolve(output,'insert-first.json'),JSON.stringify(insertFirst,null,2))
  await page.locator('[data-pdf-ribbon-tab="home"]').click();await manage.click()
  await page.locator('[data-pdf-pending-text-delete="0"]').click()
  await page.getByRole('dialog',{name:'管理插入文字',exact:true}).getByRole('button',{name:'关闭',exact:true}).click()
  await page.waitForFunction(()=>window.smoke.draft.operations.length===1&&window.smoke.draft.operations[0].kind==='replaceText')
  await add('Updated second');await page.waitForFunction(()=>window.smoke.draft.operations.length===2)
  assert.deepEqual(await page.evaluate(()=>window.smoke.draft.operations.map(op=>op.kind)),['replaceText','insertText'])
  await manage.click();await page.locator('[data-pdf-pending-text-edit="1"]').click()
  const dialog=page.getByRole('dialog',{name:'编辑待保存文字',exact:true})
  await dialog.getByLabel('插入文字基线 X',{exact:true}).fill('160');await dialog.getByLabel('插入文字基线 Y',{exact:true}).fill('220')
  await dialog.locator('[data-pdf-static-text-confirm]').click()
  await page.waitForFunction(()=>window.smoke.draft.operations[1].origin[0]===160)
 }
 await page.setViewportSize({width:390,height:700});await manage.click();await page.screenshot({path:resolve(output,'manager-narrow.png')})
 await page.locator(`[data-pdf-pending-text-edit="${mixed?1:0}"]`).click();await page.screenshot({path:resolve(output,'edit-narrow.png')})
 const layout=await page.getByRole('dialog',{name:'编辑待保存文字',exact:true}).evaluate(node=>({width:node.clientWidth,scrollWidth:node.scrollWidth,height:node.clientHeight,scrollHeight:node.scrollHeight,left:node.getBoundingClientRect().left}))
 assert.ok(layout.scrollWidth<=layout.width,JSON.stringify(layout));assert.ok(layout.left>=0,JSON.stringify(layout))
 await page.getByRole('dialog',{name:'编辑待保存文字',exact:true}).getByRole('button',{name:'取消',exact:true}).click()
 const operations=await page.evaluate(()=>window.smoke.draft.operations);assert.equal(operations.length,mixed?2:1);assert.deepEqual(operations.find(op=>op.kind==='insertText').origin,[160,220])
 const result=await bridge({kind:'patch',input,output:resolve(output,'edited.pdf'),sourceSha256:sha,operations})
 assert.deepEqual(result.appliedOperationIndices,mixed?[0,1]:[0]);assert.deepEqual(result.skippedOperations,[])
 const independent=JSON.parse(execFileSync(python,['-c',"import json,sys;from pypdf import PdfReader;p=PdfReader(sys.argv[1]).pages[0];t=p.extract_text();assert 'Updated second' in t and sys.argv[2] in t and (sys.argv[2]=='Original preserved' or 'Original preserved' not in t) and 'First inserted' not in t and 'Second inserted' not in t;print(json.dumps({'ok':True,'text':t}))",resolve(output,'edited.pdf'),mixed?'Changed original':'Original preserved'],{encoding:'utf8'}))
 assert.deepEqual(errors,[]);assert.deepEqual(httpErrors,[]);assert.equal(createHash('sha256').update(await readFile(input)).digest('hex'),sha)
 await writeFile(resolve(output,'evidence.json'),JSON.stringify({ok:true,sourceSha256:sha,operations,result,independent,layout,errors,httpErrors,scope:'Actual source PDF host, PDF.js canvas, browser draft management and CLI output; no HTTP save/publication'},null,2))
 console.log(JSON.stringify({ok:true,output,layout,applied:result.appliedOperationIndices}))
}finally{await browser?.close();await server?.close()}
