import assert from 'node:assert/strict'
import { chromium } from 'playwright'
import { createServer } from 'vite'
import { mkdir, readFile, writeFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
let input=''
for await(const chunk of process.stdin)input+=chunk
const config=JSON.parse(input),origin='http://127.0.0.1:5209'
await mkdir(config.output,{recursive:true})
const html=(await readFile(new URL('../management.html',import.meta.url),'utf8')).replace('src="/src/','src="/management/src/')
const server=await createServer({configFile:'vite.management.config.ts',server:{host:'127.0.0.1',port:5209,strictPort:true}})
await server.listen()
const browser=await chromium.launch({headless:true})
try{
 const page=await browser.newPage({viewport:{width:390,height:1100}})
 page.setDefaultTimeout(15000)
 await page.context().addCookies([{name:'report_management_session',value:config.token,url:origin+'/management/'}])
 const http=[],errors=[],widths=[]
 let writes=0,conflicts=0
 page.on('pageerror',e=>errors.push(e.message))
 await page.route('**/management/metrics?**',r=>r.fulfill({contentType:'text/html',body:html}))
 await page.route('**/management/api/v1/**',async route=>{
  const req=route.request(),url=new URL(req.url())
  const response=await route.fetch({url:config.apiOrigin+url.pathname+url.search,headers:{...req.headers(),cookie:'report_management_session='+config.token}})
  const body=await response.json()
  http.push({path:url.pathname,query:url.search,method:req.method(),status:response.status(),body:url.pathname.endsWith('/me')?{username:body.username}:body})
  if(req.method()!=='GET'){
   assert.equal(req.method(),'PUT');assert.equal(response.status(),200,JSON.stringify(body));assert.equal(req.postDataJSON().expectedVersion,1);writes++
   const d=req.postDataJSON().definition
   assert.equal(d.fieldRef,'warehouse.test.budget.amount');assert.equal(d.timeField,'warehouse.test.budget.period');assert.equal(d.dimensions[0].fieldRef,'warehouse.test.budget.project_id')
   return route.abort('failed')
  }
  await route.fulfill({response})
 })
 await page.goto(origin+'/management/metrics?'+new URLSearchParams({database:config.database,companyId:config.companyId,editMetric:'budget'}))
 const editor=page.getByRole('region',{name:'指标定义编辑',exact:true})
 await editor.locator('#metric-name').fill('本地保留的指标名称')
 const form=editor.getByRole('region',{name:'取数字段目录选择',exact:true})
 await form.getByRole('button',{name:'从已发布目录选择取数字段',exact:true}).click()
 await form.getByRole('button',{name:'浏览 合成数据源 · warehouse 版本 1',exact:true}).click()
 await form.getByRole('button',{name:'采用字段 warehouse.test.budget.amount',exact:true}).waitFor()
 const input=editor.locator('#metric-field')
 await input.fill('warehouse.test.budget.not_in_catalog')
 await form.getByRole('button',{name:'采用字段 warehouse.test.budget.amount',exact:true}).click()
 assert.equal(await input.inputValue(),'warehouse.test.budget.amount')
 for(const [label,field,target] of [['时间字段','warehouse.test.budget.period','#metric-time'],['维度字段 1','warehouse.test.budget.project_id','#metric-dimension-field-0']]){
  const picker=editor.getByRole('region',{name:label+'目录选择',exact:true})
  await picker.getByRole('button',{name:'从已发布目录选择'+label,exact:true}).click()
  await picker.getByRole('button',{name:'浏览 合成数据源 · warehouse 版本 1',exact:true}).click()
  await picker.getByRole('button',{name:'采用字段 '+field,exact:true}).click()
  assert.equal(await editor.locator(target).inputValue(),field)
  await picker.getByRole('button',{name:'收起'+label,exact:true}).click()
 }
 assert.equal(writes,0)
 await page.addScriptTag({path:fileURLToPath(new URL('../node_modules/axe-core/axe.min.js',import.meta.url))})
 for(const width of [1440,1280,768,390]){
  await page.setViewportSize({width,height:1100})
  await page.evaluate(async()=>{await new Promise(requestAnimationFrame);await Promise.all(document.getAnimations().filter(a=>a.effect?.getComputedTiming().iterations!==Infinity).map(a=>a.finished.catch(()=>undefined)))})
  const axe=await page.evaluate(async()=>(await window.axe.run('main')).violations.filter(i=>['serious','critical'].includes(i.impact)).map(i=>i.id))
  const overflow=await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth)
  assert.deepEqual(axe,[]);assert.equal(overflow,false)
  await form.screenshot({path:config.output+'/field-picker-before-'+width+'.png',animations:'disabled'});widths.push({width,axe,overflow})
 }
 await form.getByRole('textbox',{name:'搜索取数字段目录',exact:true}).fill('amount')
 await form.getByRole('button',{name:'搜索取数字段目录',exact:true}).click()
 await form.getByRole('button',{name:'采用字段 warehouse.test.budget.amount',exact:true}).waitFor()
 await editor.getByRole('button',{name:'保存指标草稿',exact:true}).click()
 await page.getByText('提交结果待确认',{exact:false}).waitFor()
 await page.reload()
 await page.getByRole('button',{name:'读取原提交结果',exact:true}).click()
 await page.getByText('当前草稿与原提交一致',{exact:false}).waitFor()
 await page.getByRole('region',{name:'指标定义编辑',exact:true}).screenshot({path:config.output+'/field-picker-recovered-390.png',animations:'disabled'})
 assert.equal(writes,1);assert.deepEqual(errors,[])
 await page.waitForLoadState('networkidle')
 await writeFile(config.output+'/http-evidence.json',JSON.stringify(http,null,2))
 await writeFile(config.output+'/browser-evidence.json',JSON.stringify({writes,widths,errors,unknownResponseReadback:true,threeFieldsSelected:true},null,2))
}finally{await browser.close();await server.close()}
