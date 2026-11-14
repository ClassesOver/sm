import assert from 'node:assert/strict'

// 供统一冻结构建验收复用：page 已打开允许裁剪和静态文字插入的真实 PDF 编辑器。
// 只配置后取消；不应用裁剪、不选择文字落点、不保存或变更业务草稿。
export async function verifyPdfInputLifecycleInEditor(page) {
  const checks = [], root = page.locator('#report-editor')
  const cropCommand = page.locator('[data-source-command-id="genoffice.pdf.page.crop"]')
  const insertCommand = page.locator('[data-source-command-id="genoffice.pdf.home.edit.insertText"]')
  async function escape(target, kind) {
    if (kind === 'consumed') {
      await target.evaluate(element => element.addEventListener('keydown', event => event.preventDefault(), { once: true }))
      await page.keyboard.press('Escape')
    } else if (kind === 'plain') await page.keyboard.press('Escape')
    else await target.evaluate((element, kind) => element.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true, isComposing: kind === 'composition', keyCode: kind === '229' ? 229 : 27 })), kind)
  }
  await page.locator('[data-pdf-ribbon-tab="page"]').click()
  for (const kind of ['consumed', 'composition', '229', 'plain']) {
    await cropCommand.click()
    const dialog = page.locator('.pdf-crop-dialog[aria-label="裁切当前页面"]'), stage = dialog.locator('[data-pdf-crop-canvas]')
    await stage.waitFor()
    const labels = ['左侧裁去 (%)', '顶部裁去 (%)', '右侧裁去 (%)', '底部裁去 (%)']
    for (let index = 0; index < labels.length; index++) await dialog.getByLabel(labels[index], { exact: true }).fill(String([10, 20, 30, 40][index]))
    const input = dialog.getByLabel(labels[2], { exact: true }), handle = stage.locator('[data-pdf-crop-handle="e"]')
    await handle.scrollIntoViewIfNeeded(); await input.evaluate(element => element.focus({ preventScroll: true }))
    await stage.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))))
    const bounds = await stage.boundingBox(), grip = await handle.boundingBox()
    assert.ok(bounds && grip)
    const x = Math.round(grip.x + grip.width / 2), y = Math.round(grip.y + grip.height / 2), dx = Math.round(bounds.width / 10)
    await page.mouse.move(x, y); await page.mouse.down(); await escape(input, kind)
    await page.mouse.move(x + dx, y); await page.mouse.up()
    const actual = Number(await input.inputValue()), expected = kind === 'plain' ? 30 : 30 - dx / bounds.width * 100
    assert.ok(Math.abs(actual - expected) < .02, JSON.stringify({ component: 'crop', kind, actual, expected, bounds }))
    assert.equal(await dialog.evaluate(element => element.open), kind !== 'plain')
    if (kind !== 'plain') await dialog.getByRole('button', { name: '取消', exact: true }).click()
    checks.push({ component: 'crop', kind, actual, expected, bounds })
  }
  await page.locator('[data-pdf-ribbon-tab="home"]').click()
  for (const kind of ['consumed', 'composition', '229', 'plain']) {
    await insertCommand.click()
    const dialog = page.locator('.pdf-static-text-dialog')
    await dialog.getByLabel('插入文字内容', { exact: true }).fill('Keyboard lifecycle verification')
    await dialog.locator('[data-pdf-static-text-confirm]').click()
    assert.equal(await insertCommand.evaluate(element => element === document.activeElement), true)
    await escape(insertCommand, kind)
    const mode = await root.getAttribute('data-pdf-mode')
    assert.equal(mode, kind === 'plain' ? 'select' : 'staticText')
    if (kind !== 'plain') await page.keyboard.press('Escape')
    checks.push({ component: 'static-text', kind, mode })
  }
  return checks
}
