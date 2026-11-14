import assert from 'node:assert/strict'
import {writeFile} from 'node:fs/promises'
import {join} from 'node:path'
import AxeBuilder from '@axe-core/playwright'

// 真实宿主的阅读/键盘检查；颜色浏览只用Escape退出，不产生草稿或历史。
export async function inspectShapeFormat(page,{output,targets,draft}){
 const evidence={cases:[],palettes:[],failures:[]},before=await draft(),pane=page.locator('.slides-shape-format-pane')
 const check=(ok,label)=>{if(!ok)evidence.failures.push(label)}
 for(const target of targets){
  await page.locator('#object-select').selectOption(target.id)
  for(const viewport of ['1440x900','320x640','640x360','390x320','1440x360']){
   const [width,height]=viewport.split('x').map(Number),label=`${target.name}/${viewport}`;await page.setViewportSize({width,height});await page.evaluate(()=>document.fonts.ready)
   const geometry=await pane.evaluate(node=>{const r=node.getBoundingClientRect();return{x:r.x,right:r.right,width:r.width,overflow:node.scrollWidth>node.clientWidth+1,font:getComputedStyle(node).fontFamily,groups:[...node.querySelectorAll('fieldset>legend')].map(n=>n.textContent),workspace:document.querySelector('.slides-workspace').getBoundingClientRect().height}})
   check(!geometry.overflow&&geometry.x>=0&&geometry.right<=width+1,`${label}: 横向溢出`);check(geometry.groups.join(',')==='填充,轮廓',`${label}: 缺少原生分组`);check(geometry.font.includes('Noto Sans')&&geometry.workspace>=90,`${label}: 字体或工作区高度错误`)
   const states=[]
   for(const control of await pane.locator('input,button').all()){
    const radio=await control.evaluate(node=>node.type==='radio'),disabled=await control.isDisabled(),tabbable=!radio||await control.isChecked()
    if(!disabled){await control.focus();if(tabbable){await page.keyboard.press('Tab');await page.keyboard.press('Shift+Tab')}}
    await control.scrollIntoViewIfNeeded()
    const state=await control.evaluate(node=>{const r=node.getBoundingClientRect(),s=getComputedStyle(node);return{label:node.getAttribute('aria-label')||node.closest('label')?.textContent||node.textContent,type:node.type,disabled:node.disabled,focused:node===document.activeElement,font:s.fontFamily,height:r.height,width:r.width,ring:s.outlineStyle!=='none'&&parseFloat(s.outlineWidth)>=2,hit:node.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2)),exposed:[[r.x+3,r.y+3],[r.right-3,r.y+3],[r.x+3,r.bottom-3],[r.right-3,r.bottom-3]].every(([x,y])=>node.contains(document.elementFromPoint(x,y)))}})
    check(state.hit&&state.exposed&&(disabled||state.focused&&state.ring),`${label}: ${state.label}命中、边缘或焦点失败`)
    if(!radio)check(state.height>=26&&state.height<=32&&state.font.includes('Noto Sans'),`${label}: ${state.label}未采用紧凑主题控件`)
    states.push({...state,tabbable})
   }
   const locks=await pane.evaluate(node=>({fill:node.querySelector('[data-chart-format-well="shape-fill"]').disabled,stroke:node.querySelector('[data-chart-format-well="shape-stroke"]').disabled,width:node.querySelector('[data-shape-width]').disabled}))
   check(locks.fill===!target.fillEditable&&locks.stroke===!target.strokeEditable&&locks.width===!target.strokeEditable,`${label}: 来源能力锁定错误`)
   const protectedKeys=[];let errorState
   if(target.strokeEditable){
    const field=pane.locator('[data-shape-width]'),initial=await field.inputValue();await field.fill('0');await field.press('Enter')
    const invalid=await field.getAttribute('aria-invalid')==='true';check(invalid,`${label}: 非法粗细缺少错误状态`)
    await field.focus()
    const protectedState=await field.evaluate(node=>{
     const records=[]
     for(const key of ['Enter','Escape'])for(const protection of ['composition','legacy','handled']){
      const event=new KeyboardEvent('keydown',{key,bubbles:true,cancelable:true,isComposing:protection==='composition',keyCode:protection==='legacy'?229:0});if(protection==='handled')event.preventDefault();node.dispatchEvent(event)
      records.push({key,protection,value:node.value,focused:node===document.activeElement,prevented:event.defaultPrevented})
     }
     return records
    })
    for(const record of protectedState){check(record.value==='0'&&record.focused&&record.prevented===(record.protection==='handled'),`${label}: 粗细保护 ${JSON.stringify(record)}`);protectedKeys.push(record)}
    const status=pane.locator('[role=status]');await status.focus();await status.scrollIntoViewIfNeeded();await page.keyboard.press('Tab');await page.keyboard.press('Shift+Tab')
    errorState=await status.evaluate(node=>{const r=node.getBoundingClientRect(),s=getComputedStyle(node),input=node.closest('section').querySelector('[data-shape-width]'),field=getComputedStyle(input);return{id:node.id,description:input.getAttribute('aria-describedby'),label:node.getAttribute('aria-label'),text:node.textContent,focused:node===document.activeElement,ring:s.outlineStyle!=='none'&&parseFloat(s.outlineWidth)>=2,hit:node.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2)),height:r.height,lineHeight:parseFloat(s.lineHeight),color:s.color,border:field.borderTopColor}})
    check(errorState.id&&errorState.id===errorState.description&&errorState.label==='形状格式状态',`${label}: 错误说明没有关联输入`);check(errorState.focused&&errorState.ring&&errorState.hit&&errorState.height>=errorState.lineHeight,`${label}: 错误说明不可聚焦阅读`);check(errorState.color===errorState.border,`${label}: 错误轮廓被主题覆盖 ${JSON.stringify(errorState)}`)
    const errorAxe=await new AxeBuilder({page}).include('.slides-shape-format-pane').analyze();check(errorAxe.violations.length===0,`${label}: 错误状态axe ${JSON.stringify(errorAxe.violations)}`);errorState.axe=errorAxe.violations
    await page.screenshot({path:join(output,`shape-error-${viewport}.png`)})
    await field.press('Escape');check(await field.inputValue()===initial,`${label}: 非法输入无法撤回`);await field.fill('4')
    await field.evaluate(node=>node.addEventListener('keydown',event=>event.preventDefault(),{capture:true,once:true}));await field.press('Enter');check(await field.inputValue()==='4',`${label}: 已消费Enter被提交或回填`)
    await field.press('Escape');await page.waitForTimeout(250);check(await field.inputValue()===initial,`${label}: Escape后旧粗细仍被提交`)
   }
   for(const field of ['fill','stroke']){
    const well=pane.locator(`[data-chart-format-well="shape-${field}"]`);if(await well.isDisabled())continue
    await well.focus();await well.scrollIntoViewIfNeeded();await well.press('ArrowDown');const popup=page.locator('[data-chart-format-palette]');await popup.waitFor()
    const box=await popup.evaluate(node=>{const r=node.getBoundingClientRect();return{x:r.x,y:r.y,right:r.right,bottom:r.bottom}})
    check(box.x>=0&&box.y>=0&&box.right<=width+1&&box.bottom<=height+1,`${label}: ${field}色板越界`)
    const cells=[]
    // 在70色表中实际连续按方向键，包含跨行与尾部回绕。
    for(let index=0;index<70;index++){
     const active=popup.locator('[role=gridcell]:focus');check(await active.count()===1,`${label}: ${field}色板没有键盘焦点`);if(!await active.count())break
     await active.scrollIntoViewIfNeeded();const state=await active.evaluate(node=>{const r=node.getBoundingClientRect(),s=getComputedStyle(node);return{pos:node.dataset.pos,ring:s.outlineStyle!=='none'&&parseFloat(s.outlineWidth)>=2,exposed:[[r.x+3,r.y+3],[r.right-3,r.y+3],[r.x+3,r.bottom-3],[r.right-3,r.bottom-3]].every(([x,y])=>node.contains(document.elementFromPoint(x,y)))}})
     check(state.ring&&state.exposed,`${label}: ${field}/${state.pos}色块焦点或边缘错误`);cells.push(state);await page.keyboard.press('ArrowRight')
    }
    check(new Set(cells.map(c=>c.pos)).size===70,`${label}: ${field}没有遍历70色`)
    await page.screenshot({path:join(output,`shape-palette-${target.name.replaceAll(' ','-')}-${field}-${viewport}.png`)})
    await page.keyboard.press('Escape');check(await well.evaluate(node=>node===document.activeElement)&&await popup.count()===0,`${label}: 色板Escape未恢复入口`)
    evidence.palettes.push({target:target.name,field,width,height,box,cells,escapeRestored:true})
   }
   const screenshots=[]
   for(const [phase,control]of [['first',pane.locator('input').first()],['last',pane.locator('[data-shape-width]')]]){
    if(await control.isEnabled())await control.focus();await control.scrollIntoViewIfNeeded();const file=`shape-format-${target.name.replaceAll(' ','-')}-${viewport}-${phase}.png`;await page.screenshot({path:join(output,file)});screenshots.push(file)
   }
   const axe=await new AxeBuilder({page}).include('.slides-shape-format-pane').analyze();check(axe.violations.length===0,`${label}: axe ${JSON.stringify(axe.violations)}`)
   assert.deepEqual(await draft(),before);evidence.cases.push({target:target.name,width,height,geometry,locks,states,screenshots,protectedKeys,errorState,axe:axe.violations});await writeFile(join(output,'shape-format-layout.json'),JSON.stringify(evidence,null,2))
  }
 }
 await page.setViewportSize({width:1440,height:1000});return evidence
}
