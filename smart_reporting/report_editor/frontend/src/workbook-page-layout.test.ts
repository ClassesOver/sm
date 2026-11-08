import { afterEach, expect, it, vi } from 'vitest'
import { createBlankWorkbook, matchMarginPreset, readWorkbook } from '@sheets-web/xlsx-engine'
import { applyWorkbookOperations } from '../../../reporting/workbook_engine/bridge/operations'
import { createWorkbookEditorView } from './workbook-main'
import { createNativeOfficeTransport } from './native-office-view'
import { NativeDraft, type NativeDraftIdentity, type NativeSaveRequest } from './native-draft'
import { createEditorShell } from './shell'

const grid = vi.hoisted(() => ({ api: undefined as any, ribbon: undefined as any, apply: vi.fn(() => false), instances: [] as any[] }))
vi.mock('@univerjs/preset-sheets-core', () => ({ UniverSheetsCorePreset: () => ({}) }))
vi.mock('@univerjs/preset-sheets-note', () => ({ UniverSheetsNotePreset: () => ({}) }))
vi.mock('@univerjs/preset-sheets-find-replace', () => ({ UniverSheetsFindReplacePreset: () => ({}) }))
vi.mock('@univerjs/preset-sheets-drawing', () => ({ UniverSheetsDrawingPreset: () => ({}) }))
vi.mock('@univerjs/preset-sheets-table', () => ({ UniverSheetsTablePreset: () => ({}) }))
vi.mock('@univerjs/preset-sheets-sort', () => ({ UniverSheetsSortPreset: () => ({}) }))
vi.mock('@univerjs/preset-sheets-filter', () => ({ UniverSheetsFilterPreset: () => ({}) }))
vi.mock('./workbook-ribbon', () => ({
  mountWorkbookRibbon: (_host: unknown, callback: unknown) => { grid.ribbon = callback as (command: string) => void; return { dispose() {}, refreshState() {} } },
  applyWorkbookRibbonCommand: grid.apply,
}))
vi.mock('./workbook-vendor/grid/create-univer', async () => {
  const { Univer, IUniverInstanceService, LocaleType, mergeLocales } = await import('@univerjs/core')
  const CoreZhCN = (await import('@univerjs/preset-sheets-core/locales/zh-CN')).default
  const NoteZhCN = (await import('@univerjs/preset-sheets-note/locales/zh-CN')).default
  const { FUniver } = await import('@univerjs/core/lib/facade')
  const { UniverSheetsPlugin } = await import('@univerjs/sheets')
  const { UniverSheetsNotePlugin } = await import('@univerjs/sheets-note')
  const { UniverSheetsSortPlugin } = await import('@univerjs/sheets-sort')
  await import('@univerjs/sheets/facade')
  await import('@univerjs/sheets-note/facade')
  return { createUniver: () => {
    const univer = new Univer({ locale: LocaleType.ZH_CN, locales: { [LocaleType.ZH_CN]: mergeLocales(CoreZhCN, NoteZhCN) } })
    grid.instances.push(univer)
    univer.registerPlugin(UniverSheetsPlugin)
    univer.registerPlugin(UniverSheetsNotePlugin)
    univer.registerPlugin(UniverSheetsSortPlugin)
    const api = FUniver.newAPI(univer)
    const create = api.createWorkbook.bind(api)
    api.createWorkbook = data => {
      const workbook = create(data)
      univer.__getInjector().get(IUniverInstanceService).focusUnit(workbook.getId())
      return workbook
    }
    grid.api = api
    return { univer, univerAPI: api }
  } }
})
const identity: NativeDraftIdentity = { documentId: 'main-page-layout', revision: 1, sourceSha256: 'b'.repeat(64),
  scope: { database: 'fixture', companyId: 'company', userId: 'user', threadId: 'thread' } }
