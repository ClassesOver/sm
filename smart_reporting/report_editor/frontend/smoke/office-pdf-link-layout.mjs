import assert from 'node:assert/strict'
import {writeFile} from 'node:fs/promises'
import {join} from 'node:path'

export async function inspectLinkLayout(page,{directory,phase,layout,draft}){
 const dialog=page.getByRole('dialog',{name:'添加链接',exact:true}),before=await draft()
 const values=()=>dialog.locator('input').evaluateAll(nodes=>nodes.map(node=>node.value))
 const original=await values(),check=(ok,label)=>{if(!ok)layout.failures.push(`${phase}: ${label}`)}
 for(const [width,height] of [[1440,900],[768,720],[320,640],[640,360],[390,320]]){
  await page.setViewportSize({width,height});await page.evaluate(()=>document.fonts.ready)
  const geometry=await dialog.evaluate(node=>{const r=node.getBoundingClientRect(),s=getComputedStyle(node);return {left:r.left,right:r.right,top:r.top,bottom:r.bottom,overflow:node.scrollWidth>node.clientWidth+1,font:s.fontFamily,header:!!node.querySelector('header h3'),footer:!!node.querySelector('footer .pdf-link-actions'),description:node.querySelector('[role=region]')?.getAttribute('aria-label')}})
  check(geometry.left>=0&&geometry.top>=0&&geometry.right<=width+1&&geometry.bottom<=height+1&&!geometry.overflow,`${width}x${height}窗口边界`)
  check(geometry.header&&geometry.footer&&geometry.description==='链接设置说明',`${width}x${height}标题操作区和说明`)
  const states=[]
  for(const control of await dialog.locator('button,input,[tabindex="0"]').all()){
   if(!await control.isVisible())continue
   await control.scrollIntoViewIfNeeded();await control.focus();await page.keyboard.press('Tab');await page.keyboard.press('Shift+Tab')
   const state=await control.evaluate(node=>{const r=node.getBoundingClientRect(),s=getComputedStyle(node),inset=Math.min(5,r.width/4,r.height/4),points=[[r.x+r.width/2,r.y+r.height/2],[r.x+inset,r.y+inset],[r.right-inset,r.y+inset],[r.x+inset,r.bottom-inset],[r.right-inset,r.bottom-inset]];return {label:node.getAttribute('aria-label')||node.textContent,tag:node.tagName,focused:node===document.activeElement,ring:s.outlineStyle!=='none'&&parseFloat(s.outlineWidth)>=2,height:r.height,font:s.fontFamily,points,hit:points.every(([x,y])=>node.contains(document.elementFromPoint(x,y)))}})
   check(state.hit&&state.focused&&state.ring,`${width}x${height} ${state.label}焦点命中`)
   if(['BUTTON','INPUT'].includes(state.tag))check(state.height>=28&&state.height<=32&&state.font===geometry.font,`${width}x${height} ${state.label}紧凑尺寸字体`)
   states.push(state)
  }
  const chrome=await dialog.evaluate(node=>[...node.querySelectorAll('header,footer')].map(n=>{const r=n.getBoundingClientRect();return {top:r.top,bottom:r.bottom}}))
  check(chrome.length===2&&chrome.every(r=>r.top>=0&&r.bottom<=height),`${width}x${height}滚动后标题和操作可见`)
  const screenshots=[]
  for(const position of ['first','last']){
   const controls=dialog.locator('button,input');await(position==='first'?controls.first():controls.last()).scrollIntoViewIfNeeded()
   const file=`link-${phase}-${width}x${height}-${position}.png`;await page.screenshot({path:join(directory,file)});screenshots.push(file)
  }
  assert.deepEqual(await values(),original);assert.deepEqual(await draft(),before)
  layout.cases.push({phase,width,height,geometry,states,chrome,screenshots});await writeFile(join(directory,'layout.json'),JSON.stringify(layout,null,2))
  console.log(JSON.stringify({phase,width,height,controls:states.length,failures:layout.failures.length}))
 }
 await page.setViewportSize({width:1440,height:900})
}
