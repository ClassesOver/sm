import assert from 'node:assert/strict'
import {writeFile} from 'node:fs/promises'
import {join} from 'node:path'
import AxeBuilder from '@axe-core/playwright'

async function protect(control,key,protection){
 return control.evaluate((node,{key,protection})=>{const event=new KeyboardEvent('keydown',{key,bubbles:true,cancelable:true,isComposing:protection==='composition',keyCode:protection==='legacy'?229:0});if(protection==='handled')event.preventDefault();node.dispatchEvent(event);return{key,protection,focused:node===document.activeElement,connected:node.isConnected,prevented:event.defaultPrevented}},{key,protection})
}

// 真实来源图表的属性窗格与共享颜色图库；浏览结束不留下草稿。
export async function inspectChartFormat(page,{output,targets,draft}){
 const evidence={cases:[],palettes:[],failures:[]},before=await draft(),pane=page.locator('.slides-chart-format-pane')
 const check=(ok,label)=>{if(!ok)evidence.failures.push(label)}
 for(const target of targets){
  await page.locator(`.slide-open[data-slide-index="${target.slideIndex}"]`).click();await page.locator('#object-select').selectOption(target.id)
  for(const viewport of ['1440x900','320x640','640x360','390x320','1440x360']){
   const [width,height]=viewport.split('x').map(Number),label=`${target.kind}/${viewport}`;await page.setViewportSize({width,height});await page.evaluate(()=>document.fonts.ready)
   await pane.scrollIntoViewIfNeeded()
   const geometry=await pane.evaluate(node=>{const r=node.getBoundingClientRect();return{x:r.x,right:r.right,width:r.width,overflow:node.scrollWidth>node.clientWidth+1,font:getComputedStyle(node).fontFamily,themeFont:getComputedStyle(node.closest('.slides-embedded')).fontFamily,groups:[...node.querySelectorAll('fieldset>legend')].map(n=>n.textContent),wrapping:[...node.querySelectorAll('.fp-chart-point-label')].every(n=>getComputedStyle(n).whiteSpace!=='nowrap'&&n.scrollWidth<=n.clientWidth+1)}})
   check(!geometry.overflow&&geometry.x>=0&&geometry.right<=width+1,`${label}: 横向溢出`);check(geometry.font===geometry.themeFont,`${label}: 主题字体`)
   check(JSON.stringify(geometry.groups)===JSON.stringify(target.seriesNames),`${label}: 原生系列分组`);check(geometry.wrapping,`${label}: 类别名完整换行`)
   const states=[]
   for(const control of await pane.locator('button').all()){
    const disabled=await control.isDisabled();await control.scrollIntoViewIfNeeded()
    if(!disabled){await control.focus();await page.keyboard.press('Tab');await page.keyboard.press('Shift+Tab')}
    const state=await control.evaluate(node=>{const r=node.getBoundingClientRect(),s=getComputedStyle(node),points=[[r.x+r.width/2,r.y+r.height/2],[r.x+3,r.y+3],[r.right-3,r.y+3],[r.x+3,r.bottom-3],[r.right-3,r.bottom-3]];return{label:node.getAttribute('aria-label')||node.textContent,disabled:node.disabled,focused:node===document.activeElement,font:s.fontFamily,height:r.height,ring:s.outlineStyle!=='none'&&parseFloat(s.outlineWidth)>=2,hit:points.every(([x,y])=>node.contains(document.elementFromPoint(x,y)))}})
    check(state.hit&&(disabled||state.focused&&state.ring),`${label}: ${state.label}命中或焦点`);check(Math.abs(state.height-28)<1&&state.font===geometry.themeFont,`${label}: ${state.label}紧凑主题控件`);states.push(state)
   }
   const protectedKeys=[]
   if(target.kind==='scatter')check((await pane.innerText()).includes('散点图')&&states.length===0,`${label}: 散点图原因与守卫`)
   else{
    const well=pane.locator('[data-chart-format-well="0:0"]');await well.scrollIntoViewIfNeeded();await well.focus()
    for(const protection of ['composition','legacy','handled']){const record=await protect(well,'ArrowDown',protection);check(record.focused&&record.prevented===(protection==='handled')&&await page.locator('[data-chart-format-palette]').count()===0,`${label}: 保护打开 ${JSON.stringify(record)}`);protectedKeys.push({target:'trigger',...record})}
    await well.press('ArrowDown');const popup=page.locator('[data-chart-format-palette]');await popup.waitFor()
    const first=popup.locator('[role=gridcell]:focus');check(await first.count()===1,`${label}: 打开焦点`)
    for(const key of ['ArrowLeft','ArrowRight','ArrowUp','ArrowDown','Home','End','Escape'])for(const protection of ['composition','legacy','handled']){
     const record=await protect(first,key,protection);check(record.focused&&record.connected&&record.prevented===(protection==='handled')&&await popup.count()===1,`${label}: 保护色块 ${JSON.stringify(record)}`);protectedKeys.push({target:'palette',...record})
    }
    await first.evaluate(node=>node.addEventListener('keydown',event=>event.preventDefault(),{capture:true,once:true}));const firstPos=await first.getAttribute('data-pos');await first.press('ArrowRight');check(await popup.locator('[role=gridcell]:focus').getAttribute('data-pos')===firstPos,`${label}: 实际已消费方向键被图库重新处理`)
    const box=await popup.evaluate(node=>{const r=node.getBoundingClientRect();return{x:r.x,y:r.y,right:r.right,bottom:r.bottom}});check(box.x>=0&&box.y>=0&&box.right<=width+1&&box.bottom<=height+1,`${label}: 色板边界`)
    const cells=[]
    for(let index=0;index<70;index++){
     const active=popup.locator('[role=gridcell]:focus');check(await active.count()===1,`${label}: 色板焦点`);if(!await active.count())break
     await active.scrollIntoViewIfNeeded();const state=await active.evaluate(node=>{const r=node.getBoundingClientRect(),s=getComputedStyle(node);return{pos:node.dataset.pos,ring:s.outlineStyle!=='none'&&parseFloat(s.outlineWidth)>=2,hit:[[r.x+3,r.y+3],[r.right-3,r.y+3],[r.x+3,r.bottom-3],[r.right-3,r.bottom-3]].every(([x,y])=>node.contains(document.elementFromPoint(x,y)))}});check(state.ring&&state.hit,`${label}: ${state.pos}色块可见性`);cells.push(state);await page.keyboard.press('ArrowRight')
    }
    check(new Set(cells.map(c=>c.pos)).size===70,`${label}: 70色遍历`);await page.screenshot({path:join(output,`chart-palette-${target.kind}-${viewport}.png`)})
    const paletteAxe=await new AxeBuilder({page}).include('[data-chart-format-palette]').analyze();check(paletteAxe.violations.length===0,`${label}: 色板axe ${JSON.stringify(paletteAxe.violations)}`)
    await page.keyboard.press('Escape');check(await well.evaluate(node=>node===document.activeElement)&&await popup.count()===0,`${label}: Escape返回入口`);evidence.palettes.push({kind:target.kind,width,height,box,cells,axe:paletteAxe.violations})
   }
   const screenshots=[]
   for(const phase of ['first','last']){
    const controls=pane.locator('button');if(await controls.count()){const target=phase==='first'?controls.first():controls.last();await target.scrollIntoViewIfNeeded()}else await pane.scrollIntoViewIfNeeded()
    const file=`chart-format-${target.kind}-${viewport}-${phase}.png`;await page.screenshot({path:join(output,file)});screenshots.push(file)
   }
   const axe=await new AxeBuilder({page}).include('.slides-chart-format-pane').analyze();check(axe.violations.length===0,`${label}: 窗格axe ${JSON.stringify(axe.violations)}`)
   assert.deepEqual(await draft(),before);evidence.cases.push({kind:target.kind,width,height,geometry,states,screenshots,protectedKeys,axe:axe.violations});await writeFile(join(output,'chart-format-layout.json'),JSON.stringify(evidence,null,2));console.log(JSON.stringify({layout:label,controls:states.length,failures:evidence.failures.length}))
  }
 }
 await page.setViewportSize({width:1440,height:900});return evidence
}

