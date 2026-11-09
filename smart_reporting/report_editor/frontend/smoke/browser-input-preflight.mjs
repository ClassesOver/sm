import assert from 'node:assert/strict'

/** Check native editing before attributing a browser failure to an editor. */
export async function verifyBrowserTextInput(browser) {
  const page = await browser.newPage()
  try {
    await page.setContent('<input aria-label="Input baseline" value="25.4"><dialog><input aria-label="Modal baseline" value="19.05"></dialog>')
    const events = []
    await page.exposeFunction('recordInputBaseline', event => events.push(event))
    await page.evaluate(() => {
      for (const type of ['beforeinput', 'input']) document.addEventListener(type, event => {
        void window.recordInputBaseline({ type, label: event.target.getAttribute('aria-label'), data: event.data })
      })
    })
    await page.getByLabel('Input baseline', { exact: true }).fill('25')
    assert.equal(await page.getByLabel('Input baseline', { exact: true }).inputValue(), '25', 'Bare HTML input cannot be edited; this browser runtime cannot validate editor input')
    await page.evaluate(() => document.querySelector('dialog').showModal())
    await page.getByLabel('Modal baseline', { exact: true }).fill('20')
    assert.equal(await page.getByLabel('Modal baseline', { exact: true }).inputValue(), '20', 'Bare HTML modal input cannot be edited; this browser runtime cannot validate editor input')
    assert.ok(events.some(event => event.type === 'input' && event.label === 'Input baseline'))
    assert.ok(events.some(event => event.type === 'input' && event.label === 'Modal baseline'))
    return { browserVersion: browser.version(), bareInput: '25', modalInput: '20', events }
  } finally {
    await page.close()
  }
}
