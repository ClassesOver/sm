// 真实产品构造器/CSS；apply和宿主可用性为显式回调夹具，不证明来源选区或文件保存。
import assert from 'node:assert/strict'
import {mkdir,writeFile} from 'node:fs/promises'
import {spawn} from 'node:child_process'
import {fileURLToPath} from 'node:url'
import {join} from 'node:path'
import {setTimeout as delay} from 'node:timers/promises'
import {chromium} from 'playwright'
import {inspectDocxLinkLayout} from './office-docx-link-layout.mjs'
const frontend=fileURLToPath(new URL('../',import.meta.url)),directory=process.env.DOCX_LINK_COMPONENT_OUTPUT,port=Number(process.env.DOCX_LINK_COMPONENT_PORT??4397),base='http://127.0.0.1:'+port+'/reports/v1/editor/assets/'
assert.ok(directory);await mkdir(directory,{recursive:true})
const server=spawn('./node_modules/.bin/vite',['--host','127.0.0.1','--port',String(port),'--strictPort'],{cwd:frontend,stdio:'ignore'}),layout={cases:[],failures:[]},errors=[]
let browser,page
try{
 for(let i=0;;i++){assert.equal(server.exitCode,null);try{if((await fetch(base+'native.html')).ok)break}catch{}assert.ok(i<100);await delay(250)}
 browser=await chromium.launch({headless:true,...(process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE?{executablePath:process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE}:{})})
 for(const phase of ['initial','error','readonly','readonly-error']){
  page=await browser.newPage({viewport:{width:1440,height:900}});page.on('pageerror',e=>errors.push(e.message));page.on('console',m=>{if(m.type()==='error')errors.push(m.text())})
  await page.route('**/link-fixture.html',r=>r.fulfill({contentType:'text/html',body:'<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><link rel="stylesheet" href="./src/style.css"><link rel="stylesheet" href="./src/office-theme.css"><link rel="stylesheet" href="./src/docx.css"></head><body><button id="entry">打开超链接</button><main id="fixture"></main></body></html>'}))
  await page.goto(base+'link-fixture.html')
  await page.evaluate(async base=>{
   const {openDocxLinkDialog}=await import(base+'src/docx-link-dialog.ts');window.linkReadonly=false;window.linkError=true;window.linkApplied=[];window.linkClosed=0
   document.querySelector('#entry').addEventListener('click',()=>{window.linkController=openDocxLinkDialog(document.querySelector('#fixture'),'https://example.test/source?name=年度报告',{unavailable:()=>window.linkReadonly,apply:value=>{if(window.linkError)throw new Error('来源校验失败：'+'请核对链接及原选区后重试，已保留当前输入。'.repeat(50));window.linkApplied.push(value)},onClose:()=>window.linkClosed++})})
  },base)
  await page.locator('#entry').click();const dialog=page.getByRole('dialog',{name:'Link',exact:true}),field=dialog.getByLabel('Link URL',{exact:true})
  const value='https://example.test/保留😀?a=1&b='+('long'.repeat(80));await field.fill(value)
  if(phase.endsWith('error')){await dialog.locator('[type=submit]').click();await dialog.getByRole('alert').getByText('来源校验失败：',{exact:false}).waitFor()}
  if(phase.startsWith('readonly')){await page.evaluate(()=>{window.linkReadonly=true;window.linkController.refresh()});assert.equal(await field.isDisabled(),true);assert.equal(await dialog.locator('[type=submit]').isDisabled(),true)}
  await inspectDocxLinkLayout(page,{directory,phase,layout})
  assert.deepEqual(await page.evaluate(()=>window.linkApplied),[])
  if(phase==='error'){await page.evaluate(()=>window.linkError=false);await dialog.locator('[type=submit]').click();assert.deepEqual(await page.evaluate(()=>window.linkApplied),[value])}
  else await page.keyboard.press('Escape')
  await dialog.waitFor({state:'hidden'});assert.equal(await page.locator('#entry').evaluate(n=>n===document.activeElement),true);assert.equal(await page.evaluate(()=>window.linkClosed),1);await page.close()
 }
 assert.deepEqual(errors,[]);if(process.env.DOCX_LINK_COMPONENT_BASELINE!=='1')assert.deepEqual(layout.failures,[])
 await writeFile(join(directory,'evidence.json'),JSON.stringify({ok:!layout.failures.length,baseline:process.env.DOCX_LINK_COMPONENT_BASELINE==='1',callbackIsFixture:true,layout,errors},null,2));console.log(JSON.stringify({cases:layout.cases.length,failures:layout.failures.length,errors}))
}catch(error){await page?.screenshot({path:join(directory,'failure.png')}).catch(()=>{});await writeFile(join(directory,'failure.json'),JSON.stringify({error:String(error),stack:error.stack,errors},null,2));throw error}
finally{await browser?.close();server.kill();if(server.exitCode===null)await Promise.race([new Promise(done=>server.once('exit',done)),delay(5000)]);if(server.exitCode===null)server.kill('SIGKILL')}
