import assert from 'node:assert/strict'
import {writeFile} from 'node:fs/promises'
import {join} from 'node:path'

export async function inspectDocxFind(page,{output,editingEnabled,draft,snapshot}){
 const evidence={cases:[],failures:[]},before=await snapshot(),pending=await draft(),panel=page.locator('.docx-find-replace')
 const check=(ok,label)=>{if(!ok)evidence.failures.push(label)}
 for(const size of ['1440x900','320x640','640x360','390x320','1440x360']){
  const [width,height]=size.split('x').map(Number);await page.setViewportSize({width,height})
  for(const mode of ['find','replace']){
   const label=`${editingEnabled}/${size}/${mode}`
   await page.locator('[data-tab-id=home]').click();await page.locator(`[data-action="${mode}"]`).click()
   await panel.locator('[data-find-query]').fill('cat')
   check(await panel.locator('.find-result').count()===13,`${label}: 匹配数量错误`)
   const replacementLocked=await panel.locator('[data-find-replacement]').isDisabled(),actionsLocked=await panel.locator('[data-find-action=replace],[data-find-action=replace-all]').evaluateAll(nodes=>nodes.every(node=>node.disabled))
   check(replacementLocked===!editingEnabled&&actionsLocked===!editingEnabled,`${label}: 替换锁定状态错误`)
   const geometry=await panel.evaluate(node=>{const r=node.getBoundingClientRect();return {x:r.x,y:r.y,right:r.right,bottom:r.bottom,width:r.width,height:r.height,
    overflow:node.scrollWidth>node.clientWidth+1,font:getComputedStyle(node).fontFamily,
    tabs:[...node.querySelectorAll('[data-find-tab]')].map(tab=>({role:tab.getAttribute('role'),selected:tab.getAttribute('aria-selected')})),
    labels:[...node.querySelectorAll('.find-row > label')].map(label=>label.childNodes[0]?.textContent),
    results:{tabindex:node.querySelector('.find-results').tabIndex,height:node.querySelector('.find-results').clientHeight,scrollHeight:node.querySelector('.find-results').scrollHeight}}})
   check(!geometry.overflow&&geometry.x>=0&&geometry.right<=width+1,`${label}: 横向溢出`)
   check(geometry.font.includes('Noto Sans'),`${label}: 字体不是主题字体`)
   check(geometry.labels.length===2,`${label}: 缺少可见字段标签`)
   check(geometry.tabs.every(tab=>tab.role==='tab')&&geometry.tabs.filter(tab=>tab.selected==='true').length===1,`${label}: 标签选中状态不可辨识`)
   const controls=[]
   for(const control of await panel.locator('button:enabled,input:enabled,select:enabled').all()){
    if(!await control.isVisible()||await control.evaluate(node=>node.tabIndex<0))continue
    await control.focus();await page.keyboard.press('Tab');await page.keyboard.press('Shift+Tab');await control.scrollIntoViewIfNeeded()
    const state=await control.evaluate(node=>{const r=node.getBoundingClientRect(),s=getComputedStyle(node);return {label:node.getAttribute('aria-label')||node.textContent,type:node.type,
     focused:node===document.activeElement,ring:s.outlineStyle!=='none'&&parseFloat(s.outlineWidth)>=2,font:s.fontFamily,height:r.height,
     hit:node.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2)),exposed:[[r.x+3,r.y+3],[r.right-3,r.y+3],[r.x+3,r.bottom-3],[r.right-3,r.bottom-3]].every(([x,y])=>node.contains(document.elementFromPoint(x,y)))}})
    check(state.focused&&state.ring&&state.hit&&state.exposed,`${label}: ${state.label}焦点或完整命中失败`)
    if(state.type!=='checkbox'&&!await control.evaluate(node=>node.classList.contains('find-result')))check(state.height>=26&&state.height<=32,`${label}: ${state.label}不是紧凑控件`)
    controls.push(state)
   }
   const tabs=panel.locator('[data-find-tab]'),tabKeys=[]
   await tabs.first().focus()
   for(const [key,index]of [['End',1],['Home',0],['ArrowRight',1],['ArrowLeft',0]]){
    await page.keyboard.press(key);const selected=await tabs.nth(index).evaluate(node=>node===document.activeElement&&node.getAttribute('aria-selected')==='true');check(selected,`${label}: ${key}标签键盘切换失败`);tabKeys.push({key,selected})
   }
   await panel.locator(`[data-find-tab="${mode}"]`).click()
   const result=panel.locator('.find-result').nth(2);await result.focus();await page.keyboard.press('Enter')
   const resultFocused=await panel.locator('.find-result.on').evaluate(node=>node===document.activeElement)
   check(resultFocused,`${label}: 结果激活后焦点丢失`)
   const last=panel.locator('.find-result').last();await last.focus();await last.scrollIntoViewIfNeeded();await page.screenshot({path:join(output,`find-results-${editingEnabled}-${mode}-${size}.png`)})
   const query=panel.locator('[data-find-query]');await query.focus();await query.press('Enter');await query.press('Shift+Enter');const queryFocused=await query.evaluate(node=>node===document.activeElement);check(queryFocused,`${label}: 输入框导航后焦点丢失`);const queryResultVisible=await panel.locator('.find-result.on').evaluate(node=>{const r=node.getBoundingClientRect(),list=node.parentElement.getBoundingClientRect();return r.top>=list.top-1&&r.bottom<=list.bottom+1});check(queryResultVisible,`${label}: 输入框导航未滚动到当前结果`);await query.scrollIntoViewIfNeeded()
   await page.screenshot({path:join(output,`find-${editingEnabled}-${mode}-${size}.png`)})
   assert.deepEqual(await snapshot(),before);assert.deepEqual(await draft(),pending)
   evidence.cases.push({editingEnabled,width,height,mode,geometry,controls,resultFocused,tabKeys,queryFocused,queryResultVisible,replacementLocked,actionsLocked})
   await writeFile(join(output,`find-layout-${editingEnabled}.json`),JSON.stringify(evidence,null,2))
  }
 }
 await page.setViewportSize({width:1440,height:900})
 return evidence
}
