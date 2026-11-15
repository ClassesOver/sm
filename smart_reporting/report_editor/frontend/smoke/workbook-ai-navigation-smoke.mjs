// Production browser + native HTTP/grants + Agno tool call + actual Univer view.
import assert from 'node:assert/strict'
import {readFile,writeFile,mkdtemp} from 'node:fs/promises'
import {spawn} from 'node:child_process'
import {tmpdir} from 'node:os'
import {join,delimiter} from 'node:path'
import {fileURLToPath} from 'node:url'
import {setTimeout as delay} from 'node:timers/promises'
import {createHash} from 'node:crypto'
import {chromium} from 'playwright'
const frontend=fileURLToPath(new URL('../',import.meta.url)),repo=fileURLToPath(new URL('../../../../',import.meta.url))
const candidateMode=process.env.WORKBOOK_AI_NAVIGATION_CANDIDATE==='1'
const directory=process.env.WORKBOOK_AI_NAVIGATION_DIRECTORY??await mkdtemp(join(tmpdir(),'workbook-ai-navigation-'))
const port=Number(process.env.WORKBOOK_AI_NAVIGATION_PORT??4367),origin=`http://127.0.0.1:${port}`
const staticDirectory=process.env.PDF_SMOKE_STATIC_DIRECTORY??join(frontend,'../static')
const server=process.env.WORKBOOK_AI_NAVIGATION_EXTERNAL_SERVER==='1'?null:spawn(process.env.WORKBOOK_AI_NAVIGATION_PYTHON??join(repo,'.venv/bin/python'),
 [join(frontend,'smoke/workbook-ai-navigation-server.py'),'--directory',directory,'--port',String(port)],{cwd:repo,env:{...process.env,PYTHONPATH:[repo,process.env.PYTHONPATH].filter(Boolean).join(delimiter)},stdio:'pipe'})
let serverLog='',browser,page
server?.stdout.on('data',data=>{serverLog+=data});server?.stderr.on('data',data=>{serverLog+=data})
const errors=[],assetErrors=[],checks=[],assets=new Map(),sha=bytes=>createHash('sha256').update(bytes).digest('hex')
try {
 for(let attempt=0;;attempt++){
  if(server)assert.equal(server.exitCode,null,serverLog)
  try{if((await fetch(origin+'/__smoke__/state',{signal:AbortSignal.timeout(1000)})).ok)break}catch{}
  assert(attempt<240,serverLog);await delay(250)
 }
 const info=JSON.parse(await readFile(directory+'/info.json','utf8'))
 browser=await chromium.launch({headless:true,...(process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE?{executablePath:process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE}:{}),args:['--disable-dev-shm-usage']})
 page=await browser.newPage({viewport:{width:1560,height:1000}})
 page.on('pageerror',error=>errors.push(String(error)))
 page.on('response',response=>{
  const path=new URL(response.url()).pathname,prefix='/reports/v1/editor/assets/'
  if(path.startsWith(prefix)&&/\.(js|css)$/.test(path))checks.push((async()=>{
   assert.equal(response.status(),200);const bytes=await response.body(),disk=await readFile(join(staticDirectory,path.slice(prefix.length)))
   assert.equal(sha(bytes),sha(disk));assets.set(path,sha(bytes))
  })().catch(error=>assetErrors.push(String(error))))
 })
 await page.goto(origin+info.openPath)
 await page.waitForFunction(()=>document.querySelector('#report-editor')?.getAttribute('aria-busy')==='false',null,{timeout:90000})
 await page.getByText('Target',{exact:true}).first().click()
 const address=page.locator('[data-u-comp="defined-name"] input')
 await address.fill('A1');await address.press('Enter')
 const operations=()=>page.evaluate(()=>Object.entries(localStorage).filter(([key])=>key.startsWith('native-editor-draft:')).flatMap(([,value])=>JSON.parse(value).operations??[]))
 const before=await operations()
 await page.locator('.workbook-ribbon .office-ai-entry').click()
 if(candidateMode)await page.locator('[data-office-ai-mode="edit"]').click()
 const panel=page.locator(candidateMode?'.workbook-native-ai':'.native-office-assistant')
 await panel.locator('textarea').fill('定位到当前工作表K2000:L2001')
 if(candidateMode)await panel.locator('select').selectOption('workbook')
 let posted
 page.on('request',request=>{if(request.url().endsWith(candidateMode?'/workbook-ai/start':'/ai/office-read/start'))posted=request.postDataJSON()})
 await panel.locator(candidateMode?'[type="submit"]':'[data-office-ai="start"]').click()
 await page.waitForFunction(({candidateMode})=>document.querySelector(candidateMode?'.workbook-native-ai .native-ai-status':'.native-office-assistant [role="status"]')?.textContent?.includes('已定位到 Target!K2000:L2001'),{candidateMode},{timeout:60000})
 if(candidateMode){
  assert.equal(posted.navigationEnabled,true);assert.equal(posted.selection.sheetName,'Target')
  assert.equal(await panel.locator('.native-ai-preview').isVisible(),false)
 }else{assert.equal(posted.viewSelection.sheetName,'Target');assert.equal(posted.selection,null)}
 assert.match(await address.inputValue(),/K2000:L2001/)
 assert.deepEqual(await operations(),before)
 const state=await (await fetch(origin+'/__smoke__/state')).json()
 assert.equal(state.sha256,info.sha256);assert.equal(state.saved,0)
 assert(!state.requests.some(item=>item.method==='POST'&&/save|\/accept$/.test(item.path)))
 await Promise.all(checks);assert.deepEqual(assetErrors,[]);assert(assets.size>0)
 assert([...assets.keys()].some(path=>path.includes('workbook-ai-navigation')))
 assert.deepEqual(errors,[])
 await page.screenshot({path:directory+'/navigated.png',fullPage:true})
 await writeFile(directory+'/evidence.json',JSON.stringify({status:'passed',posted,address:await address.inputValue(),state,errors,assets:Object.fromEntries(assets),viewportProof:'Production reveal verifies SDK viewport and actual selection; inspect navigated.png for independent visual evidence'},null,2))
 console.log('Navigation browser passed; artifact directory: '+directory)
} catch(error) {
 if(page){await page.screenshot({path:directory+'/failed.png',fullPage:true}).catch(()=>{});await writeFile(directory+'/failed.json',JSON.stringify({error:String(error),errors,url:page.url(),text:await page.locator('body').innerText().catch(()=>''),serverLog},null,2))}
 throw error
} finally {await browser?.close();server?.kill('SIGTERM')}
