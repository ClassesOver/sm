import assert from 'node:assert/strict'
import { writeFile } from 'node:fs/promises'
import AxeBuilder from '@axe-core/playwright'

export async function inspectWorkbookThemeMenus(page, { output, draft }) {
  const before = await draft(), results = []
  for (const [width, height] of [[1440, 900], [640, 360], [390, 320], [320, 640]]) {
    await page.setViewportSize({ width, height })
    for (const id of ['theme', 'theme-colors', 'theme-fonts']) {
      const control = page.locator(`[data-ribbon-menu="${id}"]`)
      // 通过Tab进入目标，包含功能区的真实水平滚动，而非直接改scrollLeft。
      await control.focus(); await page.keyboard.press('Shift+Tab'); await page.keyboard.press('Tab')
      const state = await control.evaluate(node => {
        const rect = node.getBoundingClientRect(), style = getComputedStyle(node)
        const center = document.elementFromPoint(rect.x + rect.width / 2, rect.y + rect.height / 2)
        const panel = node.closest('[role=tabpanel]').getBoundingClientRect()
        return { label: node.getAttribute('aria-label'), focused: node === document.activeElement, hit: node.contains(center), width: rect.width, height: rect.height, top: rect.top, bottom: rect.bottom,
          within: rect.left >= Math.max(0, panel.left) && rect.right <= Math.min(innerWidth, panel.right) + 1, outline: parseFloat(style.outlineWidth), font: style.fontFamily,
          options: [...node.options].map(option => ({ value: option.value, label: option.textContent })) }
      })
      assert.ok(state.focused && state.hit && state.within && state.top >= 0 && state.bottom <= height + 1, JSON.stringify(state))
      assert.ok(state.width >= 100 && state.height >= 28 && state.outline >= 2, JSON.stringify(state))
      assert.ok(state.options.length > 5 && state.options.every(option => option.label))
      await control.press('Alt+ArrowDown'); await page.keyboard.press('Escape')
      assert.equal(await control.evaluate(node => node === document.activeElement), true)
      assert.deepEqual(await draft(), before)
      results.push({ id, width, height, geometry: state })
    }
    const accessibility = await new AxeBuilder({ page }).include('.workbook-ribbon').analyze()
    assert.deepEqual(accessibility.violations, [])
    results.at(-1).accessibility = { violations: [] }
    await page.screenshot({ path: `${output}/menus-${width}x${height}.png` })
    await writeFile(`${output}/layout.json`, JSON.stringify({ results }, null, 2))
  }
  await page.setViewportSize({ width: 1440, height: 1100 })
  return results
}
