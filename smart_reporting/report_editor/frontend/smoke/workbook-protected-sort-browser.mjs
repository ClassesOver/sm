// From frontend: node --max-old-space-size=4096 smoke/workbook-protected-sort-browser.mjs
import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { readFile } from 'node:fs/promises'
import { createServer } from 'node:http'
import Module from 'node:module'
import { resolve } from 'node:path'
import { build as bundle } from 'esbuild'
import { chromium } from 'playwright'
import { build } from 'vite'

const digest = bytes => createHash('sha256').update(bytes).digest('hex')
const xlsx = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
const engine = resolve('../../reporting/workbook_engine')
const modules = await bundle({
  stdin: {
    contents: "export { applyWorkbookOperations } from './bridge/operations'; export { createBlankWorkbook, readWorkbook } from './packages/xlsx-engine/src/index'",
    resolveDir: engine,
  },
  platform: 'node', format: 'cjs', bundle: true, write: false,
})
const compiled = new Module(resolve(engine, 'sort-smoke.cjs'))
compiled.filename = resolve(engine, 'sort-smoke.cjs')
compiled._compile(modules.outputFiles[0].text, compiled.filename)
const { applyWorkbookOperations, createBlankWorkbook, readWorkbook } = compiled.exports
const source = Buffer.from(await applyWorkbookOperations(await createBlankWorkbook(), [
  { kind: 'applyCellEdits', edits: [['Group', 'Score'], ['B', 3], ['A', 1], ['A', 4]].flatMap((values, row) =>
    values.map((value, column) => ({ sheetName: 'Sheet1', row, column, writeValue: true, cell: { value }, style: { protectionLocked: false } }))) },
  { kind: 'applyCellEdits', edits: [{ sheetName: 'Sheet1', row: 1, column: 2, writeValue: true, cell: { value: 'Locked' } }] },
  { kind: 'protectSheet', sheetName: 'Sheet1', protect: true, allow: { sort: true } },
]))

