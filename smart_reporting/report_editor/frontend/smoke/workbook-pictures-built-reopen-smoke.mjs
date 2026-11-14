// 最终static只读重开：HTTP授权/修订响应明确为夹具，xlsx复用真实Python保存产物。
import assert from 'node:assert/strict'
import {createServer} from 'node:http'
import {readFile,mkdir,writeFile} from 'node:fs/promises'
import {createHash} from 'node:crypto'
import {join,resolve} from 'node:path'
import {chromium} from 'playwright'
const root=resolve(process.env.XLSX_PICTURES_STATIC),out=resolve(process.env.XLSX_PICTURES_OUTPUT),file=resolve(process.env.XLSX_PICTURES_XLSX),prefix='/reports/v1/editor/assets/',port=Number(process.env.XLSX_PICTURES_PORT??4518)
await mkdir(out,{recursive:true});const data=await readFile(file),hash=b=>createHash('sha256').update(b).digest('hex'),sha=hash(data)
const mediaType='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',requests=[],modules=[],errors=[],layout=[]
const server=createServer(async(req,res)=>{try{const url=new URL(req.url,'http://localhost');let path=decodeURIComponent(url.pathname);if(!path.startsWith(prefix)){res.writeHead(404);res.end();return}path=resolve(root,path.slice(prefix.length));if(!path.startsWith(root+'/'))throw Error('scope');const bytes=await readFile(path);res.setHeader('Content-Type',path.endsWith('.js')?'text/javascript':path.endsWith('.css')?'text/css':path.endsWith('.html')?'text/html':path.endsWith('.woff2')?'font/woff2':'application/octet-stream');res.end(bytes)}catch{res.writeHead(404);res.end()}})
await new Promise(done=>server.listen(port,'127.0.0.1',done));let browser,page
try{
 browser=await chromium.launch({headless:true,executablePath:process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE??'/snap/bin/chromium'});page=await browser.newPage({viewport:{width:1440,height:900}})
 page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>requests.push({url:r.url(),type:r.resourceType()}));page.on('response',async r=>{if(/\.(?:js|css)(?:\?|$)/.test(r.url())){try{const bytes=await r.body(),path=resolve(root,new URL(r.url()).pathname.slice(prefix.length)),disk=await readFile(path);assert.deepEqual(bytes,disk,`frozen asset mismatch: ${path}`);modules.push({url:r.url(),status:r.status(),sha256:hash(bytes),size:bytes.length,staticPath:path,diskSha256:hash(disk)})}catch(e){errors.push(String(e))}}})
 const api='**/reports/v1/native/xlsx-pictures/2/api/'
 await page.route(api+'context',r=>r.fulfill({json:{context:{documentId:'xlsx-pictures',format:'xlsx',revision:2,parentRevision:1,scope:{database:'fixture',companyId:'fixture',userId:'fixture',threadId:'fixture'},sourceFile:{path:'saved.xlsx',size:data.length,sha256:sha,mediaType},origin:'upload'},threadActor:{personId:'{3D8AA7AF-8EC0-5187-BCAD-CA956C14C05A}',author:'fixture'},csrfToken:'fixture',capabilities:{xlsx_editor:true},editingEnabled:true}}))
 await page.route(api+'file',r=>r.fulfill({contentType:mediaType,body:data}))
 await page.addInitScript(()=>history.replaceState(null,'','/reports/v1/native/xlsx-pictures/2'))
 await page.goto(`http://127.0.0.1:${port}${prefix}native.html`);await page.waitForFunction(()=>document.querySelector('#report-editor')?.getAttribute('aria-busy')==='false',null,{timeout:90000})
 await page.screenshot({path:join(out,'reopened.png')})
 await page.locator('[data-ribbon-tab=Insert]').click()
 await page.locator('[data-ribbon-command=insert-equation]').click()
 const dialog=()=>page.locator('.workbook-picture-dialog [role=dialog]')
 await dialog().getByRole('button',{name:'A = \\pi r^2',exact:true}).waitFor()
 for(const [width,height] of [[1440,900],[640,360],[390,320]]){
  await page.setViewportSize({width,height});const geometry=await dialog().evaluate(n=>{const r=n.getBoundingClientRect();return{x:r.x,y:r.y,right:r.right,bottom:r.bottom}})
  assert(geometry.x>=0&&geometry.y>=0&&geometry.right<=width+1&&geometry.bottom<=height+1,JSON.stringify(geometry))
  await dialog().getByRole('button',{name:'取消',exact:true}).click({trial:true});layout.push({width,height,geometry});await page.screenshot({path:join(out,`equation-${width}x${height}.png`)})
 }
 await dialog().getByRole('button',{name:'取消',exact:true}).click();await page.setViewportSize({width:1440,height:900})
 await page.locator('[data-ribbon-command=insert-icons]').click();assert.equal(await dialog().locator('.dialog-tabs button').count(),9)
 await dialog().getByPlaceholder('搜索图标（英文）').fill('airplane');assert(await dialog().locator('.icons-grid button').count()>0)
 await page.screenshot({path:join(out,'icons.png')});await dialog().getByRole('button',{name:'关闭',exact:true}).click()
 const picker=page.waitForEvent('filechooser');await page.locator('[data-ribbon-command=insert-picture]').click();await picker
 await page.locator('input[data-workbook-picture]').evaluate(n=>n.dispatchEvent(new Event('cancel')))
 assert.deepEqual(errors,[]);assert(modules.some(m=>m.url.includes('workbook-main-')&&m.status===200));assert(modules.every(m=>m.status===200));await writeFile(join(out,'evidence.json'),JSON.stringify({ok:true,scope:'final static built read-only native main UI; authorized HTTP context/file fixture; previously Python-saved XLSX; no production repository claim',staticRoot:root,xlsxSha256:sha,layout,modules,requests,errors},null,2));console.log(JSON.stringify({ok:true,out,modules:modules.length,xlsxSha256:sha}))
}catch(e){await page?.screenshot({path:join(out,'failure.png')}).catch(()=>{});await writeFile(join(out,'failure.json'),JSON.stringify({error:String(e),stack:e.stack,errors,modules,requests,layout},null,2));throw e}finally{await browser?.close();server.close()}
