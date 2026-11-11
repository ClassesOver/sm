import assert from 'node:assert/strict'
import { chromium } from 'playwright'
import { createServer } from 'vite'
import { mkdir, readFile, writeFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
let input=''
for await(const chunk of process.stdin)input+=chunk
const config=JSON.parse(input),origin='http://127.0.0.1:5208'
await mkdir(config.output,{recursive:true})
const html=(await readFile(new URL('../management.html',import.meta.url),'utf8')).replace('src="/src/','src="/management/src/')
const server=await createServer({configFile:'vite.management.config.ts',server:{host:'127.0.0.1',port:5208,strictPort:true}})
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
   assert.equal(req.method(),'PUT')
   if(response.status()===409){conflicts++;return route.fulfill({response})}
   assert.equal(response.status(),200,JSON.stringify(body));assert.equal(req.postDataJSON().expectedVersion,2);writes++
   return route.abort('failed')
  }
  await route.fulfill({response})
 })
 await page.goto(origin+'/management/metrics?'+new URLSearchParams({database:config.database,companyId:config.companyId,editMetric:'budget'}))
 const editor=page.getByRole('region',{name:'指标定义编辑',exact:true})
 await editor.locator('#metric-name').fill('本地保留的指标名称')
 // 第二名管理员经同一真实HTTP契约先写入服务器；首位管理员保留旧CAS。
 const base=await page.request.get(config.apiOrigin+'/management/api/v1/metrics/budget?'+new URLSearchParams({scopeDatabase:config.database,companyId:config.companyId}),{headers:{cookie:'report_management_session='+config.token}})
 const current=await base.json()
 const {scopeId,revision,...definition}=current.draft.document
 const me=await page.request.get(config.apiOrigin+'/management/api/v1/me',{headers:{cookie:'report_management_session='+config.token}})
 const session=await me.json()
 const concurrent=await page.request.put(config.apiOrigin+'/management/api/v1/metrics/budget/draft',{headers:{cookie:'report_management_session='+config.token,origin, 'x-csrf-token':session.csrfToken},data:{scopeDatabase:config.database,companyId:config.companyId,expectedVersion:1,definition:{...definition,name:'服务器更新的指标名称',aliases:['另一管理员补充的指标别名']}}})
 assert.equal(concurrent.status(),200,await concurrent.text())
 http.push({path:'/management/api/v1/metrics/budget/draft',method:'PUT',status:200,actor:'concurrent-admin',body:await concurrent.json()})
 await editor.getByRole('button',{name:'保存指标草稿',exact:true}).click()
 await editor.getByRole('button',{name:'读取原提交结果',exact:true}).click()
 const form=page.getByRole('region',{name:'指标冲突逐项对照',exact:true})
 await form.getByText('服务器更新的指标名称',{exact:true}).waitFor()
 await form.getByRole('radio',{name:'指标名称：保留本地',exact:true}).check()
 await form.getByRole('radio',{name:'别名：采用服务器',exact:true}).check()
 await form.getByRole('checkbox',{name:'确认指标冲突选择',exact:true}).check()
 await page.addScriptTag({path:fileURLToPath(new URL('../node_modules/axe-core/axe.min.js',import.meta.url))})
 for(const width of [1440,1280,768,390]){
  await page.setViewportSize({width,height:1100})
  await page.evaluate(async()=>{await new Promise(requestAnimationFrame);await Promise.all(document.getAnimations().filter(a=>a.effect?.getComputedTiming().iterations!==Infinity).map(a=>a.finished.catch(()=>undefined)))})
  const axe=await page.evaluate(async()=>(await window.axe.run('main')).violations.filter(i=>['serious','critical'].includes(i.impact)).map(i=>i.id))
  const overflow=await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth)
  assert.deepEqual(axe,[]);assert.equal(overflow,false)
  await form.screenshot({path:config.output+'/conflict-before-'+width+'.png',animations:'disabled'});widths.push({width,axe,overflow})
 }
 await editor.getByRole('button',{name:'采用指标核对结果继续编辑',exact:true}).click()
 await editor.getByText('已按服务器指标草稿版本 2 准备本地修改',{exact:false}).waitFor()
 assert.equal(writes,0)
 assert.equal(await editor.locator('#metric-name').inputValue(),'本地保留的指标名称')
 assert.equal(await editor.locator('[aria-label="指标别名"]').inputValue(),'另一管理员补充的指标别名')
 const archives=await page.evaluate(()=>Object.keys(sessionStorage).filter(k=>k.startsWith('management-metric-conflict:')).map(k=>JSON.parse(sessionStorage.getItem(k))))
 assert.equal(archives.length,1);assert.equal(archives[0].pending.expectedVersion,1)
 await writeFile(config.output+'/conflict-archive.json',JSON.stringify(archives,null,2))
 await editor.getByRole('button',{name:'保存指标草稿',exact:true}).click()
 await page.getByText('提交结果待确认',{exact:false}).waitFor()
 await page.reload()
 await page.getByRole('button',{name:'读取原提交结果',exact:true}).click()
 await page.getByText('当前草稿与原提交一致',{exact:false}).waitFor()
 await page.getByRole('region',{name:'指标定义编辑',exact:true}).screenshot({path:config.output+'/conflict-recovered-390.png',animations:'disabled'})
 assert.equal(writes,1);assert.deepEqual(errors,[])
 await page.waitForLoadState('networkidle')
 await writeFile(config.output+'/http-evidence.json',JSON.stringify(http,null,2))
 await writeFile(config.output+'/browser-evidence.json',JSON.stringify({writes,conflicts,widths,errors,unknownResponseReadback:true},null,2))
}finally{await browser.close();await server.close()}
