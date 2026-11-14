import assert from 'node:assert/strict'
import {createServer} from 'node:http'
import {spawnSync} from 'node:child_process'
import {createHash} from 'node:crypto'
import {mkdir,readFile,readdir,writeFile} from 'node:fs/promises'
import {join,resolve} from 'node:path'
import {fileURLToPath} from 'node:url'
import {chromium} from 'playwright'
import {inspectEditableRanges} from './office-xlsx-editable-ranges-layout.mjs'

// HTTP context/save应答为夹具；实际构建宿主、Univer、Python保存桥和下载文件不作模拟。
const frontend=fileURLToPath(new URL('../',import.meta.url)),repo=resolve(frontend,'../../..')
const directory=process.env.EDITABLE_RANGES_SMOKE_DIRECTORY,staticRoot=process.env.EDITABLE_RANGES_SMOKE_STATIC
assert.ok(directory&&staticRoot,'显式指定隔离构建及全新证据目录')
await mkdir(directory,{recursive:true})
const reviewOnly=process.env.EDITABLE_RANGES_REVIEW_ONLY==='1'
const existing=await readdir(directory)
if(!reviewOnly)assert.equal(existing.some(name=>/^(?:saved|revision-2|downloaded)/.test(name)),false,'禁止重放已成功保存的来源；使用只读复核模式')
const sha=bytes=>createHash('sha256').update(bytes).digest('hex')
const manifest=await readFile(join(staticRoot,'.vite/manifest.json'))
assert.equal(sha(manifest),process.env.EDITABLE_RANGES_EXPECTED_MANIFEST_SHA256,'锁定已构建manifest身份')
const scripts=['office-xlsx-editable-ranges-smoke.mjs','office-xlsx-editable-ranges-fixture.py','office-xlsx-editable-ranges-layout.mjs']
const scriptHashes=Object.fromEntries(await Promise.all(scripts.map(async name=>[name,sha(await readFile(join(frontend,'smoke',name)))])))
await writeFile(join(directory,'build-manifest.json'),manifest)
const fixture=payload=>{
 const result=spawnSync(join(repo,'.venv/bin/python'),[join(frontend,'smoke/office-xlsx-editable-ranges-fixture.py')],{cwd:repo,env:{...process.env,PYTHONPATH:repo,TMPDIR:'/dev/shm',PYTHONDONTWRITEBYTECODE:'1'},input:JSON.stringify({directory,...payload}),encoding:'utf8',maxBuffer:20*1024*1024})
 assert.equal(result.status,0,result.stderr);return JSON.parse(result.stdout)
}
if(!existing.includes('source.xlsx')){assert.equal(reviewOnly,false);fixture({mode:'create'})}
const media='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',documentId='editable-ranges-built'
const source=await readFile(join(directory,'source.xlsx')),revisions=new Map([[1,source]])
let saved,saveCount=0,saveAttempted=false,routeError,page,browser,stage='setup'
if(reviewOnly){saved=JSON.parse(await readFile(join(directory,'saved.json'),'utf8'));const bytes=await readFile(join(directory,'revision-2.xlsx'));assert.equal(sha(bytes),saved.sha256);revisions.set(2,bytes)}
const layout={cases:[],failures:[]},results=[],assets=new Map(),assetChecks=[],errors=[]
const http=createServer(async(req,res)=>{try{
 const url=new URL(req.url,'http://localhost'),match=/^\/reports\/v1\/native\/editable-ranges-built\/(\d+)(?:\/api\/(context|file|save))?$/.exec(url.pathname)
 if(match){
  const revision=Number(match[1]),action=match[2],bytes=revisions.get(revision);assert.ok(bytes)
  if(action==='context'){res.setHeader('Content-Type','application/json');res.end(JSON.stringify({context:{documentId,format:'xlsx',revision,parentRevision:revision-1,scope:{database:'f',companyId:'f',userId:'f',threadId:'f'},sourceFile:{path:`editable-ranges-${revision}.xlsx`,size:bytes.length,sha256:sha(bytes),mediaType:media},origin:'upload'},csrfToken:'csrf',capabilities:{xlsx_editor:true},editingEnabled:true}));return}
  if(action==='file'){res.setHeader('Content-Type',media);res.end(bytes);return}
  if(action==='save'){
   assert.equal(reviewOnly,false,'只读模式禁止保存');assert.equal(req.method,'POST');assert.equal(revision,1);assert.equal(saveAttempted,false,'禁止重复保存');saveAttempted=true
   const chunks=[];for await(const chunk of req)chunks.push(chunk)
   const payload=JSON.parse(Buffer.concat(chunks).toString())
   const patched=fixture({mode:'patch',operations:payload.operations}),output=await readFile(join(directory,'revision-2.xlsx'))
   assert.equal(sha(output),patched.sha256);revisions.set(2,output);saveCount++
   saved={revision:2,sourceRevision:1,...patched,operations:payload.operations};await writeFile(join(directory,'saved.json'),JSON.stringify(saved,null,2))
   res.setHeader('Content-Type','application/json');res.end(JSON.stringify({documentId,revision:2,parentRevision:1,revisionRegistered:true,artifacts:{xlsx:{downloadUrl:'/download/2.xlsx',...patched}},editor:{openUrl:`/reports/v1/native/${documentId}/2`},validation:{ok:false,issues:[{code:'manual_review',message:'允许编辑区域待人工复核，文件已生成。'}]}}));return
  }
 }
 if(url.pathname==='/download/2.xlsx'){assert.ok(saved);res.setHeader('Content-Type',media);res.setHeader('Content-Disposition','attachment; filename=editable-ranges.xlsx');res.end(revisions.get(2));return}
 const prefix='/reports/v1/editor/assets/',path=match&&!match[2]?'native.html':url.pathname.startsWith(prefix)?url.pathname.slice(prefix.length):null
 assert.ok(path&&!path.includes('..'),'未知资源路径')
 const bytes=await readFile(join(staticRoot,path)),extension=path.split('.').at(-1)
 res.setHeader('Content-Type',({html:'text/html',js:'application/javascript',css:'text/css',json:'application/json',wasm:'application/wasm',svg:'image/svg+xml',woff2:'font/woff2',ttf:'font/ttf'})[extension]??'application/octet-stream');res.end(bytes)
 }catch(error){routeError=String(error);res.writeHead(500,{'Content-Type':'application/json'});res.end(JSON.stringify({detail:routeError}))}})
