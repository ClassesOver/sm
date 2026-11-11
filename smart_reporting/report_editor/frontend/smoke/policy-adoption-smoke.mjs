import { chromium } from 'playwright'
import { fileURLToPath } from 'node:url'
import { mkdir, writeFile } from 'node:fs/promises'
// 仅验证独立确认组件，接口受控；先在frontend启动Vite（127.0.0.1:5187）。
const directory = fileURLToPath(new URL('../../../../docs/superpowers/reports/artifacts/2026-11-11-policy-adoption-ui', import.meta.url))
await mkdir(directory, {recursive:true})
const browser = await chromium.launch({headless:true})
const results = []
try {
for (const width of [1440,1280,768,390]) {
 const page = await browser.newPage({viewport:{width,height:1000}})
 await page.route('**/reports/v1/editor/assets/', route=>route.fulfill({contentType:'text/html',body:'<!doctype html><html lang="zh-CN"><head><title>新口径确认组件验收</title></head><body></body></html>'}))
 await page.goto('http://127.0.0.1:5187/reports/v1/editor/assets/')
 await page.evaluate(async () => {
  const {mountPolicyAdoption} = await import('/reports/v1/editor/assets/src/evidence-policy-adoption.ts')
  document.body.innerHTML='<main><aside style="width:min(340px,100%);padding:12px;box-sizing:border-box"><h1 style="font-size:18px">本报告计算依据</h1><div id="panel"></div></aside></main>'
  document.body.style.cssText='margin:0;background:#f5f7fa;font-family:system-ui;color:#253044'
  const style=document.createElement('link');style.rel='stylesheet';style.href='/reports/v1/editor/assets/src/style.css';document.head.append(style)
  const task={taskId:'task',status:'completed',execution:{status:'completed',runId:'native',issueCodes:[]}}
  mountPolicyAdoption(document.querySelector('#panel'), {storageKey:'browser-policy',getDraft:()=>({markdown:'报告'}),client:{
   policyAdoptionOptions:async()=>({parentRevision:2,items:[{policyVersion:{policyId:'budget',revision:2},name:'医院月度预算口径'}],nextCursor:null}),
   previewPolicyAdoption:async()=>({previewHash:'a'.repeat(64),preview:{originalPolicyVersion:{policyId:'budget',revision:1},targetPolicyVersion:{policyId:'budget',revision:2},changedFields:['filters','metric_versions'],changes:[{field:'filters',before:'无附加过滤条件',after:'project_id 等于 A'}],issues:[{code:'partial',message:'执行率缺少实际发生额，选择预算指标不能证明执行率已回答。'}],questions:[{id:'q-budget',text:'本期预算是多少？'},{id:'q-rate',text:'本期预算执行率是多少？'}],metricOptions:[{metricVersion:{metricId:'budget',revision:2},name:'预算金额',unit:'元'}]}}),
   adoptPolicy:async()=>task,dataRefreshStatus:async()=>task,
   dataRefreshDelivery:async()=>({task,delivery:{revision:3,validation:{ok:false,issues:[{message:'业务核对未完成；实际发生额待补充。'}]},pdf:{downloadUrl:'/download/pdf'},word:{downloadUrl:'/download/docx'},pptx:{downloadUrl:'/download/pptx'},xlsx:{downloadUrl:'/download/xlsx'},editor:{openUrl:'/editor/new'}}}),
  }})
 })
 await page.getByText('采用新业务口径',{exact:true}).click()
 await page.getByRole('button',{name:'选择已发布口径',exact:true}).click()
 await page.getByLabel('目标口径（最新发布版本）').selectOption('0')
 await page.getByRole('button',{name:'核对变更与问题'}).click()
 if(await page.getByRole('button',{name:'读取新口径任务进度'}).count())throw Error('hidden status visible')
 if(await page.getByRole('button',{name:'加载更多口径'}).count())throw Error('hidden pagination visible')
 await page.getByText('过滤范围',{exact:true}).click()
 await page.getByLabel('本期预算是多少？：选择指标').selectOption('0')
 await page.getByLabel('本期预算是多少？：选择原因').fill('采用已核对的预算金额指标。')
 await page.getByLabel('本期预算执行率是多少？：选择指标').selectOption('unavailable')
 await page.getByLabel('本期预算执行率是多少？：选择原因').fill('缺少实际发生额，保留未回答。')
 await page.getByRole('button',{name:'确认采用并生成新报告'}).focus()
 const keyboardFocus=await page.evaluate(()=>document.activeElement?.textContent)
 await page.screenshot({path:`${directory}/confirmation-${width}.png`,fullPage:true})
 await page.addScriptTag({path:fileURLToPath(new URL('../node_modules/axe-core/axe.min.js', import.meta.url))})
 const before=await page.evaluate(async()=> (await axe.run('main')).violations.filter(v=>['critical','serious'].includes(v.impact)).map(v=>v.id))
 await page.keyboard.press('Enter')
 await page.getByRole('button',{name:'读取已生成文件'}).click()
 await page.getByRole('link',{name:'下载 XLSX · 修订 3'}).waitFor()
 const after=await page.evaluate(async()=> (await axe.run('main')).violations.filter(v=>['critical','serious'].includes(v.impact)).map(v=>v.id))
 const overflow=await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth)
 await page.screenshot({path:`${directory}/delivery-${width}.png`,fullPage:true})
 const result={width,overflow,keyboardFocus,seriousOrCritical:[...before,...after],links:await page.getByRole('link').count()}
 results.push(result)
 if(overflow||before.length||after.length||result.links!==5)throw Error(JSON.stringify(result))
 await page.close()
}
 await writeFile(`${directory}/browser-evidence.json`,JSON.stringify({scope:'独立组件，受控接口；不是完整Editor或真实报告端到端验收',results},null,2))
 console.log(JSON.stringify(results))
}finally{await browser.close()}
