import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { once } from 'node:events'
import { spawn, spawnSync } from 'node:child_process'
import { copyFile, mkdir, readFile, writeFile } from 'node:fs/promises'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { setTimeout as delay } from 'node:timers/promises'
import { chromium } from 'playwright'

const frontend = process.env.SCATTER_VALUE_LABELS_FRONTEND_DIRECTORY ?? fileURLToPath(new URL('../', import.meta.url))
const repo = process.env.SCATTER_VALUE_LABELS_REPO_DIRECTORY ?? fileURLToPath(new URL('../../../../', import.meta.url))
const harnessPath = fileURLToPath(import.meta.url)
const fixturePath = join(frontend, 'smoke/workbook-scatter-value-labels-browser-fixture.py')
const out = process.env.SCATTER_VALUE_LABELS_DIRECTORY ?? '/dev/shm/office-scatter-value-labels-20261113/browser-run-1'
const staticRoot = process.env.PDF_SMOKE_STATIC_DIRECTORY
const engineRoot = process.env.AGENT_REPORTING_WORKBOOK_ENGINE_DIR
const serverWrapper = process.env.SCATTER_VALUE_LABELS_SERVER_WRAPPER
const port = Number(process.env.SCATTER_VALUE_LABELS_PORT ?? 4391)
const origin = `http://127.0.0.1:${port}`
const python = join(repo, '.venv/bin/python')
const sha = bytes => createHash('sha256').update(bytes).digest('hex')

assert.equal(process.env.SCATTER_VALUE_LABELS_RUN_AUTHORIZED, '1', 'root authorization is required before running this smoke')
assert(out.startsWith('/dev/shm/office-scatter-value-labels-20261113/'), 'evidence directory must stay on the requested tmpfs path')
assert(staticRoot, 'PDF_SMOKE_STATIC_DIRECTORY must point to the frozen static build')
assert(engineRoot, 'AGENT_REPORTING_WORKBOOK_ENGINE_DIR must point to the isolated workbook engine')
await mkdir(out, { recursive: false })

const frozenInputs = {}
for (const path of [harnessPath, fixturePath, ...(serverWrapper ? [serverWrapper] : [])]) {
  const name = path.slice(path.lastIndexOf('/') + 1)
  const copy = join(out, name)
  await copyFile(path, copy)
  frozenInputs[name] = sha(await readFile(copy))
}
await writeFile(join(out, 'harness-inputs.json'), JSON.stringify(frozenInputs, null, 2))

const fixtureCopy = join(out, 'workbook-scatter-value-labels-browser-fixture.py')
const fixture = spawnSync(python, [fixtureCopy, join(out, 'fixture.xlsx')], { cwd: repo, encoding: 'utf8' })
assert.equal(fixture.status, 0, fixture.stderr)
const manifestPath = join(staticRoot, '.vite/manifest.json')
const manifestSha256 = sha(await readFile(manifestPath))
const enginePath = join(engineRoot, 'dist/cli.mjs')
const runtimeBefore = { path: enginePath, sha256: sha(await readFile(enginePath)) }
const inspectRequestPath = join(out, 'fixture-inspect-request.json')
await writeFile(inspectRequestPath, JSON.stringify({ kind: 'inspect', input: join(out, 'fixture.xlsx') }, null, 2))
const inspection = spawnSync(process.execPath, [enginePath, inspectRequestPath], { cwd: repo, encoding: 'utf8' })
await writeFile(join(out, 'fixture-inspect.stdout.json'), inspection.stdout ?? '')
await writeFile(join(out, 'fixture-inspect.stderr.log'), inspection.stderr ?? '')
assert.equal(inspection.status, 0, inspection.stderr)
const inspectedFixture = JSON.parse(inspection.stdout)
const inspectedSheet = inspectedFixture.sheets.find(sheet => sheet.name === 'Scatter labels')
assert(inspectedSheet, 'the inspected workbook must contain the actual fixture worksheet')
const expectedCells = { B2: 0, B3: 0.25, B4: null, B5: 0.5, D2: 0, D3: 1.25, D4: null, D5: 2.5 }
for (const [address, value] of Object.entries(expectedCells)) assert.equal(inspectedSheet.cells[address]?.value ?? null, value, `actual worksheet cell ${address}`)
const sourceSeries = [
  { title: 'Scatter value labels', valuesRef: "'Scatter labels'!$B$2:$B$5", xValuesRef: "'Scatter labels'!$A$2:$A$5", numberFormat: '0%' },
  { title: 'Scatter no labels', valuesRef: "'Scatter labels'!$D$2:$D$5", xValuesRef: "'Scatter labels'!$C$2:$C$5", numberFormat: '0.00' },
]
for (const expected of sourceSeries) {
  const series = inspectedSheet.charts.find(chart => chart.title === expected.title)?.series[0]
  assert(series, `the actual fixture chart ${expected.title} must have its source series`)
  for (const key of ['valuesRef', 'xValuesRef', 'numberFormat']) assert.equal(series[key], expected[key])
}
const fixtureInspectionIdentity = { inputSha256: sha(await readFile(join(out, 'fixture.xlsx'))), runtime: runtimeBefore, exitCode: inspection.status, expectedCells, sourceSeries }
await writeFile(join(out, 'fixture-inspect-identity.json'), JSON.stringify(fixtureInspectionIdentity, null, 2))
const wrapperCopy = serverWrapper ? join(out, serverWrapper.slice(serverWrapper.lastIndexOf('/') + 1)) : undefined
const server = spawn(python, [...(wrapperCopy ? [wrapperCopy] : []), join(frontend, 'smoke/workbook-ai-charts-server.py'), '--directory', out, '--port', String(port), '--source', join(out, 'fixture.xlsx')], {
  cwd: repo,
  env: { ...process.env, PYTHONPATH: repo, PDF_SMOKE_STATIC_DIRECTORY: staticRoot },
  stdio: 'pipe',
})
let serverLog = '', browser, page, initialState, stage = 'server'
server.stdout.on('data', data => { serverLog += data })
server.stderr.on('data', data => { serverLog += data })
const errors = [], consoleErrors = [], httpErrors = [], assetHashes = {}, assetChecks = []