await new Promise(resolve=>http.listen(0,'127.0.0.1',resolve));const app=`http://127.0.0.1:${http.address().port}`

try {
 browser=await chromium.launch({headless:true});page=await browser.newPage({viewport:{width:1440,height:900},acceptDownloads:true,permissions:['clipboard-read','clipboard-write']})
 page.on('pageerror',error=>errors.push(error.message));page.on('console',m=>{if(m.type()==='error')errors.push(m.text())});page.on('dialog',d=>d.type()==='beforeunload'?d.accept():d.dismiss())
 page.on('response',response=>{const path=new URL(response.url()).pathname,prefix='/reports/v1/editor/assets/';if(!path.startsWith(prefix)||!(/\.(?:js|css)$/.test(path)))return;assetChecks.push((async()=>{assert.equal(response.status(),200);const bytes=await response.body();assert.equal(sha(bytes),sha(await readFile(join(staticRoot,path.slice(prefix.length)))));assets.set(path,sha(bytes))})())})
 const ready=()=>page.waitForFunction(()=>document.querySelector('#report-editor')?.getAttribute('aria-busy')==='false',null,{timeout:60000})
 const open=async revision=>{await page.goto(`${app}/reports/v1/native/${documentId}/${revision}`);await ready()}
 const command=async(tab,id)=>{await page.locator(`[data-ribbon-tab="${tab}"]`).click();await page.locator(`[data-ribbon-command="${id}"]`).click()}
 const goto=async reference=>{await command('Home','goto-open');await page.locator('[data-goto-reference]').fill(reference);await page.locator('.workbook-ribbon-goto-dialog button[type="submit"]').click();await page.locator('.workbook-ribbon-goto-dialog').waitFor({state:'hidden'})}
 const drafts=()=>page.evaluate(()=>Object.fromEntries(Object.keys(localStorage).filter(key=>key.startsWith('native-editor-draft:')).map(key=>[key,JSON.parse(localStorage.getItem(key))])))
 const operations=async()=>Object.values(await drafts()).flatMap(value=>value.operations)
 // 提交期间宿主inert会暂时移出可访问树；不能把role locator的消失当作提交完成。
 const modal=page.locator('[role="dialog"][aria-label="允许用户编辑区域"]'),opener=page.locator('[data-ribbon-command="allow-edit-ranges-open"]')
 const inspect=phase=>inspectEditableRanges(page,{directory,phase,layout,draft:operations})
 const ranges=async()=>modal.locator('[data-range]').evaluateAll(rows=>rows.map(row=>({name:row.querySelector('[data-name]').value,sqref:row.querySelector('[data-ref]').value})))
 const expected=[{name:'Sales_Input',sqref:'B2:C4 E2:E4'},{name:'Keep',sqref:'D8'},{name:'Extra',sqref:'F2:F4'}]
 const openDialog=async()=>{await command('Review','allow-edit-ranges-open');await modal.waitFor()}
 const rangesDisabled=async()=>{await page.locator('[data-ribbon-tab="Review"]').click();return opener.isDisabled()}
 const copy=async(reference,expected)=>{
  await goto(reference);await page.evaluate(()=>navigator.clipboard.writeText('waiting'));await page.keyboard.press('Control+c')
  await page.waitForFunction(async expected=>(await navigator.clipboard.readText()).replaceAll('\r\n','\n').trimEnd()===expected,expected,{timeout:10000})
  return (await page.evaluate(()=>navigator.clipboard.readText())).trimEnd()
 }
 const history=async(before,after,phase)=>{
  const settled=expected=>page.waitForFunction(expected=>!document.querySelector('#report-editor')?.inert && JSON.stringify(Object.keys(localStorage).filter(k=>k.startsWith('native-editor-draft:')).flatMap(k=>JSON.parse(localStorage.getItem(k)).operations))===JSON.stringify(expected),expected)
  await command('File','undo');await settled(before);assert.deepEqual(await operations(),before,`${phase}撤销`)
  await command('File','redo');await settled(after);assert.deepEqual(await operations(),after,`${phase}重做`)
  results.push({phase,before,after});await writeFile(join(directory,'steps.json'),JSON.stringify(results,null,2))
 }
 if(!reviewOnly){
  await open(1);await goto('Inputs!E2:E4');stage='cancel-contract';const original=await operations()
  for(const close of ['cancel','escape','title']){
   await openDialog();assert.equal(await modal.locator('[data-range]').count(),3)
   await modal.getByLabel('区域名称 1',{exact:true}).fill('Cancelled')
   if(close==='cancel')await modal.locator('[data-action=cancel]').click();else if(close==='title')await modal.locator('.modal-close').click();else await page.keyboard.press('Escape')
   await modal.waitFor({state:'hidden'});assert.deepEqual(await operations(),original);assert.equal(await opener.evaluate(n=>n===document.activeElement),true)
  }
  stage='duplicate-error';await openDialog();await inspect('built-initial')
  await modal.getByLabel('区域名称 2',{exact:true}).fill('Entry');await modal.locator('[type=submit]').click()
  await page.waitForFunction(()=>!!document.querySelector('[aria-label="允许编辑区域错误"]')?.textContent)
  assert.deepEqual(await operations(),original);await inspect('built-duplicate-error')
  await modal.locator('[data-action=cancel]').click()
  stage='edit-definitions';await openDialog()
  await modal.getByLabel('区域名称 1',{exact:true}).fill('Sales_Input')
  await modal.getByLabel('区域引用 1',{exact:true}).fill('B2:C4 E2:E4')
  await modal.getByLabel('删除区域 2',{exact:true}).focus();await page.keyboard.press('Enter')
  assert.equal(await modal.getByLabel('区域名称 2',{exact:true}).evaluate(n=>n===document.activeElement),true)
  await modal.locator('[data-action=add]').click();assert.equal(await modal.getByLabel('区域名称 3',{exact:true}).evaluate(n=>n===document.activeElement),true)
  await modal.getByLabel('区域名称 3',{exact:true}).fill('Extra');await modal.getByLabel('区域引用 3',{exact:true}).fill('F2:F4')
  assert.deepEqual(await ranges(),expected);await modal.locator('[type=submit]').click()
  await page.waitForFunction(()=>document.querySelector('[role="dialog"][aria-label="允许用户编辑区域"]')?.hidden===true && !document.querySelector('#report-editor')?.inert)
  const defined=await operations();await writeFile(join(directory,'defined-draft.json'),JSON.stringify({defined,expected},null,2));assert.deepEqual(defined.find(op=>op.kind==='setSheetEditableRanges')?.ranges,expected)
  await history(original,defined,'definitions');await page.reload();await ready();assert.deepEqual(await operations(),defined)
  await openDialog();assert.deepEqual(await ranges(),expected);await inspect('built-refreshed');await modal.locator('[data-action=cancel]').click()
  stage='protect';await command('Review','sheet-protect');await page.waitForFunction(()=>document.querySelector('.workbook-feedback')?.textContent?.includes('设为受保护'))
  await page.waitForFunction(()=>Object.keys(localStorage).filter(k=>k.startsWith('native-editor-draft:')).some(k=>JSON.parse(localStorage.getItem(k)).operations.some(op=>op.kind==='protectSheet'&&op.protect===true)))
  const protectedDraft=await operations();await history(defined,protectedDraft,'protect')
  assert.equal(await rangesDisabled(),true)
  stage='allowed-value';await goto('Inputs!B2');await page.keyboard.type('42');await page.keyboard.press('Enter')
  await page.waitForFunction(()=>Object.keys(localStorage).filter(k=>k.startsWith('native-editor-draft:')).some(k=>JSON.parse(localStorage.getItem(k)).operations.some(op=>op.kind==='applyCellEdits'&&op.edits.some(e=>e.sheetName==='Inputs'&&e.row===1&&e.column===1&&e.cell?.value===42))))
  const edited=await operations();await history(protectedDraft,edited,'allowed-value');await copy('Inputs!B2','42')
  stage='allowed-formula';await goto('Inputs!E2');await page.keyboard.type('=SUM(B2:C2)');await page.keyboard.press('Enter');await copy('Inputs!E2','45')
  const formulaDraft=await operations();await history(edited,formulaDraft,'allowed-formula')
  stage='blocked-cell';await goto('Inputs!A2');await page.keyboard.type('forbidden');await page.keyboard.press('Enter');await copy('Inputs!A2','locked');assert.deepEqual(await operations(),formulaDraft)
  await page.reload();await ready();assert.deepEqual(await operations(),formulaDraft);await copy('Inputs!B2','42');await copy('Inputs!E2','45')
  stage='unsupported-definition';await goto('Restricted!A1');await openDialog();await modal.getByRole('alert').waitFor();assert.equal(await modal.locator('[type=submit]').isDisabled(),true)
  await inspect('built-password-readonly');await page.keyboard.press('Escape');assert.deepEqual(await operations(),formulaDraft)
  stage='save';await page.locator('[data-action=save]').click();await page.waitForFunction(()=>document.querySelector('.save-state-label')?.textContent?.includes('已保存修订 2'),null,{timeout:60000})
  assert.equal(saveCount,1);assert.equal(routeError,undefined)
  const text=await page.locator('body').innerText();assert.ok(text.includes('允许编辑区域待人工复核，文件已生成。'));await writeFile(join(directory,'save-warning.json'),JSON.stringify({saveCount,text},null,2))
 }
 stage='download';if(reviewOnly)await open(2)
 const [download]=await Promise.all([page.waitForEvent('download'),page.locator('[data-action="xlsx-download"]').click()]);assert.equal(await download.failure(),null)
 const downloaded=await readFile(await download.path());assert.equal(sha(downloaded),saved.sha256);assert.deepEqual(downloaded,revisions.get(2));await writeFile(join(directory,'downloaded.xlsx'),downloaded)
 const independent=fixture({mode:'inspect'});await writeFile(join(directory,'independent-check.json'),JSON.stringify(independent,null,2))
 const response=await page.request.get(`${app}/download/2.xlsx`);assert.equal(response.status(),200);assert.equal(sha(await response.body()),saved.sha256)
 stage='reopen';await open(2);assert.deepEqual(await operations(),[]);await copy('Inputs!B2','42');await copy('Inputs!E2','45');assert.equal(await rangesDisabled(),true)
 // 原文件受保护时入口正确禁用；在新修订草稿中撤销保护，只为核对真实保存的定义。
 await command('Review','sheet-protect');await page.waitForFunction(()=>document.querySelector('.workbook-feedback')?.textContent?.includes('保护将在保存后移除'))
 await openDialog();assert.deepEqual(await ranges(),expected);await inspect('built-reopened-definitions');await modal.locator('[data-action=cancel]').click()
 await command('File','undo');await page.waitForFunction(()=>!document.querySelector('#report-editor')?.inert && Object.keys(localStorage).filter(k=>k.startsWith('native-editor-draft:')).every(k=>JSON.parse(localStorage.getItem(k)).operations.length===0));assert.deepEqual(await operations(),[]);assert.equal(await rangesDisabled(),true)
 const context=await page.request.get(`${app}/reports/v1/native/${documentId}/2/api/context`).then(r=>r.json());assert.equal(context.context.sourceFile.sha256,saved.sha256)
 await Promise.all(assetChecks);assert.ok(assets.size>100);assert.deepEqual(errors,[]);assert.deepEqual(layout.failures,[]);assert.equal(routeError,undefined)
 for(const name of scripts)assert.equal(sha(await readFile(join(frontend,'smoke',name))),scriptHashes[name],'运行中验收脚本变化')
 const evidence={ok:true,directory,reviewOnly,saveCount,manifestSha256:sha(manifest),browserVersion:browser.version(),results,independent,context,layout,assets:Object.fromEntries(assets),errors,scriptHashes,
  validationWarningVerified:!reviewOnly,revision2Reopened:true,allowedValueAndFormula:true,lockedValueUnchanged:true,scope:'实际构建/Univer/保存桥/HTTP下载；身份/CSRF/修订登记应答为夹具，非桌面Excel实机'}
 await writeFile(join(directory,'evidence.json'),JSON.stringify(evidence,null,2));console.log(JSON.stringify({ok:true,directory,saveCount,layoutCases:layout.cases.length,assets:assets.size,independent}))
}catch(error){if(page){await page.screenshot({path:join(directory,'failure.png')}).catch(()=>{});await writeFile(join(directory,'failure.html'),await page.content()).catch(()=>{});await writeFile(join(directory,'failure-storage.json'),JSON.stringify(await page.evaluate(()=>Object.fromEntries(Object.entries(localStorage))),null,2)).catch(()=>{})}await writeFile(join(directory,'failure.json'),JSON.stringify({stage,routeError,error:String(error),stack:error.stack},null,2));throw error}
finally{await browser?.close();await new Promise(done=>http.close(done))}
