// 固定DOCX真浏览器分页诊断；只截图完整位于可见预览浮层内的纸张。
import assert from 'node:assert/strict'
import {readFile,writeFile,mkdir} from 'node:fs/promises'
import {resolve,extname} from 'node:path'
import {createHash} from 'node:crypto'
import {createServer} from 'node:http'
import {chromium} from 'playwright'
const artifact=process.env.DOCX_COMPLEX_ARTIFACT??'/tmp/sr-word-complex-20261111',output=process.env.DOCX_COMPLEX_EVIDENCE??artifact+'/clip-corrected'
const staticRoot=resolve(process.env.DOCX_TEST_DIST??new URL('../../static',import.meta.url).pathname),port=Number(process.env.DOCX_TEST_PORT??4390),base='http://127.0.0.1:'+port,prefix='/reports/v1/editor/assets/'
const sha=b=>createHash('sha256').update(b).digest('hex'),bytes=await readFile(resolve(artifact,'downloaded-native.docx')),model=JSON.parse(await readFile(resolve(artifact,'native-model.json'),'utf8'))
assert.equal(sha(bytes),'7f4e32ee954f8eaaa98e97e904932369199971d323edf17b8cbbad578cde0391');assert.equal(model.sourceSha256,sha(bytes))
const manifestSha256=sha(await readFile(resolve(staticRoot,'.vite/manifest.json')))
await mkdir(output,{recursive:true})
const server=createServer(async(req,res)=>{try{const path=new URL(req.url,base).pathname;assert.ok(path.startsWith(prefix));const f=resolve(staticRoot,path.slice(prefix.length));assert.ok(f.startsWith(staticRoot+'/'));const body=await readFile(f);res.writeHead(200,{'Content-Type':({'.js':'application/javascript','.css':'text/css','.html':'text/html','.woff2':'font/woff2','.png':'image/png','.svg':'image/svg+xml'})[extname(f)]??'application/octet-stream'});res.end(body)}catch{res.writeHead(404);res.end('not found')}})
await new Promise((ok,no)=>{server.once('error',no);server.listen(port,'127.0.0.1',ok)})
let browser
try{
 browser=await chromium.launch({headless:true});const page=await browser.newPage({viewport:{width:1600,height:1500}}),errors=[],chunks={},identities=[]
 page.on('pageerror',e=>errors.push(e.message));page.on('console',m=>{if(m.type()==='error')errors.push(m.text())})
 page.on('response',r=>{const p=new URL(r.url()).pathname;if(r.status()>=400)errors.push(r.status()+' '+p);if(r.ok()&&p.startsWith(prefix)&&p.endsWith('.js'))identities.push(r.body().then(async b=>{assert.equal(sha(b),sha(await readFile(resolve(staticRoot,p.slice(prefix.length)))));chunks[p]=sha(b)}))})
 await page.route('**/favicon.ico',r=>r.fulfill({body:'',status:200}))
 await page.route('**/reports/v1/native/fixture-pagination/1',async r=>r.fulfill({body:await readFile(resolve(staticRoot,'native.html')),contentType:'text/html'}))
 await page.route('**/reports/v1/native/fixture-pagination/1/api/**',async r=>{const p=new URL(r.request().url()).pathname;if(p.endsWith('/context'))return r.fulfill({json:{context:{documentId:'fixture-pagination',format:'docx',revision:1,parentRevision:null,scope:{database:'f',companyId:'f',userId:'f',threadId:'f'},sourceFile:{path:'downloaded-native.docx',size:bytes.length,sha256:sha(bytes),mediaType:'application/vnd.openxmlformats-officedocument.wordprocessingml.document'},origin:'report'},csrfToken:'fixture',capabilities:{docx_editor:true},editingEnabled:true}});if(p.endsWith('/file'))return r.fulfill({body:bytes});assert.ok(p.endsWith('/preview'));assert.deepEqual(r.request().postDataJSON().operations,[]);return r.fulfill({json:{sourceSha256:sha(bytes),draftSha256:sha(bytes),model}})})
 await page.goto(base+'/reports/v1/native/fixture-pagination/1');await page.locator('.docx-source-home').waitFor({timeout:20000}).catch(async e=>{await page.screenshot({path:resolve(output,'load-failure.png')});console.error(JSON.stringify({errors,body:await page.locator('body').innerText()}));throw e})
 const snapshots=[],iterations=[];let markers=[],bodyMetrics=null,canvasMetrics=null,platformFonts=null
 for(let iteration=0;iteration<4;iteration++){
  await page.locator('[data-tab-id=view]').click();await page.locator('[data-action=pagination-preview]').click();await page.waitForFunction(()=>window.__previewDebug?.slices?.length>0)
  await page.evaluate(()=>document.fonts.ready)
  const cuts=await page.evaluate(()=>window.__previewDebug.slices.map(({start,end,section,pageNo})=>({start,end,section,pageNo})))
  if(iteration)assert.deepEqual(cuts,iterations[0]);iterations.push(cuts)
  if(iteration===0){
   const cdp=await page.context().newCDPSession(page)
   await cdp.send('DOM.enable');await cdp.send('CSS.enable')
   const rootNode=await cdp.send('DOM.getDocument')
   const node=await cdp.send('DOM.querySelector',{nodeId:rootNode.root.nodeId,selector:'.editor-scroll .ProseMirror p[data-idx="5"]'})
   platformFonts=await cdp.send('CSS.getPlatformFontsForNode',{nodeId:node.nodeId})
   console.log(JSON.stringify({platformFonts}))
   await writeFile(resolve(output,'platform-fonts.json'),JSON.stringify(platformFonts,null,2))
   await cdp.detach()
   canvasMetrics=await page.locator('.editor-scroll .ProseMirror').evaluate(el=>{const c=getComputedStyle(el);return {paddingTop:c.paddingTop,paddingBottom:c.paddingBottom,width:el.getBoundingClientRect().width}})
   bodyMetrics=await page.evaluate(()=>{
    const root=document.querySelector('.editor-scroll .ProseMirror'),p=[...root.querySelectorAll('p')].find(p=>p.textContent.startsWith('BODY101'))
    const read=el=>{const c=getComputedStyle(el),r=el.getBoundingClientRect();return {fontFamily:c.fontFamily,fontSize:c.fontSize,lineHeight:c.lineHeight,width:r.width,height:r.height,marginTop:c.marginTop,marginBottom:c.marginBottom,letterSpacing:c.letterSpacing,lineFactor:c.getPropertyValue('--doc-line-factor'),latin:c.getPropertyValue('--doc-line-factor-latin'),cjk:c.getPropertyValue('--doc-line-factor-cjk')}}
    return {paragraph:read(p),spans:[...p.querySelectorAll('span')].map(read)}
   })
   markers=await page.locator('.pv-page').evaluateAll(papers=>papers.map((paper,i)=>{
    const pr=paper.getBoundingClientRect(),seen=[]
    for(const clip of paper.querySelectorAll('.pv-clip,.pv-footnotes,.pv-endnotes')){
     const cr=clip.getBoundingClientRect(),walker=document.createTreeWalker(clip,NodeFilter.SHOW_TEXT)
     for(let n;(n=walker.nextNode());)for(const m of n.data.matchAll(/BODY[123][0-9]{2}|ROW[0-9]{3}|NOTEFOOT[12]|NOTEEND1/g)){
      if(getComputedStyle(n.parentElement).visibility==='hidden')continue
      const r=document.createRange();r.setStart(n,m.index);r.setEnd(n,m.index+m[0].length)
      if([...r.getClientRects()].some(b=>{const x=(b.left+b.right)/2,y=(b.top+b.bottom)/2;return x>=Math.max(cr.left,pr.left)&&x<=Math.min(cr.right,pr.right)&&y>=Math.max(cr.top,pr.top)&&y<=Math.min(cr.bottom,pr.bottom)}))seen.push(m[0])
     }
    }return {page:i+1,seen}
   }))
   const found=new Set(markers.flatMap(p=>p.seen))
   for(const i of [1,2,3])for(let j=1;j<=(i===2?18:14);j++)assert.ok(found.has('BODY'+i+String(j).padStart(2,'0')),'missing body '+i+j)
   for(let j=1;j<=62;j++)assert.ok(found.has('ROW'+String(j).padStart(3,'0')),'missing row '+j)
   for(const n of ['NOTEFOOT1','NOTEFOOT2','NOTEEND1'])assert.ok(found.has(n),'missing note '+n)
   const notes=await page.locator('.pv-page').evaluateAll(els=>els.findIndex(el=>el.querySelector('.pv-footnotes'))+1),count=cuts.length
   for(const n of [...new Set([1,notes,count])].filter(n=>n>0)){
    const paper=page.locator('.pv-page').nth(n-1);await paper.evaluate(el=>el.scrollIntoView({block:'center'}))
    const geometry=await paper.evaluate(el=>{const r=el.getBoundingClientRect(),s=document.querySelector('.pv-scroll').getBoundingClientRect();return {paper:r.toJSON(),scroll:s.toJSON(),innerHeight,valid:r.top>=s.top-.5&&r.bottom<=s.bottom+.5&&r.left>=s.left-.5&&r.right<=s.right+.5&&r.bottom<=innerHeight}})
    assert.ok(geometry.valid,'纸张必须完整位于pv-scroll与浏览器视口内')
    await paper.screenshot({path:resolve(output,'page-'+n+'.png')});snapshots.push({page:n,...geometry})
   }
  }
  await page.keyboard.press('Escape');await page.locator('.pv-overlay').waitFor({state:'hidden'});await page.evaluate(()=>{window.__previewDebug=null})
 }
 await page.waitForLoadState('networkidle');await Promise.all(identities);assert.deepEqual(errors,[]);assert.equal(sha(await readFile(resolve(staticRoot,'.vite/manifest.json'))),manifestSha256)
 let sourceDiff=null
 if(process.env.DOCX_SOURCE_CUTS){
  const source=JSON.parse(await readFile(process.env.DOCX_SOURCE_CUTS,'utf8'))
  const expected=source.slices??source.cuts??source.iterations?.[0]??source.samples?.[0]?.slices
  assert.ok(Array.isArray(expected),'source evidence must include slices/cuts, not only page markers')
  const actual=iterations[0];assert.equal(actual.length,expected.length,'source page count')
  let maxCutErrorPx=0
  actual.forEach((cut,i)=>{assert.equal(cut.section,expected[i].section,'source section '+i);for(const k of ['start','end']){const delta=Math.abs(cut[k]-expected[i][k]);assert.ok(delta<=1e-6,'source '+k+' mismatch page '+(i+1));maxCutErrorPx=Math.max(maxCutErrorPx,delta)}})
  sourceDiff={path:process.env.DOCX_SOURCE_CUTS,pages:actual.length,maxCutErrorPx,epsilonPx:1e-6}
 }
 const evidence={sourceSha256:sha(bytes),manifestSha256,iterations,snapshots,markers,bodyMetrics,canvasMetrics,platformFonts,sourceDiff,chunks,errors};await writeFile(resolve(output,'evidence.json'),JSON.stringify(evidence,null,2));assert.ok(platformFonts.fonts.some(f=>f.postScriptName==='Caladea-Regular'&&f.isCustomFont&&f.glyphCount>0),'Latin Word alias must use loaded Caladea');console.log(JSON.stringify({ok:true,pages:iterations[0].length,stableOpens:iterations.length,output,manifestSha256,errors}))
}finally{await browser?.close();await new Promise(ok=>server.close(ok))}
