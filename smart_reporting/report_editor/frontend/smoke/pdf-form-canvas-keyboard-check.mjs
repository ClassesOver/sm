import assert from 'node:assert/strict'

// 调用方提供真实画布控件和草稿读取；不替换产品监听或坐标计算。
export async function inspectPdfFormCanvasKeys(page, rect, operations) {
  const before = await operations(), events = []
  for (const mode of ['composing', 'legacy229', 'consumed']) {
    for (const key of ['Enter', ' ']) {
      await rect.focus(); await page.keyboard.press('Escape')
      assert.equal(await rect.getAttribute('aria-pressed'), 'false')
      const result = await dispatch(rect, key, mode)
      assert.equal(await rect.getAttribute('aria-pressed'), 'false', `${mode}/${key} must not select a field`)
      assert.deepEqual(await operations(), before)
      if (mode !== 'consumed') assert.equal(result.defaultPrevented, false)
      await page.keyboard.press(key === ' ' ? 'Space' : key)
      assert.equal(await rect.getAttribute('aria-pressed'), 'true', `ordinary ${key} must select`)
      events.push({ mode, key, ...result })
    }
    for (const key of ['ArrowRight', 'ArrowUp', 'Escape']) {
      await rect.focus(); await page.keyboard.press('Enter')
      const geometry = await rect.evaluate(node => ['x', 'y', 'width', 'height'].map(name => node.getAttribute(name)))
      const result = await dispatch(rect, key, mode)
      assert.equal(await rect.getAttribute('aria-pressed'), 'true', `${mode}/${key} must preserve selection`)
      assert.deepEqual(await operations(), before, `${mode}/${key} must preserve the draft`)
      assert.deepEqual(await rect.evaluate(node => ['x', 'y', 'width', 'height'].map(name => node.getAttribute(name))), geometry)
      if (mode !== 'consumed') assert.equal(result.defaultPrevented, false)
      events.push({ mode, key, ...result })
    }
  }
  await page.keyboard.press('Escape')
  assert.equal(await rect.getAttribute('aria-pressed'), 'false')
  assert.deepEqual(await operations(), before)
  return events
}

async function dispatch(rect, key, mode) {
  return rect.evaluate((node, { key, mode }) => {
    if (mode === 'consumed') node.addEventListener('keydown', event => event.preventDefault(), { once: true, capture: true })
    const event = new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true, isComposing: mode === 'composing', keyCode: mode === 'legacy229' ? 229 : 0, shiftKey: key === 'ArrowUp' })
    node.dispatchEvent(event)
    return { defaultPrevented: event.defaultPrevented, isComposing: event.isComposing, keyCode: event.keyCode }
  }, { key, mode })
}
