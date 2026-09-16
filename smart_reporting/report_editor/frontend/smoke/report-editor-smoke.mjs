import process from 'node:process'

const playwrightModule = process.env.REPORT_EDITOR_PLAYWRIGHT ?? 'playwright'
const playwright = await import(playwrightModule)
const { chromium, firefox } = playwright.default ?? playwright

const url = process.env.REPORT_EDITOR_URL
if (!url) {
  throw new Error('请设置 REPORT_EDITOR_URL 为带有效编辑会话的报告地址')
}

const browserType = process.env.REPORT_EDITOR_BROWSER === 'firefox' ? firefox : chromium
const browser = await browserType.launch({ headless: process.env.HEADLESS !== '0' })
const allowMutation = process.env.REPORT_EDITOR_ALLOW_MUTATION === '1'

async function runMutationSmoke(page) {
  const result = await page.evaluate(async () => {
    const basePath = window.location.pathname.replace(/\/$/, '')
    const request = async (path, init = {}) => {
      const response = await fetch(`${basePath}${path}`, {
        credentials: 'same-origin',
        ...init,
      })
      const payload = await response.json()
      return { response: { ok: response.ok, status: response.status }, payload }
    }
    const loaded = await request('/api/document')
    if (!loaded.response.ok) throw new Error(`加载失败：${loaded.response.status}`)
    const original = loaded.payload.markdown
    const csrf = loaded.payload.csrfToken
    const probe = `${original.trimEnd()}\n\n<!-- report-editor-smoke -->\n`
    const headers = {
      'Content-Type': 'application/json',
      Origin: window.location.origin,
      'X-CSRF-Token': csrf,
    }
    const saved = await request('/api/document', {
      method: 'PUT',
      headers,
      body: JSON.stringify({ markdown: probe, expectedSha256: loaded.payload.sha256 }),
    })
    if (!saved.response.ok) throw new Error(`保存失败：${saved.response.status}`)
    const conflict = await request('/api/document', {
      method: 'PUT',
      headers,
      body: JSON.stringify({ markdown: `${probe}冲突`, expectedSha256: loaded.payload.sha256 }),
    })
    if (conflict.response.status !== 409) {
      throw new Error(`预期 CAS 409，实际 ${conflict.response.status}`)
    }
    const restored = await request('/api/document', {
      method: 'PUT',
      headers,
      body: JSON.stringify({ markdown: original, expectedSha256: saved.payload.sha256 }),
    })
    if (!restored.response.ok) throw new Error(`恢复原文失败：${restored.response.status}`)
    const exported = await request('/api/export', {
      method: 'POST',
      headers: { ...headers, 'X-Request-ID': crypto.randomUUID() },
      body: JSON.stringify({ expectedSha256: restored.payload.sha256 }),
    })
    if (!exported.response.ok) throw new Error(`导出失败：${exported.response.status}`)
    return exported.payload
  })
  for (const [format, magic] of [['pdf', '%PDF-'], ['word', 'PK']]) {
    const artifact = result[format]
    const response = await page.request.get(artifact.downloadUrl)
    if (!response.ok()) throw new Error(`${format} 下载失败：${response.status()}`)
    const content = await response.body()
    if (!content.subarray(0, magic.length).equals(Buffer.from(magic))) {
      throw new Error(`${format} 文件头无效`)
    }
    if (artifact.size && content.length !== artifact.size) {
      throw new Error(`${format} 文件大小不一致：${content.length} != ${artifact.size}`)
    }
  }
  console.log(JSON.stringify({ mutation: 'passed', revision: result.revision, requestId: result.requestId }))
}

try {
  for (const viewport of [
    { width: 375, height: 812 },
    { width: 1280, height: 900 },
  ]) {
    const page = await browser.newPage({ viewport })
    await page.goto(url, { waitUntil: 'networkidle' })
    await page.locator('.ProseMirror').waitFor({ state: 'visible', timeout: 20_000 })

    const result = await page.evaluate(() => ({
      width: window.innerWidth,
      scrollWidth: document.documentElement.scrollWidth,
      loadStateHidden: document.querySelector('.editor-load-state')?.hidden ?? false,
      toolbarButtons: document.querySelectorAll('.report-actions button').length,
      toolbarIcons: document.querySelectorAll('.report-actions svg').length,
      saveState: document.querySelector('.save-state-label')?.textContent ?? '',
    }))

    if (result.scrollWidth > result.width) {
      throw new Error(`${result.width}px 视口出现横向溢出：${result.scrollWidth}px`)
    }
    if (!result.loadStateHidden) throw new Error(`${result.width}px 加载面板仍可见`)
    if (result.toolbarButtons < 6 || result.toolbarIcons < 6) {
      throw new Error(`${result.width}px 工具栏控件不足：${JSON.stringify(result)}`)
    }
    console.log(JSON.stringify(result))
    await page.close()
  }
  if (allowMutation) {
    const page = await browser.newPage({ viewport: { width: 1280, height: 900 } })
    await page.goto(url, { waitUntil: 'networkidle' })
    await runMutationSmoke(page)
    await page.close()
  }
} finally {
  await browser.close()
}
