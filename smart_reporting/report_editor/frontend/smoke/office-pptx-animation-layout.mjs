import assert from 'node:assert/strict'
import { mkdir, writeFile } from 'node:fs/promises'
import { resolve } from 'node:path'

export const animationLongName = '来源对象完整名称：季度经营分析、收入构成及同比变化😀 '.repeat(14)

// Adds via the actual ribbon and undoes every layout-only edit before native-save assertions.
export async function inspectPptxAnimationLayout(page, { output, viewports }) {
  await mkdir(output, { recursive: true })
  const draft = () => page.evaluate(() => JSON.parse(Object.entries(localStorage).find(([key]) => key.includes('fixture-pptx'))?.[1] ?? '{"operations":[]}').operations)
  const original = await draft(), evidence = { cases: [], failures: [] }
  const command = id => page.locator(`[data-command="${id}"]`)
  const pane = page.locator('.slides-animation-pane'), rows = () => pane.locator('.animation-pane-row')
  await page.locator('[data-ribbon-tab="animations"]').click()
  await command('toggleAnimationPane').click()
  const originalCount = await rows().count()
  for (let i = 0; i < 24; i++) await command('addAnimation').click()
  assert.equal(await rows().count(), originalCount + 24)
  const baseline = await draft()
  for (const viewport of viewports.split(',')) {
    const [width, height] = viewport.split('x').map(Number)
    await page.setViewportSize({ width, height })
    const check = (ok, message) => { if (!ok) evidence.failures.push(`${viewport}: ${message}`) }
    await pane.scrollIntoViewIfNeeded()
    const close = pane.getByRole('button', { name: '关闭动画窗格', exact: true })
    check(await close.count() === 1, '缺少标题关闭')
    const geometry = await pane.evaluate(node => {
      const r = node.getBoundingClientRect(), list = node.querySelector('ol'), l = list.getBoundingClientRect()
      return { x: r.x, right: r.right, width: r.width, viewportWidth: innerWidth, font: getComputedStyle(node).fontFamily,
        list: { height: l.height, scrollHeight: list.scrollHeight, clientHeight: list.clientHeight, overflow: getComputedStyle(list).overflowY },
        horizontalOverflow: node.scrollWidth > node.clientWidth + 1,
        actions: [...node.querySelectorAll('.animation-pane-actions button')].map(control => { const c = control.getBoundingClientRect(); return { width: c.width, height: c.height, font: getComputedStyle(control).fontFamily } }) }
    })
    check(geometry.x >= 0 && geometry.right <= width + 1 && !geometry.horizontalOverflow, '窗格横向溢出')
    check(geometry.font.includes('Noto Sans') && geometry.actions.every(c => c.font.includes('Noto Sans')), '字体未继承Office主题')
    check(geometry.actions.every(c => c.width >= 24 && c.width <= 30 && c.height >= 24 && c.height <= 30), '排序按钮尺寸错误')
    check(geometry.list.height <= Math.min(420, height * .48) + 1 && geometry.list.scrollHeight > geometry.list.clientHeight && ['auto','scroll'].includes(geometry.list.overflow), '长列表未限制内部滚动')
    const first = rows().nth(0).locator('.animation-pane-select')
    check((await first.textContent()).includes(animationLongName), '完整对象名被截断')
    check((await first.getAttribute('title') ?? '').includes(animationLongName), '完整对象名未进入提示')
    const states = []
    for (const index of [0, originalCount + 12, originalCount + 23]) {
      let select = rows().nth(index).locator('.animation-pane-select')
      await select.focus(); await page.keyboard.press('Tab'); await page.keyboard.press('Shift+Tab')
      await select.evaluate(node => node.scrollIntoView({ block: 'center', inline: 'nearest', behavior: 'instant' }))
      const state = await select.evaluate(node => {
        const r = node.getBoundingClientRect(), s = getComputedStyle(node)
        return { index: node.closest('[data-animation-row]').dataset.animationRow, hit: node.contains(document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2)), focused: node === document.activeElement, ring: s.outlineStyle !== 'none' && parseFloat(s.outlineWidth) >= 2 }
      })
      check(state.hit && state.focused && state.ring, `第${index + 1}条动画不可达或无焦点环`)
      const longRow = await select.evaluate(node => node.scrollHeight > node.clientHeight + 1)
      if (longRow) {
        await select.press('End')
        check(await select.evaluate(node => node.scrollTop + node.clientHeight >= node.scrollHeight - 1), '长对象名End未滚动到底')
        await select.press('Home')
        check(await select.evaluate(node => node.scrollTop <= 1), '长对象名Home未返回开头')
      }
      await select.press('Enter')
      select = rows().nth(index).locator('.animation-pane-select')
      check(await select.evaluate(node => node === document.activeElement), '选中动画后焦点丢失')
      check(await select.getAttribute('aria-pressed') === 'true', '选中态错误')
      await select.press('Enter')
      check(await select.getAttribute('aria-pressed') === 'false', '取消选中失败')
      states.push({ ...state, longRow })
    }
    const list = pane.locator('ol')
    await list.evaluate(node => { node.scrollTop = node.scrollHeight })
    const scrollBefore = await list.evaluate(node => node.scrollTop)
    const last = rows().last().locator('.animation-pane-select')
    await last.click()
    check(await list.evaluate(node => node.scrollTop) >= scrollBefore - 2, '重绘将列表滚动重置')
    await rows().last().locator('.animation-pane-select').click()
    await page.screenshot({ path: resolve(output, `animation-${viewport}-bottom.png`) })
    const move = rows().nth(1).getByRole('button', { name: '上移：第 2 条动画', exact: true })
    await move.click()
    check(await rows().first().locator('.animation-pane-select').evaluate(node => node === document.activeElement), '移动到边界后焦点未跟随')
    await page.locator('[data-source-action="onUndo"]').click(); assert.deepEqual(await draft(), baseline)
    await rows().last().getByRole('button', { name: `删除：第 ${originalCount + 24} 条动画`, exact: true }).click()
    check(await rows().last().locator('.animation-pane-select').evaluate(node => node === document.activeElement), '删除后焦点未返回存活行')
    await page.locator('[data-source-action="onUndo"]').click(); assert.deepEqual(await draft(), baseline)
    await list.evaluate(node => { node.scrollTop = 0 })
    await pane.scrollIntoViewIfNeeded()
    await page.screenshot({ path: resolve(output, `animation-${viewport}.png`) })
    let closeState
    if (await close.count()) {
      await close.focus(); await page.keyboard.press('Tab'); await page.keyboard.press('Shift+Tab')
      await close.scrollIntoViewIfNeeded()
      closeState = await close.evaluate(node => {
        const r = node.getBoundingClientRect(), s = getComputedStyle(node)
        return { width: r.width, height: r.height, focused: node === document.activeElement, hit: node.contains(document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2)), ring: s.outlineStyle !== 'none' && parseFloat(s.outlineWidth) >= 2 }
      })
      check(closeState.width === 28 && closeState.height === 28 && closeState.focused && closeState.hit && closeState.ring, '标题关闭尺寸、命中或键盘焦点错误')
      await close.click()
    }
    else await command('toggleAnimationPane').click()
    check(await pane.isHidden(), '关闭后窗格仍可见')
    check(await command('toggleAnimationPane').getAttribute('aria-pressed') === 'false', '入口选中态未重置')
    check(await command('toggleAnimationPane').evaluate(node => node === document.activeElement), '关闭未恢复入口焦点')
    assert.deepEqual(await draft(), baseline)
    await command('toggleAnimationPane').click()
    evidence.cases.push({ width, height, geometry, states, scrollBefore, closeState })
  }
  // Each viewport made two edits and undid them; the surviving history is the 24 additions.
  for (let i = 0; i < 24; i++) await page.locator('[data-source-action="onUndo"]').click()
  assert.deepEqual(await draft(), original)
  assert.equal(await rows().count(), originalCount)
  for (let i = 0; i < originalCount; i++) await rows().first().locator('button[title="删除"]').click()
  assert.equal(await rows().count(), 0)
  const close = pane.getByRole('button', { name: '关闭动画窗格', exact: true })
  evidence.empty = { focusedClose: await close.evaluate(node => node === document.activeElement), text: await pane.locator('.animation-pane-empty').textContent() }
  assert.equal(evidence.empty.focusedClose, true)
  assert.ok(evidence.empty.text.includes('本页还没有动画'))
  await page.screenshot({ path: resolve(output, 'animation-empty.png') })
  for (let i = 0; i < originalCount; i++) await page.locator('[data-source-action="onUndo"]').click()
  assert.deepEqual(await draft(), original)
  assert.equal(await rows().count(), originalCount)
  await command('toggleAnimationPane').click()
  await page.setViewportSize({ width: 1440, height: 1000 })
  await writeFile(resolve(output, 'animation-layout-evidence.json'), JSON.stringify(evidence, null, 2))
  assert.deepEqual(evidence.failures, [], JSON.stringify(evidence.failures))
  return evidence
}
