import assert from 'node:assert/strict'
import {writeFile} from 'node:fs/promises'
import {join} from 'node:path'

export async function inspectExistingImageLayout(page,{directory,phase,layout,draft}){
 const dialog=page.getByRole('dialog',{name:'编辑已有图像',exact:true}),before=await draft()
 const values=()=>dialog.locator('input:not([type=file]),select').evaluateAll(nodes=>nodes.map(node=>node.value))
 const original=await values(),check=(ok,label)=>{if(!ok)layout.failures.push(`${phase}: ${label}`)}
 for(const [width,height] of [[1440,900],[768,720],[320,640],[640,360],[390,320]]){
  await page.setViewportSize({width,height});await page.evaluate(()=>document.fonts.ready)
  const geometry=await dialog.evaluate(node=>{const r=node.getBoundingClientRect(),s=getComputedStyle(node);return {left:r.left,right:r.right,top:r.top,bottom:r.bottom,overflow:node.scrollWidth>node.clientWidth+1,font:s.fontFamily,header:!!node.querySelector('header h3'),footer:!!node.querySelector('footer .pdf-layout-actions'),groups:[...node.querySelectorAll('fieldset legend')].map(n=>n.textContent),labelColumns:[...node.querySelectorAll('label')].map(n=>parseFloat(getComputedStyle(n).gridTemplateColumns))}})
  check(geometry.left>=0&&geometry.top>=0&&geometry.right<=width+1&&geometry.bottom<=height+1&&!geometry.overflow,`${width}x${height}窗口边界`)
  check(geometry.header&&geometry.footer&&geometry.groups.join('|')==='位置与尺寸|替换图像|像素编辑',`${width}x${height}标题操作区和分组`)
  check(geometry.labelColumns.every(size=>size<=60),`${width}x${height}紧凑标签列`)
  const states=[]
  for(const control of await dialog.locator('button,input:not([type=file]),select,[tabindex="0"]').all()){
   if(!await control.isVisible())continue
   await control.scrollIntoViewIfNeeded();const disabled=await control.isDisabled()
   if(!disabled){await control.focus();await page.keyboard.press('Tab');await page.keyboard.press('Shift+Tab')}
   const state=await control.evaluate(node=>{const r=node.getBoundingClientRect(),s=getComputedStyle(node);return {label:node.getAttribute('aria-label')||node.textContent,tag:node.tagName,disabled:!!node.disabled,focused:node===document.activeElement,ring:s.outlineStyle!=='none'&&parseFloat(s.outlineWidth)>=2,height:r.height,font:s.fontFamily,hit:[[r.x+r.width/2,r.y+r.height/2],[r.x+2,r.y+2],[r.right-2,r.y+2],[r.x+2,r.bottom-2],[r.right-2,r.bottom-2]].every(([x,y])=>node.contains(document.elementFromPoint(x,y)))}})
   check(state.hit&&(disabled||state.focused&&state.ring),`${width}x${height} ${state.label}焦点命中`)
   if(['BUTTON','INPUT','SELECT'].includes(state.tag))check(state.height>=28&&state.height<=32&&state.font===geometry.font,`${width}x${height} ${state.label}紧凑尺寸字体`)
   states.push(state)
  }
  const screenshots=[]
  for(const position of ['first','last']){
   const controls=dialog.locator('button,input:not([type=file]),select').filter({visible:true})
   await(position==='first'?controls.first():controls.last()).scrollIntoViewIfNeeded()
   const file=`existing-image-${phase}-${width}x${height}-${position}.png`;await page.screenshot({path:join(directory,file)});screenshots.push(file)
  }
  assert.deepEqual(await values(),original);assert.deepEqual(await draft(),before)
  layout.cases.push({phase,width,height,geometry,states,screenshots});await writeFile(join(directory,'layout.json'),JSON.stringify(layout,null,2));console.log(JSON.stringify({phase,width,height,controls:states.length,failures:layout.failures.length}))
 }
 await page.setViewportSize({width:1440,height:900})
}
