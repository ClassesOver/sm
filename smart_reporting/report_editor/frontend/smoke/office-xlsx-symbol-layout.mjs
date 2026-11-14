import assert from 'node:assert/strict'
import {writeFile} from 'node:fs/promises'
import {join} from 'node:path'
import AxeBuilder from '@axe-core/playwright'

export async function inspectSymbolLayout(page,{directory,phase,layout,draft}){
 const dialog=page.getByRole('dialog',{name:'插入符号',exact:true}),card=dialog.locator('.workbook-symbol-dialog'),before=await draft()
 const selected=()=>dialog.locator('[role=tab][aria-selected=true]').textContent(),original=await selected()
 const check=(ok,label)=>{if(!ok)layout.failures.push(`${phase}: ${label}`)}
 for(const [width,height] of [[1440,900],[768,720],[320,640],[640,360],[390,320]]){
  await page.setViewportSize({width,height});await page.evaluate(()=>document.fonts.ready)
  const geometry=await card.evaluate(node=>{const r=node.getBoundingClientRect(),s=getComputedStyle(node);return {left:r.left,right:r.right,top:r.top,bottom:r.bottom,overflow:node.scrollWidth>node.clientWidth+1,font:s.fontFamily,header:!!node.querySelector('header h2'),footer:!!node.querySelector('footer [data-symbol-close]'),tabStops:[...node.querySelectorAll('[role=tab]')].filter(n=>n.tabIndex===0).length,symbolStops:[...node.querySelectorAll('[data-symbol]')].filter(n=>n.tabIndex===0).length}})
  check(geometry.left>=0&&geometry.top>=0&&geometry.right<=width+1&&geometry.bottom<=height+1&&!geometry.overflow,`${width}x${height}窗口边界`)
  check(geometry.header&&geometry.footer,`${width}x${height}固定标题与操作区`)
  check(geometry.tabStops===1&&geometry.symbolStops===1,`${width}x${height}分类/符号单一Tab入口`)
  const protectedNavigation=[]
  for(const control of [dialog.locator('[role=tab][aria-selected=true]'),dialog.locator('[data-symbol][tabindex="0"]')]){
   await control.focus()
   for(const key of ['ArrowRight','Home','End'])for(const protection of ['composition','legacy','handled']){
    const preserved=await control.evaluate((node,{key,protection})=>{
     const event=new KeyboardEvent('keydown',{key,bubbles:true,cancelable:true,isComposing:protection==='composition',keyCode:protection==='legacy'?229:0})
     if(protection==='handled')event.preventDefault()
     node.dispatchEvent(event);return node===document.activeElement&&node.isConnected
    },{key,protection})
    check(preserved,`${width}x${height} ${key}/${protection}导航未保留`);protectedNavigation.push({key,protection,preserved})
   }
   await control.evaluate(node=>node.addEventListener('keydown',event=>{if(event.key==='ArrowRight')event.preventDefault()},{capture:true,once:true}))
   await control.press('ArrowRight');check(await control.evaluate(node=>node===document.activeElement),`${width}x${height}已消费实际方向键未保留`)
  }
  const states=[],screenshots=[]
  for(const control of await dialog.locator('button,[tabindex="0"]').all()){
   if(!await control.isVisible())continue
   await control.scrollIntoViewIfNeeded();await control.focus()
   const roundTrip=await control.evaluate(node=>node.tabIndex>=0)
   if(roundTrip){await page.keyboard.press('Tab');await page.keyboard.press('Shift+Tab')}
   const state=await control.evaluate(node=>{const r=node.getBoundingClientRect(),s=getComputedStyle(node),points=[[r.x+r.width/2,r.y+r.height/2],[r.x+2,r.y+2],[r.right-2,r.y+2],[r.x+2,r.bottom-2],[r.right-2,r.bottom-2]].map(([x,y])=>{const hit=document.elementFromPoint(x,y);return {x,y,hit:node.contains(hit),target:hit?.outerHTML.slice(0,180)}});return {label:node.getAttribute('aria-label')||node.textContent,tag:node.tagName,symbol:node.hasAttribute('data-symbol'),focused:node===document.activeElement,ring:s.outlineStyle!=='none'&&parseFloat(s.outlineWidth)>=2,height:r.height,width:r.width,radius:s.borderRadius,font:s.fontFamily,lineHeight:s.lineHeight,hit:points.every(p=>p.hit),misses:points.filter(p=>!p.hit)}})
   check(state.hit&&state.focused&&state.ring,`${width}x${height} ${state.label}焦点命中`)
   if(state.tag==='BUTTON')check((state.symbol?state.height>=32&&state.height<=40:state.height>=28&&state.height<=32)&&state.font===geometry.font,`${width}x${height} ${state.label}紧凑尺寸字体`)
   else check(state.height>=parseFloat(state.lineHeight)+4,`${width}x${height} ${state.label}至少一行可读`)
   states.push({...state,roundTrip})
   if(state.label==='符号插入错误'){const file=`symbol-${phase}-${width}x${height}-error-focus.png`;await page.screenshot({path:join(directory,file)});screenshots.push(file)}
  }
  for(const position of ['first','last']){const controls=dialog.locator('button').filter({visible:true});await(position==='first'?controls.first():controls.last()).scrollIntoViewIfNeeded();const file=`symbol-${phase}-${width}x${height}-${position}.png`;await page.screenshot({path:join(directory,file)});screenshots.push(file)}
  const axe=await new AxeBuilder({page}).include('.workbook-symbol-dialog').analyze();check(axe.violations.length===0,`${width}x${height} axe: ${JSON.stringify(axe.violations)}`)
  assert.equal(await selected(),original);assert.deepEqual(await draft(),before)
  layout.cases.push({phase,width,height,geometry,protectedNavigation,axeViolations:axe.violations,states,screenshots});await writeFile(join(directory,'layout.json'),JSON.stringify(layout,null,2));console.log(JSON.stringify({phase,width,height,controls:states.length,failures:layout.failures.length}))
 }
 await page.setViewportSize({width:1440,height:900})
}
