// 真实产品构造器/CSS；异步apply边界为夹具，不宣称宿主保存或权限验收。
import assert from 'node:assert/strict'
import { mkdir, readFile, writeFile } from 'node:fs/promises'
import { openSync, closeSync } from 'node:fs'
import { createHash } from 'node:crypto'
import { spawn } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import { join } from 'node:path'
import { setTimeout as delay } from 'node:timers/promises'
import { chromium } from 'playwright'
import { inspectEditableRanges } from './office-xlsx-editable-ranges-layout.mjs'
const frontend=fileURLToPath(new URL('../',import.meta.url)),directory=process.env.EDITABLE_RANGES_COMPONENT_OUTPUT
assert.ok(directory); await mkdir(directory,{recursive:true})
const baseline=process.env.EDITABLE_RANGES_BASELINE==='1',port=Number(process.env.EDITABLE_RANGES_PORT??4399),base=`http://127.0.0.1:${port}/reports/v1/editor/assets/`,layout={cases:[],failures:[]},errors=[]
const files=['src/workbook-editable-ranges-dialog.ts','src/workbook.css','src/modal.ts','src/focus-trap.ts','smoke/office-xlsx-editable-ranges-layout.mjs','smoke/office-xlsx-editable-ranges-component.mjs']
const hashes=async()=>Object.fromEntries(await Promise.all(files.map(async f=>[f,createHash('sha256').update(await readFile(join(frontend,f))).digest('hex')])))
const source=await hashes(),fd=openSync(join(directory,'vite.log'),'wx')
const server=spawn(process.execPath,['--input-type=module','-e',`import {createServer} from 'vite';const s=await createServer({cacheDir:${JSON.stringify(join(directory,'vite-cache'))},server:{host:'127.0.0.1',port:${port},strictPort:true}});await s.listen()`],{cwd:frontend,stdio:['ignore',fd,fd]});closeSync(fd)
let browser,page
try {
  for(let i=0;;i++){assert.equal(server.exitCode,null);try{if((await fetch(base+'native.html')).ok)break}catch{}assert.ok(i<100);await delay(250)}
  browser=await chromium.launch({headless:true});page=await browser.newPage({viewport:{width:1440,height:900}})
  page.on('pageerror',e=>errors.push(e.message));page.on('console',m=>{if(m.type()==='error')errors.push(m.text())})
  await page.route('**/editable-ranges-fixture.html',r=>r.fulfill({contentType:'text/html',body:'<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><link rel="stylesheet" href="./src/style.css"><link rel="stylesheet" href="./src/office-theme.css"><link rel="stylesheet" href="./src/workbook.css"></head><body><button id="entry">打开允许用户编辑区域</button><main id="fixture"></main></body></html>'}))
  await page.goto(base+'editable-ranges-fixture.html')
  await page.evaluate(async base=>{
    const {createEditableRangesDialog}=await import(base+'src/workbook-editable-ranges-dialog.ts')
    window.rangeInput={sheetName:'Inputs',ranges:[{name:'Entry',sqref:'B2:C4'}],selection:'E2:E4'}
    window.rangeMode='pending';window.rangeCalls=[]
    const dialog=createEditableRangesDialog(document.querySelector('#fixture'),async(sheetName,ranges)=>{
      window.rangeCalls.push({sheetName,ranges})
      if(window.rangeMode==='pending')await new Promise((resolve,reject)=>{window.rangeRelease={resolve,reject}})
    })
    document.querySelector('#entry').addEventListener('click',()=>dialog.open(window.rangeInput))
  },base)
  const dialog=page.getByRole('dialog',{name:'允许用户编辑区域',exact:true}),inspect=phase=>inspectEditableRanges(page,{directory,phase,layout})
  await page.locator('#entry').click();await inspect('initial')
  if(!baseline){
    for(let i=2;i<=7;i++){await dialog.locator('[data-action=add]').click();await dialog.getByLabel(`区域名称 ${i}`,{exact:true}).fill(`长名称_<保真>&_区域_${i}_${'R'.repeat(80)}`)}
    await inspect('long-list')
    await dialog.locator('[data-range] button').nth(3).focus();await page.keyboard.press('Enter')
    assert.equal(await dialog.getByLabel('区域名称 4',{exact:true}).evaluate(n=>n===document.activeElement),true)
    await dialog.locator('[type=submit]').click();await page.waitForFunction(()=>!!window.rangeRelease);await inspect('pending')
    await page.keyboard.press('Escape');assert.equal(await dialog.isVisible(),true)
    await page.evaluate(()=>window.rangeRelease.reject(new Error('区域名称重复：'+'请保留当前定义，修改名称后重试。'.repeat(40))))
    await dialog.getByRole('alert').getByText('区域名称重复：',{exact:false}).waitFor();await inspect('long-error')
    await dialog.locator('[data-action=cancel]').click();assert.equal(await page.locator('#entry').evaluate(n=>n===document.activeElement),true)
    await page.evaluate(()=>window.rangeInput={sheetName:'Inputs',ranges:[],protected:true})
    await page.locator('#entry').click();await inspect('protected')
    assert.equal(await dialog.locator('[type=submit]').isDisabled(),true);await page.keyboard.press('Escape')
    await page.evaluate(()=>window.rangeInput={sheetName:'Inputs',ranges:[{name:'Secret_'+ 'S'.repeat(120),sqref:'A1',readonlyReason:'此区域包含密码或权限描述：'+'请在桌面Excel核对。'.repeat(24)}]})
    await page.locator('#entry').click();await inspect('unsupported')
    await dialog.locator('.modal-close').click();assert.equal(await page.locator('#entry').evaluate(n=>n===document.activeElement),true)
    assert.equal((await page.evaluate(()=>window.rangeCalls)).length,1)
  }
  assert.deepEqual(await hashes(),source,'运行中本批源文件发生变化');assert.deepEqual(errors,[])
  const result={ok:!baseline&&layout.failures.length===0,baseline,source,layout,errors,callbackIsFixture:true,browser:browser.version()}
  await writeFile(join(directory,'evidence.json'),JSON.stringify(result,null,2));console.log(JSON.stringify({cases:layout.cases.length,failures:layout.failures.length}))
  if(!baseline)assert.deepEqual(layout.failures,[])
}catch(error){await page?.screenshot({path:join(directory,'failure.png')}).catch(()=>{});await writeFile(join(directory,'failure.json'),JSON.stringify({error:String(error),stack:error.stack,errors},null,2));throw error}
finally{await browser?.close();server.kill();if(server.exitCode===null)await Promise.race([new Promise(done=>server.once('exit',done)),delay(5000)]);if(server.exitCode===null)server.kill('SIGKILL')}
