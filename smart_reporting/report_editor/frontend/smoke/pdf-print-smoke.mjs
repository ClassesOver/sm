import assert from 'node:assert/strict'
import { spawn } from 'node:child_process'
import { setTimeout as delay } from 'node:timers/promises'
import { chromium } from 'playwright'

const frontend = process.cwd()
const port = Number(process.env.PDF_PRINT_SMOKE_PORT ?? 4197)
const baseUrl = `http://127.0.0.1:${port}`
const server = spawn('./node_modules/.bin/vite', ['--host', '127.0.0.1', '--port', String(port), '--strictPort'], { cwd: frontend, stdio: 'ignore' })
let browser
try {
  for (let attempt = 0; attempt < 100; attempt++) {
    try { if ((await fetch(`${baseUrl}/reports/v1/editor/assets/native.html`)).ok) break } catch {}
    await delay(250)
  }
  browser = await chromium.launch({ headless: true })
  const page = await browser.newPage()
  await page.goto(`${baseUrl}/reports/v1/editor/assets/native.html`)
  await page.setContent('<header id="shell-header">Shell chrome</header><main id="report-editor" class="native-pdf-editor"><div class="pdf-ribbon">Ribbon</div></main>')
  await page.addStyleTag({ url: `${baseUrl}/reports/v1/editor/assets/src/pdf-ribbon.css` })
  await page.emulateMedia({ media: 'print' })
  const result = await page.evaluate(async () => {
    const { renderPdfPrintHost } = await import('/reports/v1/editor/assets/src/pdf-operations.ts')
    const root = document.querySelector('#report-editor')
    const loadOrder = []
    const mockPage = {
      getViewport: ({ rotation }) => ({ width: rotation % 180 ? 400 : 300, height: rotation % 180 ? 300 : 400 }),
      render: () => ({ promise: Promise.resolve() }),
    }
    const pages = [
      { pageId: 'source:p2', index: 1, rotation: 0 },
      { pageId: 'source:p1', index: 0, rotation: 90 },
    ]
    const handle = await renderPdfPrintHost(root, pages, async index => { loadOrder.push(index); return mockPage }, 2, 48_000_000)
    let printed = 0
    let captured
    window.print = () => {
      printed++
      captured = {
        canvasCount: handle.host.querySelectorAll('canvas').length,
        pageCount: handle.host.querySelectorAll('.pdf-print-page').length,
        ribbonDisplay: getComputedStyle(root.querySelector('.pdf-ribbon')).display,
        printHostDisplay: getComputedStyle(handle.host).display,
        shellVisibility: getComputedStyle(document.querySelector('#shell-header')).visibility,
      }
      window.dispatchEvent(new Event('afterprint'))
    }
    window.addEventListener('afterprint', handle.cleanup, { once: true })
    handle.print(() => window.print())
    return { loadOrder, printed, captured, cleaned: !root.querySelector('.pdf-print-document') }
  })
  assert.deepEqual(result.loadOrder, [1, 0])
  assert.equal(result.printed, 1)
  assert.deepEqual(result.captured, { canvasCount: 2, pageCount: 2, ribbonDisplay: 'none', printHostDisplay: 'block', shellVisibility: 'hidden' })
  assert.equal(result.cleaned, true)
  console.log(JSON.stringify({ ok: true, ...result }))
} finally {
  await browser?.close()
  server.kill('SIGTERM')
}
