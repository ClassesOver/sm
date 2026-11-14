import assert from 'node:assert/strict'
import {createServer} from 'node:http'
import {spawnSync} from 'node:child_process'
import {createHash} from 'node:crypto'
import {mkdir,readFile,readdir,writeFile} from 'node:fs/promises'
import {join,resolve} from 'node:path'
import {fileURLToPath} from 'node:url'
import {setTimeout as delay} from 'node:timers/promises'
import {chromium} from 'playwright'
import {inspectAnalysisLayout} from './office-xlsx-analysis-layout.mjs'

// HTTP context/save应答为夹具；实际构建宿主、Univer、Python保存桥和下载文件不作模拟。
const frontend=fileURLToPath(new URL('../',import.meta.url)),repo=resolve(frontend,'../../..')
const directory=process.env.CONSOLIDATE_SMOKE_DIRECTORY,staticRoot=process.env.CONSOLIDATE_SMOKE_STATIC
assert.ok(directory&&staticRoot,'显式指定隔离构建及全新证据目录')
await mkdir(directory,{recursive:true})
const reviewOnly=process.env.CONSOLIDATE_SMOKE_REVIEW_ONLY==='1'
const existing=await readdir(directory)
if(!reviewOnly)assert.equal(existing.some(name=>/^(?:saved|revision-2|downloaded)/.test(name)),false,'禁止重放已成功保存的来源；使用只读复核模式')
const sha=bytes=>createHash('sha256').update(bytes).digest('hex')
const manifest=await readFile(join(staticRoot,'.vite/manifest.json'))
assert.equal(sha(manifest),process.env.CONSOLIDATE_EXPECTED_MANIFEST_SHA256,'锁定已构建manifest身份')
const scripts=['workbook-consolidate-built-smoke.mjs','office-xlsx-consolidate-fixture.py','office-xlsx-analysis-layout.mjs']
const scriptHashes=Object.fromEntries(await Promise.all(scripts.map(async name=>[name,sha(await readFile(join(frontend,'smoke',name)))])))
await writeFile(join(directory,'build-manifest.json'),manifest)
const fixture=payload=>{
 const result=spawnSync(join(repo,'.venv/bin/python'),[join(frontend,'smoke/office-xlsx-consolidate-fixture.py')],{cwd:repo,env:{...process.env,PYTHONPATH:repo,TMPDIR:'/dev/shm',PYTHONDONTWRITEBYTECODE:'1'},input:JSON.stringify({directory,...payload}),encoding:'utf8',maxBuffer:20*1024*1024})
 assert.equal(result.status,0,result.stderr);return JSON.parse(result.stdout)
}
if(!existing.includes('source.xlsx')){assert.equal(reviewOnly,false);fixture({mode:'create'})}
const media='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',documentId='consolidate-built'
const source=await readFile(join(directory,'source.xlsx')),revisions=new Map([[1,source]])
let saved,saveCount=0,saveAttempted=false,routeError,page,browser,stage='setup'
if(reviewOnly){saved=JSON.parse(await readFile(join(directory,'saved.json'),'utf8'));const bytes=await readFile(join(directory,'revision-2.xlsx'));assert.equal(sha(bytes),saved.sha256);revisions.set(2,bytes)}
const layout={cases:[],failures:[]},results=[],assets=new Map(),assetChecks=[],errors=[]
const http=createServer(async(req,res)=>{try{
 const url=new URL(req.url,'http://localhost'),match=/^\/reports\/v1\/native\/consolidate-built\/(\d+)(?:\/api\/(context|file|save))?$/.exec(url.pathname)
 if(match){
  const revision=Number(match[1]),action=match[2],bytes=revisions.get(revision);assert.ok(bytes)
  if(action==='context'){res.setHeader('Content-Type','application/json');res.end(JSON.stringify({context:{documentId,format:'xlsx',revision,parentRevision:revision-1,scope:{database:'f',companyId:'f',userId:'f',threadId:'f'},sourceFile:{path:`consolidate-${revision}.xlsx`,size:bytes.length,sha256:sha(bytes),mediaType:media},origin:'upload'},csrfToken:'csrf',capabilities:{xlsx_editor:true},editingEnabled:true}));return}
  if(action==='file'){res.setHeader('Content-Type',media);res.end(bytes);return}
  if(action==='save'){
   assert.equal(reviewOnly,false,'只读模式禁止保存');assert.equal(req.method,'POST');assert.equal(revision,1);assert.equal(saveAttempted,false,'禁止重复保存');saveAttempted=true
   const chunks=[];for await(const chunk of req)chunks.push(chunk)
   const payload=JSON.parse(Buffer.concat(chunks).toString())
   const patched=fixture({mode:'patch',operations:payload.operations}),output=await readFile(join(directory,'revision-2.xlsx'))
   assert.equal(sha(output),patched.sha256);revisions.set(2,output);saveCount++
   saved={revision:2,sourceRevision:1,...patched,operations:payload.operations};await writeFile(join(directory,'saved.json'),JSON.stringify(saved,null,2))
   res.setHeader('Content-Type','application/json');res.end(JSON.stringify({documentId,revision:2,parentRevision:1,revisionRegistered:true,artifacts:{xlsx:{downloadUrl:'/download/2.xlsx',...patched}},editor:{openUrl:`/reports/v1/native/${documentId}/2`},validation:{ok:false,issues:[{code:'manual_review',message:'合并计算结果版式待复核，文件已生成。'}]}}));return
  }
 }
 if(url.pathname==='/download/2.xlsx'){assert.ok(saved);res.setHeader('Content-Type',media);res.setHeader('Content-Disposition','attachment; filename=consolidate.xlsx');res.end(revisions.get(2));return}
 const prefix='/reports/v1/editor/assets/',path=match&&!match[2]?'native.html':url.pathname.startsWith(prefix)?url.pathname.slice(prefix.length):null
 assert.ok(path&&!path.includes('..'),'未知资源路径')
 const bytes=await readFile(join(staticRoot,path)),extension=path.split('.').at(-1)
 res.setHeader('Content-Type',({html:'text/html',js:'application/javascript',css:'text/css',json:'application/json',wasm:'application/wasm',svg:'image/svg+xml',woff2:'font/woff2',ttf:'font/ttf'})[extension]??'application/octet-stream');res.end(bytes)
 }catch(error){routeError=String(error);res.writeHead(500,{'Content-Type':'application/json'});res.end(JSON.stringify({detail:routeError}))}})
