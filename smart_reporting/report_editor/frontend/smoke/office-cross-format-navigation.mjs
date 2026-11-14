import assert from 'node:assert/strict'
import { writeFile } from 'node:fs/promises'
import { join } from 'node:path'
import AxeBuilder from '@axe-core/playwright'

const viewports = [[1440,900],[320,640],[640,360],[390,320]]
async function protectedKey(control, key, protection, extra = {}) {
  return control.evaluate((node, { key, protection, extra }) => {
    const event = new KeyboardEvent('keydown', { key, bubbles:true, cancelable:true, isComposing:protection === 'composition', keyCode:protection === 'legacy' ? 229 : 0, ...extra })
    if (protection === 'handled') event.preventDefault()
    node.dispatchEvent(event)
    return { focused:node === document.activeElement, connected:node.isConnected, prevented:event.defaultPrevented }
  }, { key, protection, extra })
}
async function focusState(control, page, backward = false) {
  await control.focus(); await control.scrollIntoViewIfNeeded()
  // 编辑正文的 Tab/Shift+Tab 有缩进语义；导航末项从前一控件往返，不把正文当作普通按钮。
  await page.keyboard.press(backward ? 'Shift+Tab' : 'Tab'); await page.keyboard.press(backward ? 'Tab' : 'Shift+Tab')
  return control.evaluate(node => {
    const r=node.getBoundingClientRect(), s=getComputedStyle(node)
    return { label:node.getAttribute('aria-label') || node.textContent, focused:node === document.activeElement, ring:s.outlineStyle !== 'none' && parseFloat(s.outlineWidth) >= 2, hit:node.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2)), x:r.x, y:r.y, right:r.right, bottom:r.bottom }
  })
}

