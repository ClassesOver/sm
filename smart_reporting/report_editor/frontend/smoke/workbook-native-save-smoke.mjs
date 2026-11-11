import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { mkdir, writeFile } from 'node:fs/promises'
import { spawn, spawnSync } from 'node:child_process'
import { setTimeout as delay } from 'node:timers/promises'
import { chromium } from 'playwright'

const frontend = process.cwd()
const repo = new URL('../../../', `file://${frontend}/`).pathname
const port = Number(process.env.WORKBOOK_SMOKE_PORT ?? 4189)
const smokeCase = process.env.WORKBOOK_SMOKE_CASE ?? 'format-autosum'
if (!['format-autosum', 'sort', 'row-column', 'draft-recovery', 'structural-undo', 'rotation'].includes(smokeCase)) throw new Error(`Unknown workbook smoke case: ${smokeCase}`)
const baseUrl = `http://127.0.0.1:${port}`
const runPython = input => {
  const result = spawnSync(process.env.WORKBOOK_SMOKE_PYTHON ?? `${repo}/.venv/bin/python`, ['-c', `
import base64, json, sys
from io import BytesIO
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font
from openpyxl.workbook.defined_name import DefinedName
payload = json.load(sys.stdin)
if payload['mode'] == 'create':
    book = Workbook()
    sheet = book.active
    sheet.title = 'Summary'
    if payload['scenario'] == 'rotation':
        sheet['A1'] = 'Rotated source'
        sheet['A1'].alignment = Alignment(textRotation=135, horizontal='center', wrap_text=True, indent=2)
        sheet['A1'].font = Font(name='Calibri', size=14, bold=True, italic=True, color='194361')
        sheet['B1'] = '=1+1'
        sheet['B1'].alignment = Alignment(textRotation=90)
        sheet['B1'].number_format = '0.00'
        sheet['C1'] = 'Untouched stacked'
        sheet['C1'].alignment = Alignment(textRotation=255)
        sheet['D1'] = 'merged'
        sheet.merge_cells('D1:E2')
        book.defined_names.add(DefinedName('Revenue', attr_text='Summary!$A$1'))
    elif payload['scenario'] == 'sort':
        sheet['A1'] = 'zeta'
        sheet['A2'] = 'alpha'
    elif payload['scenario'] == 'structural-undo':
        sheet['A1'] = 'original'
        sheet['A2'] = 'second'
        sheet['B2'] = '=A1'
        sheet['C1'] = 'merged'
        sheet.merge_cells('C1:D2')
        book.defined_names.add(DefinedName('Revenue', attr_text='Summary!$A$1'))
    elif payload['scenario'] == 'row-column':
        sheet['A1'] = 'header'
        sheet['A2'] = 'value'
        sheet['B2'] = '=LEN(A2)'
        sheet['B2'].number_format = '0.00'
    else:
        sheet['A1'] = 12.34
        sheet['A2'] = 2
        sheet['B1'] = '=1+1'
    stream = BytesIO(); book.save(stream)
    print(base64.b64encode(stream.getvalue()).decode())
elif payload['mode'] == 'patch':
    from smart_reporting.report_editor.native_office import patch_office
    content = base64.b64decode(payload['bytes'])
    result = patch_office('xlsx', content, payload['operations'])
    print(base64.b64encode(result).decode())
elif payload['mode'] == 'inspect':
    book = load_workbook(BytesIO(base64.b64decode(payload['bytes'])), data_only=False)
    sheet = book['Summary']
    if payload['scenario'] == 'rotation':
        print(json.dumps({'rotation':sheet['A1'].alignment.textRotation,'horizontal':sheet['A1'].alignment.horizontal,'wrap':sheet['A1'].alignment.wrap_text,'indent':sheet['A1'].alignment.indent,
            'bold':sheet['A1'].font.bold,'italic':sheet['A1'].font.italic,'fontSize':sheet['A1'].font.sz,'formula':sheet['B1'].value,'formulaRotation':sheet['B1'].alignment.textRotation,'formulaNumberFormat':sheet['B1'].number_format,
            'untouchedRotation':sheet['C1'].alignment.textRotation,'definedName':book.defined_names['Revenue'].attr_text,'merges':list(map(str,sheet.merged_cells.ranges))}))
        sys.exit(0)
    if payload['scenario'] == 'sort':
        print(json.dumps({'values': [sheet['A1'].value, sheet['A2'].value], 'sheets': book.sheetnames}))
        sys.exit(0)
    if payload['scenario'] == 'row-column':
        print(json.dumps({'values': [sheet['A1'].value, sheet['A2'].value, sheet['A3'].value], 'formula': sheet['B2'].value, 'numberFormat': sheet['B2'].number_format, 'sheets': book.sheetnames}))
        sys.exit(0)
    if payload['scenario'] == 'structural-undo':
        print(json.dumps({'values': [sheet['A1'].value, sheet['A2'].value], 'formula': sheet['B2'].value, 'definedName': book.defined_names['Revenue'].attr_text, 'merges': list(map(str, sheet.merged_cells.ranges)), 'sheets': book.sheetnames}))
        sys.exit(0)
    font = sheet['A1'].font
    print(json.dumps({'value': sheet['A1'].value, 'secondValue': sheet['A2'].value, 'bold': font.bold, 'fontName': font.name, 'fontSize': font.sz, 'fontColor': font.color.rgb if font.color and font.color.type == 'rgb' else None, 'numberFormat': sheet['A1'].number_format, 'formula': sheet['B1'].value, 'autoSum': sheet['A3'].value, 'sheets': book.sheetnames}))
`], { cwd: repo, env: { ...process.env, PYTHONPATH: repo }, input: JSON.stringify(input), encoding: 'utf8', maxBuffer: 20 * 1024 * 1024 })
  if (result.status !== 0) throw new Error(result.stderr || `python exited ${result.status}`)
  return result.stdout.trim()
}
const sourceBytes = Buffer.from(runPython({ mode: 'create', scenario: smokeCase }), 'base64')
const sourceSha = createHash('sha256').update(sourceBytes).digest('hex')
let savedBytes
let savePayload
const saveAttempts = []
const builtDirectory = process.env.WORKBOOK_SMOKE_BUILD_DIR
const server = spawn('./node_modules/.bin/vite', [
  ...(builtDirectory ? ['preview', '--outDir', builtDirectory] : []),
  '--host', '127.0.0.1', '--port', String(port), '--strictPort',
], { cwd: frontend, stdio: 'ignore' })
let browser
try {
  for (let attempt = 0; attempt < 100; attempt++) {
    try { if ((await fetch(`${baseUrl}/reports/v1/editor/assets/native.html`)).ok) break } catch {}
    await delay(250)
  }
  browser = await chromium.launch({ headless: true, ...(process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE ? { executablePath: process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE } : {}) })
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, acceptDownloads: true })
  const pageErrors = []
  const failedResponses = []
  page.on('pageerror', error => pageErrors.push(error.message))
  page.on('console', message => {
    if (message.type() !== 'error') return
    if (smokeCase === 'draft-recovery' && message.location().url.endsWith('/api/save') && message.text().includes('503')) return
    pageErrors.push(message.text())
  })
  page.on('dialog', dialog => dialog.accept())
  page.on('response', response => { if (response.status() >= 400) failedResponses.push({ status: response.status(), url: response.url() }) })
  await page.route('**/reports/v1/native/fixture-xlsx/1/api/context', route => route.fulfill({ json: {
    context: { documentId: 'fixture-xlsx', format: 'xlsx', revision: 1, parentRevision: null,
      scope: { database: 'fixture', companyId: 'fixture', userId: 'fixture', threadId: 'fixture' },
      sourceFile: { path: 'fixture.xlsx', size: sourceBytes.length, sha256: sourceSha, mediaType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' }, origin: 'upload' },
    csrfToken: 'fixture-csrf', capabilities: { xlsx_editor: true }, editingEnabled: true,
  } }))
  await page.route('**/reports/v1/native/fixture-xlsx/1/api/file', route => route.fulfill({ body: sourceBytes, contentType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' }))
  await page.route('**/reports/v1/native/fixture-xlsx/1/api/save', async route => {
    savePayload = route.request().postDataJSON()
    saveAttempts.push(savePayload)
    if (smokeCase === 'draft-recovery' && saveAttempts.length < 3) {
      await route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ detail: '注入保存网络故障' }) })
      return
    }
    const encoded = runPython({ mode: 'patch', bytes: sourceBytes.toString('base64'), operations: savePayload.operations })
    savedBytes = Buffer.from(encoded, 'base64')
    const sha256 = createHash('sha256').update(savedBytes).digest('hex')
    await route.fulfill({ json: { documentId: 'fixture-xlsx', revision: 2, parentRevision: 1, revisionRegistered: true,
      artifacts: { xlsx: { downloadUrl: '/fixture-download.xlsx', size: savedBytes.length, sha256 } },
      editor: { openUrl: '/reports/v1/native/fixture-xlsx/2' }, validation: { ok: true, issues: [] } } })
  })
  await page.route('**/fixture-download.xlsx', route => route.fulfill({ body: savedBytes, contentType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' }))
  await page.route('**/reports/v1/native/fixture-xlsx/2/api/context', route => route.fulfill({ json: {
    context: { documentId: 'fixture-xlsx', format: 'xlsx', revision: 2, parentRevision: 1, scope: { database: 'fixture', companyId: 'fixture', userId: 'fixture', threadId: 'fixture' }, sourceFile: { path: 'saved.xlsx', size: savedBytes.length, sha256: createHash('sha256').update(savedBytes).digest('hex'), mediaType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' }, origin: 'upload' }, csrfToken: 'fixture-csrf', capabilities: { xlsx_editor: true }, editingEnabled: true,
  } }))
  await page.route('**/reports/v1/native/fixture-xlsx/2/api/file', route => route.fulfill({ body: savedBytes, contentType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' }))
  await page.addInitScript(() => history.replaceState(null, '', `/reports/v1/native/fixture-xlsx/${new URL(location.href).searchParams.get('revision') === '2' ? 2 : 1}`))
  await page.goto(`${baseUrl}/reports/v1/editor/assets/native.html`)
  try { await page.locator('.workbook-ribbon').waitFor({ timeout: 60000 }) }
  catch { throw new Error(JSON.stringify({ url: page.url(), body: (await page.locator('body').innerText()).slice(0, 1000), pageErrors, failedResponses })) }
  await page.waitForFunction(() => document.querySelectorAll('.workbook-grid canvas').length >= 1, null, { timeout: 60000 })
  const geometry = await page.evaluate(() => Object.fromEntries(['#app', '.report-workspace', '.editor-surface', '#report-editor', '.workbook-grid', '.workbook-grid canvas']
    .map(selector => { const element = document.querySelector(selector); const rect = element?.getBoundingClientRect(); return [selector, rect ? { width: rect.width, height: rect.height, display: getComputedStyle(element).display } : null] })))
  if (!geometry['.workbook-grid']?.width || !geometry['.workbook-grid']?.height) throw new Error(JSON.stringify({ geometry, pageErrors, failedResponses }))
  if (!await page.locator('.workbook-grid canvas').count()) throw new Error(JSON.stringify({ url: page.url(), body: await page.locator('body').innerText(), pageErrors, failedResponses }))
  if (smokeCase === 'rotation') {
    const persistedRotation = angle => page.waitForFunction(({ expected, fallback }) => Object.keys(localStorage).filter(key => key.startsWith('native-editor-draft:')).some(key => {
      const edits = JSON.parse(localStorage.getItem(key)).operations.flatMap(op => op.kind === 'applyCellEdits' ? op.edits : [])
      return (edits.filter(edit => edit.row === 0 && edit.column === 0 && edit.style?.textRotation !== undefined).at(-1)?.style.textRotation ?? fallback) === expected
    }), { expected: angle, fallback: 135 })
    await page.locator('.workbook-grid').click({ position: { x: 120, y: 36 } })
    assert.equal(await page.locator('[data-ribbon-command="rotate:-45"]').getAttribute('aria-pressed'), 'true')
    for (const [id, angle] of [['45',45],['vertical',255],['-45',135],['90',90],['-90',180],['0',0]]) {
      await page.locator(`[data-ribbon-command="rotate:${id}"]`).click(); await persistedRotation(angle)
      assert.equal(await page.locator(`[data-ribbon-command="rotate:${id}"]`).getAttribute('aria-pressed'), 'true')
    }
    await page.locator('.workbook-grid').click({ position: { x: 120, y: 36 } }); await page.keyboard.press('Control+z'); await persistedRotation(180)
    await page.keyboard.press('Control+y'); await persistedRotation(0)
    await page.goto(`${baseUrl}/reports/v1/editor/assets/native.html`)
    await page.waitForFunction(() => document.querySelectorAll('.workbook-grid canvas').length >= 1, null, { timeout: 60000 })
    await page.locator('.workbook-grid').click({ position: { x: 120, y: 36 } })
    assert.equal(await page.locator('[data-ribbon-command="rotate:0"]').getAttribute('aria-pressed'), 'true')
  } else if (smokeCase === 'structural-undo') {
    const persistedStructure = async present => page.waitForFunction(expected => Object.keys(localStorage)
      .filter(key => key.startsWith('native-editor-draft:')).some(key => {
        const operations = JSON.parse(localStorage.getItem(key)).operations
        return operations.some(operation => operation.kind === 'applyRowColumnOps') === expected
      }), present)
    await page.locator('.workbook-grid').click({ position: { x: 120, y: 36 } })
    await page.locator('[data-ribbon-command="delete-row-here"]').click()
    await persistedStructure(true)
    await page.locator('.workbook-grid').click({ position: { x: 120, y: 36 } })
    await page.keyboard.press('Control+z')
    await persistedStructure(false)
    await page.keyboard.press('Control+y')
    await persistedStructure(true)
    await page.keyboard.press('Control+z')
    await persistedStructure(false)
  } else if (smokeCase === 'sort') {
    await page.locator('.workbook-grid').click({ position: { x: 120, y: 36 } })
    await page.keyboard.press('Shift+ArrowDown')
    await page.locator('[data-ribbon-tab="Data"]').click()
    await page.locator('[data-ribbon-command="sort:asc"]').click()
    const feedback = await page.locator('.workbook-feedback').innerText()
    if (!feedback.includes('Selection updated')) throw new Error(`Sort command was not applied: ${feedback}`)
  } else if (smokeCase === 'row-column') {
    await page.locator('.workbook-grid').click({ position: { x: 120, y: 36 } })
    await page.locator('[data-ribbon-command="insert-row-here"]').click()
    await page.locator('.workbook-grid').click({ position: { x: 120, y: 56 } })
    await page.locator('[data-ribbon-command="delete-row-here"]').click()
    await page.locator('.workbook-grid').click({ position: { x: 120, y: 36 } })
    await page.locator('[data-ribbon-command="insert-col-here"]').click()
    await page.locator('.workbook-grid').click({ position: { x: 120, y: 36 } })
    await page.locator('[data-ribbon-command="delete-col-here"]').click()
    const feedback = await page.locator('.workbook-feedback').innerText()
    if (!feedback.includes('Selection updated')) throw new Error(`Row/column command was not applied: ${feedback}`)
  } else {
    await page.locator('.workbook-grid').click({ position: { x: 120, y: 36 } })
    await page.locator('[data-ribbon-command="bold"]').click()
    await page.locator('[data-ribbon-control="font-family"]').selectOption('Calibri')
    await page.locator('[data-ribbon-control="font-size"]').selectOption('14')
    await page.locator('[data-ribbon-control="font-color"]').fill('#cc0000')
    await page.locator('[data-ribbon-command="format:0.00"]').click()
    await page.locator('[data-ribbon-command="decimal-inc"]').click()
    await page.locator('.workbook-grid').click({ position: { x: 120, y: 36 } })
    await page.keyboard.press('Shift+ArrowDown')
    await page.locator('[data-ribbon-command="autofn:SUM"]').click()
    await page.locator('[data-ribbon-command="rotate:45"]').evaluate(button => {
      if (button.disabled) throw new Error('persistable text rotation command must be available')
    })
  }
  if (smokeCase === 'draft-recovery') {
    const persistedBold = async bold => {
      await page.waitForFunction(expected => Object.keys(localStorage).filter(key => key.startsWith('native-editor-draft:'))
        .some(key => JSON.parse(localStorage.getItem(key)).operations.flatMap(op => op.kind === 'applyCellEdits'
          ? op.edits.filter(edit => edit.row === 0 && edit.column === 0 && edit.style?.bold !== undefined) : []).at(-1)?.style.bold === expected), bold)
    }
    await persistedBold(true)
    await page.goto(`${baseUrl}/reports/v1/editor/assets/native.html`)
    await page.waitForFunction(() => document.querySelectorAll('.workbook-grid canvas').length >= 1, null, { timeout: 60000 })
    assert.ok((await page.locator('.save-state-label').innerText()).includes('已恢复本地草稿'))
    // 真实网格必须恢复加粗；再次点击会取消，Univer 撤销/重做也必须更新同一个持久化草稿。
    await page.locator('.workbook-grid').click({ position: { x: 120, y: 36 } })
    await page.locator('[data-ribbon-command="bold"]').click()
    await persistedBold(false)
    await page.locator('.workbook-grid').click({ position: { x: 120, y: 36 } })
    await page.keyboard.press('Control+z')
    await persistedBold(true)
    await page.keyboard.press('Control+y')
    await persistedBold(false)
    await page.locator('[data-ribbon-command="bold"]').click()
    await persistedBold(true)
    await page.locator('[data-action="save"]').click()
    await page.waitForFunction(() => document.querySelector('.save-state-label')?.textContent.includes('保存失败'))
    await page.goto(`${baseUrl}/reports/v1/editor/assets/native.html`)
    await page.waitForFunction(() => document.querySelectorAll('.workbook-grid canvas').length >= 1, null, { timeout: 60000 })
    await page.locator('[data-action="save"]').click()
    await page.waitForFunction(() => document.querySelector('.save-state-label')?.textContent.includes('保存失败'))
    assert.deepEqual(saveAttempts[1], saveAttempts[0], '恢复后未修改的失败重试必须保持 requestId 与 operations')
    await page.locator('.workbook-grid').click({ position: { x: 120, y: 56 } })
    await page.keyboard.type('3')
    await page.keyboard.press('Enter')
  }
  await page.locator('[data-action="save"]').click()
  await page.waitForFunction(() => document.querySelector('.save-state-label')?.textContent === '已保存修订 2', null, { timeout: 30000 })
  if (smokeCase === 'rotation') {
    assert.ok(savePayload.operations.some(op => op.kind === 'applyCellEdits' && op.edits.some(edit => edit.row === 0 && edit.column === 0 && edit.style?.textRotation === 0)), JSON.stringify(savePayload))
    assert.ok(savePayload.operations.flatMap(op => op.kind === 'applyCellEdits' ? op.edits : []).every(edit => edit.row === 0 && edit.column === 0 && !edit.writeValue && Object.keys(edit.style).every(key => key === 'textRotation')), JSON.stringify(savePayload))
  } else if (smokeCase === 'structural-undo') {
    assert.ok(savePayload?.operations.every(operation => operation.kind !== 'applyRowColumnOps'), JSON.stringify(savePayload))
  } else if (smokeCase === 'sort') {
    assert.ok(savePayload?.operations.some(operation => operation.kind === 'applyCellEdits'
      && operation.edits.some(edit => edit.sheetName === 'Summary' && edit.row === 0 && edit.column === 0 && edit.cell?.value === 'alpha')
      && operation.edits.some(edit => edit.sheetName === 'Summary' && edit.row === 1 && edit.column === 0 && edit.cell?.value === 'zeta')), JSON.stringify(savePayload))
  } else if (smokeCase === 'row-column') {
    assert.deepEqual(savePayload?.operations.map(operation => operation.kind), [
      'applyRowColumnOps', 'applyRowColumnOps', 'applyRowColumnOps', 'applyRowColumnOps',
    ], JSON.stringify(savePayload))
    const operations = savePayload?.operations.flatMap(operation => operation.kind === 'applyRowColumnOps'
      && operation.sheetName === 'Summary' ? operation.ops : []) ?? []
    assert.deepEqual(operations.map(op => [op.kind, op.index, op.count]), [
      ['insert-rows', 0, 1], ['remove-rows', 1, 1], ['insert-cols', 0, 1], ['remove-cols', 0, 1],
    ], JSON.stringify(savePayload))
  } else {
    assert.ok(savePayload?.operations.some(operation => operation.kind === 'applyCellEdits'
      && operation.edits.some(edit => edit.sheetName === 'Summary' && edit.style?.bold === true && edit.style?.fontFamily === 'Calibri' && edit.style?.fontSize === 14 && edit.style?.fontColor === '#cc0000' && edit.style?.numberFormat === '0.000')), JSON.stringify(savePayload))
    assert.ok(savePayload?.operations.some(operation => operation.kind === 'applyCellEdits'
      && operation.edits.some(edit => edit.sheetName === 'Summary' && edit.row === 2 && edit.column === 0 && edit.cell?.formula === '=SUM(A1:A2)')), JSON.stringify(savePayload))
  }
  const download = await page.evaluate(async () => {
    const response = await fetch('/fixture-download.xlsx')
    return { status: response.status, bytes: Array.from(new Uint8Array(await response.arrayBuffer())) }
  })
  assert.equal(download.status, 200)
  const downloaded = Buffer.from(download.bytes)
  assert.equal(createHash('sha256').update(downloaded).digest('hex'), createHash('sha256').update(savedBytes).digest('hex'))
  const reopened = JSON.parse(runPython({ mode: 'inspect', scenario: smokeCase, bytes: downloaded.toString('base64') }))
  if (smokeCase === 'rotation') {
    assert.deepEqual(reopened, { rotation:0,horizontal:'center',wrap:true,indent:2,bold:true,italic:true,fontSize:14,formula:'=1+1',formulaRotation:90,formulaNumberFormat:'0.00',untouchedRotation:255,definedName:'Summary!$A$1',merges:['D1:E2'] })
    await page.goto(`${baseUrl}/reports/v1/editor/assets/native.html?revision=2`)
    await page.waitForFunction(() => document.querySelectorAll('.workbook-grid canvas').length >= 1, null, { timeout:60000 })
    await page.locator('.workbook-grid').click({ position:{x:120,y:36} })
    assert.equal(await page.locator('[data-ribbon-command="rotate:0"]').getAttribute('aria-pressed'),'true')
  } else if (smokeCase === 'structural-undo') assert.deepEqual(reopened, { values: ['original', 'second'], formula: '=A1', definedName: 'Summary!$A$1', merges: ['C1:D2'], sheets: ['Summary'] })
  else if (smokeCase === 'sort') assert.deepEqual(reopened, { values: ['alpha', 'zeta'], sheets: ['Summary'] })
  else if (smokeCase === 'row-column') assert.deepEqual(reopened, { values: [null, 'value', null], formula: '=LEN(A2)', numberFormat: '0.00', sheets: ['Summary'] })
  else assert.deepEqual(reopened, { value: 12.34, secondValue: smokeCase === 'draft-recovery' ? 3 : 2, bold: true, fontName: 'Calibri', fontSize: 14, fontColor: 'FFCC0000', numberFormat: '0.000', formula: '=1+1', autoSum: '=SUM(A1:A2)', sheets: ['Summary'] })
  if (smokeCase === 'draft-recovery') {
    assert.equal(saveAttempts.length, 3)
    assert.notEqual(saveAttempts[2].requestId, saveAttempts[0].requestId)
    assert.equal(await page.evaluate(() => Object.keys(localStorage).some(key => key.startsWith('native-editor-draft:'))), false)
  }
  assert.deepEqual(pageErrors, [])
  const evidence = { ok: true, scenario: smokeCase, productionBuild: !!builtDirectory, browserVersion: browser.version(), sourceSha256:sourceSha, downloadedSha256:createHash('sha256').update(downloaded).digest('hex'), operations:savePayload.operations, operationKinds: savePayload.operations.map(operation => operation.kind), downloadedBytes: downloaded.length, reopened, desktopVerified:false }
  if (process.env.WORKBOOK_SMOKE_EVIDENCE_DIR) { await mkdir(process.env.WORKBOOK_SMOKE_EVIDENCE_DIR,{recursive:true}); await writeFile(`${process.env.WORKBOOK_SMOKE_EVIDENCE_DIR}/source.xlsx`,sourceBytes); await writeFile(`${process.env.WORKBOOK_SMOKE_EVIDENCE_DIR}/downloaded.xlsx`,downloaded); await writeFile(`${process.env.WORKBOOK_SMOKE_EVIDENCE_DIR}/evidence.json`,JSON.stringify(evidence,null,2)) }
  console.log(JSON.stringify(evidence))
} finally {
  await browser?.close()
  server.kill('SIGTERM')
}
