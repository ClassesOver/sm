import { afterEach, expect, it, vi } from 'vitest'
import { createBlankWorkbook } from '@sheets-web/xlsx-engine'
async function fileBytes() { return (await createBlankWorkbook()).slice().buffer as ArrayBuffer }
import FindReplaceZhCN from '@univerjs/preset-sheets-find-replace/locales/zh-CN'
import { createEditorShell } from './shell'
import { createWorkbookEditorView } from './workbook-main'
const localeRuntime = vi.hoisted(() => ({ options: undefined as any, selectionEvents: [] as string[] }))
vi.mock('@univerjs/core', async importOriginal => {
  const { mergeLocales } = await importOriginal<typeof import('@univerjs/core')>()
  return { ...(await importOriginal<typeof import('@univerjs/core')>()), LocaleType: { ZH_CN: 'zhCN' }, mergeLocales }
})
vi.mock('@univerjs/preset-sheets-core', () => ({ UniverSheetsCorePreset: () => ({}) }))
vi.mock('@univerjs/preset-sheets-find-replace', () => ({ UniverSheetsFindReplacePreset: () => ({}) }))
vi.mock('@univerjs/preset-sheets-drawing', () => ({ UniverSheetsDrawingPreset: () => ({}) }))
vi.mock('@univerjs/preset-sheets-table', () => ({ UniverSheetsTablePreset: () => ({ plugins: [] }) }))
vi.mock('./workbook-ribbon', async importOriginal => {
  const actual = await importOriginal<typeof import('./workbook-ribbon')>()
  return {
    ...actual,
    mountWorkbookRibbon: (host: HTMLElement, onCommand: (command: string) => void) => {
      host.innerHTML = '<button data-ribbon-command="bold">Bold</button><button data-ribbon-command="format:0.00">Number</button>'
      host.querySelectorAll('button').forEach(button => button.addEventListener('click', () => onCommand(button.dataset.ribbonCommand!)))
      return { dispose() {} }
    },
  }
})
vi.mock('@sheets-web/xlsx-engine', async importOriginal => {
  const actual = await importOriginal<typeof import('@sheets-web/xlsx-engine')>()
  return { ...actual, readWorkbook: async () => ({
    sheets: [{ name: 'Sheet', path: 'xl/worksheets/sheet1.xml', cells: { A1: { value: 'before' } }, merges: [], columns: [], rows: [], freeze: null, dimension: null }],
    styles: { numFmts: new Map(), fonts: [], fills: [], borders: [], cellXfs: [] }, themePalette: undefined,
  }) }
})
vi.mock('../../../reporting/workbook_engine/bridge/operations', () => ({ applyWorkbookOperations: async (bytes: unknown) => bytes }))
vi.mock('./workbook-vendor/grid/create-univer', () => ({ createUniver: (options: unknown) => {
  localeRuntime.options = options
  const snapshot: any = {
    sheets: { sheet0: { name: 'Sheet', rowHeader: { hidden: 0 }, columnHeader: { hidden: 0 }, cellData: { 0: { 0: { v: 'before' } } } } },
    sheetOrder: ['sheet0'],
    styles: {},
  }
  const range: any = {
    getCellStyleData: () => snapshot.styles[snapshot.sheets.sheet0.cellData[0][0].s] ?? {},
    getRow: () => 0, getColumn: () => 0, getHeight: () => 1, getWidth: () => 1,
    getWrap: () => snapshot.styles[snapshot.sheets.sheet0.cellData[0][0].s]?.tb === 2,
    setFontWeight: (value: string) => {
      const style = { ...range.getCellStyleData(), bl: value === 'bold' ? 1 : 0 }
      snapshot.styles.boldStyle = style; snapshot.sheets.sheet0.cellData[0][0].s = 'boldStyle'
    },
    setNumberFormat: (pattern: string) => {
      const style = { ...range.getCellStyleData(), n: { pattern } }
      snapshot.styles.numberStyle = style; snapshot.sheets.sheet0.cellData[0][0].s = 'numberStyle'
    },
    setFontStyle: vi.fn(), setFontLine: vi.fn(), setWrap: vi.fn(), setHorizontalAlignment: vi.fn(),
    merge: vi.fn(), breakApart: vi.fn(),
  }
  const sheetCore = { getConfig: () => snapshot.sheets.sheet0, getRowManager: () => ({ getRowData: () => ({}) }), getColumnManager: () => ({ getColumnData: () => ({}) }), getCustomMetadata: () => ({}) }
  const sheet = { getSheetId: () => 'sheet0', getSheet: () => sheetCore, getSelection: () => ({ getActiveRange: () => range }), getSheetName: () => 'Sheet', getRange: () => range }
  const workbook: any = {
    getId: () => 'book', getSnapshot: () => snapshot, getSheets: () => [sheet],
    getActiveSheet: () => sheet, getSheetBySheetId: () => sheet, insertSheet: vi.fn(),
    onSelectionChange: () => { localeRuntime.selectionEvents.push('subscribe'); return { dispose() { localeRuntime.selectionEvents.push('dispose') } } },
  }
  return { univer: { dispose: vi.fn() }, univerAPI: {
    Event: { BeforeCommandExecute: 'BeforeCommandExecute' }, addEvent() { return { dispose() {} } },
    onCommandExecuted() { return { dispose() {} } }, getActiveWorkbook: () => workbook, disposeUnit() {}, createWorkbook() {},
  } }
} }))
vi.mock('./workbook-rtl', () => ({ installWorkbookRtl: () => ({ dispose() {} }) }))
vi.mock('./workbook-vendor/grid/decimal-step', () => ({ stepSelectionDecimals: vi.fn() }))
vi.mock('./workbook-vendor/grid/sync', async () => {
  const actual = await vi.importActual<typeof import('./workbook-vendor/grid/sync')>('./workbook-vendor/grid/sync')
  return { ...actual, loadWorkbookData: vi.fn(() => { localeRuntime.selectionEvents.push('load') }) }
})
vi.mock('./workbook-vendor/grid/sparkline-render', () => ({ setSparklines: vi.fn(), setSparklineWorkbookResolver() {} }))
vi.mock('./workbook-vendor/grid/chart-render', () => ({ setCharts: vi.fn() }))
vi.mock('./workbook-vendor/core/univer-data', () => ({ buildWorkbookData: () => ({ sheets: {} }) }))
vi.mock('./workbook-vendor/core/data-tools', () => ({ geometryChanges: () => ({ columns: [], rows: [] }) }))
vi.mock('./workbook-grid-operations', () => ({ gridMergeChanges: () => [], planGridSheets: () => ({ renames: [], additions: [], removals: [], order: ['Sheet'] }), structuralMutation: () => null }))
afterEach(() => { document.body.replaceChildren(); vi.restoreAllMocks(); localeRuntime.selectionEvents.length = 0 })
it('native XLSX uses trusted transport, keeps unregistered draft and exposes successful revision without navigation', async () => {
  document.body.innerHTML = '<main id="app"></main>'
  const shell = createEditorShell(document.querySelector('#app')!, 'full', 'xlsx')
  const file = vi.fn(async () => ({ bytes: await fileBytes(), sha256: 'a'.repeat(64) }))
  let saves = 0
  const request = vi.fn(async (path: string, _payload?: unknown) => {
    if (path !== 'save') throw Error(`unexpected ${path}`)
    return { revision: 2, revisionRegistered: ++saves > 1, editor: { openUrl: '/next-revision' }, xlsx: { downloadUrl: '/download' }, validation: { ok: false, issues: [{ message: '待复核' }] } }
  })
  const view = await createWorkbookEditorView(shell, { native: true, file, request: request as any })
  expect(file).toHaveBeenCalledOnce(); expect(shell.editor.querySelector('form')!.hidden).toBe(true)
  expect(shell.editor.querySelector('[data-ribbon-command="bold"]')).not.toBeNull()
  shell.editor.querySelector<HTMLButtonElement>('[data-ribbon-command="bold"]')!.click()
  shell.editor.querySelector<HTMLButtonElement>('[data-ribbon-command="format:0.00"]')!.click()
  expect(shell.statusLabel.textContent).toBe('有未保存修改')
  shell.save.click(); await vi.waitFor(() => expect(saves, shell.editor.querySelector('.workbook-feedback')?.textContent ?? '').toBe(1)); await vi.waitFor(() => expect(shell.save.disabled).toBe(false))
  expect(request.mock.calls[0]?.[1]).toMatchObject({
    expectedSha256: 'a'.repeat(64),
    operations: [{ kind: 'applyCellEdits', edits: [{ sheetName: 'Sheet', row: 0, column: 0, writeValue: false, style: { bold: true, numberFormat: '0.00' } }] }],
  })
  shell.save.click(); await vi.waitFor(() => expect(saves).toBe(2)); await vi.waitFor(() => expect(shell.save.disabled).toBe(true))
  expect(request.mock.calls.map(([path]) => path)).toEqual(['save', 'save'])
  await vi.waitFor(() => expect(shell.editor.querySelector<HTMLAnchorElement>('.native-next-revision')?.getAttribute('href')).toBe('/next-revision'))
  expect(shell.editor.inert).toBe(false)
  expect(shell.editor.textContent).toContain('待复核')
  shell.editor.querySelector<HTMLButtonElement>('[data-ribbon-command="bold"]')!.click()
  expect(shell.editor.querySelector<HTMLAnchorElement>('.native-next-revision')?.getAttribute('href')).toBe('/next-revision')
  expect(shell.editor.textContent).toContain('待复核')
  view?.dispose()
})
it('loads the preset Chinese Find/Replace locale into the workbook runtime', async () => {
  document.body.innerHTML = '<main id="app"></main>'
  const shell = createEditorShell(document.querySelector('#app')!, 'full', 'xlsx')
  const view = await createWorkbookEditorView(shell, {
    native: true, file: async () => ({ bytes: await fileBytes(), sha256: 'a'.repeat(64) }),
  })
  expect(localeRuntime.options.locale).toBe('zhCN')
  const locale = localeRuntime.options.locales.zhCN['find-replace']
  expect(locale).toEqual(FindReplaceZhCN['find-replace'])
  expect(locale.dialog).toMatchObject({ title: '查找', replace: '替换', 'replace-all': '替换全部' })
  view?.dispose()
})

