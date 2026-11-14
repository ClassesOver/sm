import assert from 'node:assert/strict'
import { writeFile } from 'node:fs/promises'
import AxeBuilder from '@axe-core/playwright'

export async function inspectWatermarkDialog(page, { output, open, draft, trigger }) {
  const results = [], before = await draft()
  for (const [width, height] of [[1440, 900], [640, 360], [390, 320], [320, 640]]) {
    await page.setViewportSize({ width, height })
    for (const phase of ['none', 'text', 'error']) {
      await open()
      const dialog = page.locator('.docx-watermark-dialog')
      await dialog.waitFor()
      assert.equal(await dialog.locator('input[name=mode]:checked').evaluate(node => node === document.activeElement), true)
      if (phase !== 'none') await dialog.locator('input[name=mode][value=text]').check()
      if (phase === 'error') {
        await dialog.locator('input[name=text]').fill('')
        await dialog.locator('button[value=ok]').click()
        const error = dialog.getByRole('alert', { name: '水印设置错误' })
        await error.waitFor()
        assert.match(await error.textContent(), /请输入水印文字/)
        // 从前一个字段按真实Tab进入错误说明，确认可阅读及焦点环。
        await dialog.locator('input[name=layout]:checked').focus()
        await page.keyboard.press('Tab')
        assert.equal(await error.evaluate(node => node === document.activeElement), true)
        assert.ok(await error.evaluate(node => parseFloat(getComputedStyle(node).outlineWidth) >= 2))
      }
      const geometry = await dialog.evaluate(node => {
        const box = node.getBoundingClientRect(), header = node.querySelector(':scope > header'), footer = node.querySelector(':scope > footer'), body = node.querySelector('.docx-watermark-body')
        if (!header || !footer || !body) return { missingParts: true }
        const h = header.getBoundingClientRect(), f = footer.getBoundingClientRect(), b = body.getBoundingClientRect()
        const result = { x: box.x, y: box.y, right: box.right, bottom: box.bottom, overflow: node.scrollWidth > node.clientWidth + 1, bodyOverflow: body.scrollWidth > body.clientWidth + 1, scrollable: body.scrollHeight > body.clientHeight, font: getComputedStyle(node).fontFamily, headerTop: h.top, footerBottom: f.bottom, bodyTop: b.top, bodyBottom: b.bottom }
        body.scrollTop = body.scrollHeight
        result.headerMoved = header.getBoundingClientRect().top !== h.top
        result.footerMoved = footer.getBoundingClientRect().bottom !== f.bottom
        return result
      })
      assert.equal(geometry.missingParts, undefined)
      assert.ok(geometry.x >= 0 && geometry.y >= 0 && geometry.right <= width + 1 && geometry.bottom <= height + 1, JSON.stringify(geometry))
      assert.equal(geometry.overflow, false); assert.equal(geometry.bodyOverflow, false)
      assert.equal(geometry.headerMoved, false); assert.equal(geometry.footerMoved, false)
      const controls = []
      for (const control of await dialog.locator('button, input:not([type=radio]), input[type=radio]:checked, select, [role=alert]:not([hidden])').all()) {
        if (!await control.isEnabled()) continue
        await control.focus()
        const state = await control.evaluate(node => {
          const r = node.getBoundingClientRect(), center = document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2), body = node.closest('.docx-watermark-body')?.getBoundingClientRect()
          return { label: node.getAttribute('aria-label') || node.getAttribute('name') || node.textContent, focused: node === document.activeElement, hit: node.contains(center), top: r.top, bottom: r.bottom, withinBody: !body || r.top >= body.top - 1 && r.bottom <= body.bottom + 1 }
        })
        assert.ok(state.focused && state.hit && state.top >= 0 && state.bottom <= height + 1 && state.withinBody, JSON.stringify(state))
        controls.push(state)
      }
      const accessibility = await new AxeBuilder({ page }).include('.docx-watermark-dialog').analyze()
      assert.deepEqual(accessibility.violations, [])
      await page.screenshot({ path: `${output}-${phase}-${width}x${height}.png` })
      const close = phase === 'none' ? dialog.getByRole('button', { name: '关闭水印设置' }) : dialog.locator('button[value=cancel]')
      if (phase === 'error') await page.keyboard.press('Escape')
      else await close.click()
      await dialog.waitFor({ state: 'detached' })
      assert.equal(await trigger().evaluate(node => node === document.activeElement), true)
      assert.deepEqual(await draft(), before)
      results.push({ phase, width, height, geometry, controls, accessibility: { violations: [] } })
      await writeFile(`${output}-layout.json`, JSON.stringify({ results }, null, 2))
    }
  }
  await page.setViewportSize({ width: 1600, height: 1100 })
  return results
}
