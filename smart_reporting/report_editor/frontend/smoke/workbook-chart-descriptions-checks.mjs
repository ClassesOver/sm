import assert from 'node:assert/strict'
import {join} from 'node:path'
import AxeBuilder from '@axe-core/playwright'

export async function checkChartDescriptions(page, directory, charts) {
 const checks=[]
 const draft=()=>page.evaluate(()=>Object.entries(localStorage).filter(([key])=>key.startsWith('native-editor-draft:')).map(([key,value])=>[key,JSON.parse(value).operations]))
 const before=await draft()
 for(const viewport of [{width:1440,height:900},{width:640,height:360},{width:390,height:320},{width:320,height:640}]){
  await page.setViewportSize(viewport)
  const tab=page.locator('[data-ribbon-tab="Chart Design"]')
  await tab.scrollIntoViewIfNeeded();await tab.focus();await tab.press('Enter')
  const entry=page.locator('[data-ribbon-command="chart-descriptions"]')
  assert.equal(await entry.isEnabled(),true)
  await entry.scrollIntoViewIfNeeded();await entry.focus();await entry.press('Enter')
  const dialog=page.getByRole('dialog',{name:'图表说明',exact:true})
  await dialog.waitFor({state:'visible'})
  await dialog.evaluate(async node=>{await Promise.all(node.getAnimations({subtree:true}).map(animation=>animation.finished.catch(()=>{})))})
  assert.deepEqual(await dialog.locator('[data-chart-description] h3').allTextContents(),charts.map((chart,index)=>chart.title||`未命名图表 ${index+1}`))
  const descriptionText=await dialog.textContent()
  for(const chart of charts)for(const series of chart.series){
   assert(descriptionText.includes(series.valuesRef))
   if(series.color)assert(descriptionText.includes(`系列填充：${series.color==='transparent'?'无填充':series.color}`))
   for(const [index,color] of Object.entries(series.pointColors??{}))assert(descriptionText.includes(`第 ${Number(index)+1} 个数据点：${color==='transparent'?'无填充':color}`))
   if(series.colorPreviewUnavailable)assert(descriptionText.includes('来源填充暂不支持预览，请下载原件查看'))
  }
  assert.deepEqual(await dialog.locator('[data-chart-description] strong').allTextContents(),Array(charts.length).fill('Revenue'))
  assert.equal(await dialog.getByRole('button',{name:'关闭图表说明',exact:true}).evaluate(node=>node===document.activeElement),true)
  const bounds=await dialog.locator('.workbook-chart-descriptions').evaluate(node=>{const r=node.getBoundingClientRect();return {x:r.x,y:r.y,right:r.right,bottom:r.bottom}})
  assert(bounds.x>=0&&bounds.y>=0&&bounds.right<=viewport.width+1&&bounds.bottom<=viewport.height+1,JSON.stringify({viewport,bounds}))
  const aria=await dialog.ariaSnapshot()
  for(const chart of charts)assert(aria.includes(chart.title),'Full title absent from accessibility tree')
  const region=dialog.getByRole('region',{name:'图表说明列表'})
  assert.equal(await region.evaluate(node=>node.scrollTop),0,'Newly opened descriptions must start at the first chart')
  assert.equal(await region.evaluate(node=>node.scrollWidth<=node.clientWidth+1),true,'Full titles must wrap without horizontal clipping')
  await page.screenshot({path:join(directory,`chart-descriptions-start-${viewport.width}x${viewport.height}.png`),fullPage:true})
  await region.focus()
  const scroll=await region.evaluate(node=>({height:node.clientHeight,full:node.scrollHeight}))
  await region.press('End')
  if(scroll.full>scroll.height)await page.waitForFunction(()=>document.querySelector('.workbook-chart-descriptions-scroll')?.scrollTop>0)
  const close=dialog.getByRole('button',{name:'关闭',exact:true})
  assert.equal(await close.evaluate(node=>{const r=node.getBoundingClientRect(),hit=document.elementFromPoint(r.x+r.width/2,r.y+r.height/2);return !!hit&&(node===hit||node.contains(hit))}),true,'Close button must remain reachable above scrollable content')
  await close.focus();await close.press('Tab')
  assert.equal(await dialog.getByRole('button',{name:'关闭图表说明',exact:true}).evaluate(node=>node===document.activeElement),true,'Tab must wrap inside the dialog')
  const axe=await new AxeBuilder({page}).include('.modal-overlay:not([hidden])').analyze()
  assert.deepEqual(axe.violations,[])
  const ime=[]
  for(const protection of ['composition','legacy','handled']){
   const result=await close.evaluate((node,protection)=>{
    const event=new KeyboardEvent('keydown',{key:'Escape',bubbles:true,cancelable:true,isComposing:protection==='composition',keyCode:protection==='legacy'?229:0})
    if(protection==='handled')event.preventDefault()
    node.focus();node.dispatchEvent(event)
    return {protection,focused:node===document.activeElement}
   },protection)
   assert.equal(await dialog.isVisible(),true,'IME or consumed Escape must preserve the open dialog')
   assert.equal(result.focused,true);ime.push(result)
  }
  await close.evaluate(node=>node.addEventListener('keydown',event=>event.preventDefault(),{once:true}))
  await close.press('Escape');assert.equal(await dialog.isVisible(),true,'Trusted consumed Escape must preserve the dialog')
  await page.screenshot({path:join(directory,`chart-descriptions-${viewport.width}x${viewport.height}.png`),fullPage:true})
  checks.push({viewport,bounds,scroll,aria,axeViolations:axe.violations,ime,trustedConsumedEscapePreserved:true})
  await page.keyboard.press('Escape')
  await dialog.waitFor({state:'hidden'})
  assert.equal(await entry.evaluate(node=>node===document.activeElement),true,'Escape must restore the ribbon entry')
  assert.deepEqual(await draft(),before,'Reading descriptions must not alter draft operations')
  assert.equal(await page.locator('.save-state-label').textContent(),'已保存')
 }
 return checks
}
