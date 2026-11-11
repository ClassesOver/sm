import assert from 'node:assert/strict'
import {spawn,spawnSync} from 'node:child_process'
import {createHash} from 'node:crypto'
import {mkdir,readFile,writeFile} from 'node:fs/promises'
import {join,resolve} from 'node:path'
import {fileURLToPath} from 'node:url'
import {setTimeout as delay} from 'node:timers/promises'
import {chromium} from 'playwright'
const frontend=fileURLToPath(new URL('../',import.meta.url)),repo=fileURLToPath(new URL('../../../../',import.meta.url))
const directory=process.env.PDF_XLSX_IMAGES_SMOKE_DIRECTORY??'/tmp/pdf-xlsx-images-browser-20261111'
const staticDirectory=resolve(process.env.PDF_SMOKE_STATIC_DIRECTORY??join(frontend,'../static'))
const port=Number(process.env.PDF_XLSX_IMAGES_SMOKE_PORT??4327),origin='http://127.0.0.1:'+port
const sha=bytes=>createHash('sha256').update(bytes).digest('hex')
await mkdir(directory,{recursive:true})
const manifest=await readFile(join(staticDirectory,'.vite/manifest.json'))
await writeFile(join(directory,'build-manifest.json'),manifest)
const server=spawn(join(repo,'.venv/bin/python'),[join(frontend,'smoke/pdf-xlsx-images-server.py'),'--directory',directory,'--port',String(port)],{cwd:repo,env:{...process.env,PYTHONPATH:repo},stdio:'pipe'})
let browser,page,stage='server',serverLog=''
server.stdout.on('data',data=>{serverLog+=data});server.stderr.on('data',data=>{serverLog+=data})
const pageErrors=[],consoleErrors=[],httpErrors=[],assetErrors=[],checks=[],assets=new Map()
try{
 for(let attempt=0;;attempt++){
  assert.equal(server.exitCode,null,serverLog)
  try{if((await fetch(origin+'/__smoke__/state',{signal:AbortSignal.timeout(1500)})).ok)break}catch{}
  assert(attempt<240,serverLog);await delay(250)
 }
 const info=JSON.parse(await readFile(join(directory,'server-info.json'),'utf8'))
 browser=await chromium.launch({headless:true,...(process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE?{executablePath:process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE}:{})});page=await browser.newPage({viewport:{width:1500,height:1100}})
 page.on('pageerror',error=>pageErrors.push(error.message))
 page.on('console',message=>{if(message.type()==='error')consoleErrors.push(message.text())})
 page.on('response',response=>{
  const path=new URL(response.url()).pathname
  if(response.status()>=400)httpErrors.push({path,status:response.status()})
  if(!path.startsWith('/reports/v1/editor/assets/')||!/.m?js$/.test(path))return
  checks.push((async()=>{const bytes=await response.body(),disk=await readFile(join(staticDirectory,path.slice('/reports/v1/editor/assets/'.length)));assert.equal(sha(bytes),sha(disk));assets.set(path,sha(bytes))})().catch(error=>assetErrors.push(String(error))))
 })
 stage='real-native-grant';await page.goto(origin+info.openPath)
 await page.waitForFunction(()=>document.querySelector('#report-editor')?.getAttribute('aria-busy')==='false',null,{timeout:60000})
 await page.locator('[data-pdf-ribbon-tab="home"]').click()
 await page.locator('[data-source-command-id="genoffice.pdf.home.convert.toExcel"]').click()
 const dialog=page.getByRole('dialog',{name:'转换 PDF 为Excel',exact:true});await dialog.waitFor({state:'visible'})
 stage='actual-conversion'
 const pending=page.waitForResponse(response=>response.url().endsWith('/api/convert-office')&&response.request().method()==='POST')
 await dialog.locator('[data-pdf-convert-office-apply]').click()
 const response=await pending,result=await response.json()
 assert.equal(response.status(),200,JSON.stringify(result));assert.equal(result.source.sha256,info.sourceSha256);assert.equal(result.validation.ok,false)
 assert.equal(response.request().postDataJSON().format,'xlsx');assert.equal(response.request().postDataJSON().expectedSha256,info.sourceSha256)
 assert.equal(result.conversion.pageResults.length,3);assert(result.conversion.pageResults.every(page=>page.status==='ok'))
 assert(result.validation.issues.some(issue=>String(issue.message??issue).includes('不代表原图文相对排版')))
 const artifact=result.artifacts.xlsx;assert(artifact?.downloadUrl)
 stage='actual-signed-download';const download=await page.request.get(artifact.downloadUrl)
 assert.equal(download.status(),200);const bytes=await download.body();assert.equal(sha(bytes),artifact.sha256);assert.equal(bytes.length,artifact.size)
 await writeFile(join(directory,'converted.xlsx'),bytes);await writeFile(join(directory,'conversion.json'),JSON.stringify(result,null,2))
 await dialog.getByRole('link',{name:'下载转换后的 XLSX',exact:true}).waitFor({state:'visible'})
 await dialog.screenshot({path:join(directory,'converted-xlsx.png')})
 stage='independent-openpyxl-pillow-anchors'
 const verification=spawnSync(join(repo,'.venv/bin/python'),[join(frontend,'smoke/pdf-xlsx-images-verify.py'),join(directory,'converted.xlsx'),'--output',join(directory,'independent.json')],{cwd:repo,encoding:'utf8'})
 assert.equal(verification.status,0,verification.stdout+verification.stderr)
 const independent=JSON.parse(await readFile(join(directory,'independent.json'),'utf8'))
 await Promise.all(checks);assert(assets.size>0)
 for(const errors of [assetErrors,pageErrors,consoleErrors,httpErrors])assert.deepEqual(errors,[])
 assert.deepEqual(await readFile(join(staticDirectory,'.vite/manifest.json')),manifest)
 const state=await(await fetch(origin+'/__smoke__/state',{signal:AbortSignal.timeout(5000)})).json()
 assert.equal(state.sourceSha256,info.sourceSha256);assert.equal(state.savedRevisions,0)
 const summary={ok:true,directory,staticDirectory,scope:'real browser/native grant-cookie-CSRF/packed PDF engine/publication/signed download; in-memory repositories',manifestSha256:sha(manifest),browserVersion:browser.version(),sourceSha256:info.sourceSha256,sourceUnchanged:true,artifact,independent,manualReview:true,assets:Object.fromEntries(assets),assetErrors,pageErrors,consoleErrors,httpErrors,requests:state.requests}
 await writeFile(join(directory,'summary.json'),JSON.stringify(summary,null,2));console.log(JSON.stringify({ok:true,directory}))
}catch(error){
 await page?.screenshot({path:join(directory,'failure.png'),fullPage:true}).catch(()=>{})
 if(page)await page.content().then(text=>writeFile(join(directory,'failure.html'),text)).catch(()=>{})
 await writeFile(join(directory,'failure.json'),JSON.stringify({stage,error:String(error),assetErrors,pageErrors,consoleErrors,httpErrors},null,2));throw error
}finally{
 await browser?.close();server.kill();await writeFile(join(directory,'server.log'),serverLog)
 if(server.exitCode===null)await Promise.race([new Promise(resolve=>server.once('exit',resolve)),delay(5000)])
 if(server.exitCode===null)server.kill('SIGKILL')
}
