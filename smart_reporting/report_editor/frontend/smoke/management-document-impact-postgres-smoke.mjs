import assert from 'node:assert/strict'
import { chromium } from 'playwright'
import { createServer } from 'vite'
import { mkdir, readFile, writeFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
let input=''
for await(const chunk of process.stdin)input+=chunk
const config=JSON.parse(input),origin='http://127.0.0.1:5206'
await mkdir(config.output,{recursive:true})
const html=(await readFile(new URL('../management.html',import.meta.url),'utf8')).replace('src="/src/','src="/management/src/')
const server=await createServer({configFile:'vite.management.config.ts',server:{host:'127.0.0.1',port:5206,strictPort:true}})
await server.listen()
const browser=await chromium.launch({headless:true})
try{
 const page=await browser.newPage({viewport:{width:390,height:1100}})
 page.setDefaultTimeout(15000)
 await page.context().addCookies([{name:'report_management_session',value:config.token,url:origin+'/management/'}])
 const http=[],errors=[],widths=[]
 let writes=0
 page.on('pageerror',e=>errors.push(e.message))
 await page.route('**/management/knowledge?**',r=>r.fulfill({contentType:'text/html',body:html}))
 await page.route('**/management/api/v1/**',async route=>{
  const req=route.request(),url=new URL(req.url())
  const response=await route.fetch({url:config.apiOrigin+url.pathname+url.search,headers:{...req.headers(),cookie:'report_management_session='+config.token}})
  const body=await response.json()
  http.push({path:url.pathname,query:url.search,method:req.method(),status:response.status(),body:url.pathname.endsWith('/me')?{username:body.username}:body})
  if(req.method()!=='GET'){
   assert.equal(req.method(),'POST');assert.equal(response.status(),200,JSON.stringify(body));assert.ok(url.pathname.endsWith('/budget-rules/revisions/1/review'))
   assert.equal(req.postDataJSON().decision,'revoked');writes++
   return route.abort('failed')
  }
  await route.fulfill({response})
 })
 await page.goto(origin+'/management/knowledge?'+new URLSearchParams({database:config.database,companyId:config.companyId,document:'budget-rules',revision:'1'}))
 const form=page.getByRole('region',{name:'原件修订审核',exact:true})
 await form.getByRole('combobox',{name:'审核决定',exact:true}).click()
 await page.getByTitle('撤销原件访问',{exact:true}).click()
 const impact=page.getByRole('region',{name:'原件撤销影响',exact:true})
 const trigger=impact.getByRole('button',{name:'核对撤销影响',exact:true})
 await trigger.focus();await page.keyboard.press('Enter')
 await impact.getByText('历史报告依据',{exact:true}).waitFor()
 await impact.getByText('依据编号：'+config.basisId,{exact:true}).waitFor()
 await impact.getByText('已发布口径',{exact:true}).waitFor()
 await impact.getByText('当前默认配置',{exact:true}).waitFor()
 await impact.getByText('证据集合',{exact:true}).waitFor()
 await page.addScriptTag({path:fileURLToPath(new URL('../node_modules/axe-core/axe.min.js',import.meta.url))})
 for(const width of [1440,1280,768,390]){
  await page.setViewportSize({width,height:1100})
  await page.evaluate(async()=>{await new Promise(requestAnimationFrame);await Promise.all(document.getAnimations().filter(a=>a.effect?.getComputedTiming().iterations!==Infinity).map(a=>a.finished.catch(()=>undefined)))})
  const axe=await page.evaluate(async()=>(await window.axe.run('main')).violations.filter(i=>['serious','critical'].includes(i.impact)).map(i=>i.id))
  const overflow=await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth)
  assert.deepEqual(axe,[]);assert.equal(overflow,false)
  await impact.screenshot({path:config.output+'/impact-before-'+width+'.png',animations:'disabled'});widths.push({width,axe,overflow})
 }
 await form.getByRole('textbox',{name:'审核理由',exact:true}).fill('核对四类登记关联后撤销合成原件。')
 await form.getByRole('checkbox',{name:'确认原件审核',exact:true}).check()
 await form.getByRole('button',{name:'提交原件审核',exact:true}).click()
 await page.getByText('原件审核结果待确认，请读取原审核结果',{exact:false}).waitFor()
 await page.reload()
 await page.getByRole('button',{name:'读取原审核结果',exact:true}).click()
 await page.getByText('已撤销修订不可重新启用，请登记新修订。',{exact:true}).waitFor()
 await page.getByRole('button',{name:'核对撤销影响',exact:true}).click()
 await page.getByText('依据编号：'+config.basisId,{exact:true}).waitFor()
 await page.getByRole('region',{name:'原件撤销影响',exact:true}).screenshot({path:config.output+'/impact-recovered-390.png',animations:'disabled'})
 assert.equal(writes,1);assert.deepEqual(errors,[])
 await page.waitForLoadState('networkidle')
 await writeFile(config.output+'/http-evidence.json',JSON.stringify(http,null,2))
 await writeFile(config.output+'/browser-evidence.json',JSON.stringify({writes,widths,errors,unknownResponseReadback:true},null,2))
}finally{await browser.close();await server.close()}
