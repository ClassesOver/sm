// 只验证真实 Ribbon/Static Fill 源与 CSS 的几何；不连接 API，不执行保存或表单修改。
import assert from 'node:assert/strict'
import {createHash} from 'node:crypto'
import {createServer} from 'node:http'
import {readFile,writeFile,mkdir,mkdtemp,readdir} from 'node:fs/promises'
import {join,resolve} from 'node:path'
import {tmpdir} from 'node:os'
import {fileURLToPath} from 'node:url'
import {build} from 'esbuild'
import ts from 'typescript'
import {chromium} from 'playwright'

const repo=fileURLToPath(new URL('../../../../',import.meta.url)),live=join(repo,'smart_reporting/report_editor/frontend')
const source=resolve(process.env.PDF_FILL_LAYOUT_SOURCE??live)
const cssSource=resolve(process.env.PDF_FILL_LAYOUT_CSS_SOURCE??source)
const production=resolve(process.env.PDF_FILL_LAYOUT_STATIC??join(live,'../static'))
const output=process.env.PDF_FILL_LAYOUT_OUTPUT?resolve(process.env.PDF_FILL_LAYOUT_OUTPUT):await mkdtemp(join(tmpdir(),'pdf-fill-ribbon-layout-'))
const mode=process.env.PDF_FILL_LAYOUT_MODE??'source',sha=bytes=>createHash('sha256').update(bytes).digest('hex')
assert(['source','built'].includes(mode),'PDF_FILL_LAYOUT_MODE must be source or built')
assert(mode!=='built'||process.env.PDF_FILL_LAYOUT_BROWSER_SUMMARY,'built mode requires explicit PDF_FILL_LAYOUT_BROWSER_SUMMARY with browser-observed stylesheet order')
await mkdir(output,{recursive:true});const save=async(name,value)=>{await writeFile(join(output,name),Buffer.isBuffer(value)||typeof value==='string'?value:JSON.stringify(value,null,2))}
const text=await readFile(join(source,'src/pdf-main.ts'),'utf8'),ast=ts.createSourceFile('pdf-main.ts',text,ts.ScriptTarget.Latest,true,ts.ScriptKind.TS)
function unique(test){const matches=[];function visit(node){if(test(node))matches.push(node);ts.forEachChild(node,visit)}visit(ast);assert.equal(matches.length,1);return matches[0].getText(ast)}
const fn=name=>unique(node=>ts.isFunctionDeclaration(node)&&node.name?.text===name)
const declaration=name=>unique(node=>ts.isVariableStatement(node)&&node.declarationList.declarations.some(item=>ts.isIdentifier(item.name)&&item.name.text===name))
const start=text.indexOf("  const formGroup = ribbon.group('fillForm'"),end=text.indexOf("  commandGroup=ribbon.group('formDesign'",start);assert(start>0&&end>start)
// 只读几何夹具；冻结真实 read-model 仅在显式传入时使用，不把夹具数字当业务事实。
const setup=text.slice(start,end),model=process.env.PDF_FILL_LAYOUT_MODEL?JSON.parse(await readFile(process.env.PDF_FILL_LAYOUT_MODEL,'utf8')).model:{capabilities:{createFormField:true,staticFill:true},formFields:[{name:'party.answer',kind:'radio',value:'Maybe',options:['Yes','Maybe'],editable:true},{name:'party.choice',kind:'choice',value:'Three',options:['Three','Two','One'],editable:true},{name:'party.code',kind:'text',value:'C001',editable:true}]}
const manifest=await readFile(join(production,'.vite/manifest.json')).catch(error=>{throw new Error('Build frontend assets first (npm run build), or set PDF_FILL_LAYOUT_STATIC explicitly',{cause:error})}),names=await readdir(join(production,'assets'))
if(process.argv.includes('--check-config')){
 for(const path of [join(source,'src/pdf-ribbon.ts'),join(source,'src/pdf.css'),join(cssSource,'src/pdf-ribbon.css'),join(source,'src/office-theme.css')])await readFile(path)
 if(mode==='built')await readFile(process.env.PDF_FILL_LAYOUT_BROWSER_SUMMARY)
 console.log(JSON.stringify({ok:true,check:'config-only; no browser/API/save',source,cssSource,production,output,mode,modelSource:process.env.PDF_FILL_LAYOUT_MODEL??'portable three-field geometry fixture',manifestSha256:sha(manifest)}));process.exit(0)
}
const entry=`import {createPdfRibbon} from ${JSON.stringify(join(source,'src/pdf-ribbon.ts'))};
import {pdfRibbonLabel} from ${JSON.stringify(join(source,'src/pdf-ribbon-locales.ts'))};
import {addPdfCommandIcon} from ${JSON.stringify(join(source,'src/pdf-ribbon-command-icons.ts'))};
import {createPdfRibbonIcon} from ${JSON.stringify(join(source,'src/pdf-ribbon-icons.ts'))};
const root=document.querySelector('#report-editor'),ribbon=createPdfRibbon(root,{hasForms:true});let commandGroup;
const model=${JSON.stringify(model)},draft={operations:[],closed:false,saving:false},response={editingEnabled:true,pdfFormAIEnabled:false};
const formDesignPreview=false,locked=false,previewing=false,previewDocument=undefined;
const editableButtons=[],PDF_EXCLUSIVE_DRAFT_KINDS=[],undo=undefined,redo=undefined;
${fn('documentElement')}
${fn('button')}
${declaration('sourceCommand')}
${setup}
${fn('renderFormControls')}
renderFormControls(model.formFields);document.querySelector('[data-pdf-ribbon-tab=fillForm]').click();window.layoutReady=true;`
await save('entry.ts',entry)
const built=await build({absWorkingDir:repo,stdin:{contents:entry,resolveDir:source,sourcefile:'pdf-fill-layout-entry.ts',loader:'ts'},bundle:true,format:'esm',platform:'browser',write:false,metafile:true,logLevel:'silent',outfile:join(output,'entry.js')})
const inputs={};for(const path of Object.keys(built.metafile.inputs))if(!path.endsWith('pdf-fill-layout-entry.ts'))inputs[path]=sha(await readFile(resolve(repo,path)))
const bundle=built.outputFiles.find(file=>file.path.endsWith('.js')).contents;await save('entry.js',Buffer.from(bundle));await save('esbuild-metafile.json',built.metafile)
const files=new Map([['/entry.js',{bytes:Buffer.from(bundle),type:'application/javascript'}]]),styles=[]
async function stylesheet(path){const bytes=await readFile(path),url='/style-'+styles.length+'.css';styles.push({path,sha256:sha(bytes),url});files.set(url,{bytes,type:'text/css'})}
if(mode==='built'){
 const previous=JSON.parse(await readFile(process.env.PDF_FILL_LAYOUT_BROWSER_SUMMARY,'utf8'))
 for(const url of Object.keys(previous.assets).filter(path=>path.endsWith('.css'))){const stem=url.split('/').at(-1).replace(/-[^-]+\.css$/,'-'),matches=names.filter(name=>name.startsWith(stem)&&name.endsWith('.css'));assert.equal(matches.length,1,stem);await stylesheet(join(production,'assets',matches[0]))}
}else{
 const core=names.filter(name=>/^style-.*\.css$/.test(name));assert.equal(core.length,1);await stylesheet(join(production,'assets',core[0]));for(const name of ['pdf.css','pdf-ribbon.css','office-theme.css'])await stylesheet(join(name==='pdf-ribbon.css'?cssSource:source,'src',name))
}
await save('inputs.json',{source,cssSource,production,mode,modelSource:process.env.PDF_FILL_LAYOUT_MODEL??'portable three-field geometry fixture',manifestSha256:sha(manifest),styles,bundleSha256:sha(bundle),sourceInputs:inputs,extractedSetupSha256:sha(setup),modelSha256:sha(JSON.stringify(model)),scope:mode==='built'?'real Ribbon and AST-extracted PDF Static Fill setup; real compiled production CSS in explicitly supplied browser-observed stylesheet order':'real Ribbon and AST-extracted PDF Static Fill setup; production core CSS followed by actual pdf.css/pdf-ribbon.css/office-theme.css import order; not a full product build'})
const server=createServer((request,response)=>{const url=new URL(request.url,'http://localhost');if(url.pathname==='/'){const lang=url.searchParams.get('lang')??'zh';response.writeHead(200,{'Content-Type':'text/html'});response.end(`<!doctype html><html lang="${lang}"><head><meta charset="utf-8">${styles.map(style=>`<link rel="stylesheet" href="${style.url}">`).join('')}</head><body class="editor-format-pdf"><div id="report-editor" class="native-pdf-editor"></div><script type="module" src="/entry.js"></script></body></html>`);return}const file=files.get(url.pathname);if(!file){response.writeHead(404);response.end();return}response.writeHead(200,{'Content-Type':file.type});response.end(file.bytes)})
await new Promise(done=>server.listen(0,'127.0.0.1',done));const origin='http://127.0.0.1:'+server.address().port,errors=[],cases=[];let browser
try{
 browser=await chromium.launch({headless:true,...(process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE?{executablePath:process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE}:{})})
 for(const language of ['zh','en'])for(const width of [1600,640]){
  const page=await browser.newPage({viewport:{width,height:1000}}),pageErrors=[];page.on('pageerror',error=>pageErrors.push(String(error)));await page.goto(origin+'/?lang='+language);await page.waitForFunction(()=>window.layoutReady===true)
  const target=page.locator('.pdf-ribbon-group').filter({has:page.locator('[data-pdf-static-fill-action]')});assert.equal(await target.count(),1);await target.scrollIntoViewIfNeeded()
  const measure=()=>target.evaluate(group=>{const rect=element=>{const r=element.getBoundingClientRect();return {left:r.left,top:r.top,right:r.right,bottom:r.bottom,width:r.width,height:r.height}};const heading=group.querySelector('h2'),titleStyle=getComputedStyle(heading),panel=group.closest('[role=tabpanel]');return {caption:{...rect(heading),text:heading.textContent,lineHeight:parseFloat(titleStyle.lineHeight),whiteSpace:titleStyle.whiteSpace},group:rect(group),panel:{...rect(panel),scrollWidth:panel.scrollWidth,clientWidth:panel.clientWidth},bodyWidth:document.body.scrollWidth,viewport:innerWidth,buttons:[...group.querySelectorAll('[data-pdf-static-fill-action]')].map(button=>({action:button.dataset.pdfStaticFillAction,...rect(button)}))}})
  const geometry=await measure(),issues=[];assert.deepEqual(geometry.buttons.map(button=>button.action).sort(),['check','complete','cross','manage','text']);const bottom=Math.max(...geometry.buttons.map(button=>button.bottom));if(geometry.caption.top-bottom<4-.1)issues.push('caption与按钮框垂直间隔不足4px');if(geometry.caption.height>geometry.caption.lineHeight+.5)issues.push('caption换行');if(geometry.caption.left<geometry.group.left-.5||geometry.caption.right>geometry.group.right+.5)issues.push('caption未由组宽承载');if(Math.abs(geometry.group.height-(width===640?138:114))>.5)issues.push('三行原总高度改变（桌面114px/窄屏138px）');if(geometry.bodyWidth>width+1)issues.push('body横向溢出');if(new Set(geometry.buttons.map(button=>button.top.toFixed(1))).size!==3)issues.push('按钮不再是三行');if(pageErrors.length)issues.push(...pageErrors)
  const reachable=[];for(const button of await target.locator('[data-pdf-static-fill-action]').all()){await button.scrollIntoViewIfNeeded();await button.click({trial:true});const position=await button.boundingBox();const panel=await target.locator('..').boundingBox();assert(position&&panel);assert(position.x>=panel.x-1&&position.x+position.width<=panel.x+panel.width+1);reachable.push(await button.getAttribute('data-pdf-static-fill-action'))}
  assert.deepEqual([...reachable].sort(),['check','complete','cross','manage','text']);const after=await measure();if(after.bodyWidth>width+1)issues.push('滚动后body横向溢出');await target.scrollIntoViewIfNeeded();await save(language+'-'+width+'.png',await page.screenshot({fullPage:true}));const result={language,width,geometry,captionGap:geometry.caption.top-bottom,reachable,issues};cases.push(result);if(issues.length)errors.push({language,width,issues});await save(language+'-'+width+'.json',result);await page.close()
 }
 const result={ok:errors.length===0,mode,cases,errors,manifestSha256:sha(manifest),notes:'en使用真实locale映射；当前Static Fill caption/按钮未收录英译，保持产品中文fallback，不伪造翻译；仅trial可达检查，不调用编辑事件或API'};await save('result.json',result);console.log(JSON.stringify({ok:result.ok,output,cases:cases.map(value=>({language:value.language,width:value.width,captionGap:value.captionGap,issues:value.issues}))}));assert.deepEqual(errors,[])
}finally{await browser?.close();await new Promise(done=>server.close(done))}
