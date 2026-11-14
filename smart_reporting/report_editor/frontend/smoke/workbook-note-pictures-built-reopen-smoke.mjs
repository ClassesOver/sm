// 最终static只读重开：HTTP授权/修订响应明确为夹具，xlsx复用真实Python保存产物。
import assert from 'node:assert/strict'
import {createServer} from 'node:http'
import {readFile,mkdir,writeFile} from 'node:fs/promises'
import {createHash} from 'node:crypto'
import {join,resolve} from 'node:path'
import {chromium} from 'playwright'
const root=resolve(process.env.NOTE_STATIC),out=resolve(process.env.NOTE_OUTPUT),file=resolve(process.env.NOTE_XLSX),prefix='/reports/v1/editor/assets/',port=Number(process.env.NOTE_PORT??4513)
await mkdir(out,{recursive:true});const data=await readFile(file),hash=b=>createHash('sha256').update(b).digest('hex'),sha=hash(data)
const mediaType='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',requests=[],modules=[],errors=[],layout=[]
const server=createServer(async(req,res)=>{try{const url=new URL(req.url,'http://localhost');let path=decodeURIComponent(url.pathname);if(!path.startsWith(prefix)){res.writeHead(404);res.end();return}path=resolve(root,path.slice(prefix.length));if(!path.startsWith(root+'/'))throw Error('scope');const bytes=await readFile(path);res.setHeader('Content-Type',path.endsWith('.js')?'text/javascript':path.endsWith('.css')?'text/css':path.endsWith('.html')?'text/html':path.endsWith('.woff2')?'font/woff2':'application/octet-stream');res.end(bytes)}catch{res.writeHead(404);res.end()}})
await new Promise(done=>server.listen(port,'127.0.0.1',done));let browser,page
try{
 browser=await chromium.launch({headless:true,executablePath:process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE??'/snap/bin/chromium'});page=await browser.newPage({viewport:{width:1440,height:900}})
 page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>requests.push({url:r.url(),type:r.resourceType()}));page.on('response',async r=>{if(r.url().endsWith('.js')){try{const bytes=await r.body();modules.push({url:r.url(),status:r.status(),sha256:hash(bytes),size:bytes.length})}catch(e){errors.push(String(e))}}})
 const api='**/reports/v1/native/note-pictures/2/api/'
 await page.route(api+'context',r=>r.fulfill({json:{context:{documentId:'note-pictures',format:'xlsx',revision:2,parentRevision:1,scope:{database:'fixture',companyId:'fixture',userId:'fixture',threadId:'fixture'},sourceFile:{path:'saved.xlsx',size:data.length,sha256:sha,mediaType},origin:'upload'},csrfToken:'fixture',capabilities:{xlsx_editor:true},editingEnabled:true}}))
 await page.route(api+'file',r=>r.fulfill({contentType:mediaType,body:data}))
 await page.addInitScript(()=>history.replaceState(null,'','/reports/v1/native/note-pictures/2'))
 await page.goto(`http://127.0.0.1:${port}${prefix}native.html`);await page.waitForFunction(()=>document.querySelector('#report-editor')?.getAttribute('aria-busy')==='false',null,{timeout:90000})
 await page.locator('.workbook-note-pictures-toggle').click();await page.locator('.np-card img').waitFor();assert.equal(await page.locator('.np-card').count(),1);await page.getByText('保留批注文字',{exact:true}).waitFor();await page.getByText('作者甲',{exact:true}).waitFor();assert(await page.locator('.np-card img').evaluate(n=>n.complete&&n.naturalWidth===80&&n.naturalHeight===30))
 for(const [width,height] of [[1440,900],[640,360],[390,320]]){await page.setViewportSize({width,height});const geometry=await page.locator('.note-pictures-pane').evaluate(n=>{const r=n.getBoundingClientRect();return{x:r.x,y:r.y,right:r.right,bottom:r.bottom}});assert(geometry.x>=0&&geometry.y>=0&&geometry.right<=width+1&&geometry.bottom<=height+1,JSON.stringify(geometry));for(const selector of ['[data-note-pictures-close]','[data-note-picture-insert]','[data-note-picture-remove]']){await page.locator(selector).scrollIntoViewIfNeeded();await page.locator(selector).click({trial:true})}layout.push({width,height,geometry});await page.screenshot({path:join(out,`pane-${width}x${height}.png`)})}
 assert.deepEqual(errors,[]);assert(modules.some(m=>m.url.includes('workbook-note-picture-controls-')&&m.status===200));assert(modules.every(m=>m.status===200));await writeFile(join(out,'evidence.json'),JSON.stringify({ok:true,scope:'final static built read-only native main UI; authorized HTTP context/file fixture; previously Python-saved XLSX; no production repository claim',staticRoot:root,xlsxSha256:sha,layout,modules,requests,errors},null,2));console.log(JSON.stringify({ok:true,out,modules:modules.length,xlsxSha256:sha}))
}catch(e){await page?.screenshot({path:join(out,'failure.png')}).catch(()=>{});await writeFile(join(out,'failure.json'),JSON.stringify({error:String(e),stack:e.stack,errors,modules,requests,layout},null,2));throw e}finally{await browser?.close();server.close()}
