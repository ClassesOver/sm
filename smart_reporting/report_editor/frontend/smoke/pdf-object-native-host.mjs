import assert from 'node:assert/strict'

// 完整 native.html 的 HTTP 身份/文件/来源预览夹具；实际宿主、PDF.js 与草稿恢复均来自产品。
export async function openPdfObjectNativeHost(page, { source, mode, base, requests }) {
  const bytes = Buffer.from(source.bytes, 'base64')
  const scope = { database: 'fixture', companyId: 'fixture', userId: 'fixture', threadId: 'fixture' }
  const identity = { documentId: 'pdf-object-native-' + mode, revision: 1, sourceSha256: source.model.sourceSha256, scope }
  const pageId = source.model.pages[0].pageId
  const image = 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=='
  const operations = mode === 'note-edit'
    ? [{ kind: 'addTextAnnotation', pageId, rect: [70, 600, 94, 624], text: '年度经营报告的便签正文。'.repeat(20), createdMs: 1794412800000 }]
    : [{ kind: 'addDrawing', pageId, shape: mode === 'image-resize' ? 'image' : 'rect', color: [1, 0, 0], width: 2, rect: [72, 500, 180, 560], ...(mode === 'image-resize' ? { image } : {}) }]
  const key = 'native-editor-draft:v1:' + JSON.stringify([...Object.values(scope), identity.documentId, 1, identity.sourceSha256])
  await page.addInitScript(({ key, identity, operations }) => {
    localStorage.clear()
    localStorage.setItem(key, JSON.stringify({ version: 1, identity, operations }))
    window.pdfObjectInteractionDraftKey = key
  }, { key, identity, operations })
  const path = `/reports/v1/native/${identity.documentId}/1`
  await page.route(`**${path}/api/**`, async route => {
    const operation = new URL(route.request().url()).pathname.split('/').at(-1)
    requests.push({ mode, operation, method: route.request().method() })
    if (operation === 'context') return route.fulfill({ json: {
      context: { documentId: identity.documentId, revision: 1, parentRevision: null, format: 'pdf', origin: 'upload', scope,
        sourceFile: { path: 'pdf-object-native.pdf', size: bytes.length, sha256: identity.sourceSha256, mediaType: 'application/pdf' } },
      csrfToken: 'fixture', capabilities: { pdf_editor: true }, editingEnabled: true,
    } })
    if (operation === 'file') return route.fulfill({ body: bytes, contentType: 'application/pdf' })
    if (operation === 'preview') {
      assert.deepEqual(route.request().postDataJSON().operations, [], '交互检查仅允许初始来源读取')
      return route.fulfill({ json: { sourceSha256: identity.sourceSha256, draftSha256: identity.sourceSha256, model: source.model, appliedOperationIndices: [], skippedOperations: [] } })
    }
    return route.fulfill({ status: 500, json: { detail: '交互检查禁止保存、导出或其他业务请求' } })
  })
  await page.route(`**${path}`, async route => route.fulfill({ response: await route.fetch({ url: `${base}native.html` }) }))
  await page.goto(new URL(path, base).href)
  await page.waitForFunction(() => document.querySelector('#report-editor')?.getAttribute('aria-busy') === 'false' && document.querySelector('.pdf-page-content canvas'), null, { timeout: 60000 })
  assert.deepEqual(await page.evaluate(() => JSON.parse(localStorage.getItem(window.pdfObjectInteractionDraftKey)).operations), operations)
}

export async function openPdfObjectFromNativeRibbon(page, mode) {
  if (mode === 'note-edit') await page.locator('.pdf-pending-note').getByRole('button', { name: '编辑便签', exact: true }).click()
  else {
    await page.locator('[data-pdf-ribbon-tab="annotate"]').click()
    await page.getByRole('button', { name: '待保存绘图', exact: true }).click()
    await page.locator('.pdf-pending-drawings-panel [data-pdf-pending-drawing] button').click()
    await page.getByRole('button', { name: mode === 'drawing-move' ? '移动所选绘图' : '缩放所选图像', exact: true }).click()
  }
}

export async function inspectPdfNativeRibbon(page) {
  const tabs = page.locator('[data-pdf-ribbon-tab]:visible')
  const ids = await tabs.evaluateAll(nodes => nodes.map(node => node.dataset.pdfRibbonTab))
  const checks = []
  const selected = id => page.locator(`[data-pdf-ribbon-tab="${id}"]`)
  async function check(id) {
    assert.equal(await page.locator('[data-pdf-ribbon-tab][aria-selected="true"]').count(), 1)
    assert.equal(await selected(id).getAttribute('aria-selected'), 'true')
    assert.equal(await selected(id).getAttribute('tabindex'), '0')
    assert.ok(await selected(id).evaluate(node => {
      const r = node.getBoundingClientRect()
      return r.y >= 0 && r.bottom <= innerHeight && r.x >= 0 && r.right <= innerWidth && node.contains(document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2))
    }), '功能区已选页签应实际可命中')
    const visible = await page.locator('[data-pdf-ribbon-panel]:visible').evaluateAll(nodes => nodes.map(node => node.dataset.pdfRibbonPanel))
    assert.deepEqual(visible, [id])
    checks.push(id)
  }
  for (const id of ids) { await selected(id).click(); await check(id) }
  await selected(ids[0]).click()
  for (const [key, id] of [['End', ids.at(-1)], ['Home', ids[0]], ['ArrowRight', ids[1]], ['ArrowLeft', ids[0]]]) {
    await page.keyboard.press(key); await check(id)
    assert.ok(await selected(id).evaluate(node => document.activeElement === node))
  }
  return { ids, checks, realClicks: ids.length, keyboard: ['End', 'Home', 'ArrowRight', 'ArrowLeft'], hitTestPassed: true }
}
