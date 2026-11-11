import assert from 'node:assert/strict'
import { chromium } from 'playwright'
import { createServer } from 'vite'
import { mkdir, readFile, writeFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
let input=''
for await(const chunk of process.stdin)input+=chunk
const config=JSON.parse(input),origin='http://127.0.0.1:5210'
await mkdir(config.output,{recursive:true})
const html=(await readFile(new URL('../management.html',import.meta.url),'utf8')).replace('src="/src/','src="/management/src/')
const server=await createServer({configFile:'vite.management.config.ts',server:{host:'127.0.0.1',port:5210,strictPort:true}})
await server.listen()
const browser=await chromium.launch({headless:true})
try{
 const page=await browser.newPage({viewport:{width:390,height:1100}})
 page.setDefaultTimeout(15000)
 await page.context().addCookies([{name:'report_management_session',value:config.token,url:origin+'/management/'}])
 const http=[],errors=[],widths=[]
 let writes=0,conflicts=0
 page.on('pageerror',e=>errors.push(e.message))
 await page.route('**/management/statistical-policies?**',r=>r.fulfill({contentType:'text/html',body:html}))
 await page.route('**/management/api/v1/**',async route=>{
  const req=route.request(),url=new URL(req.url())
  const response=await route.fetch({url:config.apiOrigin+url.pathname+url.search,headers:{...req.headers(),cookie:'report_management_session='+config.token}})
  const body=await response.json()
  http.push({path:url.pathname,query:url.search,method:req.method(),status:response.status(),body:url.pathname.endsWith('/me')?{username:body.username}:body})
  if(req.method()!=='GET'){
   assert.equal(req.method(),'PUT');assert.equal(response.status(),200,JSON.stringify(body));assert.equal(req.postDataJSON().expectedVersion,2);writes++
   const d=req.postDataJSON().definition
   assert.equal(d.filters[0].fieldRef,'warehouse.test.budget.project_id');assert.deepEqual(d.joins[0].leftKeys,['warehouse.test.budget.project_id']);assert.deepEqual(d.joins[0].rightKeys,['warehouse.test.budget.project_id']);assert.equal(d.readinessPolicy.watermarkField,'warehouse.test.budget.period')
   return route.abort('failed')
  }
  await route.fulfill({response})
 })
 await page.goto(origin+'/management/statistical-policies?'+new URLSearchParams({database:config.database,companyId:config.companyId,editPolicy:'monthly-budget'}))
 const editor=page.getByRole('region',{name:'统计口径定义编辑',exact:true})
 await editor.locator('#policy-name').fill('目录选择后的口径')
 for(const [label,field,target] of [['筛选 1 字段','warehouse.test.budget.project_id','筛选 1 字段'],['关联 1 左键 1','warehouse.test.budget.project_id','关联 1 左键 1'],['关联 1 右键 1','warehouse.test.budget.project_id','关联 1 右键 1'],['源水位字段','warehouse.test.budget.period','源水位字段（可选）']]){
  const picker=editor.getByRole('region',{name:label+'目录选择',exact:true})
  await picker.getByRole('button',{name:'从已发布目录选择'+label,exact:true}).click()
  await picker.getByRole('button',{name:'浏览 合成数据源 · warehouse 版本 1',exact:true}).click()
  await picker.getByRole('button',{name:'采用字段 '+field,exact:true}).click()
  assert.equal(await editor.getByRole('textbox',{name:target,exact:true}).inputValue(),field)
  if(label!=='源水位字段')await picker.getByRole('button',{name:'收起'+label,exact:true}).click()
 }
 const form=editor.getByRole('region',{name:'源水位字段目录选择',exact:true})
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
 await editor.getByRole('button',{name:'保存口径草稿',exact:true}).click()
 await page.getByText('提交结果待确认',{exact:false}).waitFor()
 await page.reload()
 await page.getByRole('button',{name:'读取原口径提交结果',exact:true}).click()
 await page.getByText('当前草稿与原提交一致',{exact:false}).waitFor()
 await page.getByRole('region',{name:'统计口径定义编辑',exact:true}).screenshot({path:config.output+'/field-picker-recovered-390.png',animations:'disabled'})
 assert.equal(writes,1);assert.deepEqual(errors,[])
 await page.waitForLoadState('networkidle')
 await writeFile(config.output+'/http-evidence.json',JSON.stringify(http,null,2))
 await writeFile(config.output+'/browser-evidence.json',JSON.stringify({writes,widths,errors,unknownResponseReadback:true,fourFieldsSelected:true},null,2))
}finally{await browser.close();await server.close()}