// 真实 DOCX 宿主；不写入正文或草稿。事件保护是合成协议检查，不模拟系统候选窗。
export async function inspectDocxNavigation(page, { output, phase }) {
  const panel=page.locator('[data-docx-navigation]'), query=panel.locator('[data-navigation-query]'), count=panel.locator('[data-navigation-search-count]'), cases=[]
  const selected=()=>page.getByRole('textbox',{name:'Word 文档编辑区'}).evaluate(node=>({from:node.editor.state.selection.from,to:node.editor.state.selection.to}))
  for(const [width,height] of viewports){
    await page.setViewportSize({width,height}); await page.evaluate(()=>document.fonts.ready)
    await query.fill('cat'); await query.focus(); const before=await selected(), protections=[]
    for(const key of ['Enter','Escape'])for(const protection of ['composition','legacy','handled'])for(const shiftKey of [false,true]){
      const state=await protectedKey(query,key,protection,{shiftKey}); assert.ok(state.focused&&state.connected); assert.equal(state.prevented,protection==='handled'); assert.equal(await query.inputValue(),'cat'); assert.equal(await count.textContent(),'0/5'); assert.deepEqual(await selected(),before); assert.ok(await panel.isVisible()); protections.push({key,protection,shiftKey,...state})
    }
    await query.evaluate(node=>node.addEventListener('keydown',event=>event.preventDefault(),{capture:true,once:true})); await query.press('Enter'); assert.equal(await count.textContent(),'0/5')
    await query.press('Enter'); assert.equal(await count.textContent(),'1/5'); await query.press('Shift+Enter'); assert.equal(await count.textContent(),'5/5')
    const queryState=await focusState(query,page); assert.ok(queryState.focused&&queryState.ring&&queryState.hit,JSON.stringify(queryState))
    const searchAxe=await new AxeBuilder({page}).include('[data-docx-navigation]').analyze(); assert.deepEqual(searchAxe.violations,[])
    await page.screenshot({path:join(output,`navigation-${phase}-${width}x${height}-search.png`)})
    await panel.locator('[data-navigation-search-action=clear]').click()
    const tab=panel.locator('[data-navigation-tab=headings]'); await tab.focus()
    for(const key of ['ArrowLeft','ArrowRight','Home','End','Escape'])for(const protection of ['composition','legacy','handled']){
      const state=await protectedKey(tab,key,protection); assert.ok(state.focused&&state.connected); assert.equal(await tab.getAttribute('aria-selected'),'true'); assert.ok(await panel.isVisible()); protections.push({target:'tab',key,protection,...state})
    }
    await tab.press('ArrowRight'); assert.equal(await panel.locator('[data-navigation-tab=pages]').getAttribute('aria-selected'),'true'); await page.keyboard.press('ArrowLeft'); assert.equal(await tab.getAttribute('aria-selected'),'true')
    const headings=panel.locator('[data-navigation-heading]'), first=headings.first(), headingCount=await headings.count(); assert.ok(headingCount>=4); await first.focus()
    for(const key of ['ArrowLeft','ArrowRight','ArrowUp','ArrowDown','Home','End','Escape'])for(const protection of ['composition','legacy','handled']){
      const state=await protectedKey(first,key,protection); assert.ok(state.focused&&state.connected); assert.equal(await headings.count(),headingCount); assert.ok(await panel.isVisible()); protections.push({target:'tree',key,protection,...state})
    }
    await first.evaluate(node=>node.addEventListener('keydown',event=>event.preventDefault(),{capture:true,once:true})); await first.press('ArrowDown'); assert.ok(await first.evaluate(node=>node===document.activeElement)); await first.press('ArrowDown'); assert.ok(await headings.nth(1).evaluate(node=>node===document.activeElement))
    const states=[]
    for(const control of await panel.locator('button,input').all())if(await control.isVisible()&&await control.isEnabled()){
      const lastHeading=await control.evaluate(node=>node===[...node.closest('[data-docx-navigation]').querySelectorAll('[data-navigation-heading]')].at(-1))
      const state=await focusState(control,page,lastHeading); assert.ok(state.focused&&state.ring&&state.hit,JSON.stringify(state)); assert.ok(state.x>=0&&state.right<=width+1&&state.y>=0&&state.bottom<=height+1,JSON.stringify(state)); states.push({...state,backwardRoundTrip:lastHeading})
    }
    const treeAxe=await new AxeBuilder({page}).include('[data-docx-navigation]').analyze(); assert.deepEqual(treeAxe.violations,[])
    await page.screenshot({path:join(output,`navigation-${phase}-${width}x${height}-tree.png`)})
    await first.focus(); await first.press('Escape'); assert.equal(await panel.isVisible(),false); await page.locator('[data-action=navigation-toggle]').click(); await query.fill('cat')
    cases.push({phase,width,height,protections,queryState,states,axe:[searchAxe.violations,treeAxe.violations],ordinarySearchAndTreeNavigation:true,escapeClosed:true})
    await writeFile(join(output,`navigation-${phase}.json`),JSON.stringify(cases,null,2))
  }
  await page.setViewportSize({width:1440,height:1000}); return cases
}

