// 真实窗口/CSS；回调为可释放Promise，仅证明交互，不代替筛选引擎/文件验收。
import assert from 'node:assert/strict'
import {mkdir,readFile,writeFile} from 'node:fs/promises'
import {openSync,closeSync} from 'node:fs'
import {createHash} from 'node:crypto'
import {spawn} from 'node:child_process'
import {fileURLToPath} from 'node:url'
import {join} from 'node:path'
import {setTimeout as delay} from 'node:timers/promises'
import {chromium} from 'playwright'
import {inspectAnalysisLayout} from './office-xlsx-analysis-layout.mjs'
const frontend=fileURLToPath(new URL('../',import.meta.url)),directory=process.env.ADVANCED_FILTER_COMPONENT_OUTPUT
assert.ok(directory);await mkdir(directory,{recursive:true})
const port=Number(process.env.ADVANCED_FILTER_COMPONENT_PORT??4396),base=`http://127.0.0.1:${port}/reports/v1/editor/assets/`,layout={cases:[],failures:[]},errors=[]
const files=['src/workbook-advanced-filter-dialog.ts','src/workbook.css','src/modal.ts','src/focus-trap.ts','smoke/office-xlsx-analysis-layout.mjs','smoke/office-xlsx-advanced-filter-component-smoke.mjs']
const hashes=async()=>Object.fromEntries(await Promise.all(files.map(async file=>[file,createHash('sha256').update(await readFile(join(frontend,file))).digest('hex')])))
const source=await hashes(),serverLog=openSync(join(directory,'vite.log'),'wx')
const server=spawn(process.execPath,['--input-type=module','-e',`import {createServer} from 'vite'; const server=await createServer({cacheDir:${JSON.stringify(join(directory,'vite-cache'))},server:{host:'127.0.0.1',port:${port},strictPort:true}});await server.listen()`],{cwd:frontend,stdio:['ignore',serverLog,serverLog]})
closeSync(serverLog)
let browser,page
try{
 for(let i=0;;i++){assert.equal(server.exitCode,null);try{if((await fetch(base+'native.html')).ok)break}catch{}assert.ok(i<100);await delay(250)}
 browser=await chromium.launch({headless:true,...(process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE?{executablePath:process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE}:{})})
 page=await browser.newPage({viewport:{width:1440,height:900}});page.on('pageerror',e=>errors.push(e.message));page.on('console',m=>{if(m.type()==='error')errors.push(m.text())})
 await page.route('**/advanced-filter-fixture.html',r=>r.fulfill({contentType:'text/html',body:'<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><link rel="stylesheet" href="./src/style.css"><link rel="stylesheet" href="./src/office-theme.css"><link rel="stylesheet" href="./src/workbook.css"></head><body><button id="entry">打开高级筛选</button><main id="fixture"></main></body></html>'}))
 await page.goto(base+'advanced-filter-fixture.html')
 await page.evaluate(async base=>{
  const {createAdvancedFilterDialog}=await import(base+'src/workbook-advanced-filter-dialog.ts')
  window.filterCalls=[]
  const dialog=createAdvancedFilterDialog(document.querySelector('#fixture'),(target,input)=>{
   window.filterCalls.push({target,input});return new Promise((resolve,reject)=>{window.filterComplete=result=>result==='error'?reject(new Error('来源筛选失败：'+'请核对范围与条件，保留字段后重试。'.repeat(40))):resolve({})})
  })
  document.querySelector('#entry').addEventListener('click',()=>dialog.open({unitId:'fixture-book',sheetId:'fixture-sheet',workbookCore:{},sheetCore:{},range:{startRow:4,endRow:8,startColumn:2,endColumn:4},snapshotSignature:'snapshot',selectionSignature:'selection',filterSignature:'null',revision:1,fields:[{colId:0,label:'地区 '+ '<保真> & 😀 '.repeat(35)},{colId:1,label:'金额'}]}))
 },base)
 const dialog=page.getByRole('dialog',{name:'高级筛选',exact:true}),inspect=phase=>inspectAnalysisLayout(page,{directory,label:'高级筛选',phase,layout})
 await page.locator('#entry').click();await dialog.waitFor();await inspect('filter-initial')
 if(process.env.ADVANCED_FILTER_INITIAL_ONLY!=='1'){
  await dialog.locator('[type=submit]').click();await dialog.getByRole('alert').getByText('请填写第一筛选条件',{exact:true}).waitFor();await inspect('filter-empty-error')
  await dialog.getByLabel('第一条件值',{exact:true}).fill(' A ');await dialog.locator('[type=submit]').click();await page.waitForFunction(()=>window.filterCalls.length===1)
  assert.equal(await dialog.getAttribute('aria-busy'),'true');await inspect('filter-busy')
  await page.keyboard.press('Escape');assert.equal(await dialog.isVisible(),true)
  await page.evaluate(()=>window.filterComplete('error'));await dialog.getByRole('alert').getByText('来源筛选失败：',{exact:false}).waitFor();await inspect('filter-long-error')
  assert.equal(await dialog.getByLabel('第一条件值',{exact:true}).inputValue(),' A ')
  await dialog.locator('[type=submit]').click();await page.waitForFunction(()=>window.filterCalls.length===2);await page.evaluate(()=>window.filterComplete('ok'));await dialog.waitFor({state:'hidden'})
  assert.equal(await page.locator('#entry').evaluate(n=>n===document.activeElement),true)
  const calls=await page.evaluate(()=>window.filterCalls);assert.deepEqual(calls[0],calls[1]);assert.deepEqual(calls[0].input,{colId:0,operator1:'equal',value1:' A ',operator2:'equal',value2:'',and:true})
 }
 assert.deepEqual(await hashes(),source,'运行时本批来源变化');assert.deepEqual(errors,[])
 const evidence={ok:layout.failures.length===0,baseline:process.env.ADVANCED_FILTER_COMPONENT_BASELINE==='1',callbackIsFixture:true,actualEngineVerified:false,source,browser:browser.version(),layout,errors}
 await writeFile(join(directory,'evidence.json'),JSON.stringify(evidence,null,2));console.log(JSON.stringify({cases:layout.cases.length,failures:layout.failures.length,errors}))
 if(!evidence.baseline)assert.deepEqual(layout.failures,[])
}catch(error){await page?.screenshot({path:join(directory,'failure.png')}).catch(()=>{});await writeFile(join(directory,'failure.json'),JSON.stringify({error:String(error),stack:error.stack,errors},null,2));throw error}
finally{await browser?.close();server.kill();if(server.exitCode===null)await Promise.race([new Promise(done=>server.once('exit',done)),delay(5000)]);if(server.exitCode===null)server.kill('SIGKILL')}
