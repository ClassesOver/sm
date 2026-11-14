import assert from 'node:assert/strict'
import { writeFile } from 'node:fs/promises'
import { join } from 'node:path'

export async function inspectEditableRanges(page, { directory, phase, layout, draft = async () => [] }) {
  const dialog = page.getByRole('dialog', { name: '允许用户编辑区域', exact: true })
  const values = () => dialog.locator('input').evaluateAll(nodes => nodes.map(n => [n.value, n.disabled]))
  const before = await values(), original = await draft()
  const check = (condition, message) => { if (!condition) layout.failures.push(`${phase}: ${message}`) }
  for (const [width, height] of [[1440,900], [768,720], [320,640], [640,360], [390,320]]) {
    await page.setViewportSize({ width, height }); await page.evaluate(() => document.fonts.ready)
    await dialog.evaluate(n => Promise.all(n.getAnimations({subtree:true}).map(a => a.finished.catch(() => {}))))
    const geometry = await dialog.locator('.modal-card').evaluate(n => {
      const r = n.getBoundingClientRect(), body = n.querySelector('.workbook-editable-ranges-body')
      return { left:r.left, right:r.right, top:r.top, bottom:r.bottom, width:r.width, font:getComputedStyle(n).fontFamily,
        overflow:n.scrollWidth>n.clientWidth+1, header:!!n.querySelector(':scope > header h2'), footer:!!n.querySelector(':scope > form > footer'),
        internalScroll:!!body && getComputedStyle(body).overflowY==='auto',
        named:['region','status','alert'].every(role => !!n.querySelector(`[role=${role}][tabindex="0"][aria-label]`)) }
    })
    check(geometry.left>=0 && geometry.top>=0 && geometry.right<=width+1 && geometry.bottom<=height+1 && !geometry.overflow, `${width}x${height}边界`)
    check(geometry.header && geometry.footer && geometry.internalScroll && geometry.named, `${width}x${height}固定标题/操作与可读区域`)
    if (width===1440) check(geometry.width===600, '桌面窗口宽度600px')
    const controls=dialog.locator('button:visible,input:visible,[tabindex="0"]:visible').filter({ visible:true }), states=[]
    for (const control of await controls.all()) {
      if (await control.isDisabled()) continue
      await control.scrollIntoViewIfNeeded(); await control.focus(); await page.keyboard.press('Tab'); await page.keyboard.press('Shift+Tab')
      const state=await control.evaluate(n => {
        const r=n.getBoundingClientRect(), s=getComputedStyle(n), radius=parseFloat(s.borderTopLeftRadius)||0, inset=Math.max(2,radius*(1-Math.SQRT1_2)+1)
        const points=[[r.x+r.width/2,r.y+r.height/2],[r.x+inset,r.y+inset],[r.right-inset,r.y+inset],[r.x+inset,r.bottom-inset],[r.right-inset,r.bottom-inset]]
        return { label:n.getAttribute('aria-label')||n.textContent, tag:n.tagName, focus:n===document.activeElement,
          ring:s.outlineStyle!=='none' && parseFloat(s.outlineWidth)>=2, height:r.height, lineHeight:parseFloat(s.lineHeight), font:s.fontFamily,
          points:points.map(([x,y]) => ({x,y,hit:n.contains(document.elementFromPoint(x,y))})) }
      })
      check(state.focus && state.ring && state.points.every(p=>p.hit), `${width}x${height} ${state.label}键盘焦点/命中`)
      check(state.font===geometry.font, `${width}x${height} ${state.label}主题字体`)
      if (state.tag==='P') check(state.height>=state.lineHeight+4, `${width}x${height} ${state.label}阅读高度`)
      else check(state.height>=28 && state.height<=32, `${width}x${height} ${state.label}紧凑控件`)
      states.push(state)
    }
    const tabbable=dialog.locator('button:visible:not(:disabled),input:visible:not(:disabled),[tabindex="0"]:visible')
    await tabbable.last().focus(); await page.keyboard.press('Tab')
    check(await tabbable.first().evaluate(n=>n===document.activeElement), `${width}x${height}末端Tab循环`)
    await page.keyboard.press('Shift+Tab'); check(await tabbable.last().evaluate(n=>n===document.activeElement), `${width}x${height}反向Tab循环`)
    const screenshots=[]
    for (const end of ['first','last']) {
      await (end==='first'?tabbable.first():tabbable.last()).scrollIntoViewIfNeeded()
      const file=`${phase}-${width}x${height}-${end}.png`; await page.screenshot({path:join(directory,file)}); screenshots.push(file)
    }
    assert.deepEqual(await values(),before); assert.deepEqual(await draft(),original)
    layout.cases.push({phase,width,height,geometry,states,screenshots})
    await writeFile(join(directory,'layout.json'),JSON.stringify(layout,null,2))
    console.log(JSON.stringify({phase,width,height,failures:layout.failures.length}))
  }
  await page.setViewportSize({width:1440,height:900})
}
