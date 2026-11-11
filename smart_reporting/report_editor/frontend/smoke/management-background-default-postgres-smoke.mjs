import assert from 'node:assert/strict'
import { chromium } from 'playwright'
import { createServer } from 'vite'
import { mkdir, readFile, writeFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
let input=''
for await(const chunk of process.stdin)input+=chunk
const config=JSON.parse(input),origin='http://127.0.0.1:5205'
await mkdir(config.output,{recursive:true})
const html=(await readFile(new URL('../management.html',import.meta.url),'utf8')).replace('src="/src/','src="/management/src/')
const server=await createServer({configFile:'vite.management.config.ts',server:{host:'127.0.0.1',port:5205,strictPort:true}})
await server.listen()
const browser=await chromium.launch({headless:true})
try{
 const page=await browser.newPage({viewport:{width:390,height:1100}})
 page.setDefaultTimeout(15000)
 await page.context().addCookies([{name:'report_management_session',value:config.token,url:origin+'/management/'}])
 const http=[],errors=[],widths=[]
 let writes=0
 page.on('pageerror',e=>errors.push(e.message))
 await page.route('**/management/statistical-policies?**',r=>r.fulfill({contentType:'text/html',body:html}))
 await page.route('**/management/api/v1/**',async route=>{
  const req=route.request(),url=new URL(req.url())
  const response=await route.fetch({url:config.apiOrigin+url.pathname+url.search,headers:{...req.headers(),cookie:'report_management_session='+config.token}})
  const body=await response.json()
  http.push({path:url.pathname,query:url.search,method:req.method(),status:response.status(),body:url.pathname.endsWith('/me')?{username:body.username}:body})
  if(req.method()!=='GET'){
   assert.equal(req.method(),'PUT');assert.equal(response.status(),200,JSON.stringify(body));assert.ok(url.pathname.endsWith('/report-policy-defaults/budget_execution'))
   assert.deepEqual(req.postDataJSON().policyVersion,{policyId:'monthly-budget',revision:1})
   assert.equal(req.postDataJSON().expectedVersion,1);assert.equal(req.postDataJSON().backgroundReleaseId,config.releaseId);writes++
   return route.abort('failed')
  }
  await route.fulfill({response})
 })
 await page.goto(origin+'/management/statistical-policies?'+new URLSearchParams({database:config.database,companyId:config.companyId}))
 await page.getByRole('button',{name:'版本与影响',exact:true}).click()
 const form=page.getByRole('region',{name:'场景默认口径',exact:true})
 await form.getByText('当前背景：未设置',{exact:true}).waitFor()
 await form.getByRole('checkbox',{name:'确认调整场景默认',exact:true}).check()
 assert.equal(await form.getByRole('button',{name:'确认调整默认',exact:true}).isDisabled(),true)
 await form.getByRole('button',{name:'从已发布背景材料中选择',exact:true}).click()
 const preview=form.getByRole('button',{name:'预览原文 本期项目背景 修订 1',exact:true})
 await preview.click()
 await page.getByRole('dialog').getByText('项目B本期采购计划调整，仅作解释材料，不改变预算执行率公式。',{exact:true}).waitFor()
 await page.keyboard.press('Escape');await page.getByRole('dialog').waitFor({state:'detached'})
 await page.waitForFunction(()=>document.activeElement?.textContent==='预览原文 本期项目背景 修订 1')
 await form.getByRole('button',{name:'选择集合 '+config.releaseId,exact:true}).click()
 await form.getByText('本次背景：'+config.releaseId,{exact:true}).waitFor()
 assert.equal(await form.getByRole('checkbox',{name:'确认调整场景默认',exact:true}).isChecked(),false)
 await page.addScriptTag({path:fileURLToPath(new URL('../node_modules/axe-core/axe.min.js',import.meta.url))})
 for(const width of [1440,1280,768,390]){
  await page.setViewportSize({width,height:1100})
  await page.evaluate(async()=>{await new Promise(requestAnimationFrame);await Promise.all(document.getAnimations().filter(a=>a.effect?.getComputedTiming().iterations!==Infinity).map(a=>a.finished.catch(()=>undefined)))})
  const axe=await page.evaluate(async()=>(await window.axe.run('main')).violations.filter(i=>['serious','critical'].includes(i.impact)).map(i=>i.id))
  const overflow=await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth)
  assert.deepEqual(axe,[]);assert.equal(overflow,false)
  assert.equal(await form.getByRole('button',{name:'选择集合 '+config.releaseId,exact:true}).evaluate(e=>e.scrollWidth>e.clientWidth+1),false)
  await form.screenshot({path:config.output+'/background-before-'+width+'.png',animations:'disabled'});widths.push({width,axe,overflow})
 }
 await form.getByRole('checkbox',{name:'确认调整场景默认',exact:true}).check()
 await form.getByRole('button',{name:'确认调整默认',exact:true}).click()
 await form.getByText('默认调整结果待确认',{exact:false}).waitFor()
 await page.reload();await page.getByRole('button',{name:'版本与影响',exact:true}).click()
 await form.getByRole('button',{name:'读取原默认调整结果',exact:true}).click()
 await form.getByText('当前默认与原目标一致',{exact:false}).waitFor()
 await form.getByText('当前背景：'+config.releaseId,{exact:true}).waitFor()
 await form.screenshot({path:config.output+'/background-recovered-390.png',animations:'disabled'})
 assert.equal(writes,1);assert.deepEqual(errors,[])
 await page.waitForLoadState('networkidle')
 await writeFile(config.output+'/http-evidence.json',JSON.stringify(http,null,2))
 await writeFile(config.output+'/browser-evidence.json',JSON.stringify({writes,widths,errors,unknownResponseReadback:true},null,2))
}finally{await browser.close();await server.close()}