await new Promise(resolve=>http.listen(0,'127.0.0.1',resolve));const app=`http://127.0.0.1:${http.address().port}`
const modes=[
 ...['sum','count','average','max','min'].map((fn,index)=>({fn,label:false,row:index*5+1,values:[[12,24,6],[2,2,1],[6,12,6],[10,20,6],[2,4,6]][index]})),
 ...['sum','count','average'].map((fn,index)=>({fn,label:true,row:index*5+1,values:[[8,14,20],[2,2,1],[4,7,20]][index]})),
]
try{
 browser=await chromium.launch({headless:true});page=await browser.newPage({viewport:{width:1440,height:900},acceptDownloads:true,permissions:['clipboard-read','clipboard-write']})
 page.on('pageerror',error=>errors.push(error.message));page.on('dialog',dialog=>dialog.type()==='beforeunload'?dialog.accept():dialog.dismiss())
 page.on('response',response=>{const path=new URL(response.url()).pathname,prefix='/reports/v1/editor/assets/';if(!path.startsWith(prefix)||!(/\.(?:js|css)$/.test(path)))return;assetChecks.push((async()=>{assert.equal(response.status(),200);const bytes=await response.body();assert.equal(sha(bytes),sha(await readFile(join(staticRoot,path.slice(prefix.length)))));assets.set(path,sha(bytes))})())})
 const ready=()=>page.waitForFunction(()=>document.querySelector('#report-editor')?.getAttribute('aria-busy')==='false',null,{timeout:60000})
 const open=async revision=>{await page.goto(`${app}/reports/v1/native/${documentId}/${revision}`);await ready()}
 const command=async(tab,id)=>{await page.locator(`[data-ribbon-tab="${tab}"]`).click();await page.locator(`[data-ribbon-command="${id}"]`).click()}
 const goto=async reference=>{await command('Home','goto-open');await page.locator('[data-goto-reference]').fill(reference);await page.locator('.workbook-ribbon-goto-dialog button[type="submit"]').click();await page.locator('.workbook-ribbon-goto-dialog').waitFor({state:'hidden'})}
 const drafts=()=>page.evaluate(()=>Object.fromEntries(Object.keys(localStorage).filter(key=>key.startsWith('native-editor-draft:')).map(key=>[key,JSON.parse(localStorage.getItem(key))])))
 const operations=async()=>Object.values(await drafts()).flatMap(value=>value.operations)
 const waitEdits=count=>page.waitForFunction(expected=>Object.keys(localStorage).filter(key=>key.startsWith('native-editor-draft:')).reduce((total,key)=>total+JSON.parse(localStorage.getItem(key)).operations.flatMap(op=>op.edits??[]).length,0)===expected,count)
 const modal=page.getByRole('dialog',{name:'合并计算',exact:true}),reference=modal.getByLabel('引用位置',{exact:true})
 const openDialog=async target=>{await goto(`'Summary'!${target}`);await command('Data','consolidate-open');await modal.waitFor({state:'visible'})}
 const copy=async(range,expected)=>{
  await goto(`'Summary'!${range}`);const marker=`copy-${Date.now()}`;await page.evaluate(text=>navigator.clipboard.writeText(text),marker);await page.keyboard.press('Control+c')
  const until=Date.now()+10000;let text
  do{text=(await page.evaluate(()=>navigator.clipboard.readText())).replaceAll('\r\n','\n');if(text===expected||text===expected+'\n')return text;await delay(100)}while(Date.now()<until)
  assert.equal(text,expected,`公开复制 ${range}`)
 }
 const range=item=>`${item.label?'H':'E'}${item.row}:${item.label?'I':'E'}${item.row+2}`
 const expected=item=>item.values.map((v,i)=>item.label?`${['Ada','Bob','Cara'][i]}\t${v}`:item.row===1&&i===0?'12.00':String(v)).join('\n')
 const old=item=>[0,1,2].map(i=>item.label?`${item.row===1&&i===0?'99':`old-H${item.row+i}`}\told-I${item.row+i}`:`old-E${item.row+i}`).join('\n')
 if(!reviewOnly){
  await open(1);stage='cancel-and-error';const before=await drafts();await openDialog('E1')
  await reference.fill('');await modal.getByRole('button',{name:'确定',exact:true}).click();await modal.getByRole('alert').getByText('请至少添加一个引用位置',{exact:true}).waitFor()
  await inspectAnalysisLayout(page,{directory,label:'合并计算',phase:'built-empty-error',layout,draft:drafts})
  await reference.fill("'West Side'!B1:B3");await modal.getByRole('button',{name:'添加',exact:true}).click()
  for(let i=1;i<=17;i++){await reference.fill(`'West Side'!B${i}:B${i+1}`);await modal.getByRole('button',{name:'添加',exact:true}).click()}
  // 第一项与循环第一项不同，形成18个引用，取消必须不产生单元格草稿。
  assert.equal(await modal.locator('[data-reference]').count(),18)
  await inspectAnalysisLayout(page,{directory,label:'合并计算',phase:'built-long-list',layout,draft:drafts})
  await modal.getByRole('button',{name:'取消',exact:true}).click();assert.deepEqual(await drafts(),before)
  for(const item of modes){
   stage=`${item.label?'labels':'position'}-${item.fn}`;const previous=await operations();await copy(range(item),old(item));await page.keyboard.press('Escape');await openDialog(`${item.label?'H':'E'}${item.row}`)
   await reference.fill(`'West Side'!${item.label?'A1:B3':'B1:B3'}`);await reference.press('Enter');await reference.fill(`'O''Brien'!${item.label?'A1:B2':'B1:B2'}`)
   if(item.label)await modal.getByLabel('使用左列标签',{exact:true}).check()
   await modal.getByLabel('函数',{exact:true}).selectOption(item.fn);await modal.getByRole('button',{name:'确定',exact:true}).click();await modal.waitFor({state:'hidden'})
   const previousCount=previous.flatMap(op=>op.edits??[]).length,appliedCount=previousCount+(item.label?6:3)
   await waitEdits(appliedCount);await copy(range(item),expected(item));const applied=await operations();await page.keyboard.press('Escape');await command('File','undo')
   await waitEdits(previousCount)
   assert.deepEqual(await operations(),previous);await copy(range(item),old(item));await page.keyboard.press('Escape');await command('File','redo')
   await waitEdits(appliedCount)
   assert.deepEqual(await operations(),applied);await copy(range(item),expected(item));await page.keyboard.press('Escape')
   results.push({...item,range:range(item),publicCopy:true,undoRedo:true,operations:applied});await writeFile(join(directory,'modes.json'),JSON.stringify(results,null,2))
  }
  stage='reload';const beforeRefresh=await drafts();await page.reload();await ready();assert.deepEqual(await drafts(),beforeRefresh)
  for(const item of modes){await copy(range(item),expected(item));await page.keyboard.press('Escape')}
  await writeFile(join(directory,'draft-before-save.json'),JSON.stringify(await drafts(),null,2))
  stage='save';await page.locator('[data-action="save"]').click();await page.waitForFunction(()=>document.querySelector('.save-state-label')?.textContent==='已保存修订 2',null,{timeout:60000})
  assert.equal(routeError,undefined);assert.equal(saveCount,1);assert.ok((await page.locator('.workbook-feedback').textContent()).includes('合并计算结果版式待复核，文件已生成。'))
 }
 stage='download';if(reviewOnly)await open(2)
 const [download]=await Promise.all([page.waitForEvent('download'),page.locator('[data-action="xlsx-download"]').click()]);assert.equal(await download.failure(),null)
 const downloaded=await readFile(await download.path());assert.equal(sha(downloaded),saved.sha256);assert.deepEqual(downloaded,revisions.get(2));await writeFile(join(directory,'downloaded.xlsx'),downloaded)
 const independent=fixture({mode:'verify'});await writeFile(join(directory,'independent-check.json'),JSON.stringify(independent,null,2))
 const response=await page.request.get(`${app}/download/2.xlsx`);assert.equal(response.status(),200);assert.equal(sha(await response.body()),saved.sha256)
 stage='reopen';await open(2);assert.equal(await page.locator('.save-state-label').textContent(),'已保存')
 const context=await page.evaluate(async()=>(await(await fetch(location.pathname+'/api/context')).json()).context)
 assert.equal(context.revision,2);assert.equal(context.sourceFile.sha256,saved.sha256);assert.deepEqual(await operations(),[])
 for(const item of modes){await copy(range(item),expected(item));await page.keyboard.press('Escape')}
 await openDialog('E1');await inspectAnalysisLayout(page,{directory,label:'合并计算',phase:'built-reopened',layout,draft:drafts});await modal.getByRole('button',{name:'取消',exact:true}).click()
 await page.screenshot({path:join(directory,'reopened.png'),fullPage:true});await Promise.all(assetChecks)
 assert.deepEqual(errors,[]);assert.deepEqual(layout.failures,[]);assert.equal(routeError,undefined);assert.deepEqual(await readFile(join(staticRoot,'.vite/manifest.json')),manifest)
 for(const name of scripts)assert.equal(sha(await readFile(join(frontend,'smoke',name))),scriptHashes[name],'运行期间不修改脚本')
 const summary={ok:true,directory,reviewOnly,saveCount,manifestSha256:sha(manifest),browserVersion:browser.version(),results,independent,context,sourceBytes:source.length,outputBytes:downloaded.length,layout,assets:Object.fromEntries(assets),errors,scriptHashes,validationWarningVerified:!reviewOnly,revision2Reopened:true,scope:'构建宿主+真实保存桥；HTTP授权/修订登记为fixture，非桌面Excel实机'}
 await writeFile(join(directory,'summary.json'),JSON.stringify(summary,null,2));console.log(JSON.stringify({ok:true,saveCount,modes:results.length,layoutCases:layout.cases.length,assets:assets.size}))
}catch(error){if(page){await writeFile(join(directory,'failure.html'),await page.content()).catch(()=>{});await page.screenshot({path:join(directory,'failure.png'),fullPage:true}).catch(()=>{})}console.error(JSON.stringify({stage,directory,routeError}));throw error}
finally{await browser?.close();await new Promise(resolve=>http.close(resolve))}