it('native XLSX reports initialization failure to its host', async () => {
  document.body.innerHTML = '<main id="app"></main>'
  const shell = createEditorShell(document.querySelector('#app')!, 'full', 'xlsx')
  await expect(createWorkbookEditorView(shell, { native: true, file: async () => { throw Error('文件已变化') } })).rejects.toThrow('文件已变化')
})

it('native AI adopts into the same NativeDraft, undoes, redoes and saves its combined operations', async () => {
  const { NativeDraft } = await import('./native-draft')
  document.body.innerHTML = '<main id="app"></main>'
  const shell = createEditorShell(document.querySelector('#app')!, 'full', 'xlsx')
  const nativeDraft = new NativeDraft({ documentId: 'book', revision: 1, sourceSha256: 'a'.repeat(64), scope: { database: 'db', companyId: 'co', userId: 'user', threadId: 'thread' } }, sessionStorage)
  const base = [{ kind: 'applyColumnWidths', sheetName: 'Sheet', entries: [{ index: 1, widthChars: 20 }] }]
  nativeDraft.setOperations(base)
  const candidate = { editId: 'ai', status: 'succeeded', snapshotSha256: 'b'.repeat(64), proposal: { summary: '新增公式', operations: [{ kind: 'applyCellEdits', edits: [{ sheetName: 'Sheet', row: 1, column: 0, writeValue: true, cell: { value: null, formula: 'SUM(A1:B1)' } }] }] } }
  const combined = [...base, ...candidate.proposal.operations]
  const api = { start: vi.fn(async () => candidate), status: vi.fn(async () => candidate), accept: vi.fn(async () => ({ operations: combined })), cancel: vi.fn(async () => ({})), cancelRequest: vi.fn(async () => ({})) }
  const request = vi.fn(async () => ({ revision: 2, revisionRegistered: true, editor: { openUrl: '/book/2' }, xlsx: { downloadUrl: '/download-ai.xlsx' }, validation: { ok: true, issues: [] } }))
  const view = await createWorkbookEditorView(shell, { native: true, draft: nativeDraft, nativeAI: api, file: async () => ({ bytes: await fileBytes(), sha256: 'a'.repeat(64) }), request: request as any })
  const panel = shell.editor.querySelector<HTMLElement>('.workbook-native-ai')!
  panel.querySelector('textarea')!.value = '新增公式'
  panel.querySelector('form')!.dispatchEvent(new Event('submit', { cancelable: true }))
  await vi.waitFor(() => expect(panel.querySelector<HTMLElement>('.native-ai-preview')!.hidden, panel.querySelector('.native-ai-status')?.textContent ?? '').toBe(false))
  expect(nativeDraft.operations).toEqual(base)
  panel.querySelector<HTMLButtonElement>('.native-ai-accept')!.click()
  await vi.waitFor(() => expect(nativeDraft.operations).toEqual(combined))
  expect(localeRuntime.selectionEvents.slice(-3)).toEqual(['dispose', 'load', 'subscribe'])
  panel.querySelector<HTMLButtonElement>('.native-ai-undo')!.click()
  await vi.waitFor(() => expect(nativeDraft.operations).toEqual(base))
  panel.querySelector<HTMLButtonElement>('.native-ai-redo')!.click()
  await vi.waitFor(() => expect(nativeDraft.operations).toEqual(combined))
  shell.save.click()
  await vi.waitFor(() => expect(request).toHaveBeenCalledWith('save', { expectedSha256: 'a'.repeat(64), operations: combined }))
  await vi.waitFor(() => expect(shell.exportXlsx.getAttribute('href')).toBe('/download-ai.xlsx'))
  expect(nativeDraft.operations).toEqual(combined)
  view?.dispose(); sessionStorage.clear()
})