try {
  for (let attempt = 0; ; attempt++) {
    assert.equal(server.exitCode, null, serverLog)
    try {
      const response = await fetch(origin + '/__smoke__/state', { signal: AbortSignal.timeout(1500) })
      if (response.ok) { initialState = await response.json(); break }
    } catch {}
    assert(attempt < 240, serverLog)
    await delay(250)
  }
  await writeFile(join(out, 'initial-state.json'), JSON.stringify(initialState, null, 2))

  const info = JSON.parse(await readFile(join(out, 'server-info.json'), 'utf8'))
  browser = await chromium.launch({ headless: true, ...(process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE ? { executablePath: process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE } : {}) })
  page = await browser.newPage({ viewport: { width: 1600, height: 1050 }, acceptDownloads: true })
  page.setDefaultTimeout(20000)
  page.on('pageerror', error => errors.push(error.message))
  page.on('console', message => { if (message.type() === 'error') consoleErrors.push(message.text()) })
  page.on('response', response => {
    const path = new URL(response.url()).pathname
    if (response.status() >= 400) httpErrors.push({ path, status: response.status() })
    if (path.startsWith('/reports/v1/editor/assets/') && /\.(?:js|css)$/.test(path)) assetChecks.push((async () => {
      const bytes = await response.body()
      const disk = await readFile(join(staticRoot, decodeURIComponent(path.slice('/reports/v1/editor/assets/'.length))))
      assert.equal(sha(bytes), sha(disk), `served asset differs: ${path}`)
      assetHashes[path] = sha(bytes)
    })())
  })
  await page.addInitScript(() => {
    window.__scatterValueLabels = []
    window.__scatterLinePoints = []
    const ids = new WeakMap()
    let nextId = 0
    const canvasId = canvas => {
      if (!ids.has(canvas)) ids.set(canvas, ++nextId)
      return ids.get(canvas)
    }
    const matrix = ctx => {
      const m = ctx.getTransform()
      return { a: m.a, b: m.b, c: m.c, d: m.d, e: m.e, f: m.f }
    }
    const fillText = CanvasRenderingContext2D.prototype.fillText
    CanvasRenderingContext2D.prototype.fillText = function (text, x, y, maxWidth) {
      if (this.font === '9px system-ui') window.__scatterValueLabels.push({ text: String(text), x, y, canvasId: canvasId(this.canvas), transform: matrix(this), textAlign: this.textAlign, textBaseline: this.textBaseline })
      return fillText.call(this, text, x, y, maxWidth)
    }
    const paths = new WeakMap()
    const beginPath = CanvasRenderingContext2D.prototype.beginPath
    CanvasRenderingContext2D.prototype.beginPath = function () {
      paths.set(this, [])
      return beginPath.call(this)
    }
    for (const method of ['moveTo', 'lineTo']) {
      const draw = CanvasRenderingContext2D.prototype[method]
      CanvasRenderingContext2D.prototype[method] = function (x, y) {
        const path = paths.get(this) ?? []
        path.push({ method, x, y, canvasId: canvasId(this.canvas), transform: matrix(this) })
        paths.set(this, path)
        return draw.call(this, x, y)
      }
    }
    const stroke = CanvasRenderingContext2D.prototype.stroke
    CanvasRenderingContext2D.prototype.stroke = function (...args) {
      if (args.length === 0 && this.lineWidth > 0) {
        for (const point of paths.get(this) ?? []) window.__scatterLinePoints.push({ ...point, strokeStyle: String(this.strokeStyle).toLowerCase() })
      }
      return stroke.apply(this, args)
    }
  })

  const ready = () => page.waitForFunction(() => document.querySelector('#report-editor')?.getAttribute('aria-busy') === 'false', null, { timeout: 90000 })
  const command = async id => {
    await page.locator('[data-ribbon-tab="Chart Design"]').click()
    await page.locator(`[data-ribbon-command="${id}"]`).click()
  }
  const pane = () => page.locator('.workbook-chart-format-pane:not([hidden])')
  const charts = () => page.evaluate(() => [...window.__sheetsWebCharts.store.values()].flat().map(chart => ({
    title: chart.title,
    chartPath: chart.chartPath,
    kind: chart.kind,
    design: chart.design,
    dataLabels: chart.dataLabels,
    series: chart.series.map(series => ({ numberFormat: series.numberFormat, marker: series.marker, valuesRef: series.valuesRef, xValuesRef: series.xValuesRef, values: series.values, xValues: series.xValues })),
  })))
  const draft = () => page.evaluate(() => Object.entries(localStorage).filter(([key]) => key.startsWith('native-editor-draft:')).flatMap(([, value]) => JSON.parse(value).operations ?? []))
  const selectChart = async chart => {
    if (await pane().count()) await pane().getByRole('button', { name: '关闭图表格式', exact: true }).click()
    await command('chart-descriptions')
    await page.locator(`[data-select-chart="${chart.chartPath}"]`).click()
    await command('chart-format-pane')
    await pane().waitFor()
  }
  const decimalLabelGeometry = async () => {
    const expected = ['0.00', '1.25', '2.50']
    await page.waitForFunction(texts => texts.every(text => window.__scatterValueLabels.some(label => label.text === text)), expected)
    const samples = await page.evaluate(() => window.__scatterValueLabels.filter(label => ['0.00', '1.25', '2.50'].includes(label.text)))
    const linePoints = await page.evaluate(() => window.__scatterLinePoints)
    const identity = label => JSON.stringify([label.text, label.x, label.y, label.canvasId, label.transform])
    const labels = [...new Map(samples.map(label => [identity(label), label])).values()]
    assert.deepEqual(labels.map(label => label.text).sort(), expected)
    for (const label of labels) {
      assert.equal(label.textAlign, 'center')
      assert.equal(label.textBaseline, 'alphabetic')
      const point = linePoints.find(candidate => candidate.canvasId === label.canvasId && candidate.strokeStyle === '#1b7f5a' && candidate.x === label.x && candidate.y === label.y + 8 && JSON.stringify(candidate.transform) === JSON.stringify(label.transform))
      assert(point, `decimal label ${label.text} must be centered 8 canvas units above its actual scatter point`)
    }
    return { samples, labels, linePoints }
  }

  stage = 'open'
  await page.goto(origin + info.openPath)
  await ready()
  await page.waitForFunction(() => [...(window.__sheetsWebCharts?.store.values() ?? [])].flat().length === 2)
  await page.waitForFunction(() => window.__scatterValueLabels?.some(label => label.text === '0%'))
  const initialCharts = await charts()
  assert.equal(initialCharts.length, 2)
  const byTitle = title => initialCharts.find(chart => chart.title === title)
  const valueChart = byTitle('Scatter value labels')
  const noneChart = byTitle('Scatter no labels')
  assert(valueChart && noneChart)
  for (const chart of initialCharts) {
    assert.equal(chart.kind, 'scatter')
    assert.equal(chart.series.length, 1)
    assert.equal(chart.series[0].marker, 'none')
    const expected = sourceSeries.find(series => series.title === chart.title)
    assert(expected)
    assert.equal(chart.series[0].valuesRef, expected.valuesRef)
    assert.equal(chart.series[0].xValuesRef, expected.xValuesRef)
  }
  assert.equal(valueChart.series[0].numberFormat, '0%')
  assert.equal(noneChart.series[0].numberFormat, '0.00')
  assert.equal(valueChart.dataLabels?.showValue, true)
  assert.equal(noneChart.dataLabels?.showValue, false)
  const initialDraft = await draft()
  assert.equal(initialDraft.length, 0)

  const initialLabels = await page.evaluate(() => window.__scatterValueLabels)
  const initialLinePoints = await page.evaluate(() => window.__scatterLinePoints)
  const percentageSamples = initialLabels.filter(label => ['0%', '25%', '50%'].includes(label.text))
  const labelIdentity = label => JSON.stringify([label.text, label.x, label.y, label.canvasId, label.transform])
  const percentageLabels = [...new Map(percentageSamples.map(label => [labelIdentity(label), label])).values()]
  assert.deepEqual(percentageLabels.map(label => label.text).sort(), ['0%', '25%', '50%'])
  assert.equal(initialLabels.some(label => label.text === '0.00' || label.text === '1.25' || label.text === '2.50'), false)
  for (const label of percentageLabels) {
    assert.equal(label.textAlign, 'center')
    assert.equal(label.textBaseline, 'alphabetic')
    const point = initialLinePoints.find(candidate => candidate.canvasId === label.canvasId && candidate.strokeStyle === '#1b7f5a' && candidate.transform.a === label.transform.a && candidate.transform.d === label.transform.d && candidate.x === label.x && candidate.y === label.y + 8)
    assert(point, `label ${label.text} must be horizontally centered and 8 canvas units above its scatter point`)
    assert.deepEqual(label.transform, point.transform)
  }

  await selectChart(valueChart)
  assert.equal(await pane().getByLabel('数据标签', { exact: true }).inputValue(), 'value')
  assert.equal(await pane().getByLabel('标签数字格式', { exact: true }).count(), 0)
  assert.equal(await pane().getByLabel('标签位置', { exact: true }).count(), 0)
  assert.deepEqual(await pane().getByLabel('数据标签', { exact: true }).locator('option').allTextContents(), ['无', '值'])
  await page.screenshot({ path: join(out, 'initial-value-and-none.png'), fullPage: true })

  await selectChart(noneChart)
  assert.equal(await pane().getByLabel('数据标签', { exact: true }).inputValue(), 'none')
  assert.equal(await pane().getByLabel('标签数字格式', { exact: true }).count(), 0)
  assert.equal(await pane().getByLabel('标签位置', { exact: true }).count(), 0)
  assert.deepEqual(await pane().getByLabel('数据标签', { exact: true }).locator('option').allTextContents(), ['无', '值'])
  const draftCount = (await draft()).length
  await pane().getByLabel('数据标签', { exact: true }).selectOption('value')
  await page.waitForFunction(count => Object.entries(localStorage).filter(([key]) => key.startsWith('native-editor-draft:')).flatMap(([, value]) => JSON.parse(value).operations ?? []).length > count, draftCount)
  await page.waitForFunction(() => !document.querySelector('.workbook-chart-format-pane:not([hidden])')?.hasAttribute('aria-busy'))
  const editedDraft = await draft()
  assert.equal(editedDraft.length, draftCount + 1)
  assert(editedDraft.every(operation => operation.kind === 'applyChartEdits' && operation.edits.every(edit => edit.chartPath === noneChart.chartPath && edit.dataLabels === 'value')))
  const editedDecimalLabelGeometry = await decimalLabelGeometry()
  await page.screenshot({ path: join(out, 'draft-value-and-value.png'), fullPage: true })
  await pane().getByRole('button', { name: '关闭图表格式', exact: true }).click()

  stage = 'save'
  const saveResponse = page.waitForResponse(response => response.url().endsWith('/api/save') && response.request().method() === 'POST')
  await page.locator('[data-action="save"]').click()
  const response = await saveResponse
  const saved = await response.json()
  assert.equal(response.status(), 200, JSON.stringify(saved))
  assert.equal(saved.revisionRegistered, true)
  const [download] = await Promise.all([page.waitForEvent('download'), page.locator('[data-action="xlsx-download"]').click()])
  await download.saveAs(join(out, 'scatter-value-labels.xlsx'))
  assert.equal(sha(await readFile(join(out, 'scatter-value-labels.xlsx'))), saved.artifacts.xlsx.sha256)
  await writeFile(join(out, 'save-response.json'), JSON.stringify(saved, null, 2))

  stage = 'reopen'
  await page.goto(saved.editor.openUrl)
  await ready()
  await page.waitForFunction(() => [...(window.__sheetsWebCharts?.store.values() ?? [])].flat().length === 2)
  const reopened = await charts()
  const reopenedValue = reopened.find(chart => chart.title === 'Scatter value labels')
  const reopenedEdited = reopened.find(chart => chart.title === 'Scatter no labels')
  assert.equal(reopenedValue?.dataLabels?.showValue, true)
  assert.equal(reopenedEdited?.dataLabels?.showValue, true)
  assert.equal(reopenedValue?.series[0]?.numberFormat, '0%')
  assert.equal(reopenedEdited?.series[0]?.numberFormat, '0.00')
  const reopenedDecimalLabelGeometry = await decimalLabelGeometry()
  await selectChart(reopenedValue)
  assert.equal(await pane().getByLabel('数据标签', { exact: true }).inputValue(), 'value')
  assert.equal(await pane().getByLabel('标签数字格式', { exact: true }).count(), 0)
  assert.equal(await pane().getByLabel('标签位置', { exact: true }).count(), 0)
  await selectChart(reopenedEdited)
  assert.equal(await pane().getByLabel('数据标签', { exact: true }).inputValue(), 'value')
  assert.equal(await pane().getByLabel('标签数字格式', { exact: true }).count(), 0)
  assert.equal(await pane().getByLabel('标签位置', { exact: true }).count(), 0)
  await page.screenshot({ path: join(out, 'reopened.png'), fullPage: true })

  await Promise.all(assetChecks)
  assert(assetChecks.length > 0)
  assert.deepEqual(errors, [])
  assert.deepEqual(consoleErrors, [])
  assert.deepEqual(httpErrors, [])
  assert.equal(sha(await readFile(manifestPath)), manifestSha256)
  const state = await (await page.request.get(origin + '/__smoke__/state')).json()
  assert.equal(state.plannerCalls, 0)
  assert.equal(state.savedRevisions, 1)
  const runtimeAfter = { path: enginePath, sha256: sha(await readFile(enginePath)) }
  assert.deepEqual(runtimeAfter, runtimeBefore)
  await writeFile(join(out, 'evidence.json'), JSON.stringify({
    ok: true,
    browserVersion: browser.version(),
    sourceSha256: info.sourceSha256,
    downloadedSha256: saved.artifacts.xlsx.sha256,
    initialCharts,
    reopenedCharts: reopened,
    initialLabelSamples: initialLabels,
    uniqueInitialLabels: percentageLabels,
    initialLabels: percentageLabels,
    rawLinePoints: initialLinePoints,
    editedDecimalLabelGeometry,
    reopenedDecimalLabelGeometry,
    editedDraft,
    state,
    manifestSha256,
    assetHashes,
    runtimeBefore,
    runtimeAfter,
    frozenInputs,
    fixtureInspectionIdentity,
    initialState,
    serverPid: server.pid,
    errors,
    consoleErrors,
    httpErrors,
  }, null, 2))
  console.log(JSON.stringify({ ok: true, directory: out, savedRevisions: state.savedRevisions, assets: assetChecks.length }))
} catch (error) {
  const state = await fetch(origin + '/__smoke__/state', { signal: AbortSignal.timeout(1500) }).then(response => response.json()).catch(() => null)
  await writeFile(join(out, 'failure.json'), JSON.stringify({ stage, error: String(error), stack: error.stack, serverLog, state, initialState, serverPid: server.pid, errors, consoleErrors, httpErrors }, null, 2))
  await page?.screenshot({ path: join(out, 'failure.png'), fullPage: true }).catch(() => {})
  throw error
} finally {
  await browser?.close()
  if (server.exitCode === null) {
    const exited = once(server, 'exit')
    server.kill('SIGTERM')
    await exited
  }
  await writeFile(join(out, 'server.log'), serverLog)
}