// 真实 PDF.js 的页码/搜索行为；只读也应可导航，不能改变原稿操作。
export async function inspectPdfNavigation(page, { output, phase, waitCount, waitActive, pages, ops }) {
  const search=page.getByLabel('搜索 PDF 文字'), count=page.getByLabel('搜索匹配计数'), cases=[], before=await ops()
  for(const [width,height] of viewports){
    await page.setViewportSize({width,height}); await page.evaluate(()=>document.fonts.ready); await page.locator('[data-pdf-ribbon-tab=home]').click()
    await search.fill('cat'); await waitCount('1 / 6'); await search.focus(); const protections=[]
    for(const key of ['Enter','Escape'])for(const protection of ['composition','legacy','handled'])for(const shiftKey of [false,true]){
      const state=await protectedKey(search,key,protection,{shiftKey}); assert.ok(state.focused&&state.connected); assert.equal(state.prevented,protection==='handled'); assert.equal(await search.inputValue(),'cat'); assert.equal(await count.textContent(),'1 / 6'); protections.push({target:'search',key,protection,shiftKey,...state})
    }
    await search.evaluate(node=>node.addEventListener('keydown',event=>event.preventDefault(),{capture:true,once:true})); await search.press('Escape'); assert.equal(await search.inputValue(),'cat'); await search.press('Enter'); await waitCount('2 / 6'); await search.press('Shift+Enter'); await waitCount('1 / 6')
    const states=[await focusState(search,page)]; assert.ok(states[0].focused&&states[0].ring&&states[0].hit,JSON.stringify(states[0]))
    for(const tabName of ['home','view']){
      const tab=page.locator(`[data-pdf-ribbon-tab=${tabName}]`); await tab.click(); await tab.focus()
      for(const key of ['ArrowLeft','ArrowRight','Home','End'])for(const protection of ['composition','legacy','handled']){
        const state=await protectedKey(tab,key,protection);assert.ok(state.focused&&state.connected);assert.equal(state.prevented,protection==='handled');assert.equal(await tab.getAttribute('aria-selected'),'true');protections.push({target:`${tabName}-tab`,key,protection,...state})
      }
      await tab.press('ArrowRight');await page.keyboard.press('ArrowLeft');assert.ok(await tab.evaluate(node=>node===document.activeElement));assert.equal(await tab.getAttribute('aria-selected'),'true')
      for(const protection of ['composition','legacy','handled'])for(const modifier of ['ctrlKey','metaKey']){
        const state=await protectedKey(tab,'f',protection,{[modifier]:true}); assert.ok(state.focused&&state.connected); protections.push({target:tabName,key:'f',modifier,protection,...state})
      }
      const field=page.locator(`[data-pdf-ribbon-panel=${tabName}] .pdf-view-page-input`)
      assert.equal(await field.count(),1); await field.fill('9'); await field.focus()
      for(const protection of ['composition','legacy','handled']){
        const state=await protectedKey(field,'Enter',protection); assert.ok(state.focused&&state.connected); assert.equal(await field.inputValue(),'9'); protections.push({target:`${tabName}-page`,key:'Enter',protection,...state})
      }
      await field.fill('2'); await field.press('Enter'); await waitActive(pages[1].pageId); await field.fill('1'); await field.press('Enter'); await waitActive(pages[0].pageId)
      const state=await focusState(field,page); assert.ok(state.focused&&state.ring&&state.hit,JSON.stringify(state)); states.push({...state,tabName})
    }
    const view=page.locator('[data-pdf-ribbon-tab=view]'); await view.focus(); await view.evaluate(node=>{const consume=event=>{if(event.key.toLowerCase()!=='f')return;event.preventDefault();node.removeEventListener('keydown',consume,true)};node.addEventListener('keydown',consume,true)}); await view.press('Control+f'); assert.ok(await view.evaluate(node=>node===document.activeElement))
    await view.press('Control+f'); assert.ok(await search.evaluate(node=>node===document.activeElement)); await search.press('Escape'); await waitCount(''); assert.ok(await page.locator('.pdf-document-pages').evaluate(node=>node===document.activeElement))
    await search.fill('cat'); await waitCount('1 / 6')
    const axe=await new AxeBuilder({page}).include('.pdf-ribbon').analyze(); assert.deepEqual(axe.violations,[])
    await page.screenshot({path:join(output,`navigation-${phase}-${width}x${height}.png`)})
    assert.deepEqual(await ops(),before); cases.push({phase,width,height,protections,states,axe:axe.violations,ordinarySearchPageAndShortcut:true,draftUnchanged:true})
    await writeFile(join(output,`navigation-${phase}.json`),JSON.stringify(cases,null,2))
  }
  await page.setViewportSize({width:1440,height:1000}); return cases
}
