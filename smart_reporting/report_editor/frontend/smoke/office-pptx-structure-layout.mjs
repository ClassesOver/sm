import assert from 'node:assert/strict'
import { writeFile } from 'node:fs/promises'
import { resolve } from 'node:path'

// Inspect the real host dialog, including native select and keyboard traversal.
export async function inspectPptxStructureLayout(page, { output, viewports, draft }) {
  const evidence = { cases: [], failures: [] }
  for (const viewport of viewports.split(',')) {
    const [width, height] = viewport.split('x').map(Number)
    await page.setViewportSize({ width, height })
    const before = await draft()
    const check = (ok, message) => { if (!ok) evidence.failures.push(`${viewport}: ${message}`) }
    await page.locator('[data-ribbon-tab="tableDesign"]').click()
    const opener = page.locator('[data-command="tableStructure"]')
    await opener.click()
    const dialog = page.getByRole('dialog', { name: '调整表格行列', exact: true })
    const row = dialog.getByLabel('参考行', { exact: true })
    check(await row.evaluate(node => document.activeElement === node), '首个参考行未获得焦点')
    await row.selectOption('1')
    await dialog.getByLabel('参考列', { exact: true }).selectOption('2')
    await page.evaluate(() => document.fonts.ready)
    const geometry = await dialog.evaluate(node => {
      const r = node.getBoundingClientRect()
      return { x: r.x, y: r.y, right: r.right, bottom: r.bottom, width: r.width, font: getComputedStyle(node).fontFamily,
        overflow: node.scrollWidth > node.clientWidth + 1,
        groups: [...node.querySelectorAll('fieldset')].map(group => ({ legend: group.querySelector('legend')?.textContent, actions: group.querySelectorAll('button').length })),
        fields: [...node.querySelectorAll('select')].map(field => {
          const label = field.closest('label'), f = field.getBoundingClientRect()
          const range = document.createRange(); if (label) range.selectNodeContents(label.firstChild)
          const text = range.getBoundingClientRect()
          return { labelled: label?.textContent.includes(field.getAttribute('aria-label')), width: f.width, leftLabel: !!label && text.right < f.left && text.top < f.bottom && text.bottom > f.top }
        }),
        controls: [...node.querySelectorAll('button,select')].map(control => { const c = control.getBoundingClientRect(); return { text: control.textContent, height: c.height, x: c.x, right: c.right, font: getComputedStyle(control).fontFamily } }) }
    })
    check(geometry.x >= 0 && geometry.y >= 0 && geometry.right <= width + 1 && geometry.bottom <= height + 1 && !geometry.overflow, '窗口越界或横向溢出')
    check(geometry.font.includes('Noto Sans') && geometry.controls.every(c => c.font.includes('Noto Sans')), '控件未继承Office字体')
    check(geometry.fields.every(f => f.labelled && f.width >= 130), '缺少可见标签或参考字段过窄')
    check(JSON.stringify(geometry.groups) === JSON.stringify([{ legend: '行', actions: 3 }, { legend: '列', actions: 3 }]), '行列操作未分组')
    check(geometry.controls.every(c => c.height >= 28 && c.height <= 36 && c.x >= geometry.x && c.right <= geometry.right), '控件尺寸或横向边界错误')
    if (width >= 1000) check(geometry.width === 520 && geometry.fields.every(f => f.leftLabel), 'PC窗口宽度或左右表单布局错误')
    const first = dialog.locator('[data-settings-close]'), last = dialog.getByRole('button', { name: '取消', exact: true })
    check(await first.count() === 1, '缺少标题关闭')
    const reachability = []
    const controls = await dialog.locator('button,select').all()
    // :focus-visible follows the input modality; traverse with real Tab events.
    await last.focus(); await page.keyboard.press('Tab')
    for (const [index, control] of controls.entries()) {
      await control.scrollIntoViewIfNeeded()
      const state = await control.evaluate(node => {
        const r = node.getBoundingClientRect(), s = getComputedStyle(node)
        return { text: node.getAttribute('aria-label') ?? node.textContent, hit: node.contains(document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2)), focused: node === document.activeElement,
          ring: s.outlineStyle !== 'none' && parseFloat(s.outlineWidth) >= 2 }
      })
      check(state.hit && state.focused && state.ring, `${state.text}不可命中、聚焦或缺少焦点环`)
      reachability.push(state)
      if (index < controls.length - 1) await page.keyboard.press('Tab')
    }
    await page.screenshot({ path: resolve(output, `structure-${viewport}-bottom.png`) })
    await last.focus(); await page.keyboard.press('Tab')
    check(await first.count() === 1 && await first.evaluate(node => document.activeElement === node), 'Tab未循环到标题关闭')
    await page.keyboard.press('Shift+Tab')
    check(await last.evaluate(node => document.activeElement === node), 'Shift+Tab未循环到取消')
    await dialog.evaluate(node => { node.scrollTop = 0 })
    await page.screenshot({ path: resolve(output, `structure-${viewport}.png`) })
    await page.keyboard.press('Escape'); await dialog.waitFor({ state: 'detached' })
    check(await opener.evaluate(node => node === document.activeElement), 'Escape后入口未恢复焦点')
    assert.deepEqual(await draft(), before)
    for (const method of ['title', 'cancel']) {
      await opener.click()
      const reopened = page.getByRole('dialog', { name: '调整表格行列', exact: true })
      assert.equal(await reopened.getByLabel('参考行', { exact: true }).inputValue(), '0')
      assert.equal(await reopened.getByLabel('参考列', { exact: true }).inputValue(), '0')
      const close = reopened.locator('[data-settings-close]')
      if (method === 'title' && await close.count()) await close.click()
      else await reopened.getByRole('button', { name: '取消', exact: true }).click()
      await reopened.waitFor({ state: 'detached' })
      check(await opener.evaluate(node => document.activeElement === node), `${method}关闭后焦点未恢复`)
      assert.deepEqual(await draft(), before)
    }
    evidence.cases.push({ width, height, geometry, reachability, draftUnchanged: true })
  }
  await writeFile(resolve(output, 'structure-layout-evidence.json'), JSON.stringify(evidence, null, 2))
  assert.deepEqual(evidence.failures, [], JSON.stringify(evidence.failures))
  return evidence
}