const built = await build({ configLoader: 'runner', logLevel: 'error', publicDir: false, build: {
  write: false, manifest: false, minify: false, rollupOptions: { input: resolve('native.html') },
} })
const assets = new Map([built].flat().flatMap(result => result.output.map(entry => [
  entry.fileName, entry.type === 'asset' ? entry.source : entry.code,
])))
assert(assets.has('native.html'))
const documentPath = '/reports/v1/native/protected-sort'
const assetPath = '/reports/v1/editor/assets/'
const revisionPath = revision => `${documentPath}/${revision}`
const responseJson = (res, body, status = 200) => {
  res.writeHead(status, { 'Content-Type': 'application/json' })
  res.end(JSON.stringify(body))
}
let saved, operations, routeError
const server = createServer(async (req, res) => {
  try {
    const path = new URL(req.url, 'http://localhost').pathname
    const bytes = path.startsWith(revisionPath(2)) ? saved : source
    for (const revision of [1, 2]) {
      if (path === revisionPath(revision) + '/api/context' && bytes) return responseJson(res, {
        context: {
          documentId: 'protected-sort', format: 'xlsx', revision, parentRevision: revision === 1 ? null : 1,
          scope: { database: 'fixture', companyId: 'fixture', userId: 'fixture', threadId: 'fixture' },
          sourceFile: { path: 'protected.xlsx', size: bytes.length, sha256: digest(bytes), mediaType: xlsx }, origin: 'upload',
        },
        csrfToken: 'fixture', capabilities: { xlsx_editor: true }, editingEnabled: true,
      })
      if (path === revisionPath(revision) + '/api/file' && bytes) {
        res.writeHead(200, { 'Content-Type': xlsx }); res.end(bytes); return
      }
    }
    if (path === revisionPath(1) + '/api/save') {
      assert(!saved, 'The same revision was saved twice')
      const chunks = []
      for await (const chunk of req) chunks.push(chunk)
      operations = JSON.parse(Buffer.concat(chunks).toString()).operations
      saved = Buffer.from(await applyWorkbookOperations(source, operations))
      return responseJson(res, {
        documentId: 'protected-sort', revision: 2, parentRevision: 1, revisionRegistered: true,
        artifacts: { xlsx: { downloadUrl: '/download.xlsx', size: saved.length, sha256: digest(saved) } },
        editor: { openUrl: revisionPath(2) }, validation: { ok: true, issues: [] },
      })
    }
    if (path === '/download.xlsx' && saved) {
      res.writeHead(200, { 'Content-Type': xlsx, 'Content-Disposition': 'attachment; filename=sorted.xlsx' })
      res.end(saved); return
    }
    const file = [revisionPath(1), revisionPath(2)].includes(path) ? 'native.html' : path.startsWith(assetPath) ? path.slice(assetPath.length) : ''
    if (!assets.has(file)) { res.writeHead(404); res.end(); return }
    const suffix = file.split('.').at(-1)
    const types = { html: 'text/html', js: 'text/javascript', css: 'text/css', woff2: 'font/woff2' }
    res.writeHead(200, { 'Content-Type': types[suffix] ?? 'application/octet-stream' })
    res.end(assets.get(file))
  } catch (error) { routeError = error; responseJson(res, { detail: String(error) }, 500) }
})
await new Promise(resolve => server.listen(0, '127.0.0.1', resolve))
const base = 'http://127.0.0.1:' + server.address().port
let browser, stage = 'launch'
try {
  const executablePath = process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE
  browser = await chromium.launch({ headless: true, ...(executablePath ? { executablePath } : {}) })
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } })
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  const go = async range => {
    await page.locator('[data-ribbon-tab="Home"]').click()
    await page.locator('[data-ribbon-command="goto-open"]').click()
    await page.locator('[data-goto-reference]').fill(range)
    await page.locator('.workbook-ribbon-goto-dialog [type="submit"]').click()
    await page.locator('.workbook-ribbon-goto-dialog').waitFor({ state: 'hidden' })
  }
  const selectSort = async command => {
    await page.locator('[data-ribbon-tab="Data"]').click()
    await page.locator('[data-ribbon-control="sort"]').selectOption(command)
  }
  stage = 'open'
  await page.goto(base + revisionPath(1))
  await page.waitForFunction(() => document.querySelector('#report-editor')?.getAttribute('aria-busy') === 'false', null, { timeout: 60000 })
  stage = 'locked range'
  await go('A1:C4')
  await selectSort('sort:asc')
  await page.getByText('排序范围包含锁定单元格', { exact: false }).waitFor()
  stage = 'custom sort'
  await go('A1:B4')
  await selectSort('sort-custom-open')
  const dialog = page.getByRole('dialog', { name: '自定义排序' })
  await dialog.locator('[data-sort-level="1"] [data-sort-column]').selectOption('1')
  await dialog.locator('[data-sort-level="1"] [data-sort-order]').selectOption('desc')
  await dialog.getByRole('button', { name: '确定' }).click()
  await dialog.waitFor({ state: 'hidden' })
  stage = 'save'
  await page.locator('[data-action="save"]').click()
  await page.getByText('已保存修订 2', { exact: false }).first().waitFor()
  assert.ifError(routeError)
  assert.deepEqual(operations, [{ kind: 'sortRange', sheetName: 'Sheet1', spec: {
    range: 'A1:B4', byColumn: 'A', ascending: true, hasHeader: true, thenBy: [{ byColumn: 'B', ascending: false }],
  } }])
  stage = 'download'
  const [downloaded] = await Promise.all([
    page.waitForEvent('download'),
    page.locator('[data-action="xlsx-download"]').click(),
  ])
  const output = await readFile(await downloaded.path())
  assert.equal(digest(output), digest(saved))
  const sheet = (await readWorkbook(output)).sheets[0]
  assert.deepEqual([1, 2, 3, 4].map(row => sheet.cells['B' + row]?.value), ['Score', 4, 1, 3])
  assert.equal(sheet.cells.C2.value, 'Locked')
  assert.equal(sheet.protection.protected, true)
  assert.equal(sheet.protection.allow.sort, true)
  assert.deepEqual(errors, [])
  console.log(JSON.stringify({ browser: browser.version(), savedSha256: digest(output), operations, errors }))
} catch (error) {
  throw new Error('Protected sort browser smoke failed at ' + stage, { cause: error })
} finally {
  await browser?.close()
  await new Promise(resolve => server.close(resolve))
}