const store = () => { const data = new Map<string, string>(); return { getItem: (key: string) => data.get(key) ?? null, setItem: (key: string, value: string) => { data.set(key, value) }, removeItem: (key: string) => data.delete(key) } }
async function open(source: Uint8Array, draft: NativeDraft, save: (request: NativeSaveRequest) => Promise<unknown>) {
  document.body.innerHTML = '<main id="app"></main>'
  const shell = createEditorShell(document.querySelector('#app')!, 'full', 'xlsx')
  const context = { context: { ...identity, format: 'xlsx', sourceFile: { sha256: identity.sourceSha256 } }, editingEnabled: true }
  const transport = createNativeOfficeTransport({ api: { save } as never, context: context as never, draft })
  const view = await createWorkbookEditorView(shell, { native: true, draft, request: transport.workbook,
    file: async () => ({ bytes: source.slice().buffer as ArrayBuffer, sha256: identity.sourceSha256 }) })
  return { shell, view }
}
const sheet = () => grid.api.getActiveWorkbook().getActiveSheet()
afterEach(() => {
  for (const instance of grid.instances.splice(0)) instance.dispose()
  grid.apply.mockClear()
  document.body.replaceChildren()
})

it('journals Page Layout commands into applyPageSetups diffs and round-trips through save', async () => {
  const source = await createBlankWorkbook()
  let downloaded: Uint8Array | undefined
  const draft = new NativeDraft(identity, store(), () => `page-${Math.random()}`)
  const view = await open(source, draft, async request => {
    downloaded = await applyWorkbookOperations(source, request.operations)
    return { revision: 2, revisionRegistered: true, artifacts: { xlsx: { downloadUrl: '/page.xlsx' } }, validation: { issues: [] } }
  })
  grid.ribbon('page-orientation:landscape')
  grid.ribbon('page-margins:wide')
  await vi.waitFor(() => expect(draft.operations).toMatchObject([
    { kind: 'applyPageSetups', setups: [{ sheetName: 'Sheet1', orientation: 'landscape', margins: 'wide' }] },
  ]))
  sheet().setActiveSelection(sheet().getRange(1, 1, 2, 2))
  grid.ribbon('print-area:set')
  await vi.waitFor(() => expect(draft.operations.at(-1)).toMatchObject(
    { kind: 'applyPageSetups', setups: [{ sheetName: 'Sheet1', printArea: 'B2:C3' }] }))
  sheet().setActiveSelection(sheet().getRange(2, 0))
  grid.ribbon('page-breaks:insert')
  await vi.waitFor(() => expect(draft.operations.at(-1)).toMatchObject(
    { kind: 'applyPageSetups', setups: [{ sheetName: 'Sheet1', rowBreaks: [2] }] }))
  grid.ribbon('page-fit:width:2')
  await vi.waitFor(() => expect(draft.operations.at(-1)).toMatchObject(
    { kind: 'applyPageSetups', setups: [{ sheetName: 'Sheet1', fitToWidth: 2, fitToHeight: 0, fitToPage: true }] }))
  view.shell.save.click()
  await vi.waitFor(() => expect(downloaded).toBeDefined())
  const sheetModel = (await readWorkbook(downloaded!)).sheets[0]!
  expect(sheetModel.pageSetup).toMatchObject({ orientation: 'landscape', fitToWidth: 2, fitToHeight: 0, fitToPage: true })
  expect(matchMarginPreset(sheetModel.margins)).toBe('wide')
  expect(sheetModel.printArea).toBe('B2:C3')
  expect(sheetModel.rowBreaks).toEqual([2])
  view.view?.dispose()
})

it('skips no-op page-setup diffs and reports breaks without a page break', async () => {
  const source = await createBlankWorkbook()
  const draft = new NativeDraft(identity, store(), () => `page-${Math.random()}`)
  const view = await open(source, draft, async () => ({ revision: 2, revisionRegistered: false, validation: { issues: [] } }))
  // 文件没有打印区域时"清除"不产生操作。
  grid.ribbon('print-area:clear')
  await vi.waitFor(() => expect(view.shell.editor.querySelector<HTMLElement>('.workbook-feedback')!.textContent).toContain('打印区域已清除'))
  expect(draft.operations).toEqual([])
  // 当前位置没有分页符时移除只提示、不落盘。
  sheet().setActiveSelection(sheet().getRange(2, 0))
  grid.ribbon('page-breaks:remove')
  expect(view.shell.editor.querySelector<HTMLElement>('.workbook-feedback')!.textContent).toContain('没有可移除的分页符')
  expect(draft.operations).toEqual([])
  // 重置空分页符集合同样无差异。
  grid.ribbon('page-breaks:reset')
  expect(draft.operations).toEqual([])
  view.view?.dispose()
})
