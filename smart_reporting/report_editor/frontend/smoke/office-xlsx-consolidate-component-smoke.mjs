// 真实窗口与CSS；同步apply回调为夹具，仅证明组件交互，不证明引擎/文件保存。
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
const frontend=fileURLToPath(new URL('../',import.meta.url)),directory=process.env.CONSOLIDATE_COMPONENT_OUTPUT
assert.ok(directory);await mkdir(directory,{recursive:true})
const port=Number(process.env.CONSOLIDATE_COMPONENT_PORT??4397),base=`http://127.0.0.1:${port}/reports/v1/editor/assets/`,layout={cases:[],failures:[]},errors=[]
const files=['src/workbook-consolidate-dialog.ts','src/workbook.css','src/modal.ts','src/focus-trap.ts','smoke/office-xlsx-analysis-layout.mjs','smoke/office-xlsx-consolidate-component-smoke.mjs']
const hashes=async()=>Object.fromEntries(await Promise.all(files.map(async file=>[file,createHash('sha256').update(await readFile(join(frontend,file))).digest('hex')])))
const source=await hashes(),fd=openSync(join(directory,'vite.log'),'wx')
const server=spawn(process.execPath,['--input-type=module','-e',`import {createServer} from 'vite';const server=await createServer({cacheDir:${JSON.stringify(join(directory,'vite-cache'))},server:{host:'127.0.0.1',port:${port},strictPort:true}});await server.listen()`],{cwd:frontend,stdio:['ignore',fd,fd]});closeSync(fd)
let browser,page
try{
 for(let i=0;;i++){assert.equal(server.exitCode,null);try{if((await fetch(base+'native.html')).ok)break}catch{}assert.ok(i<100);await delay(250)}
 browser=await chromium.launch({headless:true,...(process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE?{executablePath:process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE}:{})})
 page=await browser.newPage({viewport:{width:1440,height:900}});page.on('pageerror',e=>errors.push(e.message));page.on('console',m=>{if(m.type()==='error')errors.push(m.text())})
 await page.route('**/consolidate-fixture.html',r=>r.fulfill({contentType:'text/html',body:'<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><link rel="stylesheet" href="./src/style.css"><link rel="stylesheet" href="./src/office-theme.css"><link rel="stylesheet" href="./src/workbook.css"></head><body><button id="entry">打开合并计算</button><main id="fixture"></main></body></html>'}))
 await page.goto(base+'consolidate-fixture.html')
 await page.evaluate(async base=>{
  const {createConsolidateDialog}=await import(base+'src/workbook-consolidate-dialog.ts')
  window.consolidateCalls=[];window.consolidateFail=true
  const dialog=createConsolidateDialog(document.querySelector('#fixture'),(target,input)=>{
   window.consolidateCalls.push({target,input});if(window.consolidateFail)throw new Error('目标与来源重叠：'+'请保留当前引用，核对输出单元格后重试。'.repeat(40))
  })
  document.querySelector('#entry').addEventListener('click',()=>dialog.open({workbookId:'fixture-book',sheetId:'fixture-sheet',row:0,column:4,defaultReference:'',targetLabel:'汇总!E1'}))
 },base)
 const dialog=page.getByRole('dialog',{name:'合并计算',exact:true}),reference=dialog.getByLabel('引用位置',{exact:true}),inspect=phase=>inspectAnalysisLayout(page,{directory,label:'合并计算',phase,layout})
 await page.locator('#entry').click();await dialog.waitFor();await inspect('consolidate-empty')
 if(process.env.CONSOLIDATE_INITIAL_ONLY!=='1'){
  const references=Array.from({length:18},(_,i)=>`'长引用_部门收入费用明细_<保真>&_${i}'!$A$1:$B$3`)
  for(const value of references){await reference.fill(value);await reference.press('Enter')}
  assert.equal(await dialog.locator('[data-reference]').count(),18);await inspect('consolidate-list')
  await reference.fill('invalid reference');await reference.press('Enter');await dialog.getByRole('alert').getByText('引用位置无效：',{exact:false}).waitFor();await inspect('consolidate-invalid-error')
  await reference.fill("'O''Brien'!A1:B2");await dialog.getByLabel('使用左列标签',{exact:true}).check()
  assert.deepEqual(await dialog.getByLabel('函数',{exact:true}).locator('option').evaluateAll(nodes=>nodes.map(n=>n.value)),['sum','count','average'])
  await dialog.locator('[type=submit]').click();await dialog.getByRole('alert').getByText('目标与来源重叠：',{exact:false}).waitFor();await inspect('consolidate-long-error')
  assert.equal(await reference.inputValue(),"'O''Brien'!A1:B2");assert.equal(await dialog.locator('[data-reference]').count(),18)
  const middle=dialog.locator('[data-reference] button').nth(8);await middle.focus();await page.keyboard.press('Enter')
  assert.equal(await page.evaluate(()=>document.activeElement?.getAttribute('aria-label')),`删除引用 ${references[9]}`)
  for(let i=17;i>0;i--)await dialog.locator('[data-reference] button').last().click()
  assert.equal(await reference.evaluate(n=>n===document.activeElement),true);await inspect('consolidate-removed')
  await page.evaluate(()=>window.consolidateFail=false);await dialog.locator('[type=submit]').click();await dialog.waitFor({state:'hidden'})
  assert.equal(await page.locator('#entry').evaluate(n=>n===document.activeElement),true)
  const calls=await page.evaluate(()=>window.consolidateCalls);assert.equal(calls.length,2);assert.equal(calls[0].input.references.length,19);assert.deepEqual(calls[1].input,{fn:'sum',references:["'O''Brien'!A1:B2"],leftLabels:true})
 }
 assert.deepEqual(await hashes(),source,'运行时本批来源变化');assert.deepEqual(errors,[])
 const evidence={ok:layout.failures.length===0,baseline:process.env.CONSOLIDATE_COMPONENT_BASELINE==='1',callbackIsFixture:true,actualEngineVerified:false,source,browser:browser.version(),layout,errors}
 await writeFile(join(directory,'evidence.json'),JSON.stringify(evidence,null,2));console.log(JSON.stringify({cases:layout.cases.length,failures:layout.failures.length,errors}))
 if(!evidence.baseline)assert.deepEqual(layout.failures,[])
}catch(error){await page?.screenshot({path:join(directory,'failure.png')}).catch(()=>{});await writeFile(join(directory,'failure.json'),JSON.stringify({error:String(error),stack:error.stack,errors},null,2));throw error}
finally{await browser?.close();server.kill();if(server.exitCode===null)await Promise.race([new Promise(done=>server.once('exit',done)),delay(5000)]);if(server.exitCode===null)server.kill('SIGKILL')}
