import assert from 'node:assert/strict'

// 复用真实宿主已打开的对话框；不确认、不修改字段或提交草稿。
export async function inspectSlidesDialogInputProtection(page, dialog) {
  const first = dialog.locator('[data-settings-close],.slides-size-close').first()
  const last = dialog.locator('button[value=ok],[data-command=applyCustomSlideSize]').last()
  const field = dialog.locator('input:not([disabled]),select:not([disabled])').first()
  const records = []
  for (const protection of ['composition', 'legacy229', 'consumed']) for (const reverse of [false, true]) {
    const target = reverse ? first : last; await target.focus()
    const state = await target.evaluate((node, { protection, reverse }) => {
      const event = new KeyboardEvent('keydown', { key: 'Tab', shiftKey: reverse, bubbles: true, cancelable: true, isComposing: protection === 'composition', keyCode: protection === 'legacy229' ? 229 : 0 })
      if (protection === 'consumed') event.preventDefault()
      node.dispatchEvent(event)
      return { protection, reverse, key: 'Tab', focused: document.activeElement === node, prevented: event.defaultPrevented }
    }, { protection, reverse })
    assert.ok(state.focused && state.prevented === (protection === 'consumed'), JSON.stringify(state)); records.push(state)
  }
  await last.focus(); await page.keyboard.press('Tab'); assert.equal(await first.evaluate(node => document.activeElement === node), true)
  await page.keyboard.press('Shift+Tab'); assert.equal(await last.evaluate(node => document.activeElement === node), true)
  await field.focus()
  const escape = await field.evaluate(node => ['composition', 'legacy229', 'consumed'].map(protection => {
    const event = new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true, isComposing: protection === 'composition', keyCode: protection === 'legacy229' ? 229 : 0 })
    if (protection === 'consumed') event.preventDefault()
    node.dispatchEvent(event)
    return { protection, key: 'Escape', focused: document.activeElement === node, connected: node.isConnected, prevented: event.defaultPrevented }
  }))
  assert.ok(escape.every(state => state.focused && state.connected && state.prevented === (state.protection === 'consumed')))
  return { protectedKeys: [...records, ...escape], normalTabLoop: true }
}
