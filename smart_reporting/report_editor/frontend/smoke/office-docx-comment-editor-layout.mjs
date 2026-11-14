import assert from 'node:assert/strict'
import {writeFile} from 'node:fs/promises'
import {join} from 'node:path'

export async function inspectCommentEditor(page,{output,phase,evidence}) {
 const panel=page.locator('.docx-comment-panel').filter({has:page.locator('[data-comment-text]')}),input=panel.locator('textarea')
 const snapshot=()=>page.evaluate(()=>({draft:Object.entries(localStorage).sort(),text:document.querySelector('[data-comment-text]').value}))
 const before=await snapshot(),check=(ok,label)=>{if(!ok)evidence.failures.push(`${phase}: ${label}`)}
 for(const [width,height] of [[1440,900],[320,640],[640,360],[390,320],[1440,360]]){
  await page.setViewportSize({width,height});await page.evaluate(()=>document.fonts.ready)
  await panel.scrollIntoViewIfNeeded()
  const geometry=await panel.evaluate(node=>{
   const r=node.getBoundingClientRect(),s=getComputedStyle(node)
   return {left:r.left,right:r.right,overflow:node.scrollWidth>node.clientWidth+1,font:s.fontFamily,
    themeFont:getComputedStyle(node.closest('.docx-native')).fontFamily,
    header:!!node.querySelector('header h2'),namedActions:!!node.querySelector('section[aria-label="批注操作"]')}
  })
  check(!geometry.overflow&&geometry.left>=0&&geometry.right<=width+1,`${width}x${height}横向边界`)
  check(geometry.header&&geometry.namedActions,`${width}x${height}桌面标题及操作分组`)
  const states=[]
  for(const control of await panel.locator('button:visible,select:visible,textarea:visible').all()){
   const disabled=await control.isDisabled();await control.scrollIntoViewIfNeeded()
   if(!disabled){await control.focus();await page.keyboard.press('Tab');await page.keyboard.press('Shift+Tab')}
   const state=await control.evaluate(node=>{
    const r=node.getBoundingClientRect(),s=getComputedStyle(node)
    return {label:node.getAttribute('aria-label')||node.textContent,tag:node.tagName,disabled:!!node.disabled,
     focused:document.activeElement===node,ring:s.outlineStyle!=='none'&&parseFloat(s.outlineWidth)>=2,
     height:r.height,font:s.fontFamily,hit:[[r.x+r.width/2,r.y+r.height/2],[r.x+3,r.y+3],[r.right-3,r.y+3],[r.x+3,r.bottom-3],[r.right-3,r.bottom-3]].every(([x,y])=>node.contains(document.elementFromPoint(x,y)))}
   })
   check(state.hit&&(disabled||state.focused&&state.ring),`${width}x${height} ${state.label}焦点和命中`)
   check(state.font===geometry.themeFont&&(state.tag==='TEXTAREA'||state.height>=28&&state.height<=50),`${width}x${height} ${state.label}紧凑主题控件`)
   states.push(state)
  }
  const screenshots=[]
  for(const end of ['first','last']){
   const controls=panel.locator('button:visible,select:visible,textarea:visible')
   await(end==='first'?controls.first():controls.last()).scrollIntoViewIfNeeded()
   const file=`comment-editor-${phase}-${width}x${height}-${end}.png`;await page.screenshot({path:join(output,file)});screenshots.push(file)
  }
  assert.deepEqual(await snapshot(),before,'布局检查不能改变草稿或输入')
  evidence.cases.push({phase,width,height,geometry,states,screenshots})
  await writeFile(join(output,'comment-editor-layout.json'),JSON.stringify(evidence,null,2))
  console.log(JSON.stringify({phase,width,height,controls:states.length,failures:evidence.failures.length}))
 }
 await page.setViewportSize({width:1600,height:1000});await input.scrollIntoViewIfNeeded()
}
