import { afterEach, expect, it, vi } from 'vitest'
import { createEditorShell } from './shell'
import { createWorkbookEditorView } from './workbook-main'
vi.mock('@univerjs/core', () => ({ LocaleType: { ZH_CN: 'zhCN' }, mergeLocales: () => ({}) }))
vi.mock('@univerjs/preset-sheets-core', () => ({ UniverSheetsCorePreset: () => ({}) }))
vi.mock('@univerjs/preset-sheets-find-replace', () => ({ UniverSheetsFindReplacePreset: () => ({}) }))
vi.mock('@univerjs/preset-sheets-drawing', () => ({ UniverSheetsDrawingPreset: () => ({}) }))
vi.mock('@univerjs/preset-sheets-table', () => ({ UniverSheetsTablePreset: () => ({}) }))
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
vi.mock('./workbook-vendor/grid/create-univer', () => ({ createUniver: () => {
  const snapshot: any = {
    sheets: { sheet0: { name: 'Sheet', cellData: { 0: { 0: { v: 'before' } } } } },
    sheetOrder: ['sheet0'],
    styles: {},
  }
  const range: any = {
    getCellStyleData: () => snapshot.styles[snapshot.sheets.sheet0.cellData[0][0].s] ?? {},
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
  const sheet = { getSelection: () => ({ getActiveRange: () => range }), getSheetName: () => 'Sheet' }
  const workbook: any = {
    getId: () => 'book', getSnapshot: () => snapshot, getSheets: () => [sheet],
    getActiveSheet: () => sheet, getSheetBySheetId: () => sheet, insertSheet: vi.fn(),
  }
  return { univer: { dispose: vi.fn() }, univerAPI: {
    onCommandExecuted() {}, getActiveWorkbook: () => workbook, disposeUnit() {}, createWorkbook() {},
  } }
} }))
vi.mock('./workbook-vendor/grid/decimal-step', () => ({ stepSelectionDecimals: vi.fn() }))
vi.mock('./workbook-vendor/grid/sync', async () => {
  const actual = await vi.importActual<typeof import('./workbook-vendor/grid/sync')>('./workbook-vendor/grid/sync')
  return { ...actual, loadWorkbookData: vi.fn() }
})
vi.mock('./workbook-vendor/grid/sparkline-render', () => ({ setSparklines: vi.fn() }))
vi.mock('./workbook-vendor/grid/chart-render', () => ({ setCharts: vi.fn() }))
vi.mock('./workbook-vendor/core/univer-data', () => ({ buildWorkbookData: () => ({}) }))
vi.mock('./workbook-vendor/core/data-tools', () => ({ geometryChanges: () => ({ columns: [], rows: [] }) }))
vi.mock('./workbook-grid-operations', () => ({ gridMergeChanges: () => [], planGridSheets: () => ({ renames: [], additions: [], removals: [], order: ['Sheet'] }), structuralMutation: () => null }))
afterEach(() => { document.body.replaceChildren(); vi.restoreAllMocks() })
it('native XLSX uses trusted transport, keeps unregistered draft and exposes successful revision without navigation', async () => {
  document.body.innerHTML = '<main id="app"></main>'
  const shell = createEditorShell(document.querySelector('#app')!, 'full', 'xlsx')
  const file = vi.fn(async () => ({ bytes: new ArrayBuffer(1), sha256: 'a'.repeat(64) }))
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
  shell.save.click(); await vi.waitFor(() => expect(saves).toBe(1)); await vi.waitFor(() => expect(shell.save.disabled).toBe(false))
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
it('native XLSX reports initialization failure to its host', async () => {
  document.body.innerHTML = '<main id="app"></main>'
  const shell = createEditorShell(document.querySelector('#app')!, 'full', 'xlsx')
  await expect(createWorkbookEditorView(shell, { native: true, file: async () => { throw Error('文件已变化') } })).rejects.toThrow('文件已变化')
})
