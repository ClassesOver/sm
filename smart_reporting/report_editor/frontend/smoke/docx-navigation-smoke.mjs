// 本地固定构建验收：沿用现有 DOCX built smoke 的静态 fixture server + 替身 API；不代表生产鉴权。
import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { readFile, writeFile, mkdir } from 'node:fs/promises'
import { createServer } from 'node:http'
import { spawnSync } from 'node:child_process'
import { dirname, resolve, extname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { chromium } from 'playwright'

const fixtureRoot = dirname(fileURLToPath(import.meta.url)), repo = resolve(fixtureRoot, '../../../..')
const output = resolve(process.env.DOCX_TEST_OUTPUT ?? '/tmp/docx-navigation-smoke')
const staticRoot = process.env.DOCX_TEST_DIST ?? resolve(repo, 'smart_reporting/report_editor/static')
const runtime = process.env.DOCX_TEST_ENGINE ?? resolve(repo, 'smart_reporting/reporting/doc_engine')
const port = Number(process.env.DOCX_TEST_PORT ?? 4335), base = 'http://127.0.0.1:' + port
const prefix = '/reports/v1/editor/assets/', mediaType = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
const sha = bytes => createHash('sha256').update(bytes).digest('hex')
const manifestPath = resolve(staticRoot, '.vite/manifest.json'), bridgePath = resolve(runtime, 'dist/edit-docx.mjs')
const manifestSha256 = sha(await readFile(manifestPath)), bridgeSha256 = sha(await readFile(bridgePath))
assert.equal(manifestSha256, process.env.DOCX_EXPECTED_MANIFEST_SHA256, '必须由集成人员提供冻结构建 manifest 身份')
await mkdir(output, { recursive: true })
const fixturePath = resolve(output, 'source.docx')
const python = [
  'import base64,json,sys',
  'from pathlib import Path',
  'from docx import Document',
  'from docx.enum.style import WD_STYLE_TYPE',
  'from docx.oxml import OxmlElement',
  'from docx.oxml.ns import qn',
  'from smart_reporting.reporting.delivery.docx_native import inspect_docx',
  'doc=Document()',
  'doc.add_heading("重复标题",1)',
  'doc.add_heading("",2)',
  'style=doc.styles.add_style("InheritedHeading",WD_STYLE_TYPE.PARAGRAPH)',
  'style.base_style=doc.styles["Heading 2"]',
  'doc.add_paragraph("继承正文标题",style)',
  'numbered=doc.styles.add_style("NumberedHeading",WD_STYLE_TYPE.PARAGRAPH)',
  'numbered.base_style=doc.styles["Heading 2"]',
  'num=OxmlElement("w:numPr")',
  'level=OxmlElement("w:ilvl");level.set(qn("w:val"),"0");num.append(level)',
  'identity=OxmlElement("w:numId");identity.set(qn("w:val"),"5");num.append(identity)',
  'numbered.element.get_or_add_pPr().append(num)',
  'doc.add_paragraph("编号继承标题",numbered)',
  'for i in range(25): doc.add_paragraph("第一章正文 "+str(i))',
  'doc.add_heading("重复标题",1)',
  'doc.add_heading("第二子标题",2)',
  'doc.add_paragraph("第二章正文")',
  'doc.save(sys.argv[1])',
  'raw=Path(sys.argv[1]).read_bytes()',
  'print(json.dumps({"bytes":base64.b64encode(raw).decode(),"model":inspect_docx(raw)},ensure_ascii=False))',
].join(String.fromCharCode(10))
const generated = spawnSync(resolve(repo, '.venv/bin/python'), ['-c', python, fixturePath], { cwd: repo, env: { ...process.env, PYTHONPATH: repo, AGENT_REPORTING_DOC_ENGINE_DIR: runtime }, encoding: 'utf8', maxBuffer: 20 * 1024 * 1024, timeout: 120000 })
assert.equal(generated.status, 0, generated.stderr)
const fixture = JSON.parse(generated.stdout), bytes = Buffer.from(fixture.bytes, 'base64')
const requests = [], identities = [], chunks = new Map(), errors = [], actions = []
const server = createServer(async (req, res) => {
  try {
    const path = new URL(req.url, base).pathname
    if (path === '/favicon.ico') { res.writeHead(204); res.end(); return }
    assert.ok(path.startsWith(prefix)); const file = resolve(staticRoot, path.slice(prefix.length)); assert.ok(file.startsWith(staticRoot + '/'))
    const mime = { '.js': 'application/javascript', '.css': 'text/css', '.woff2': 'font/woff2', '.html': 'text/html', '.svg': 'image/svg+xml', '.png': 'image/png' }
    res.writeHead(200, { 'Content-Type': mime[extname(file)] ?? 'application/octet-stream' }); res.end(await readFile(file))
  } catch { if (!res.headersSent) res.writeHead(404); res.end('not found') }
})
await new Promise((ok, no) => { server.once('error', no); server.listen(port, '127.0.0.1', ok) })
let browser, page
try {
  browser = await chromium.launch({ headless: true })
  for (const editingEnabled of [true, false]) {
    page = await browser.newPage({ viewport: { width: 1440, height: 1000 } })
    page.on('pageerror', error => errors.push(error.message))
    page.on('response', response => {
      const path = new URL(response.url()).pathname
      if (response.status() >= 400) errors.push(response.status() + ' ' + path)
      if (response.ok() && path.startsWith(prefix) && path.endsWith('.js')) identities.push(response.body().then(async body => { assert.equal(sha(body), sha(await readFile(resolve(staticRoot, path.slice(prefix.length))))); chunks.set(path, sha(body)) }))
    })
    const docId = 'fixture-navigation-' + editingEnabled, pathBase = '/reports/v1/native/' + docId + '/1'
    await page.route(base + pathBase, async route => route.fulfill({ body: await readFile(resolve(staticRoot, 'native.html')), contentType: 'text/html' }))
    await page.route('**' + pathBase + '/api/**', async route => {
      const request = route.request(), path = new URL(request.url()).pathname
      requests.push({ editingEnabled, method: request.method(), path })
      if (path.endsWith('/context')) return route.fulfill({ json: { context: { documentId: docId, format: 'docx', revision: 1, scope: { database: 'fixture', companyId: 'fixture', userId: 'fixture', threadId: 'fixture' }, sourceFile: { path: 'source.docx', size: bytes.length, sha256: fixture.model.sourceSha256, mediaType }, origin: 'upload' }, csrfToken: 'fixture-only', capabilities: { docx_editor: editingEnabled }, editingEnabled } })
      if (path.endsWith('/file')) return route.fulfill({ body: bytes, contentType: mediaType })
      if (path.endsWith('/preview')) return route.fulfill({ json: { sourceSha256: fixture.model.sourceSha256, draftSha256: fixture.model.sourceSha256, model: fixture.model } })
      return route.fulfill({ status: 409, json: { detail: '导航验收禁止写入' } })
    })
    await page.goto(base + pathBase); await page.locator('.docx-source-home').waitFor({ timeout: 60000 })
    const editor = page.getByRole('textbox', { name: 'Word 文档编辑区' }), panel = page.locator('[data-docx-navigation]')
    const before = await editor.innerHTML(), storageBefore = await page.evaluate(() => JSON.stringify(localStorage))
    await page.locator('[data-tab-id=view]').click()
    const toggle = page.locator('[data-action=navigation-toggle]')
    await toggle.click(); await panel.waitFor({ state: 'visible' })
    if (process.env.DOCX_NAVIGATION_LAYOUT_VIEWPORTS) {
      for (const viewport of process.env.DOCX_NAVIGATION_LAYOUT_VIEWPORTS.split(',')) {
        const [width,height] = viewport.split('x').map(Number)
        await page.setViewportSize({width,height}); await page.evaluate(() => document.fonts.ready)
        await panel.locator('[data-navigation-query]').fill('第二')
        const geometry = await panel.evaluate(node => {
          const rect=node.getBoundingClientRect(), input=node.querySelector('input'), close=node.querySelector('[data-navigation-action=close]'), button=close.getBoundingClientRect()
          return {x:rect.x,y:rect.y,right:rect.right,bottom:rect.bottom,width:rect.width,inputWidth:input.getBoundingClientRect().width,
            font:getComputedStyle(node).fontFamily,overflow:node.scrollWidth>node.clientWidth+1,
            closeAccessible:close.contains(document.elementFromPoint(button.x+button.width/2,button.y+button.height/2))}
        })
        assert.ok(geometry.x>=0&&geometry.y>=0&&geometry.right<=width+1&&geometry.bottom<=height+1,JSON.stringify(geometry))
        assert.ok(geometry.width>=220&&geometry.inputWidth>=120&&!geometry.overflow&&geometry.closeAccessible,JSON.stringify(geometry))
        assert.ok(geometry.font.includes('Noto Sans'))
        const last = panel.locator('[data-navigation-search-result]').last(); await last.scrollIntoViewIfNeeded()
        assert.ok(await last.evaluate(node=>{const rect=node.getBoundingClientRect();return node.contains(document.elementFromPoint(rect.x+rect.width/2,rect.y+rect.height/2))}))
        await page.screenshot({path:resolve(output,`${editingEnabled?'editable':'readonly'}-${viewport}.png`)})
        await panel.locator('[data-navigation-action=close]').click()
        assert.ok(await toggle.evaluate(node=>document.activeElement===node))
        assert.equal(await editor.innerHTML(),before)
        assert.equal(await page.evaluate(()=>JSON.stringify(localStorage)),storageBefore)
        actions.push({editingEnabled,width,height,geometry,documentUnchanged:true,storageUnchanged:true})
        await toggle.click()
      }
      await page.close(); continue
    }
    const headings = panel.locator('[data-navigation-heading]')
    assert.deepEqual(await headings.allTextContents(), ['重复标题', '（空标题）', '继承正文标题', '编号继承标题', '重复标题', '第二子标题'])
    await headings.nth(1).click()
    assert.equal(await editor.evaluate(node => node.editor.state.selection.$from.parent.textContent), '')
    await panel.locator('[data-navigation-collapse]').first().click()
    assert.deepEqual(await headings.allTextContents(), ['重复标题', '重复标题', '第二子标题'])
    assert.equal(await headings.nth(0).getAttribute('aria-current'), 'location')
    await headings.nth(2).click()
    assert.match(await editor.evaluate(node => node.editor.state.selection.$from.parent.textContent), /第二子标题/)
    assert.equal(await headings.nth(2).getAttribute('aria-current'), 'location')
    await headings.nth(2).press('Home'); await page.keyboard.press('ArrowRight')
    assert.equal(await headings.count(), 6)
    await panel.locator('[data-navigation-action=close]').click(); await toggle.click()
    const geometry = await page.locator('.docx-navigation-layout').evaluate(node => { const p = node.querySelector('[data-docx-navigation]').getBoundingClientRect(), e = node.querySelector('.editor-scroll').getBoundingClientRect(); return { panelRight: p.right, editorLeft: e.left, right: e.right, width: innerWidth } })
    assert.ok(geometry.panelRight <= geometry.editorLeft + 1); assert.ok(geometry.right <= geometry.width + 1)
    assert.equal(await editor.innerHTML(), before); assert.equal(await page.evaluate(() => JSON.stringify(localStorage)), storageBefore)
    assert.equal(requests.filter(request => request.path.endsWith('/save') || request.path.endsWith('/export')).length, 0)
    await page.screenshot({ path: resolve(output, editingEnabled ? 'editable.png' : 'readonly.png'), fullPage: true })
    actions.push({ editingEnabled, documentUnchanged: true, storageUnchanged: true, saveRequests: 0, headings: await headings.allTextContents(), geometry })
    if (editingEnabled) {
      await headings.nth(2).click(); await editor.evaluate(node => node.editor.view.focus()); await page.keyboard.press('Home'); await page.keyboard.type('新增')
      await page.waitForFunction(() => document.querySelector('[data-docx-navigation]')?.textContent.includes('新增继承正文标题'))
      const changed = await editor.innerHTML(), changedStorage = await page.evaluate(() => JSON.stringify(localStorage))
      await headings.last().click(); assert.equal(await editor.innerHTML(), changed); assert.equal(await page.evaluate(() => JSON.stringify(localStorage)), changedStorage)
      actions.push({ realtimeHeadingUpdate: true, navigationPreservesExistingDraft: true })
    }
    await page.close()
  }
  await Promise.all(identities); assert.deepEqual(errors, [])
  assert.equal(sha(await readFile(manifestPath)), manifestSha256); assert.equal(sha(await readFile(bridgePath)), bridgeSha256)
  assert.equal(sha(await readFile(fixturePath)), fixture.model.sourceSha256)
  const evidence = { ok: true, manifestSha256, bridgeSha256, browser: browser.version(), sourceSha256: fixture.model.sourceSha256, routeIsFixture: true, productionAuthTested: false, actions, requests, chunks: Object.fromEntries(chunks), errors }
  await writeFile(resolve(output, 'evidence.json'), JSON.stringify(evidence, null, 2)); console.log(JSON.stringify(evidence))
} catch (error) { await page?.screenshot({ path: resolve(output, 'failure.png'), fullPage: true }).catch(() => {}); throw error }
finally { await browser?.close(); await new Promise(resolve => server.close(resolve)) }
