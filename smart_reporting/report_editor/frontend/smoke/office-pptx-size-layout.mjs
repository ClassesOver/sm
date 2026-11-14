import assert from 'node:assert/strict'
import {writeFile} from 'node:fs/promises'
import {join} from 'node:path'
import {inspectSlidesDialogInputProtection} from './slides-dialog-input-protection.mjs'

export async function inspectSizeLayout(page,{output,phase,layout,draft}){
 const dialog=page.getByRole('dialog',{name:'自定义幻灯片尺寸',exact:true}),before=await draft()
 const snapshot=()=>dialog.locator('input,select').evaluateAll(nodes=>nodes.map(node=>[node.getAttribute('aria-label'),node.value]))
 const values=await snapshot(),check=(ok,label)=>{if(!ok)layout.failures.push(`${phase}: ${label}`)}
 for(const [width,height] of [[1440,900],[768,720],[320,640],[640,360],[390,320]]){
  await page.setViewportSize({width,height});await page.evaluate(()=>document.fonts.ready)
  const geometry=await dialog.evaluate(node=>{const r=node.getBoundingClientRect();return {left:r.left,right:r.right,top:r.top,bottom:r.bottom,overflow:node.scrollWidth>node.clientWidth+1,font:getComputedStyle(node).fontFamily,header:!!node.querySelector('header h2'),footer:!!node.querySelector('footer .slides-table-actions'),close:!!node.querySelector('[aria-label="关闭自定义幻灯片尺寸"]')}})
  check(geometry.left>=0&&geometry.top>=0&&geometry.right<=width+1&&geometry.bottom<=height+1&&!geometry.overflow,`${width}x${height}窗口边界`)
  check(geometry.header&&geometry.footer&&geometry.close,`${width}x${height}固定标题操作及关闭`)
  const states=[]
  for(const control of await dialog.locator('button:visible,input:visible,select:visible,[tabindex="0"]:visible').all()){
   await control.scrollIntoViewIfNeeded();await control.focus();await page.keyboard.press('Tab');await page.keyboard.press('Shift+Tab')
   const state=await control.evaluate(node=>{const r=node.getBoundingClientRect(),s=getComputedStyle(node);return {label:node.getAttribute('aria-label')||node.textContent,tag:node.tagName,focused:node===document.activeElement,ring:s.outlineStyle!=='none'&&parseFloat(s.outlineWidth)>=2,height:r.height,font:s.fontFamily,hit:[[r.x+r.width/2,r.y+r.height/2],[r.x+2,r.y+2],[r.right-2,r.y+2],[r.x+2,r.bottom-2],[r.right-2,r.bottom-2]].every(([x,y])=>node.contains(document.elementFromPoint(x,y)))}})
   check(state.hit&&state.focused&&state.ring,`${width}x${height} ${state.label}焦点及命中`)
   if(['BUTTON','INPUT','SELECT'].includes(state.tag))check(state.height>=28&&state.height<=50&&state.font===geometry.font,`${width}x${height} ${state.label}紧凑字体`)
   states.push(state)
  }
  const inputProtection=process.env.PPTX_DIALOG_INPUT_PROTECTION==='1'?await inspectSlidesDialogInputProtection(page,dialog):undefined
  const screenshots=[]
  for(const position of ['first','last']){const controls=dialog.locator('button:visible,input:visible,select:visible,[tabindex="0"]:visible');await(position==='first'?controls.first():controls.last()).scrollIntoViewIfNeeded();const file=`size-${phase}-${width}x${height}-${position}.png`;await page.screenshot({path:join(output,file)});screenshots.push(file)}
  assert.deepEqual(await snapshot(),values);assert.deepEqual(await draft(),before)
  layout.cases.push({phase,width,height,geometry,states,screenshots,inputProtection});await writeFile(join(output,'size-layout.json'),JSON.stringify(layout,null,2));console.log(JSON.stringify({phase,width,height,controls:states.length,failures:layout.failures.length}))
 }
 await page.setViewportSize({width:1600,height:1000})
}
