import assert from 'node:assert/strict'
import {writeFile} from 'node:fs/promises'
import {join} from 'node:path'

// 组件回调夹具与真实来源选区宿主共用；布局检查不修改字段或草稿。
export async function inspectDocxLinkLayout(page,{directory,phase,layout,draft=async()=>[]}){
 const dialog=page.getByRole('dialog',{name:'Link',exact:true}),card=dialog.locator('.docx-link-dialog')
 const before=await draft(),value=await dialog.getByLabel('Link URL',{exact:true}).inputValue()
 const check=(ok,message)=>{if(!ok)layout.failures.push(`${phase}: ${message}`)}
 for(const [width,height] of [[1440,900],[768,720],[320,640],[640,360],[390,320]]){
  await page.setViewportSize({width,height});await page.evaluate(()=>document.fonts.ready)
  await dialog.evaluate(node=>Promise.all(node.getAnimations({subtree:true}).map(animation=>animation.finished.catch(()=>{}))))
  const geometry=await card.evaluate(node=>{const r=node.getBoundingClientRect(),body=node.querySelector('.docx-link-body'),input=node.querySelector('input'),label=input.closest('label'),text=[...label.childNodes].find(n=>n.nodeType===Node.TEXT_NODE&&n.textContent.trim()),range=document.createRange();if(text)range.selectNodeContents(text);return {left:r.left,right:r.right,top:r.top,bottom:r.bottom,overflow:node.scrollWidth>node.clientWidth+1,font:getComputedStyle(node).fontFamily,header:!!node.querySelector(':scope > header h2'),footer:!!node.querySelector(':scope > form > footer'),bodyOverflow:body?getComputedStyle(body).overflowY:null,errorNamed:!!node.querySelector('[role=alert][aria-label][tabindex="0"]'),labelInline:!text||range.getBoundingClientRect().right<=input.getBoundingClientRect().left}})
  check(geometry.left>=0&&geometry.top>=0&&geometry.right<=width+1&&geometry.bottom<=height+1&&!geometry.overflow,`${width}x${height}窗口边界`)
  check(Math.abs(geometry.left-(width-geometry.right))<=1&&Math.abs(geometry.top-(height-geometry.bottom))<=1,`${width}x${height}窗口居中`)
  check(geometry.header&&geometry.footer&&geometry.bodyOverflow==='auto'&&geometry.errorNamed,`${width}x${height}固定区域与命名错误`)
  check(geometry.labelInline,`${width}x${height}左标签右字段`)
  const icon=await dialog.locator('.modal-close svg').evaluate(n=>{const r=n.getBoundingClientRect();return {width:r.width,height:r.height}})
  check(icon.width>=16&&icon.height>=16,`${width}x${height}关闭图标尺寸`)
  const sizes=[]
  for(const control of await dialog.locator('button:visible,input:visible').all()){
   const size=await control.evaluate(n=>({label:n.getAttribute('aria-label')||n.textContent,height:n.getBoundingClientRect().height,font:getComputedStyle(n).fontFamily,disabled:n.disabled}))
   check(size.height>=28&&size.height<=32&&size.font===geometry.font,`${width}x${height} ${size.label}紧凑控件`);sizes.push(size)
  }
  const controls=dialog.locator('button:visible:not(:disabled),input:visible:not(:disabled),[tabindex="0"]:visible'),states=[],screenshots=[]
  for(const control of await controls.all()){
   await control.scrollIntoViewIfNeeded();await control.focus();await page.keyboard.press('Tab');await page.keyboard.press('Shift+Tab')
   const state=await control.evaluate(n=>{const r=n.getBoundingClientRect(),s=getComputedStyle(n);return {label:n.getAttribute('aria-label')||n.textContent,tag:n.tagName,focus:n===document.activeElement,ring:s.outlineStyle!=='none'&&parseFloat(s.outlineWidth)>=2,height:r.height,lineHeight:s.lineHeight,hit:[[r.x+r.width/2,r.y+r.height/2],[r.x+2,r.y+2],[r.right-2,r.y+2],[r.x+2,r.bottom-2],[r.right-2,r.bottom-2]].every(([x,y])=>n.contains(document.elementFromPoint(x,y)))}})
   check(state.focus&&state.ring&&state.hit,`${width}x${height} ${state.label}焦点及五点命中`)
   if(state.tag==='P'){check(state.height>=parseFloat(state.lineHeight)+4,`${width}x${height}错误至少一行可读`);const file=`${phase}-${width}x${height}-error.png`;await page.screenshot({path:join(directory,file)});screenshots.push(file)}
   states.push(state)
  }
  for(const end of ['first','last']){await(end==='first'?controls.first():controls.last()).scrollIntoViewIfNeeded();const file=`${phase}-${width}x${height}-${end}.png`;await page.screenshot({path:join(directory,file)});screenshots.push(file)}
  await controls.last().focus();await page.keyboard.press('Tab');check(await controls.first().evaluate(n=>n===document.activeElement),`${width}x${height}末端Tab循环`)
  await page.keyboard.press('Shift+Tab');check(await controls.last().evaluate(n=>n===document.activeElement),`${width}x${height}首端反向循环`)
  assert.equal(await dialog.getByLabel('Link URL',{exact:true}).inputValue(),value);assert.deepEqual(await draft(),before)
  layout.cases.push({phase,width,height,geometry,icon,sizes,states,screenshots});await writeFile(join(directory,'link-layout.json'),JSON.stringify(layout,null,2));console.log(JSON.stringify({phase,width,height,failures:layout.failures.length}))
 }
 await page.setViewportSize({width:1440,height:900})
}
