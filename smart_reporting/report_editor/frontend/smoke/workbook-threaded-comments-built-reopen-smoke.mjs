// 最终static只读重开：HTTP授权/修订响应明确为夹具，xlsx复用真实Python保存产物。
import assert from 'node:assert/strict'
import {createServer} from 'node:http'
import {readFile,mkdir,writeFile} from 'node:fs/promises'
import {createHash} from 'node:crypto'
import {join,resolve} from 'node:path'
import {chromium} from 'playwright'
const root=resolve(process.env.THREAD_STATIC),out=resolve(process.env.THREAD_OUTPUT),file=resolve(process.env.THREAD_XLSX),prefix='/reports/v1/editor/assets/',port=Number(process.env.THREAD_PORT??4516)
await mkdir(out,{recursive:true});const data=await readFile(file),hash=b=>createHash('sha256').update(b).digest('hex'),sha=hash(data)
const mediaType='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',requests=[],modules=[],errors=[],layout=[]
const server=createServer(async(req,res)=>{try{const url=new URL(req.url,'http://localhost');let path=decodeURIComponent(url.pathname);if(!path.startsWith(prefix)){res.writeHead(404);res.end();return}path=resolve(root,path.slice(prefix.length));if(!path.startsWith(root+'/'))throw Error('scope');const bytes=await readFile(path);res.setHeader('Content-Type',path.endsWith('.js')?'text/javascript':path.endsWith('.css')?'text/css':path.endsWith('.html')?'text/html':path.endsWith('.woff2')?'font/woff2':'application/octet-stream');res.end(bytes)}catch{res.writeHead(404);res.end()}})
await new Promise(done=>server.listen(port,'127.0.0.1',done));let browser,page
try{
 browser=await chromium.launch({headless:true,executablePath:process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE??'/snap/bin/chromium'});page=await browser.newPage({viewport:{width:1440,height:900}})
 page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>requests.push({url:r.url(),type:r.resourceType()}));page.on('response',async r=>{if(r.url().endsWith('.js')){try{const bytes=await r.body();modules.push({url:r.url(),status:r.status(),sha256:hash(bytes),size:bytes.length})}catch(e){errors.push(String(e))}}})
 const api='**/reports/v1/native/xlsx-threads/2/api/'
 await page.route(api+'context',r=>r.fulfill({json:{context:{documentId:'xlsx-threads',format:'xlsx',revision:2,parentRevision:1,scope:{database:'fixture',companyId:'fixture',userId:'fixture',threadId:'fixture'},sourceFile:{path:'saved.xlsx',size:data.length,sha256:sha,mediaType},origin:'upload'},threadActor:{personId:'{3D8AA7AF-8EC0-5187-BCAD-CA956C14C05A}',author:'fixture'},csrfToken:'fixture',capabilities:{xlsx_editor:true},editingEnabled:true}}))
 await page.route(api+'file',r=>r.fulfill({contentType:mediaType,body:data}))
 await page.addInitScript(()=>history.replaceState(null,'','/reports/v1/native/xlsx-threads/2'))
 await page.goto(`http://127.0.0.1:${port}${prefix}native.html`);await page.waitForFunction(()=>document.querySelector('#report-editor')?.getAttribute('aria-busy')==='false',null,{timeout:90000})
 await page.getByRole('button',{name:'显示批注',exact:true}).click();await page.locator('.tc-text').filter({hasText:'根帖已编辑 <&'}).waitFor();await page.locator('.tc-text').filter({hasText:'最终保留回复'}).waitFor();assert.equal(await page.locator('.tc-author').first().textContent(),'fixture')
 for(const [width,height] of [[1440,900],[640,360],[390,320]]){await page.setViewportSize({width,height});const geometry=await page.locator('.threaded-comments-pane').evaluate(n=>{const r=n.getBoundingClientRect();return{x:r.x,y:r.y,right:r.right,bottom:r.bottom}});assert(geometry.x>=0&&geometry.y>=0&&geometry.right<=width+1&&geometry.bottom<=height+1,JSON.stringify(geometry));await page.locator('.tc-close').click({trial:true});layout.push({width,height,geometry});await page.screenshot({path:join(out,`pane-${width}x${height}.png`)})}
 await page.setViewportSize({width:1440,height:900});await page.locator('.tc-close').click();await page.mouse.move(85,272);await page.locator('.thread-hover-card').waitFor();await page.locator('.thread-hover-card').getByText('根帖已编辑 <&',{exact:true}).waitFor();await page.screenshot({path:join(out,'hover.png')})
 assert.deepEqual(errors,[]);assert(modules.some(m=>m.url.includes('workbook-threaded-comment-controls-')&&m.status===200));assert(modules.every(m=>m.status===200));await writeFile(join(out,'evidence.json'),JSON.stringify({ok:true,scope:'final static built read-only native main UI; authorized HTTP context/file fixture; previously Python-saved XLSX; no production repository claim',staticRoot:root,xlsxSha256:sha,layout,modules,requests,errors},null,2));console.log(JSON.stringify({ok:true,out,modules:modules.length,xlsxSha256:sha}))
}catch(e){await page?.screenshot({path:join(out,'failure.png')}).catch(()=>{});await writeFile(join(out,'failure.json'),JSON.stringify({error:String(e),stack:e.stack,errors,modules,requests,layout},null,2));throw e}finally{await browser?.close();server.close()}
