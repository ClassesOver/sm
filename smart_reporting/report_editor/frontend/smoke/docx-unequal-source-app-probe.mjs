// 固定源App原文件独立终态调查；仅临时Vite配置/夹具，不修改源checkout或宿主生产。
import {existsSync} from 'node:fs'
import {mkdtemp,readFile,writeFile,readdir} from 'node:fs/promises'
import {tmpdir} from 'node:os'
import {join} from 'node:path'
import {fileURLToPath} from 'node:url'
import {spawnSync} from 'node:child_process'
import {createRequire} from 'node:module'
import {createHash} from 'node:crypto'
import {createServer} from 'vite'
import {chromium} from 'playwright'
const source='/home/junge/pros/genoffice-source-full'
const frontend=fileURLToPath(new URL('../',import.meta.url)),repo=fileURLToPath(new URL('../../../../',import.meta.url))
const temporary=await mkdtemp(join(tmpdir(),'word-source-unequal-')),fixture=join(temporary,'fixture.docx')
const made=spawnSync(join(repo,'.venv/bin/python'),['-c',`from docx import Document
from docx.shared import Inches
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
p='${fixture}'
d=Document();s=d.sections[0];s.page_width=Inches(5);s.page_height=Inches(5)
s.left_margin=Inches(.5);s.right_margin=Inches(.5);s.top_margin=Inches(.5);s.bottom_margin=Inches(.5)
s.different_first_page_header_footer=True
cols=s._sectPr.find(qn('w:cols'));cols.set(qn('w:num'),'2');cols.set(qn('w:equalWidth'),'0')
for w in [1800,3600]:
 c=OxmlElement('w:col');c.set(qn('w:w'),str(w));c.set(qn('w:space'),'360');cols.append(c)
for i in range(3):d.add_paragraph(('Long paragraph '+str(i)+' across unequal columns. ')*12)
d.save(p)`],{encoding:'utf8'})
if(made.status)throw Error(made.stderr)
const packages=new Map()
for(const name of await readdir(join(source,'packages'))){try{const dir=join(source,'packages',name),pkg=JSON.parse(await readFile(join(dir,'package.json'),'utf8'));packages.set(pkg.name,{dir,pkg})}catch{}}
const requireFromFrontend=createRequire(join(frontend,'package.json'))
const requireFromEngine=createRequire(join(repo,'smart_reporting/reporting/doc_engine/package.json'))
const resolver={name:'temporary-source-dependencies',enforce:'pre',async resolveId(id,importer){
 if(id.startsWith('@genoffice/')){
  const parts=id.split('/'),entry=packages.get(parts.slice(0,2).join('/'))
  if(entry){const key=parts.length===2?'.':'./'+parts.slice(2).join('/'),target=entry.pkg.exports?.[key];if(typeof target==='string')return join(entry.dir,target)}
 }
 if(id==='marked')return '/home/junge/pros/agno-admin-console/frontend/node_modules/.pnpm/marked@16.4.2/node_modules/marked/lib/marked.esm.js'
 if(id.includes('?')){const [base,query]=id.split('?');for(const loader of [requireFromFrontend,requireFromEngine])try{return loader.resolve(base)+'?'+query}catch{}}
 if(!id.startsWith('.')&&!id.startsWith('/')&&!id.startsWith('\0')&&!id.startsWith('virtual:')){for(const loader of [requireFromFrontend,requireFromEngine])try{const path=loader.resolve(id);const candidates=[path.replace('/cjs/','/es/').replace(/\.cjs$/,'.mjs'),path.replace('/cjs/','/es/').replace(/\.cjs$/,'.js'),path.replace('/cjs/','/esm/').replace(/\.cjs$/,'.mjs'),path.slice(0,-4)+'.js'];return path.endsWith('.cjs')?(candidates.find(existsSync)??path):path}catch{};return null}
}}
const aliases=[]
for(const name of ['use-sync-external-store/shim/index.js','use-sync-external-store/shim/with-selector.js','jszip','fast-xml-parser','utif2'])aliases.push({find:new RegExp('^'+name+'$'),replacement:(()=>{try{return requireFromFrontend.resolve(name)}catch{return requireFromEngine.resolve(name)}})()})
for(const name of ['react','react-dom','scheduler'])aliases.push({find:new RegExp('^'+name+'(?=/|$)'),replacement:join(frontend,'node_modules',name)})
const port=Number(process.env.DOCX_SOURCE_PORT??4201)
const server=await createServer({configFile:false,root:join(source,'apps/docs/src/renderer'),plugins:[resolver],resolve:{alias:aliases},cacheDir:join(temporary,'vite-cache'),server:{port,strictPort:true,fs:{allow:[source,frontend,temporary,repo,'/home/junge/pros/agno-admin-console/frontend/node_modules']}},optimizeDeps:{include:['react','react-dom/client','react/jsx-dev-runtime','jszip','fast-xml-parser','utif2','use-sync-external-store/shim/index.js','use-sync-external-store/shim/with-selector.js']},esbuild:{jsx:'automatic'}})
const browser=await chromium.launch({headless:true}),page=await browser.newPage({viewport:{width:1600,height:1000}}),errors=[]
page.on('pageerror',error=>errors.push(error.message))
page.on('console',msg=>{if(msg.type()==='error')errors.push(msg.text())})
try{
 await server.listen()
 const bytes=await readFile(process.env.DOCX_UNEQUAL_FIXTURE??fixture),hash=createHash('sha256').update(bytes).digest('hex')
 await page.route('**/fixture.docx',route=>route.fulfill({body:bytes,contentType:'application/vnd.openxmlformats-officedocument.wordprocessingml.document'}))
 await page.addInitScript(({hash})=>{
  const pending={path:'/fixture.docx',name:'fixture.docx',dataUrl:'/fixture.docx',hash}
  const noop=()=>()=>{}
  const values={getRecentFiles:[],getAiSettings:{},getLanguage:'zh',getTheme:'light',getDocumentTheme:'follow',consumeNewBlankDoc:false,consumeAiDocContent:null,getInstalledFonts:[],getSystemFonts:[],getAuthorName:'',getAiPanelPrefs:{}}
  window.desktop=new Proxy({consumePendingOpenDocx:async()=>pending},{get(target,key){if(key in target)return target[key];if(String(key).startsWith('on'))return noop;return async()=>values[key]??null}})
 },{hash})
 await page.goto(`http://localhost:${port}`,{waitUntil:'domcontentloaded'})
 await page.waitForFunction(()=>window.__pageDebug?.slices?.length>0,null,{timeout:20000})
 await page.waitForTimeout(3000)
 const samples=[]
 for(let i=0;i<3;i++){
  samples.push(await page.evaluate(()=>{const d=window.__pageDebug,pm=document.querySelector('.ProseMirror');return {slices:d?.slices,followUps:d?.followUps,loopStops:d?.loopStops,retriggerLog:d?.retriggerLog,layoutHealth:d?.layoutHealth,colSpecs:d?.colSpecs,blocks:d?.blocks,canvas:pm?{rect:pm.getBoundingClientRect().toJSON(),border:getComputedStyle(pm).border,padding:getComputedStyle(pm).padding,line:getComputedStyle(pm).lineHeight,first:pm.querySelector('p')?.getBoundingClientRect().toJSON()}:null,pmHtml:pm?.innerHTML,body:pm?[...pm.querySelectorAll('p[data-idx]')].map(el=>({text:el.textContent.slice(0,30),css:{font:getComputedStyle(el).font,fontFamily:getComputedStyle(el).fontFamily,fontSize:getComputedStyle(el).fontSize,zoom:el.closest('.doc-zoom')?.style.zoom,lineHeight:getComputedStyle(el).lineHeight,margin:getComputedStyle(el).margin,padding:getComputedStyle(el).padding},width:el.getBoundingClientRect().width,x:el.getBoundingClientRect().left,y:el.getBoundingClientRect().top,split:[...el.querySelectorAll('.doc-col-split-float')].map(s=>s.style.cssText)})):[]}}))
  await page.waitForTimeout(1000)
 }
 const wrapProbe=await page.evaluate(async()=>{const cloneCss=[];const append=Node.prototype.appendChild;Node.prototype.appendChild=function(child){const out=append.call(this,child);if(this instanceof Element&&this.classList.contains('doc-col-probe')&&child instanceof HTMLElement){const c=getComputedStyle(child);cloneCss.push({fontFamily:c.fontFamily,fontSize:c.fontSize,lineHeight:c.lineHeight,width:c.width,letterSpacing:c.letterSpacing,css:child.style.cssText,parent:this.outerHTML.slice(0,450)})}return out};const {probeColWrap}=await import('/pagination-lines.ts');const pm=document.querySelector('.ProseMirror');pm.classList.add('measuring-natural','measuring-columns');try{return {cloneCss,tables:[...pm.querySelectorAll('p[data-idx]')].map(el=>probeColWrap(el,120,240,1))}}finally{Node.prototype.appendChild=append;pm.classList.remove('measuring-natural','measuring-columns')}})
 const parsedMeta=await page.evaluate(async()=>{const {parseDocxOffThread}=await import('/parse-off-thread.ts');const p=await parseDocxOffThread(new Uint8Array(await(await fetch('/fixture.docx')).arrayBuffer()));return {styles:Object.values(p.styles).filter(s=>s.id==='Normal'),docDefaults:p.docDefaults}})
 const fontEvidence=await page.evaluate(()=>({faces:[...document.fonts].map(f=>({family:f.family,status:f.status})),measure:['Caladea','Times New Roman','serif'].map(face=>{const c=document.createElement('canvas').getContext('2d');c.font='14.6667px '+face;return {face,width:c.measureText('Long paragraph 0 across unequal columns.').width}})}))
 const result={fontEvidence,wrapProbe,parsedMeta,probe:'fixed-source-app-unequal-final-state',source,hash,temporary,samples,errors}
 await writeFile(join(temporary,'result.json'),JSON.stringify(result,null,2))
 console.log(JSON.stringify(result))
}catch(error){console.log(JSON.stringify({probe:'fixed-source-app-boot-failed',error:String(error),errors,body:await page.locator('body').innerText().catch(()=>''),temporary}));throw error}finally{await browser.close();await server.close()}
