import assert from 'node:assert/strict'
import {writeFile} from 'node:fs/promises'
import {join} from 'node:path'

// 从真实放映入口进入，保留当前草稿；不构造替代放映或修改渲染树。
export async function inspectSlidesShow(page,{output,viewports,open,draft}){
 const evidence={cases:[],keyboard:[],failures:[]},before=await draft(),dialog=page.locator('.slides-show')
 const check=(ok,message)=>{if(!ok)evidence.failures.push(message)}
 const close=async()=>{await dialog.waitFor({state:'detached'});await page.waitForFunction(()=>!document.fullscreenElement)}
 const inspect=async(width,height,phase)=>{
  await page.evaluate(()=>document.fonts.ready);await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))))
  const geometry=await dialog.evaluate(node=>{
   const rect=element=>{const r=element.getBoundingClientRect();return {x:r.x,y:r.y,width:r.width,height:r.height,right:r.right,bottom:r.bottom}}
   const toolbar=node.querySelector('.slides-show-controls'),stage=node.querySelector('.slides-show-stage'),canvas=stage.querySelector('canvas'),note=node.querySelector('.slides-show-note')
   return {viewport:{width:innerWidth,height:innerHeight},dialog:rect(node),stage:rect(stage),canvas:rect(canvas),font:getComputedStyle(node).fontFamily,
    fullscreen:document.fullscreenElement===node,note:{...rect(note),font:getComputedStyle(note).fontFamily,text:note.textContent},
    controls:[...toolbar.querySelectorAll('button,span')].map(control=>{const s=getComputedStyle(control);return {label:control.getAttribute('aria-label'),rect:rect(control),font:s.fontFamily,radius:parseFloat(s.borderRadius),disabled:Boolean(control.disabled)}})}
  })
  const label=`${width}x${height} ${phase}`
  check(geometry.viewport.width===width&&geometry.viewport.height===height,`${label}: 视口不符合请求`)
  check(geometry.font.includes('Noto Sans')&&geometry.note.font.includes('Noto Sans'),`${label}: 放映字体未继承主题`)
  check(geometry.canvas.width>80&&geometry.canvas.height>80&&geometry.canvas.x>=0&&geometry.canvas.y>=0&&geometry.canvas.right<=width+1&&geometry.canvas.bottom<=height+1,`${label}: 幻灯片画布不可用或超出边界`)
  check(Math.abs(geometry.canvas.width/geometry.canvas.height-4/3)<0.02,`${label}: 幻灯片比例变化`)
  check(geometry.note.bottom<=height+1&&geometry.note.text.includes('只读静态放映'),`${label}: 静态能力说明不可见`)
  check(new Set(geometry.controls.map(control=>Math.round(control.rect.y+control.rect.height/2))).size===1,`${label}: 放映控制条折成多行`)
  const states=[]
  for(const control of await dialog.locator('button:enabled').all()){
   await control.focus();await page.keyboard.press('Tab');await page.keyboard.press('Shift+Tab')
   const state=await control.evaluate(node=>{const r=node.getBoundingClientRect(),s=getComputedStyle(node),hit=document.elementFromPoint(r.x+r.width/2,r.y+r.height/2);return {label:node.getAttribute('aria-label'),focused:node===document.activeElement,hit:node.contains(hit),font:s.fontFamily,radius:parseFloat(s.borderRadius),ring:s.outlineStyle!=='none'&&parseFloat(s.outlineWidth)>=2,width:r.width,height:r.height,x:r.x,y:r.y,right:r.right,bottom:r.bottom}})
   check(state.focused&&state.hit&&state.ring,`${label}: ${state.label}焦点或命中不可用`)
   check(state.font.includes('Noto Sans')&&state.radius<=6&&state.height>=28&&state.height<=36,`${label}: ${state.label}未采用紧凑主题控件`)
   check(state.x>=0&&state.y>=0&&state.right<=width+1&&state.bottom<=height+1,`${label}: ${state.label}超出视口`)
   states.push(state)
  }
  evidence.cases.push({width,height,phase,geometry,states})
  await page.screenshot({path:join(output,`show-${width}x${height}-${phase}.png`)})
  await writeFile(join(output,'show-layout.json'),JSON.stringify(evidence,null,2));assert.deepEqual(await draft(),before)
 }
 for(const viewport of viewports.split(',')){
  const [width,height]=viewport.split('x').map(Number);await page.setViewportSize({width,height})
  await dialog.focus();await page.keyboard.press('Home');await inspect(width,height,'first')
  const navigation={width,height}
  const next=dialog.getByRole('button',{name:'下一页',exact:true});await next.focus();await page.keyboard.press('Space')
  navigation.afterNext=await page.getByLabel('放映页码').textContent()
  check(navigation.afterNext==='2 / 2',`${viewport}: 空格未原生激活下一页`)
  const previous=dialog.getByRole('button',{name:'上一页',exact:true})
  navigation.previousFocused=await previous.evaluate(node=>node===document.activeElement)
  check(navigation.previousFocused,`${viewport}: 末页焦点留在禁用下一页`)
  await inspect(width,height,'last')
  await previous.focus();await page.keyboard.press('Space')
  navigation.afterPrevious=await page.getByLabel('放映页码').textContent()
  check(navigation.afterPrevious==='1 / 2',`${viewport}: 空格未原生激活上一页`)
  navigation.nextFocused=await next.evaluate(node=>node===document.activeElement)
  check(navigation.nextFocused,`${viewport}: 首页面焦点留在禁用上一页`)
  await dialog.getByRole('button',{name:'退出放映',exact:true}).focus();await page.keyboard.press('Space')
  const exited=await dialog.count()===0
  navigation.exitedBySpace=exited
  check(exited,`${viewport}: 空格未原生激活退出放映`)
  if(!exited)await dialog.getByRole('button',{name:'退出放映',exact:true}).click()
  await close()
  navigation.entryFocused=await page.locator('[data-command="startShow"]').evaluate(node=>node===document.activeElement)
  check(navigation.entryFocused,`${viewport}: 退出后未返回放映入口`)
  assert.deepEqual(await draft(),before);await open();evidence.keyboard.push(navigation)
  await writeFile(join(output,'show-layout.json'),JSON.stringify(evidence,null,2))
 }
 await page.setViewportSize({width:1440,height:1100})
 await writeFile(join(output,'show-layout.json'),JSON.stringify(evidence,null,2));assert.deepEqual(await draft(),before)
 return evidence
}
