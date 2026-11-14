import assert from 'node:assert/strict'
import {writeFile} from 'node:fs/promises'
import {join} from 'node:path'

export async function inspectBackgroundLayout(page,{directory,phase,layout,draft}){
 const dialog=page.getByRole('dialog',{name:'设置背景格式',exact:true}),before=await draft()
 const fields=()=>dialog.locator('input,select').evaluateAll(nodes=>nodes.map(n=>[n.name,n.value,n.checked,n.disabled]))
 const initial=await fields(),check=(ok,text)=>{if(!ok)layout.failures.push(`${phase}: ${text}`)}
 for(const [width,height]of [[1440,900],[768,720],[320,640],[640,360],[390,320]]){
  await page.setViewportSize({width,height});await page.evaluate(()=>document.fonts.ready)
  const geometry=await dialog.evaluate(n=>{const r=n.getBoundingClientRect(),header=n.querySelector(':scope > header'),footer=n.querySelector(':scope > footer'),body=n.querySelector('.slides-background-body');return {left:r.left,right:r.right,top:r.top,bottom:r.bottom,font:getComputedStyle(n).fontFamily,overflow:n.scrollWidth>n.clientWidth+1,header:header?.getBoundingClientRect().top,footer:footer?.getBoundingClientRect().bottom,bodyOverflow:body?getComputedStyle(body).overflowY:null,close:!!n.querySelector('[aria-label="关闭设置背景格式"]'),named:!!n.querySelector('[role=alert][aria-label="背景设置错误"][tabindex="0"]')&&!!n.querySelector('[role=status][aria-label="背景设置状态"][tabindex="0"]')}})
  check(geometry.left>=0&&geometry.top>=0&&geometry.right<=width+1&&geometry.bottom<=height+1&&!geometry.overflow,`${width}x${height}窗口边界`)
  check(Math.abs(geometry.left-(width-geometry.right))<=1&&Math.abs(geometry.top-(height-geometry.bottom))<=1,`${width}x${height}窗口居中`)
  check(width<700||Math.abs(geometry.right-geometry.left-520)<=1,`${width}x${height}桌面宽度`)
  check(geometry.header!==undefined&&geometry.footer!==undefined&&geometry.bodyOverflow==='auto'&&geometry.close&&geometry.named,`${width}x${height}固定标题操作及命名阅读区`)
  const states=[],controls=dialog.locator('button:visible:not(:disabled),input:visible:not(:disabled),select:visible:not(:disabled),[tabindex="0"]:visible')
  for(const control of await controls.all()){
   await control.scrollIntoViewIfNeeded();await control.focus();await page.keyboard.press('Tab');await page.keyboard.press('Shift+Tab')
   const state=await control.evaluate(n=>{const r=n.getBoundingClientRect(),s=getComputedStyle(n),label=n.closest('label'),select=label?.querySelector('select'),radius=Math.min(parseFloat(s.borderRadius)||0,r.width/2,r.height/2),inset=Math.min(r.width/2,r.height/2,Math.max(2,Math.ceil(radius*(1-Math.SQRT1_2)+1)))
    // 圆角外的包围盒角落不属于可点击图形；仍在真实图形内检查中心及四角。
    const samples=[[r.x+r.width/2,r.y+r.height/2],[r.x+inset,r.y+inset],[r.right-inset,r.y+inset],[r.x+inset,r.bottom-inset],[r.right-inset,r.bottom-inset]].map(([x,y])=>({x,y,inside:n.contains(document.elementFromPoint(x,y))}))
    return {label:n.getAttribute('aria-label')||label?.textContent||n.textContent,tag:n.tagName,type:n.getAttribute('type'),focus:n===document.activeElement,ring:s.outlineStyle!=='none'&&parseFloat(s.outlineWidth)>=2,width:r.width,height:r.height,radius:s.borderRadius,inset,samples,lineHeight:s.lineHeight,font:s.fontFamily,labelInline:!select||label.getBoundingClientRect().height<=34,hit:samples.every(point=>point.inside)}})
   check(state.focus&&state.ring&&state.hit,`${width}x${height} ${state.label}焦点及五点命中`)
   if(['BUTTON','INPUT','SELECT'].includes(state.tag))check((state.type==='checkbox'?state.height===16:state.height>=28&&state.height<=32)&&state.font===geometry.font,`${width}x${height} ${state.label}控件密度`)
   if(state.tag==='P')check(state.height>=parseFloat(state.lineHeight)+4,`${width}x${height} ${state.label}至少一行可读`)
   check(state.labelInline,`${width}x${height}左标签右字段`);states.push(state)
  }
  const after=await dialog.evaluate(n=>({header:n.querySelector(':scope > header')?.getBoundingClientRect().top,footer:n.querySelector(':scope > footer')?.getBoundingClientRect().bottom}))
  check(after.header===geometry.header&&after.footer===geometry.footer,`${width}x${height}滚动不移动标题和底部`)
  await controls.last().focus();await page.keyboard.press('Tab');check(await controls.first().evaluate(n=>n===document.activeElement),`${width}x${height}末端Tab循环`)
  await page.keyboard.press('Shift+Tab');check(await controls.last().evaluate(n=>n===document.activeElement),`${width}x${height}首端反向Tab循环`)
  const screenshots=[];for(const end of ['first','last']){await(end==='first'?controls.first():controls.last()).scrollIntoViewIfNeeded();const file=`background-${phase}-${width}x${height}-${end}.png`;await page.screenshot({path:join(directory,file)});screenshots.push(file)}
  assert.deepEqual(await fields(),initial);assert.deepEqual(await draft(),before)
  layout.cases.push({phase,width,height,geometry,states,screenshots});await writeFile(join(directory,'layout.json'),JSON.stringify(layout,null,2));console.log(JSON.stringify({phase,width,height,failures:layout.failures.length}))
 }
 await page.setViewportSize({width:1440,height:900})
}
