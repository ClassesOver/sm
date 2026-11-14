import assert from 'node:assert/strict'
import {writeFile} from 'node:fs/promises'
import {join} from 'node:path'

// 生产宿主与运算回调夹具共用相同布局断言；不把后者当实际求解器验收。
export async function inspectAnalysisLayout(page,{directory,label,phase,layout,draft=async()=>[]}){
 const dialog=page.getByRole('dialog',{name:label,exact:true}),card=dialog.locator('section.modal-card'),before=await draft()
 const fields=()=>dialog.locator('input,select').evaluateAll(nodes=>nodes.map(n=>[n.getAttribute('aria-label'),n.value,n.disabled,n.checked]))
 const values=await fields(),check=(ok,message)=>{if(!ok)layout.failures.push(`${label}/${phase}: ${message}`)}
 for(const [width,height] of [[1440,900],[768,720],[320,640],[640,360],[390,320]]){
  await page.setViewportSize({width,height});await page.evaluate(()=>document.fonts.ready)
  await dialog.evaluate(node=>Promise.all(node.getAnimations({subtree:true}).map(animation=>animation.finished.catch(()=>{}))))
  const geometry=await card.evaluate(node=>{const r=node.getBoundingClientRect(),body=node.querySelector('.workbook-analysis-body,.workbook-advanced-filter-body,.workbook-consolidate-body');return {left:r.left,right:r.right,top:r.top,bottom:r.bottom,overflow:node.scrollWidth>node.clientWidth+1,font:getComputedStyle(node).fontFamily,header:!!node.querySelector(':scope > header h2'),footer:!!node.querySelector(':scope > form > footer'),body:!!body,bodyOverflow:body?getComputedStyle(body).overflowY:null,named:!!node.querySelector('[role=region][tabindex="0"][aria-label]')&&!!node.querySelector('[role=status][tabindex="0"][aria-label]')&&!!node.querySelector('[role=alert][tabindex="0"][aria-label]')}})
  check(geometry.left>=0&&geometry.top>=0&&geometry.right<=width+1&&geometry.bottom<=height+1&&!geometry.overflow,`${width}x${height}窗口边界`)
  check(Math.abs(geometry.left-(width-geometry.right))<=1&&Math.abs(geometry.top-(height-geometry.bottom))<=1,`${width}x${height}窗口水平和垂直居中`)
  check(geometry.header&&geometry.footer&&geometry.body&&geometry.bodyOverflow==='auto'&&geometry.named,`${width}x${height}固定区域与命名提示`)
  const conditions=await dialog.locator('.workbook-advanced-filter-condition').evaluateAll(nodes=>nodes.map(node=>{const select=node.querySelector('select').getBoundingClientRect(),input=node.querySelector('input').getBoundingClientRect();return {select:{left:select.left,right:select.right,top:select.top,bottom:select.bottom},input:{left:input.left,right:input.right,top:input.top,bottom:input.bottom}}}))
  check(conditions.every(({select,input})=>width>480?Math.abs(select.top-input.top)<=1&&input.left>=select.right+4:Math.abs(select.left-input.left)<=1&&input.top>=select.bottom+4),`${width}x${height}条件运算符与输入在宽屏同行、窄屏对齐换行`)
  const closeIcon=await dialog.locator('.modal-close svg').evaluate(node=>{const r=node.getBoundingClientRect();return {width:r.width,height:r.height}})
  check(closeIcon.width>=16&&closeIcon.height>=16,`${width}x${height}标题关闭图标未被挤压`)
  const sizes=[]
  for(const control of await dialog.locator('button:visible,input:visible,select:visible').all()){
   const size=await control.evaluate(n=>{const r=n.getBoundingClientRect(),s=getComputedStyle(n);return {height:r.height,type:n.getAttribute('type'),font:s.fontFamily,label:n.getAttribute('aria-label')||n.textContent}})
   check((size.type==='checkbox'?size.height===16:size.height>=28&&size.height<=32)&&size.font===geometry.font,`${width}x${height} ${size.label}紧凑控件`)
   sizes.push(size)
  }
  const controls=dialog.locator('button:visible:not(:disabled),input:visible:not(:disabled),select:visible:not(:disabled),[tabindex="0"]:visible'),states=[],screenshots=[]
  check(await controls.count()>0,`${width}x${height}可用键盘阅读入口`)
  for(const control of await controls.all()){
   await control.scrollIntoViewIfNeeded();await control.focus();await page.keyboard.press('Tab');await page.keyboard.press('Shift+Tab')
   const state=await control.evaluate(n=>{const r=n.getBoundingClientRect(),s=getComputedStyle(n);return {label:n.getAttribute('aria-label')||n.textContent,tag:n.tagName,focus:n===document.activeElement,ring:s.outlineStyle!=='none'&&parseFloat(s.outlineWidth)>=2,height:r.height,lineHeight:s.lineHeight,hit:[[r.x+r.width/2,r.y+r.height/2],[r.x+2,r.y+2],[r.right-2,r.y+2],[r.x+2,r.bottom-2],[r.right-2,r.bottom-2]].every(([x,y])=>n.contains(document.elementFromPoint(x,y)))}})
   check(state.focus&&state.ring&&state.hit,`${width}x${height} ${state.label}焦点及五点命中`)
   if(state.tag==='P')check(state.height>=parseFloat(state.lineHeight)+4,`${width}x${height} ${state.label}至少一行可读`)
   states.push(state)
   if(state.tag==='P'&&phase.endsWith('error')){const file=`${phase}-${width}x${height}-${state.label}.png`;await page.screenshot({path:join(directory,file)});screenshots.push(file)}
  }
  if(await controls.count()){
   for(const end of ['first','last']){await(end==='first'?controls.first():controls.last()).scrollIntoViewIfNeeded();const file=`${phase}-${width}x${height}-${end}.png`;await page.screenshot({path:join(directory,file)});screenshots.push(file)}
   await controls.last().focus();await page.keyboard.press('Tab');check(await controls.first().evaluate(n=>n===document.activeElement),`${width}x${height}末端Tab循环`)
   await page.keyboard.press('Shift+Tab');check(await controls.last().evaluate(n=>n===document.activeElement),`${width}x${height}首端反向循环`)
  }
  assert.deepEqual(await fields(),values);assert.deepEqual(await draft(),before)
  layout.cases.push({label,phase,width,height,geometry,conditions,closeIcon,sizes,states,screenshots});await writeFile(join(directory,'layout.json'),JSON.stringify(layout,null,2));console.log(JSON.stringify({label,phase,width,height,failures:layout.failures.length}))
 }
 await page.setViewportSize({width:1440,height:900})
}
