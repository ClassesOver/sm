import { afterEach, describe, expect, it, vi } from 'vitest'

afterEach(() => { document.body.replaceChildren(); vi.clearAllMocks() })

describe('File command routing in the workbook editor', () => {
  const runtime = vi.hoisted(() => ({ api: {} as Record<string, any> }))

  vi.mock('@univerjs/core', async importOriginal => {
    const { mergeLocales } = await importOriginal<typeof import('@univerjs/core')>()
    return { ...(await importOriginal<typeof import('@univerjs/core')>()), LocaleType: { ZH_CN: 'zhCN' }, mergeLocales }
  })
  vi.mock('@univerjs/preset-sheets-core', () => ({ UniverSheetsCorePreset: () => ({}) }))
  vi.mock('@univerjs/preset-sheets-find-replace', () => ({ UniverSheetsFindReplacePreset: () => ({}) }))
  vi.mock('@univerjs/preset-sheets-drawing', () => ({ UniverSheetsDrawingPreset: () => ({}) }))
  vi.mock('@univerjs/preset-sheets-table', () => ({ UniverSheetsTablePreset: () => ({ plugins: [] }) }))
  vi.mock('@univerjs/preset-sheets-sort', () => ({ UniverSheetsSortPreset: () => ({}) }))
  vi.mock('@univerjs/preset-sheets-filter', () => ({ UniverSheetsFilterPreset: () => ({}) }))
  vi.mock('@univerjs/preset-sheets-note', () => ({ UniverSheetsNotePreset: () => ({}) }))
  vi.mock('./workbook-ribbon', async importOriginal => {
    const actual = await importOriginal<typeof import('./workbook-ribbon')>()
    return {
      ...actual,
      mountWorkbookRibbon: (host: HTMLElement, onCommand: (command: string) => void) => {
        host.innerHTML = ['print', 'undo', 'redo'].map(id => `<button data-ribbon-command="${id}">${id}</button>`).join('')
        host.querySelectorAll('button').forEach(button => button.addEventListener('click', () => onCommand(button.dataset.ribbonCommand!)))
        return { dispose() {} }
      },
    }
  })
  vi.mock('./workbook-rtl', () => ({ installWorkbookRtl: () => ({ dispose() {} }) }))
  vi.mock('./workbook-render-ready', () => ({ waitForWorkbookRendered: async () => {}, installWorkbookLoadingLock: () => ({ dispose() {} }) }))
  vi.mock('@sheets-web/xlsx-engine/zip', () => ({ createBufferEntrySource: async () => ({
    readText: async (path: string) => path === 'xl/workbook.xml' ? '<workbook><sheets/></workbook>' : '<worksheet/>',
    paths: async () => ['xl/worksheets/sheet1.xml'],
  }) }))
  vi.mock('@sheets-web/xlsx-engine', async importOriginal => {
    const actual = await importOriginal<typeof import('@sheets-web/xlsx-engine')>()
    return { ...actual, readWorkbook: async () => ({
      sheets: [{ name: 'Sheet', path: 'xl/worksheets/sheet1.xml', cells: { A1: { value: 'before' } }, merges: [], columns: [], rows: [], freeze: null, dimension: null }],
      styles: { numFmts: new Map(), fonts: [], fills: [], borders: [], cellXfs: [] }, themePalette: undefined,
    }) }
  })
  vi.mock('../../../reporting/workbook_engine/bridge/operations', () => ({ applyWorkbookOperations: async (bytes: unknown) => bytes }))
  vi.mock('./workbook-vendor/grid/create-univer', () => ({ createUniver: () => {
    const snapshot: any = { sheets: { sheet0: { name: 'Sheet', cellData: { 0: { 0: { v: 'before' } } } } }, sheetOrder: ['sheet0'], styles: {} }
    const sheet: any = { getSheetName: () => 'Sheet', getSheetId: () => 'sheet0', getSelection: () => null, getSheet: () => ({ getConfig: () => ({}) }) }
    const workbook: any = {
      getId: () => 'book', getSnapshot: () => snapshot, getSheets: () => [sheet],
      getActiveSheet: () => sheet, insertSheet: vi.fn(),
    }
    runtime.api = {
      Event: { BeforeCommandExecute: 'BeforeCommandExecute' }, addEvent: () => ({ dispose() {} }),
      onCommandExecuted() {}, getActiveWorkbook: () => workbook,
      undo: vi.fn(async () => true), redo: vi.fn(async () => false),
    }
    return { univer: { dispose: vi.fn() }, univerAPI: runtime.api }
  } }))
  vi.mock('./workbook-vendor/grid/decimal-step', () => ({ stepSelectionDecimals: vi.fn() }))
  vi.mock('./workbook-vendor/grid/sync', async () => {
    const actual = await vi.importActual<typeof import('./workbook-vendor/grid/sync')>('./workbook-vendor/grid/sync')
    return { ...actual, loadWorkbookData: vi.fn() }
  })
  vi.mock('./workbook-vendor/grid/sparkline-render', () => ({ setSparklines: vi.fn(), setSparklineWorkbookResolver() {} }))
  vi.mock('./workbook-vendor/grid/chart-render', () => ({ setCharts: vi.fn() }))
  vi.mock('./workbook-vendor/core/univer-data', () => ({ buildWorkbookData: () => ({ sheets: {} }) }))
  vi.mock('./workbook-vendor/core/data-tools', () => ({ geometryChanges: () => ({ columns: [], rows: [] }) }))
  vi.mock('./workbook-grid-operations', () => ({ gridMergeChanges: () => [], planGridSheets: () => ({ renames: [], additions: [], removals: [], order: ['Sheet'] }), structuralMutation: () => null }))
  vi.mock('./workbook-print', async importOriginal => {
    const actual = await importOriginal<typeof import('./workbook-print')>()
    return { ...actual, printDocument: vi.fn(() => true) }
  })

  it('routes File ▸ 撤销/恢复 to the live Univer undo/redo stacks and reports no-ops', async () => {
    const { createEditorShell } = await import('./shell')
    const { createWorkbookEditorView } = await import('./workbook-main')
    document.body.innerHTML = '<main id="app"></main>'
    const shell = createEditorShell(document.querySelector('#app')!, 'full', 'xlsx')
    await createWorkbookEditorView(shell, {
      native: true,
      file: async () => ({ bytes: new ArrayBuffer(1), sha256: 'a'.repeat(64) }),
      request: async () => ({}) as any,
    })
    document.querySelector<HTMLButtonElement>('[data-ribbon-command="undo"]')!.click()
    await new Promise(resolve => setTimeout(resolve, 0))
    expect(runtime.api.undo).toHaveBeenCalled()
    expect(shell.editor.querySelector<HTMLElement>('.workbook-feedback')!.textContent).toContain('已撤销上一步修改')
    document.querySelector<HTMLButtonElement>('[data-ribbon-command="redo"]')!.click()
    await new Promise(resolve => setTimeout(resolve, 0))
    expect(runtime.api.redo).toHaveBeenCalled()
    expect(shell.editor.querySelector<HTMLElement>('.workbook-feedback')!.textContent).toContain('没有可恢复的修改')
  }, 15000)

  it('opens the print preview before submitting the print job', async () => {
    const { createEditorShell } = await import('./shell')
    const { createWorkbookEditorView } = await import('./workbook-main')
    const printModule = await import('./workbook-print')
    document.body.innerHTML = '<main id="app"></main>'
    const shell = createEditorShell(document.querySelector('#app')!, 'full', 'xlsx')
    await createWorkbookEditorView(shell, {
      native: true,
      file: async () => ({ bytes: new ArrayBuffer(1), sha256: 'a'.repeat(64) }),
      request: async () => ({}) as any,
    })
    document.querySelector<HTMLButtonElement>('[data-ribbon-command="print"]')!.click()
    await vi.waitFor(() => expect(shell.editor.textContent).toContain('打印预览'), { timeout: 10000 })
    expect(printModule.printDocument).not.toHaveBeenCalled()
    expect(shell.editor.querySelector('[data-print-preview]')).not.toBeNull()
    expect(printModule.printDocument).not.toHaveBeenCalled()
    shell.editor.querySelector<HTMLButtonElement>('[data-print-cancel]')!.click()
    const dialog = shell.editor.querySelector<HTMLElement>('[data-print-preview]')?.closest<HTMLElement>('[role="dialog"]')
    if (dialog === undefined) throw new Error('打印预览节点缺失')
    expect(dialog === null || dialog.hidden).toBe(true)
  }, 15000)
})
