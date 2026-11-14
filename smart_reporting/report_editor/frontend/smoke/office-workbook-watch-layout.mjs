import assert from 'node:assert/strict'
import { writeFile } from 'node:fs/promises'
import { join } from 'node:path'

// 检查真实宿主的监视表格；不创建替代窗口、不改底稿。
export async function inspectWatchWindow(page, { output, phase, open, viewports }) {
  const evidence = { phase, cases: [], failures: [] }
  const panel = page.locator('[data-watch-window]')
  const draft = () => page.evaluate(() => ({ ...localStorage }))
  const before = await draft()
  for (const viewport of viewports.split(',')) {
    const [width, height] = viewport.split('x').map(Number)
    await page.setViewportSize({ width, height })
    const check = (ok, message) => { if (!ok) evidence.failures.push(`${phase} ${viewport}: ${message}`) }
    const geometry = await panel.evaluate(node => {
      const r = node.getBoundingClientRect(), s = getComputedStyle(node), header = node.querySelector('header'), hr = header.getBoundingClientRect(), hs = getComputedStyle(header)
      const scroll = node.querySelector('.watch-scroll'), table = node.querySelector('table')
      return { x: r.x, y: r.y, right: r.right, bottom: r.bottom, width: r.width, height: r.height,
        font: s.fontFamily, radius: parseFloat(s.borderRadius), overflow: node.scrollWidth > node.clientWidth + 1,
        header: { height: hr.height, background: hs.backgroundColor, color: hs.color },
        scroll: { height: scroll.clientHeight, width: scroll.clientWidth, scrollHeight: scroll.scrollHeight, scrollWidth: scroll.scrollWidth, tabindex: scroll.tabIndex },
        table: { headers: [...table.querySelectorAll('th')].map(th => ({ text: th.textContent, scope: th.scope })), text: table.textContent } }
    })
    check(geometry.x >= 0 && geometry.y >= 0 && geometry.right <= width && geometry.bottom <= height && !geometry.overflow, '窗口超出视口或横向溢出')
    check(geometry.font.includes('Noto Sans') && geometry.radius <= 6, '字体或圆角未统一Office主题')
    check(geometry.header.height >= 40 && geometry.header.height <= 48 && geometry.header.background !== 'rgb(31, 90, 168)', '标题仍为旧蓝色工具栏或高度异常')
    check(geometry.scroll.height >= 48 && geometry.scroll.tabindex === 0, '表格不可键盘阅读或没有可用高度')
    check(geometry.table.headers.every(th => th.scope === 'col'), '表头缺少列语义')
    if (width > 900) check(geometry.width >= 560 && geometry.width <= 680, '桌面窗口不足以显示五列')
    const states = []
    for (const control of await panel.locator('button:enabled,.watch-scroll').all()) {
      await control.focus(); await page.keyboard.press('Tab'); await page.keyboard.press('Shift+Tab')
      await control.evaluate(node => node.scrollIntoView({ block: 'nearest', inline: 'nearest', behavior: 'instant' }))
      const state = await control.evaluate(node => {
        const r = node.getBoundingClientRect(), s = getComputedStyle(node), hit = document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2)
        return { label: node.getAttribute('aria-label') || node.textContent, focused: node === document.activeElement, hit: node.contains(hit),
          ring: s.outlineStyle !== 'none' && parseFloat(s.outlineWidth) >= 2,
          font: s.fontFamily, radius: parseFloat(s.borderRadius), rect: { x: r.x, y: r.y, width: r.width, height: r.height } }
      })
      check(state.focused && state.hit && state.ring, `${state.label.slice(0, 40)}未聚焦、中心被遮挡或无焦点环`)
      check(state.font.includes('Noto Sans') && state.radius <= 6, '按钮/表格区域未使用主题样式')
      check(state.rect.height >= 28 && state.rect.x >= -1 && state.rect.x + state.rect.width <= width + 1 && state.rect.y >= -1 && state.rect.y + state.rect.height <= height + 1, '控件尺寸不足或超出视口')
      if(state.label.startsWith('删除监视'))check(state.rect.width>=44&&state.rect.height<=36,'删除按钮文字折行或尺寸不紧凑')
      states.push(state)
    }
    const scroll = panel.locator('.watch-scroll')
    await scroll.focus()
    const scrollChecks = {}
    if (geometry.scroll.scrollHeight > geometry.scroll.height + 1) {
      await page.keyboard.press('End')
      await page.waitForFunction(node => node.scrollTop + node.clientHeight >= node.scrollHeight - 2, await scroll.elementHandle(), { timeout: 3000 }).catch(() => check(false, 'End未到表尾'))
      scrollChecks.afterEnd = await scroll.evaluate(node => node.scrollTop)
      await page.screenshot({ path: join(output, `watch-${phase}-${viewport}-end.png`) })
      await page.keyboard.press('Home')
      await page.waitForFunction(node => node.scrollTop <= 1, await scroll.elementHandle(), { timeout: 3000 }).catch(() => check(false, 'Home未回表首'))
      scrollChecks.afterHome = await scroll.evaluate(node => node.scrollTop)
    }
    if (geometry.scroll.scrollWidth > geometry.scroll.width + 1) {
      scrollChecks.beforeRight=await scroll.evaluate(node=>{node.scrollTo({left:0,behavior:'instant'});return node.scrollLeft})
      check(scrollChecks.beforeRight===0,'横向按键检查前未回到表格左侧')
      await page.keyboard.press('ArrowRight')
      const movement=await scroll.evaluate(async node=>{
        const deadline=performance.now()+3000;let previous=-1,stable=0
        while(performance.now()<deadline){await new Promise(requestAnimationFrame);const left=node.scrollLeft;stable=left===previous&&left>0?stable+1:0;previous=left;if(stable>=3)return {left,settled:true}}
        return {left:node.scrollLeft,settled:false}
      })
      check(movement.settled&&movement.left>0,'键盘无法从左侧向右滚动')
      scrollChecks.afterRight=movement.left;scrollChecks.horizontalSettled=movement.settled
      await scroll.evaluate(node=>node.scrollTo({left:0,behavior:'instant'}))
    }
    await page.screenshot({ path: join(output, `watch-${phase}-${viewport}.png`) })
    await page.keyboard.press('Escape')
    const closed = await panel.count() === 0
    check(closed, 'Escape未关闭窗口')
    const entry = page.locator('[data-ribbon-command="watch-window"]')
    check(await entry.evaluate(node => node === document.activeElement), '关闭后未返回监视入口')
    if (!closed) await panel.locator('[data-watch-close]').click()
    await open()
    check(await panel.locator('[data-watch-add]').evaluate(node => node === document.activeElement), '重开未聚焦添加监视')
    evidence.cases.push({ width, height, geometry, states, scrollChecks })
    await writeFile(join(output, `watch-${phase}-layout.json`), JSON.stringify(evidence, null, 2))
    assert.deepEqual(await draft(), before)
  }
  await page.setViewportSize({ width: 1500, height: 1100 })
  await page.locator('[data-ribbon-tab="Home"]').click()
  await panel.locator('[data-watch-close]').click();await panel.waitFor({state:'detached'})
  evidence.closeAfterTabSwitch=await page.locator('[data-ribbon-tab="Home"]').evaluate(node=>node===document.activeElement)
  if(!evidence.closeAfterTabSwitch)evidence.failures.push(`${phase}: 切换Ribbon后关闭未返回当前标签`)
  await open();assert.deepEqual(await draft(),before)
  await writeFile(join(output, `watch-${phase}-layout.json`), JSON.stringify(evidence, null, 2))
  return evidence
}
