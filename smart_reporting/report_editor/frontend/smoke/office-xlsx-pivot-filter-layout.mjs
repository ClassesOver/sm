import assert from 'node:assert/strict'
import {writeFile} from 'node:fs/promises'
import {join} from 'node:path'

export async function inspectPivotFilter(page,{output,phase,evidence,draft}){
 const overlay=page.locator('[role=dialog][aria-label="透视表筛选"]'),before=await draft()
 const snapshot=()=>overlay.evaluate(node=>[...node.querySelectorAll('input,select')].map(el=>({name:el.getAttribute('aria-label')||el.value,value:el.value,checked:el.checked})))
 const initial=await snapshot(),check=(ok,label)=>{if(!ok)evidence.failures.push(`${phase}: ${label}`)}
 for(const [width,height] of [[1440,900],[768,720],[320,640],[640,360],[390,320]]){
  await page.setViewportSize({width,height});await page.evaluate(()=>document.fonts.ready)
  const card=overlay.locator('.modal-card'),geometry=await card.evaluate(node=>{
   const r=node.getBoundingClientRect(),s=getComputedStyle(node)
   return {left:r.left,right:r.right,top:r.top,bottom:r.bottom,overflow:node.scrollWidth>node.clientWidth+1,font:s.fontFamily,
    header:!!node.querySelector('header h2'),footer:!!node.querySelector('footer'),memberRegion:node.querySelector('[data-members]')?.getAttribute('aria-label')==='可选筛选成员'}
  })
  check(geometry.left>=0&&geometry.right<=width+1&&geometry.top>=0&&geometry.bottom<=height+1&&!geometry.overflow,`${width}x${height}窗口边界`)
  check(geometry.header&&geometry.footer&&geometry.memberRegion,`${width}x${height}分组及命名`)
  const states=[]
  for(const control of await overlay.locator('button:visible,input:visible,select:visible,summary:visible,[tabindex="0"]:visible').all()){
   const disabled=await control.isDisabled();await control.scrollIntoViewIfNeeded()
   if(!disabled){await control.focus();await page.keyboard.press('Tab');await page.keyboard.press('Shift+Tab')}
   const state=await control.evaluate(node=>{
    const r=node.getBoundingClientRect(),s=getComputedStyle(node)
    return {label:node.getAttribute('aria-label')||node.textContent||node.value,tag:node.tagName,type:node.type,disabled:!!node.disabled,height:r.height,font:s.fontFamily,focused:node===document.activeElement,ring:s.outlineStyle!=='none'&&parseFloat(s.outlineWidth)>=2,
     hit:[[r.x+r.width/2,r.y+r.height/2],[r.x+2,r.y+2],[r.right-2,r.y+2],[r.x+2,r.bottom-2],[r.right-2,r.bottom-2]].every(([x,y])=>node.contains(document.elementFromPoint(x,y)))}
   })
   check(state.hit&&(disabled||state.focused&&state.ring),`${width}x${height} ${state.label}焦点和命中`)
   if(state.tag==='BUTTON'||state.tag==='SELECT'||state.tag==='INPUT'&&state.type!=='checkbox')check(state.height>=28&&state.height<=50&&state.font===geometry.font,`${width}x${height} ${state.label}控件密度及字体`)
   states.push(state)
  }
  const screenshots=[]
  for(const position of ['start','end']){
   const controls=overlay.locator('button:visible,input:visible,select:visible,summary:visible,[tabindex="0"]:visible')
   await(position==='start'?controls.first():controls.last()).scrollIntoViewIfNeeded()
   const file=`pivot-filter-${phase}-${width}x${height}-${position}.png`;await page.screenshot({path:join(output,file)});screenshots.push(file)
  }
  assert.deepEqual(await snapshot(),initial);assert.deepEqual(await draft(),before)
  evidence.cases.push({phase,width,height,geometry,states,screenshots});await writeFile(join(output,'layout.json'),JSON.stringify(evidence,null,2))
  console.log(JSON.stringify({phase,width,height,controls:states.length,failures:evidence.failures.length}))
 }
 await page.setViewportSize({width:1500,height:1000})
}
