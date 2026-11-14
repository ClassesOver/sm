import assert from 'node:assert/strict'

// 调用方提供已打开导航窗格、至少40个标题且首项有子标题的真实DOCX宿主。
export async function inspectDocxLongNavigationTree(page) {
  const panel = page.locator('[data-docx-navigation]'), headings = panel.locator('[data-navigation-heading]')
  const editor = page.getByRole('textbox', { name: 'Word 文档编辑区' })
  const count = await headings.count(); assert.ok(count >= 40)
  const documentBefore = await editor.evaluate(node => JSON.stringify(node.editor.getJSON()))
  const draftBefore = await page.evaluate(() => Object.entries(localStorage).filter(([key]) => key.startsWith('native-editor-draft:')))
  const samples = []
  const inspectFocus = async expected => {
    const actual = await panel.evaluate(element => {
      const tree = element.querySelector('.docx-navigation-tree'), focused = document.activeElement
      const rectangle = focused.getBoundingClientRect(), clip = tree.getBoundingClientRect(), outer = element.getBoundingClientRect()
      const x = rectangle.x + rectangle.width / 2, y = rectangle.y + rectangle.height / 2, hit = document.elementFromPoint(x, y)
      return { text: focused.textContent, treeScroll: tree.scrollTop, panelScroll: element.scrollTop,
        visible: x >= Math.max(clip.left, outer.left, 0) && x < Math.min(clip.right, outer.right, innerWidth)
          && y >= Math.max(clip.top, outer.top, 0) && y < Math.min(clip.bottom, outer.bottom, innerHeight),
        hit: hit === focused || focused.contains(hit) }
    })
    assert.equal(actual.text, expected); assert.ok(actual.visible && actual.hit, JSON.stringify(actual))
    samples.push(actual); return actual
  }
  await headings.first().click()
  const firstText = await headings.first().innerText(), lastText = await headings.last().innerText()
  const before = await inspectFocus(firstText)
  const bodyScrollBefore = await page.locator('.docx-native .editor-scroll').evaluate(node => node.scrollTop)
  await page.keyboard.press('End'); const end = await inspectFocus(lastText)
  assert.ok(end.treeScroll > before.treeScroll)
  assert.equal(await headings.first().getAttribute('aria-current'), 'location')
  assert.equal(await page.locator('.docx-native .editor-scroll').evaluate(node => node.scrollTop), bodyScrollBefore)
  await page.keyboard.press('ArrowDown'); await inspectFocus(lastText)
  await page.keyboard.press('ArrowUp'); await inspectFocus(await headings.nth(count - 2).innerText())
  await page.keyboard.press('Home'); const home = await inspectFocus(firstText)
  assert.ok(home.treeScroll < end.treeScroll)
  await page.keyboard.press('ArrowUp'); await inspectFocus(firstText)
  for (let index = 1; index <= 20; index++) {
    await page.keyboard.press('ArrowDown'); await inspectFocus(await headings.nth(index).innerText())
  }
  assert.equal(await headings.first().getAttribute('aria-current'), 'location')
  const chosen = await headings.nth(20).innerText()
  await page.keyboard.press('Enter')
  assert.equal(await headings.nth(20).getAttribute('aria-current'), 'location')
  assert.equal(await editor.evaluate(node => node.editor.state.selection.$from.parent.textContent), chosen)
  await inspectFocus(chosen)
  await page.keyboard.press('Home'); await page.keyboard.press('ArrowLeft')
  const collapsedCount = await headings.count(); assert.ok(collapsedCount < count)
  await inspectFocus(firstText)
  await page.keyboard.press('ArrowRight'); assert.equal(await headings.count(), count)
  await inspectFocus(firstText)
  await page.keyboard.press('ArrowRight'); await inspectFocus(await headings.nth(1).innerText())
  await page.keyboard.press('ArrowLeft'); await inspectFocus(firstText)
  assert.equal(await editor.evaluate(node => JSON.stringify(node.editor.getJSON())), documentBefore)
  assert.deepEqual(await page.evaluate(() => Object.entries(localStorage).filter(([key]) => key.startsWith('native-editor-draft:'))), draftBefore)
  return { count, samples, bodyScrollUnchangedDuringFocus: true, enterNavigated: chosen, collapsedCount, documentAndDraftUnchanged: true }
}
