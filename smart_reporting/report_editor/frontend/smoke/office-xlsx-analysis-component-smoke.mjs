// 产品构造器+CSS；仅运算回调为可释放Promise，明确不证明实际求解器/保存。
import assert from 'node:assert/strict'
import {mkdir,writeFile} from 'node:fs/promises'
import {spawn} from 'node:child_process'
import {fileURLToPath} from 'node:url'
import {join} from 'node:path'
import {setTimeout as delay} from 'node:timers/promises'
import {chromium} from 'playwright'
import {inspectAnalysisLayout} from './office-xlsx-analysis-layout.mjs'
const frontend=fileURLToPath(new URL('../',import.meta.url)),directory=process.env.XLSX_ANALYSIS_COMPONENT_OUTPUT,port=Number(process.env.XLSX_ANALYSIS_COMPONENT_PORT??4395),base='http://127.0.0.1:'+port+'/reports/v1/editor/assets/'
assert.ok(directory);await mkdir(directory,{recursive:true})
const server=spawn('./node_modules/.bin/vite',['--host','127.0.0.1','--port',String(port),'--strictPort'],{cwd:frontend,stdio:'ignore'}),layout={cases:[],failures:[]},errors=[]
let browser,page
try{
 for(let i=0;;i++){assert.equal(server.exitCode,null);try{if((await fetch(base+'native.html')).ok)break}catch{}assert.ok(i<100);await delay(250)}
 browser=await chromium.launch({headless:true,...(process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE?{executablePath:process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE}:{})})
 for(const kind of ['goal','table']){
  page=await browser.newPage({viewport:{width:1440,height:900}});page.on('pageerror',e=>errors.push(e.message));page.on('console',m=>{if(m.type()==='error')errors.push(m.text())})
  await page.route('**/analysis-fixture.html',r=>r.fulfill({contentType:'text/html',body:'<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><link rel="stylesheet" href="./src/style.css"><link rel="stylesheet" href="./src/office-theme.css"><link rel="stylesheet" href="./src/workbook.css"></head><body><button id="entry">打开</button><main id="fixture"></main></body></html>'}))
  await page.goto(base+'analysis-fixture.html')
  await page.evaluate(async({base,kind})=>{
   const module=await import(base+'src/workbook-'+(kind==='goal'?'goal-seek':'data-table')+'-dialog.ts')
   const root=document.querySelector('#fixture'),entry=document.querySelector('#entry');window.analysisCalls=[]
   const callback=(target,input)=>{window.analysisCalls.push({target,input:{...input,onProgress:undefined}});input.onProgress?.(1,3);return new Promise((resolve,reject)=>{window.analysisComplete=outcome=>outcome==='error'?reject(new Error('来源计算失败：'+'请核对公式和输入，保留当前字段后重试。'.repeat(40))):resolve(kind==='goal'?{found:true,solution:15,reached:30,iterations:3}:{cells:3})})}
   const dialog=kind==='goal'?module.createGoalSeekDialog(root,callback):module.createDataTableDialog(root,callback)
   entry.addEventListener('click',()=>dialog.open({workbookId:'fixture-book',sheetId:'fixture-sheet',...(kind==='goal'?{setCell:'B1'}:{range:'D2:E5'})}))
  },{base,kind})
  await page.locator('#entry').click()
  const label=kind==='goal'?'单变量求解':'模拟运算表',dialog=page.getByRole('dialog',{name:label,exact:true})
  await dialog.waitFor();await inspectAnalysisLayout(page,{directory,label,phase:kind+'-initial',layout})
  if(process.env.XLSX_ANALYSIS_INITIAL_ONLY==='1'){await page.close();continue}
  if(kind==='goal'){await dialog.getByLabel('目标值',{exact:true}).fill('30');await dialog.getByLabel('可变单元格',{exact:true}).fill('A1')}else await dialog.getByLabel('列输入单元格',{exact:true}).fill('A1')
  await dialog.locator('[type=submit]').click();await page.waitForFunction(()=>window.analysisCalls.length===1)
  const busy=await dialog.getAttribute('aria-busy');assert.equal(busy,'true')
  await inspectAnalysisLayout(page,{directory,label,phase:kind+'-busy',layout});await page.keyboard.press('Escape');assert.equal(await dialog.isVisible(),true)
  await page.evaluate(()=>window.analysisComplete('error'));await dialog.getByRole('alert').getByText('来源计算失败：',{exact:false}).waitFor()
  await inspectAnalysisLayout(page,{directory,label,phase:kind+'-error',layout})
  await dialog.locator('[type=submit]').click();await page.waitForFunction(()=>window.analysisCalls.length===2);await page.evaluate(()=>window.analysisComplete('success'));await page.waitForFunction(()=>document.querySelector('[role=dialog]')?.getAttribute('aria-busy')==='false')
  await inspectAnalysisLayout(page,{directory,label,phase:kind+'-success',layout});await page.keyboard.press('Escape');await dialog.waitFor({state:'hidden'});assert.equal(await page.locator('#entry').evaluate(n=>n===document.activeElement),true)
  const calls=await page.evaluate(()=>window.analysisCalls);assert.equal(calls.length,2);assert.deepEqual(calls[0],calls[1]);await page.close()
 }
 assert.deepEqual(errors,[]);if(process.env.XLSX_ANALYSIS_BASELINE!=='1')assert.deepEqual(layout.failures,[])
 await writeFile(join(directory,'evidence.json'),JSON.stringify({ok:layout.failures.length===0,baseline:process.env.XLSX_ANALYSIS_BASELINE==='1',callbackIsFixture:true,actualEngineVerified:false,layout,errors},null,2));console.log(JSON.stringify({cases:layout.cases.length,failures:layout.failures.length,errors}))
}catch(error){await page?.screenshot({path:join(directory,'failure.png')}).catch(()=>{});await writeFile(join(directory,'failure.json'),JSON.stringify({error:String(error),stack:error.stack,errors},null,2));throw error}
finally{await browser?.close();server.kill();if(server.exitCode===null)await Promise.race([new Promise(done=>server.once('exit',done)),delay(5000)]);if(server.exitCode===null)server.kill('SIGKILL')}
