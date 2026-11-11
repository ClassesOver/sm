// Actual writer/PDF.js/component verification; intentionally not a product save E2E.
import assert from 'node:assert/strict'
import {spawnSync} from 'node:child_process'
import {createHash} from 'node:crypto'
import {createServer} from 'node:http'
import {mkdir,readFile,writeFile} from 'node:fs/promises'
import {join} from 'node:path'
import {fileURLToPath} from 'node:url'
import {build} from 'esbuild'
import {chromium} from 'playwright'
const frontend=fileURLToPath(new URL('../',import.meta.url)),repo=fileURLToPath(new URL('../../../../',import.meta.url))
const directory=process.env.PDF_DRAWING_FONT_DIRECTORY??'/tmp/pdf-drawing-font-browser'
await mkdir(directory,{recursive:true})
const source=spawnSync(join(repo,'.venv/bin/python'),[join(frontend,'smoke/pdf-drawing-font-source.py'),directory],{cwd:repo,env:{...process.env,PYTHONPATH:repo},encoding:'utf8'})
assert.equal(source.status,0,source.stdout+source.stderr)
const native=JSON.parse(source.stdout.trim().split('\n').at(-1))
await build({entryPoints:[join(frontend,'smoke/pdf-drawing-font-browser.mjs')],bundle:true,format:'esm',platform:'browser',outdir:directory,logLevel:'warning',external:['/reports/*']})
const assetPath='/reports/v1/editor/assets/pdfjs/standard_fonts/'
const staticFont=join(frontend,'../static/pdfjs/standard_fonts/LiberationSans-Regular.ttf')
const packageFont=join(frontend,'node_modules/pdfjs-dist/standard_fonts/LiberationSans-Regular.ttf')
const sha=bytes=>createHash('sha256').update(bytes).digest('hex')
assert.equal(sha(await readFile(staticFont)),sha(await readFile(packageFont)),'deployed Standard14 font must equal locked PDF.js font')
const fontSha256=sha(await readFile(staticFont)),requests=[],errors=[]
const server=createServer(async(request,response)=>{
 try{
  const path=new URL(request.url,'http://localhost').pathname
  requests.push(path)
  if(path==='/'){response.setHeader('Content-Type','text/html');response.end('<!doctype html><html><head><link rel="stylesheet" href="/pdf-drawing-font-browser.css"></head><body style="background:#ddd;margin:16px"><script type="module" src="/pdf-drawing-font-browser.js"></script></body></html>');return}
  const target=path==='/pdf.worker.mjs'?join(frontend,'node_modules/pdfjs-dist/legacy/build/pdf.worker.mjs')
   :path===assetPath+'LiberationSans-Regular.ttf'?staticFont
   :['/native-ap.json','/saved-ap.pdf','/saved-labels.pdf','/pdf-drawing-font-browser.js','/pdf-drawing-font-browser.css'].includes(path)?join(directory,path.slice(1)):null
  if(!target){response.statusCode=404;response.end();return}
  response.setHeader('Content-Type',path.endsWith('.js')||path.endsWith('.mjs')?'text/javascript':path.endsWith('.css')?'text/css':path.endsWith('.ttf')?'font/ttf':path.endsWith('.pdf')?'application/pdf':'application/json')
  response.end(await readFile(target))
 }catch(error){errors.push(String(error));response.statusCode=500;response.end(String(error))}
})
await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve))
let browser,page
// SVGMatrix exposes float32 values; tolerate its conversion precision only.
const near=(actual,expected,tolerance=5e-5)=>{assert.equal(actual.length,expected.length);actual.forEach((v,i)=>assert.ok(Math.abs(v-expected[i])<tolerance,`${actual} != ${expected}`))}
try{
 browser=await chromium.launch({headless:true,...(process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE?{executablePath:process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE}:{})})
 page=await browser.newPage({viewport:{width:1680,height:940},deviceScaleFactor:1})
 page.on('pageerror',error=>errors.push(error.message))
 page.on('console',message=>{if(message.type()==='error')errors.push(message.text())})
 await page.goto(`http://127.0.0.1:${server.address().port}`)
 await page.waitForFunction(()=>window.drawingReady===true)
 const checkpoints=[]
 for(const rotation of [0,90,180,270])for(const zoom of [.5,2]){
  const row=await page.evaluate(async({rotation,zoom})=>window.checkDrawing(rotation,zoom),{rotation,zoom})
  await writeFile(join(directory,`saved-labels-${rotation}-${zoom}.png`),Buffer.from(row.labelOnlyPng,'base64'));delete row.labelOnlyPng
  await writeFile(join(directory,'latest-checkpoint.json'),JSON.stringify(row,null,2))
  assert.equal(row.fontSha256,fontSha256);assert.ok(row.loadedFaces.some(font=>font.status==='loaded'))
  const [va,vb,vc,vd,ve,vf]=row.viewport
  const point=(x,y)=>[va*x+vc*y+ve,vb*x+vd*y+vf]
  for(const [index,label]of row.labels.entries()){
   const nativeLabel=native.appearance[index], [a,b,c,d,e,f]=nativeLabel.tm
   assert.equal(label.label,nativeLabel.label)
   const origin=point(e,f),u=point(e+a,f+b),down=point(e-c,f-d)
   near(label.matrix,[u[0]-origin[0],u[1]-origin[1],down[0]-origin[0],down[1]-origin[1],...origin])
   assert.ok(label.family.includes('PDF Standard Helvetica'));assert.equal(label.kerning,'none');assert.equal(label.ligatures,'none')
   assert.ok(Math.abs(label.svgAdvance-label.assetAdvance)<.04,JSON.stringify(label))
   assert.ok(Math.abs(label.svgAdvance-label.pdfAdvance)<.08,JSON.stringify(label))
  }
  near(row.caret.path.match(/-?\d+(?:\.\d+)?(?:e[-+]?\d+)?/gi).map(Number),native.appearance.at(-1).vertices.flatMap(([x,y])=>point(x,y)))
  assert.match(row.caret.path,/ Z$/);assert.equal(row.caret.stroke,'none');assert.notEqual(row.caret.fill,'none')
  await page.screenshot({path:join(directory,`compare-${rotation}-${zoom}.png`)})
  await page.locator('svg').screenshot({path:join(directory,`draft-${rotation}-${zoom}.png`)})
  await page.locator('canvas').screenshot({path:join(directory,`saved-${rotation}-${zoom}.png`)})
  await page.locator('svg line,svg path').evaluateAll(elements=>elements.forEach(element=>element.style.visibility='hidden'))
  await page.locator('svg').screenshot({path:join(directory,`draft-labels-${rotation}-${zoom}.png`)})
  checkpoints.push(row)
 }
 assert.deepEqual(errors,[])
 const fallbackPage=await browser.newPage({viewport:{width:600,height:200}})
 let failedFontRequests=0
 await fallbackPage.route('**/standard_fonts/LiberationSans-Regular.ttf',route=>{failedFontRequests++;return route.abort('failed')})
 await fallbackPage.goto(`http://127.0.0.1:${server.address().port}/?fallback=1`)
 await fallbackPage.waitForFunction(()=>window.drawingReady===true)
 const fallback=await fallbackPage.evaluate(()=>window.fallbackResult)
 await writeFile(join(directory,'fallback.json'),JSON.stringify(fallback,null,2))
 assert.ok(failedFontRequests>0);assert.equal(fallback.label,'Visible fallback');assert.ok(fallback.width>20)
 assert.ok(fallback.faces.some(font=>font.family==='PDF Standard Helvetica'&&font.status==='error'))
 await fallbackPage.screenshot({path:join(directory,'font-load-failure-fallback.png')});await fallbackPage.close()
 const result={ok:false,scope:'Actual native writer AP independently parsed by pypdf, actual PDF.js and paintDrawing component; no product save or revision registration in this probe; no antialias pixel identity claim.',browserVersion:browser.version(),fontSha256,sourceSha256:native.sourceSha256,savedSha256:native.savedSha256,checkpoints,fallback,failedFontRequests,requests,errors}
 await writeFile(join(directory,'summary.json'),JSON.stringify(result,null,2))
 const visual=spawnSync(join(repo,'.venv/bin/python'),[join(frontend,'smoke/pdf-drawing-font-verify.py'),directory],{cwd:repo,encoding:'utf8'})
 assert.equal(visual.status,0,visual.stdout+visual.stderr)
 await writeFile(join(directory,'visual-independent.json'),visual.stdout)
 result.ok=true;result.visual=JSON.parse(visual.stdout);await writeFile(join(directory,'summary.json'),JSON.stringify(result,null,2))
 console.log(JSON.stringify({ok:true,directory,checkpoints:checkpoints.length,fontSha256}))
}catch(error){await writeFile(join(directory,'failure.json'),JSON.stringify({error:String(error),errors,requests},null,2));await page?.screenshot({path:join(directory,'failure.png')}).catch(()=>{});throw error}
finally{await browser?.close();await new Promise(resolve=>server.close(resolve))}