// 同一真实来源图表的配色图库；仅浏览和关闭，不生成草稿。
export async function inspectChartGallery(page,{output,draft}){
 const cases=[],before=await draft(),toggle=page.locator('[data-chart-colors-toggle]'),menu=page.locator('[data-chart-colors-menu]'),tab=page.locator('[data-ribbon-tab=chartDesign]')
 const previous=await page.locator('[data-ribbon-tab][aria-selected=true]').getAttribute('data-ribbon-tab')
 for(const [width,height] of [[1440,900],[320,640],[640,360],[390,320],[1440,360]]){
  await page.setViewportSize({width,height});await tab.click();await toggle.focus();await toggle.scrollIntoViewIfNeeded();const protectedKeys=[]
  for(const protection of ['composition','legacy','handled']){const record=await protect(toggle,'ArrowDown',protection);assert.ok(record.focused&&record.prevented===(protection==='handled'));assert.equal(await menu.isVisible(),false);protectedKeys.push({target:'trigger',...record})}
  await toggle.press('ArrowDown');await menu.waitFor({state:'visible'});assert.equal(await menu.locator('button').count(),13)
  const first=menu.locator('button').first();assert.ok(await first.evaluate(node=>node===document.activeElement))
  for(const protection of ['composition','legacy','handled']){const record=await protect(first,'Escape',protection);assert.ok(record.focused&&record.prevented===(protection==='handled'));assert.ok(await menu.isVisible());protectedKeys.push({target:'menu',...record})}
  await first.evaluate(node=>node.addEventListener('keydown',event=>event.preventDefault(),{capture:true,once:true}));await first.press('Escape');assert.ok(await menu.isVisible())
  const box=await menu.evaluate(node=>{const r=node.getBoundingClientRect();return{x:r.x,y:r.y,right:r.right,bottom:r.bottom,overflow:node.scrollWidth>node.clientWidth+1}});assert.ok(box.x>=0&&box.y>=0&&box.right<=width+1&&box.bottom<=height+1&&!box.overflow,JSON.stringify(box))
  const states=[]
  for(const card of await menu.locator('button').all()){
   await card.focus();await card.scrollIntoViewIfNeeded();const last=await card.evaluate(node=>node===node.parentElement.lastElementChild);await page.keyboard.press(last?'Shift+Tab':'Tab');await page.keyboard.press(last?'Tab':'Shift+Tab')
   const state=await card.evaluate(node=>{const r=node.getBoundingClientRect(),s=getComputedStyle(node);return{label:node.textContent,focused:node===document.activeElement,ring:s.outlineStyle!=='none'&&parseFloat(s.outlineWidth)>=2,hit:node.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2)),font:s.fontFamily,height:r.height}})
   assert.ok(state.focused&&state.ring&&state.hit,JSON.stringify(state));states.push(state)
  }
  const axe=await new AxeBuilder({page}).include('.slides-native-chart-colors').include('.slides-native-chart-gallery').analyze();assert.deepEqual(axe.violations,[])
  await page.screenshot({path:join(output,`chart-schemes-${width}x${height}.png`)})
  await menu.locator('button').last().press('Escape');assert.equal(await menu.isVisible(),false);assert.ok(await toggle.evaluate(node=>node===document.activeElement));assert.deepEqual(await draft(),before)
  cases.push({width,height,box,states,protectedKeys,axe:axe.violations,draftUnchanged:true});await writeFile(join(output,'chart-gallery-layout.json'),JSON.stringify(cases,null,2))
 }
 await page.setViewportSize({width:1440,height:900});if(previous)await page.locator(`[data-ribbon-tab=${previous}]`).click();return cases
}
