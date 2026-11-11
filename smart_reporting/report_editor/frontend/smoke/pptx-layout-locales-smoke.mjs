import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { mkdir, readFile, writeFile } from 'node:fs/promises'
import { createServer } from 'node:http'
import { dirname, extname, resolve } from 'node:path'
import { spawnSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import { chromium } from 'playwright'

const frontend=resolve(dirname(fileURLToPath(import.meta.url)),'..'),repo=resolve(frontend,'../../..'),staticRoot=resolve(frontend,'../static')
const output=process.env.PPTX_LAYOUT_EVIDENCE??'/tmp/pptx-layout-locales-built-20261111',port=Number(process.env.PPTX_LAYOUT_PORT??4307)
const initialOnly=process.env.PPTX_LAYOUT_INITIAL_ONLY==='1'
const sha=bytes=>createHash('sha256').update(bytes).digest('hex')
const manifestSha256=sha(await readFile(resolve(staticRoot,'.vite/manifest.json')))
assert.equal(manifestSha256,process.env.PPTX_EXPECTED_MANIFEST_SHA256)
await mkdir(output,{recursive:true})
const python=[
  'import base64,json,sys',
  'from io import BytesIO',
  'from pptx import Presentation',
  'from pptx.oxml.ns import qn',
  'from pptx.util import Inches',
  'from reportlab.pdfgen import canvas',
  'from smart_reporting.report_editor.native_office import inspect_office,patch_office',
  'from smart_reporting.report_editor.slides_render import render_pptx_tree',
  'p=json.load(sys.stdin)',
  "if p['mode']=='create':",
  '    presentation=Presentation()',
  "    presentation.slide_layouts[1]._element.find(qn('p:cSld')).set('name','Revenue Review')",
  '    slide=presentation.slides.add_slide(presentation.slide_layouts[6])',
  '    shape=slide.shapes.add_textbox(Inches(1),Inches(1),Inches(5),Inches(1))',
  "    shape.name='TextBox 1';shape.text='Layout localization source fixture'",
  '    stream=BytesIO();presentation.save(stream);content=stream.getvalue()',
  "    pdfstream=BytesIO();pdf=canvas.Canvas(pdfstream);pdf.drawString(30,700,'Layout fixture');pdf.save()",
  "    print(json.dumps({'bytes':base64.b64encode(content).decode(),'pdf':base64.b64encode(pdfstream.getvalue()).decode(),'model':inspect_office('pptx',content),'tree':render_pptx_tree(content)}))",
  'else:',
  "    content=base64.b64decode(p['bytes'])",
  "    if p['operations']:content=patch_office('pptx',content,p['operations'])",
  '    print(json.dumps(render_pptx_tree(content)))',
].join('\n')
function engine(payload){const result=spawnSync(resolve(repo,'.venv/bin/python'),['-c',python],{cwd:repo,env:{...process.env,PYTHONPATH:repo},input:JSON.stringify(payload),encoding:'utf8',maxBuffer:20*1024*1024});assert.equal(result.status,0,result.stderr);return JSON.parse(result.stdout)}
const fixture=engine({mode:'create'}),source=Buffer.from(fixture.bytes,'base64'),sourceSha256=sha(source)
await writeFile(resolve(output,'source.pptx'),source)
const blank=fixture.model.layouts.find(item=>item.name==='Blank'&&item.layoutType==='blank'),title=fixture.model.layouts.find(item=>item.name==='Title Slide'&&item.layoutType==='title'),custom=fixture.model.layouts.find(item=>item.name==='Revenue Review')
assert.ok(blank&&title&&custom)
const requests=[],pageErrors=[],consoleErrors=[],failedResponses=[],runtimeJavaScript=new Map(),identities=[]
const server=createServer(async(request,response)=>{try{const path=new URL(request.url,'http://127.0.0.1').pathname,file=resolve(staticRoot,path.replace(/^\/reports\/v1\/editor\/assets\//,''));assert.ok(file.startsWith(staticRoot+'/'));const content=await readFile(file);response.writeHead(200,{'Content-Type':extname(file)==='.js'?'application/javascript':extname(file)==='.css'?'text/css':'text/html'});response.end(content)}catch{response.writeHead(404);response.end('not found')}})
await new Promise((done,reject)=>{server.once('error',reject);server.listen(port,'127.0.0.1',done)})
let browser,page
try{
  browser=await chromium.launch({headless:true,...(process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE?{executablePath:process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE}:{})})
  page=await browser.newPage({viewport:{width:1600,height:1100}})
  page.on('pageerror',error=>pageErrors.push(error.message));page.on('console',message=>{if(message.type()==='error')consoleErrors.push(message.text())})
  page.on('response',response=>{const path=new URL(response.url()).pathname;if(response.status()>=400)failedResponses.push({path,status:response.status()});if(response.ok()&&path.endsWith('.js'))identities.push(response.body().then(async bytes=>{const disk=await readFile(resolve(staticRoot,path.replace(/^\/reports\/v1\/editor\/assets\//,'')));assert.equal(sha(bytes),sha(disk),path);runtimeJavaScript.set(path,{path,size:bytes.length,sha256:sha(bytes)})}))})
  await page.route('**/favicon.ico',route=>route.fulfill({contentType:'image/svg+xml',body:'<svg xmlns="http://www.w3.org/2000/svg"/>'}))
  const scope={database:'layout-fixture',companyId:'fixture',userId:'fixture',threadId:'fixture'}
  await page.route('**/reports/v1/native/layout-fixture/1/api/**',async route=>{
    const request=route.request(),path=new URL(request.url()).pathname,payload=request.method()==='POST'?request.postDataJSON():undefined;requests.push({path,method:request.method(),payload})
    if(path.endsWith('/context'))return route.fulfill({json:{context:{documentId:'layout-fixture',format:'pptx',revision:1,parentRevision:null,scope,sourceFile:{path:'native/layout-fixture.pptx',size:source.length,sha256:sourceSha256,mediaType:'application/vnd.openxmlformats-officedocument.presentationml.presentation'},origin:'upload'},csrfToken:'fixture-only-csrf',capabilities:{pptx_editor:true},editingEnabled:true,aiEnabled:true}})
    if(path.endsWith('/file'))return route.fulfill({body:source,contentType:'application/vnd.openxmlformats-officedocument.presentationml.presentation'})
    if(path.endsWith('/preview.pdf'))return route.fulfill({body:Buffer.from(fixture.pdf,'base64'),contentType:'application/pdf'})
    assert.equal(payload?.expectedSha256,sourceSha256,path)
    if(path.endsWith('/preview')){assert.deepEqual(payload.operations,[]);return route.fulfill({json:{sourceSha256,draftSha256:sourceSha256,model:fixture.model}})}
    if(path.endsWith('/render-tree'))return route.fulfill({json:payload.operations?.length?engine({mode:'render',bytes:fixture.bytes,operations:payload.operations}):fixture.tree})
    throw new Error('Unexpected layout smoke API: '+path)
  })
  await page.addInitScript(()=>{if(window.top===window&&location.protocol==='http:')history.replaceState(null,'','/reports/v1/native/layout-fixture/1')})
  await page.goto('http://127.0.0.1:'+port+'/reports/v1/editor/assets/native.html')
  await page.locator('.slides-native-ribbon').waitFor({timeout:60000});await page.locator('.slides-canvas canvas').first().waitFor({timeout:60000})
  const ribbonIcons=await page.locator('.slides-native-ribbon button[data-command]').evaluateAll(buttons=>({count:buttons.length,invalid:buttons.filter(button=>button.querySelectorAll('svg').length!==1||!button.querySelector('svg path,svg rect,svg circle,svg line,svg polyline,svg polygon,svg text')).map(button=>button.dataset.command)}))
  assert.ok(ribbonIcons.count>70);assert.deepEqual(ribbonIcons.invalid,[])
  const entryScripts=await page.locator('script[src]').evaluateAll(scripts=>scripts.map(script=>new URL(script.src).pathname))
  const snapshot=()=>page.locator('select[data-command=layout],select[data-command=addSlideWithLayout],#layout-select').evaluateAll(pickers=>pickers.map(picker=>({command:picker.dataset.command??picker.id,aria:picker.getAttribute('aria-label'),value:picker.value,options:[...picker.options].map(option=>({value:option.value,text:option.textContent}))})))
  const assertLabels=pickers=>{for(const picker of pickers){assert.equal(picker.options.find(option=>option.value===blank.path)?.text,'空白');assert.equal(picker.options.find(option=>option.value===title.path)?.text,'标题幻灯片');assert.equal(picker.options.find(option=>option.value===custom.path)?.text,'Revenue Review · 标题和内容');assert.match(picker.aria,/版式/)}}
  const initial=await snapshot();assert.ok(initial.length>=3);assertLabels(initial)
  assert.equal(await page.locator('#object-select option:checked').textContent(),'TextBox 1');assert.match(await page.locator('.native-ai-context').textContent(),/TextBox 1/)
  await page.screenshot({path:resolve(output,'initial-layouts.png'),fullPage:true})
  let refreshed,reverse,draft
  if(!initialOnly){
  await page.locator('#layout-select').selectOption(title.path)
  await page.screenshot({path:resolve(output,'title-layout.png'),fullPage:true})
  await page.locator('#layout-select').selectOption(custom.path)
  refreshed=await snapshot();assertLabels(refreshed)
  for(const picker of refreshed.filter(item=>item.command==='layout'||item.command==='layout-select'))assert.equal(picker.value,custom.path)
  await page.screenshot({path:resolve(output,'custom-layout.png'),fullPage:true})
  await page.locator('select[data-command=layout]').first().selectOption(title.path)
  assert.equal(await page.locator('#layout-select').inputValue(),title.path)
  reverse=await snapshot();assertLabels(reverse)
  await page.locator('#layout-select').selectOption(custom.path)
  await page.locator('select[data-command=addSlideWithLayout]').selectOption(blank.path)
  await page.waitForFunction(()=>[...document.querySelectorAll('.slide-list li')].some(item=>item.textContent.includes('新建幻灯片 · 空白')))
  draft=await page.evaluate(()=>{const key=Object.keys(localStorage).find(key=>key.startsWith('native-editor-draft:v1:'));return key?JSON.parse(localStorage.getItem(key)):null})
  assert.ok(draft);assert.equal(draft.identity.sourceSha256,sourceSha256);assert.deepEqual(draft.operations[0].newSlides,[{withLayout:blank.path}]);assert.ok(draft.operations[0].slideLayouts.some(item=>item.layoutPath===custom.path));assertLabels(await snapshot())
  await page.screenshot({path:resolve(output,'new-blank-layout.png'),fullPage:true})
  await page.locator('[data-source-action=onUndo]').click();assert.equal(await page.locator('#object-select option:checked').textContent(),'TextBox 1');assert.match(await page.locator('.native-ai-context').textContent(),/TextBox 1/)
  }
  await page.waitForLoadState('networkidle')
  await Promise.all(identities);assert.ok(runtimeJavaScript.size>0);assert.deepEqual(pageErrors,[]);assert.deepEqual(consoleErrors,[]);assert.deepEqual(failedResponses,[]);assert.equal(sha(await readFile(resolve(output,'source.pptx'))),sourceSha256)
  const evidence={ok:true,mode:initialOnly?'built-browser-layout-entry-only':'built-browser-layout-only',authentication:'Playwright native API route fixture; not production authentication',engine:'actual inspect/patch/render PPTX',browserVersion:browser.version(),port,manifestSha256,sourceSha256,entryScripts,ribbonIcons,layoutPaths:{blank:blank.path,title:title.path,custom:custom.path},initial,refreshed,reverse,draft,runtimeJavaScript:[...runtimeJavaScript.values()],requests,pageErrors,consoleErrors,failedResponses}
  await writeFile(resolve(output,'evidence.json'),JSON.stringify(evidence,null,2));console.log(JSON.stringify({ok:true,output,manifestSha256,javascriptCount:runtimeJavaScript.size,layoutPaths:evidence.layoutPaths}))
}catch(error){if(page){await page.screenshot({path:resolve(output,'failure.png'),fullPage:true}).catch(()=>{});await writeFile(resolve(output,'failure.html'),await page.content()).catch(()=>{});await writeFile(resolve(output,'failure-evidence.json'),JSON.stringify({ok:false,error:error.message,manifestSha256,runtimeJavaScript:[...runtimeJavaScript.values()],requests,pageErrors,consoleErrors,failedResponses},null,2)).catch(()=>{})}throw error}
finally{await browser?.close();await new Promise(done=>server.close(done))}
