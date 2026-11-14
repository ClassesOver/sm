import assert from 'node:assert/strict'
import {writeFile} from 'node:fs/promises'
import {join} from 'node:path'

export async function inspectStampLayout(page,{directory,phase,layout,draft}){
 const dialog=page.getByRole('dialog',{name:'水印与页眉页脚',exact:true}),before=await draft()
 const snapshot=()=>dialog.locator('input').evaluateAll(nodes=>nodes.map(n=>({value:n.value,checked:n.checked})))
 const values=await snapshot(),check=(ok,label)=>{if(!ok)layout.failures.push(`${phase}: ${label}`)}
 for(const [width,height] of [[1440,900],[768,720],[320,640],[640,360],[390,320]]){
  await page.setViewportSize({width,height});await page.evaluate(()=>document.fonts.ready)
  const geometry=await dialog.evaluate(node=>{const r=node.getBoundingClientRect(),s=getComputedStyle(node);return {left:r.left,right:r.right,top:r.top,bottom:r.bottom,overflow:node.scrollWidth>node.clientWidth+1,font:s.fontFamily,header:!!node.querySelector('header h3'),footer:!!node.querySelector('footer .pdf-link-actions'),groups:[...node.querySelectorAll('fieldset legend')].map(n=>n.textContent),outputs:[...node.querySelectorAll('input[type=range]')].map(n=>({value:n.value,text:n.getAttribute('aria-valuetext'),output:n.closest('label').querySelector('output')?.textContent}))}})
  check(geometry.left>=0&&geometry.top>=0&&geometry.right<=width+1&&geometry.bottom<=height+1&&!geometry.overflow,`${width}x${height}窗口边界`)
  check(geometry.header&&geometry.footer&&geometry.groups.join('|')==='水印|页眉页脚',`${width}x${height}固定区域和分组`)
  check(geometry.outputs.every((o,i)=>o.text===o.value+(i===0?'°':'%')&&o.output===o.text),`${width}x${height}滑块数值`)
  const states=[]
  for(const control of await dialog.locator('button,input,[tabindex="0"]').all()){
   await control.scrollIntoViewIfNeeded();const disabled=await control.isDisabled()
   if(!disabled){await control.focus();await page.keyboard.press('Tab');await page.keyboard.press('Shift+Tab')}
   const state=await control.evaluate(node=>{const r=node.getBoundingClientRect(),s=getComputedStyle(node);return {label:node.getAttribute('aria-label')||node.textContent,tag:node.tagName,type:node.type,disabled:!!node.disabled,focused:node===document.activeElement,ring:s.outlineStyle!=='none'&&parseFloat(s.outlineWidth)>=2,height:r.height,font:s.fontFamily,hit:[[r.x+r.width/2,r.y+r.height/2],[r.x+2,r.y+2],[r.right-2,r.y+2],[r.x+2,r.bottom-2],[r.right-2,r.bottom-2]].every(([x,y])=>node.contains(document.elementFromPoint(x,y)))}})
   check(state.hit&&(disabled||state.focused&&state.ring),`${width}x${height} ${state.label}焦点命中`)
   if(state.tag==='BUTTON'||state.tag==='INPUT'&&state.type!=='checkbox')check(state.height>=28&&state.height<=50&&state.font===geometry.font,`${width}x${height} ${state.label}尺寸字体`)
   states.push(state)
  }
  const screenshots=[]
  for(const position of ['first','last']){const controls=dialog.locator('button,input,[tabindex="0"]');await(position==='first'?controls.first():controls.last()).scrollIntoViewIfNeeded();const file=`stamp-${phase}-${width}x${height}-${position}.png`;await page.screenshot({path:join(directory,file)});screenshots.push(file)}
  assert.deepEqual(await snapshot(),values);assert.deepEqual(await draft(),before)
  layout.cases.push({phase,width,height,geometry,states,screenshots});await writeFile(join(directory,'stamp-layout.json'),JSON.stringify(layout,null,2));console.log(JSON.stringify({phase,width,height,controls:states.length,failures:layout.failures.length}))
 }
 await page.setViewportSize({width:1440,height:900})
}
