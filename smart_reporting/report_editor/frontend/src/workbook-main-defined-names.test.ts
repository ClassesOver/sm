import { afterEach, expect, it, vi } from 'vitest'
import { applyCellEdits, applyDefinedNames, applySheetEdits, createBlankWorkbook, readWorkbook } from '@sheets-web/xlsx-engine'
import { applyWorkbookOperations } from '../../../reporting/workbook_engine/bridge/operations'
import { createWorkbookEditorView } from './workbook-main'
import { createNativeOfficeTransport } from './native-office-view'
import { NativeDraft, type NativeDraftIdentity, type NativeSaveRequest } from './native-draft'
import { createEditorShell } from './shell'
import { definedNamesPlan, definedNamesPlanOperation, liveDefinedNames, absoluteRangeRef } from './workbook-defined-names'

const grid = vi.hoisted(() => ({ api: undefined as any, ribbon: undefined as any, apply: vi.fn(() => false), instances: [] as any[] }))
vi.mock('@univerjs/preset-sheets-core', () => ({ UniverSheetsCorePreset: () => ({}) }))
vi.mock('@univerjs/preset-sheets-note', () => ({ UniverSheetsNotePreset: () => ({}) }))
vi.mock('@univerjs/preset-sheets-find-replace', () => ({ UniverSheetsFindReplacePreset: () => ({}) }))
vi.mock('@univerjs/preset-sheets-drawing', () => ({ UniverSheetsDrawingPreset: () => ({}) }))
vi.mock('@univerjs/preset-sheets-table', () => ({ UniverSheetsTablePreset: () => ({ plugins: [] }) }))
vi.mock('@univerjs/preset-sheets-sort', () => ({ UniverSheetsSortPreset: () => ({}) }))
vi.mock('@univerjs/preset-sheets-filter', () => ({ UniverSheetsFilterPreset: () => ({}) }))
vi.mock('./workbook-ribbon', () => ({
  mountWorkbookRibbon: (_host: unknown, callback: unknown) => { grid.ribbon = callback; return { dispose() {}, refreshState() {} } },
  applyWorkbookRibbonCommand: grid.apply,
}))
vi.mock('./workbook-vendor/grid/decimal-step', () => ({ stepSelectionDecimals() {} }))
vi.mock('./workbook-vendor/grid/sparkline-render', () => ({ setSparklines() {}, setSparklineWorkbookResolver() {} }))
vi.mock('./workbook-vendor/grid/chart-render', () => ({ setCharts() {} }))
vi.mock('./workbook-vendor/grid/create-univer', async () => {
  const { Univer, IUniverInstanceService, LocaleType, mergeLocales } = await import('@univerjs/core')
  const CoreZhCN = (await import('@univerjs/preset-sheets-core/locales/zh-CN')).default
  const NoteZhCN = (await import('@univerjs/preset-sheets-note/locales/zh-CN')).default
  const { FUniver } = await import('@univerjs/core/lib/facade')
  const { UniverSheetsPlugin } = await import('@univerjs/sheets')
  const { UniverSheetsNotePlugin } = await import('@univerjs/sheets-note')
  const { UniverSheetsSortPlugin } = await import('@univerjs/sheets-sort')
  const { UniverFormulaEnginePlugin } = await import('@univerjs/engine-formula')
  const { UniverSheetsFormulaPlugin } = await import('@univerjs/sheets-formula')
  const { UniverSheetsDataValidationPlugin } = await import('@univerjs/sheets-data-validation')
  const { UniverSheetsTablePlugin } = await import('@univerjs/sheets-table')
  const { UniverSheetsFilterPlugin } = await import('@univerjs/sheets-filter')
  await import('@univerjs/sheets/facade')
  await import('@univerjs/sheets-note/facade')
  await import('@univerjs/sheets-table/facade')
  return { createUniver: () => {
    const univer = new Univer({ locale: LocaleType.ZH_CN, locales: { [LocaleType.ZH_CN]: mergeLocales(CoreZhCN, NoteZhCN) } })
    grid.instances.push(univer)
    univer.registerPlugin(UniverSheetsPlugin)
    univer.registerPlugin(UniverSheetsNotePlugin)
    univer.registerPlugin(UniverSheetsSortPlugin)
    univer.registerPlugin(UniverFormulaEnginePlugin)
    univer.registerPlugin(UniverSheetsFormulaPlugin)
    univer.registerPlugin(UniverSheetsDataValidationPlugin)
    univer.registerPlugin(UniverSheetsTablePlugin)
    univer.registerPlugin(UniverSheetsFilterPlugin)
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

const identity: NativeDraftIdentity = { documentId: 'main-defined-names', revision: 1, sourceSha256: 'a'.repeat(64),
  scope: { database: 'fixture', companyId: 'company', userId: 'user', threadId: 'thread' } }
const store = () => { const data = new Map<string, string>(); return { getItem: (key: string) => data.get(key) ?? null, setItem: (key: string, value: string) => { data.set(key, value) }, removeItem: (key: string) => { data.delete(key) } } }
async function fixture() {
  // 预置一个文件既有全局名（baseline definedNames），使删除路径产生 removes。
  return applyDefinedNames(await applyCellEdits(await createBlankWorkbook(), [
    { sheetName: 'Sheet1', row: 0, column: 0, writeValue: true, cell: { value: '数据' } },
    { sheetName: 'Sheet1', row: 1, column: 0, writeValue: true, cell: { value: '北京' } },
    { sheetName: 'Sheet1', row: 0, column: 1, writeValue: true, cell: { value: 7 } },
  ]), { sets: [{ name: '旧名', refersTo: 'Sheet1!$B$2' }, { name: 'RateMark', refersTo: 'Sheet1!$B$3' }] })
}
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
// 真实 Univer 必有 getDefinedNames；测试里不允许 undefined 歧义。
const liveNames = () => liveDefinedNames(grid.api.getActiveWorkbook()) ?? []
const dialog = () => ({
  list: document.querySelector<HTMLSelectElement>('.workbook-defined-name-list')!,
  name: document.querySelector<HTMLInputElement>('.workbook-defined-name-name')!,
  ref: document.querySelector<HTMLInputElement>('.workbook-defined-name-ref')!,
  add: document.querySelector<HTMLButtonElement>('.workbook-defined-name-add')!,
  update: document.querySelector<HTMLButtonElement>('.workbook-defined-name-update')!,
  remove: document.querySelector<HTMLButtonElement>('.workbook-defined-name-delete')!,
  error: document.querySelector<HTMLElement>('.workbook-defined-name-error')!,
})
const namesOperation = (operations: any[]) => operations.find(operation => operation.kind === 'applyDefinedNames')
const history = (direction: 'undo' | 'redo') => expect(grid.api.syncExecuteCommand(`univer.command.${direction}`)).toBe(true)
afterEach(() => {
  for (const instance of grid.instances.splice(0)) instance.dispose()
  grid.apply.mockClear()
  document.body.replaceChildren()
})

it('dialog CRUD collects applyDefinedNames sets/removes, Undo/Redo reconciles, save round-trips and recovery is idempotent', async () => {
  const source = await fixture(), storage = store()
  let sequence = 0
  const draft = new NativeDraft(identity, storage, () => `names-request-${++sequence}`)
  let downloaded: Uint8Array | undefined
  const requests: NativeSaveRequest[] = []
  const save = async (request: NativeSaveRequest) => {
    requests.push(request)
    if (requests.length === 1) throw Error('network failed')
    downloaded = await applyWorkbookOperations(source, request.operations)
    return { revision: 2, revisionRegistered: true, artifacts: { xlsx: { downloadUrl: '/names.xlsx' } }, validation: { issues: [] } }
  }
  const current = await open(source, draft, save)
  // fixture 逐个前置插入：XML 顺序 [RateMark, 旧名]。
  expect(liveNames()).toEqual([{ name: 'RateMark', refersTo: 'Sheet1!$B$3' }, { name: '旧名', refersTo: 'Sheet1!$B$2' }])
  expect(draft.operations).toEqual([])

  // 新建：对话框填名称/引用后添加，草稿差分出现 applyDefinedNames sets。
  grid.ribbon('name-manager-open')
  let box = dialog()
  expect([...box.list.options].map(option => option.textContent)).toEqual(['RateMark → Sheet1!$B$3', '旧名 → Sheet1!$B$2'])
  box.name.value = '税率'
  box.ref.value = '=Sheet1!$B$2:$B$3'
  box.add.click()
  expect(box.error.textContent).toBe('')
  expect(liveNames().map(row => row.name)).toEqual(['RateMark', '旧名', '税率'])
  await vi.waitFor(() => expect(namesOperation(draft.operations)).toMatchObject({
    kind: 'applyDefinedNames', plan: { sets: [{ name: '税率', refersTo: 'Sheet1!$B$2:$B$3' }] },
  }))
  expect(current.shell.statusLabel.textContent).toContain('有未保存修改')

  // Undo/Redo：Univer 原生命令可撤销，实时差分随之回归空集再恢复。
  history('undo')
  await vi.waitFor(() => expect(draft.operations).toEqual([]))
  expect(liveNames().map(row => row.name)).toEqual(['RateMark', '旧名'])
  history('redo')
  await vi.waitFor(() => expect(namesOperation(draft.operations)).toMatchObject({
    plan: { sets: [{ name: '税率', refersTo: 'Sheet1!$B$2:$B$3' }] },
  }))

  // 编辑（改引用）；再新建第二个名称。
  grid.ribbon('name-manager-open')
  box = dialog()
  box.list.value = '税率'
  box.list.dispatchEvent(new Event('change'))
  expect(box.ref.value).toBe('Sheet1!$B$2:$B$3')
  box.ref.value = 'Sheet1!$B$2'
  box.update.click()
  expect(box.error.textContent).toBe('')
  expect(liveNames().map(row => row.name)).toEqual(['RateMark', '旧名', '税率'])
  await vi.waitFor(() => expect(namesOperation(draft.operations)).toMatchObject({
    plan: { sets: [{ name: '税率', refersTo: 'Sheet1!$B$2' }] },
  }))
  box.name.value = '城市'
  box.ref.value = 'Sheet1!$A$2'
  box.add.click()
  expect(liveNames().map(row => row.name)).toEqual(['RateMark', '旧名', '税率', '城市'])

  // 删除：选中列表既有名（baseline）后删除，差分出现在 removes。
  box.list.value = '旧名'
  box.list.dispatchEvent(new Event('change'))
  box.remove.click()
  expect(box.error.textContent).toBe('')
  expect(liveNames().map(row => row.name)).toEqual(['RateMark', '税率', '城市'])
  await vi.waitFor(() => expect(namesOperation(draft.operations)).toMatchObject({
    kind: 'applyDefinedNames',
    plan: { sets: [{ name: '税率', refersTo: 'Sheet1!$B$2' }, { name: '城市', refersTo: 'Sheet1!$A$2' }], removes: ['旧名'] },
  }))

  // 首次保存失败（网络），失败请求身份与重试请求一致。
  current.shell.save.click()
  await vi.waitFor(() => expect(current.shell.statusLabel.textContent).toContain('保存失败'))
  expect(namesOperation(requests[0]!.operations)).toMatchObject({
    kind: 'applyDefinedNames',
    plan: { sets: [{ name: '税率', refersTo: 'Sheet1!$B$2' }, { name: '城市', refersTo: 'Sheet1!$A$2' }], removes: ['旧名'] },
  })

  // 恢复：失败保存后草稿保留；重开视图重放草稿，网格与差分一致且不追加重复
  // defined-name 操作，重试请求身份保持幂等。
  current.view?.dispose()
  const recovered = new NativeDraft(identity, storage, () => `names-request-${++sequence}`)
  expect(namesOperation(recovered.operations)).toMatchObject({
    kind: 'applyDefinedNames',
    plan: { sets: [{ name: '税率', refersTo: 'Sheet1!$B$2' }, { name: '城市', refersTo: 'Sheet1!$A$2' }], removes: ['旧名'] },
  })
  const second = await open(source, recovered, save)
  // 引擎按 sets 逆序插入 XML，读回顺序为 [城市, 税率]。
  expect(liveNames()).toEqual([
    { name: '城市', refersTo: 'Sheet1!$A$2' }, { name: '税率', refersTo: 'Sheet1!$B$2' },
    { name: 'RateMark', refersTo: 'Sheet1!$B$3' },
  ])
  second.shell.save.click()
  await vi.waitFor(() => expect(second.shell.statusLabel.textContent).toContain('已保存修订 2'))
  // 幂等：重放后的重试请求与失败请求逐字节一致；若差分追加了重复的
  // applyDefinedNames，两次请求将不再相等。
  expect(requests[1]).toEqual(requests[0])
  expect(requests[1]!.operations.filter((operation: any) => operation.kind === 'applyDefinedNames')).toHaveLength(1)
  const savedModel = await readWorkbook(downloaded!)
  expect(savedModel.definedNames).toEqual([
    { name: '城市', refersTo: 'Sheet1!$A$2' }, { name: '税率', refersTo: 'Sheet1!$B$2' },
    { name: 'RateMark', refersTo: 'Sheet1!$B$3' },
  ])
  expect(recovered.closed).toBe(true)
  second.view?.dispose()
})

it('dialog rejects invalid names, cell-ref-like names, case duplicates and empty refs without mutating', async () => {
  const source = await fixture(), draft = new NativeDraft(identity, store(), () => 'names-invalid')
  const current = await open(source, draft, async () => { throw Error('not saving') })
  grid.ribbon('name-manager-open')
  const box = dialog()
  const attempt = (name: string, ref: string): string => {
    box.name.value = name
    box.ref.value = ref
    box.add.click()
    return box.error.textContent
  }
  expect(attempt('A1', 'Sheet1!$B$2')).toContain('不合法')
  expect(attempt('_xlnm.Print_Area', 'Sheet1!$B$2')).toContain('不合法')
  expect(attempt('1季度', 'Sheet1!$B$2')).toContain('不合法')
  expect(attempt('R1C1', 'Sheet1!$B$2')).toContain('不合法')
  // 对话框先做非空守卫，空引用在新建入口被拦截。
  expect(attempt('合法名', '')).toBe('请填写名称和引用。')
  expect(attempt('合法名', '   ')).toBe('请填写名称和引用。')
  expect(attempt('合法名', `Sheet1!$A$1:${'Z'.repeat(600)}`)).toContain('引用过长')
  expect(attempt('税率', 'Sheet1!$B$2:$B$3')).toBe('')
  // 大小写不敏感判重（Excel 语义），保留原名。
  expect(attempt('RATEMARK', 'Sheet1!$A$1')).toContain('冲突')
  expect(attempt('ratemark', 'Sheet1!$A$1')).toContain('冲突')
  expect(liveNames().map(row => row.name)).toEqual(['RateMark', '旧名', '税率'])
  await vi.waitFor(() => expect(draft.operations.filter((operation: any) => operation.kind === 'applyDefinedNames')).toHaveLength(1))
  // 更新入口：清空引用触发引擎层校验（对话框守卫只挡新建）。
  box.list.value = '旧名'
  box.list.dispatchEvent(new Event('change'))
  box.ref.value = ''
  box.update.click()
  expect(box.error.textContent).toBe('引用不能为空。')
  expect(liveNames().map(row => row.name)).toEqual(['RateMark', '旧名', '税率'])
  // 更新到冲突名同样被拒绝。
  box.list.value = '旧名'
  box.list.dispatchEvent(new Event('change'))
  box.name.value = '税率'
  box.update.click()
  expect(box.error.textContent).toContain('冲突')
  expect(liveNames().map(row => row.name)).toEqual(['RateMark', '旧名', '税率'])
  current.view?.dispose()
})

it('define-name prefills the selection absolute address and use-in-formula inserts into empty cells only', async () => {
  const source = await fixture(), draft = new NativeDraft(identity, store(), () => 'names-quick')
  const current = await open(source, draft, async () => { throw Error('not saving') })
  // define-name：选区 A1:B2 → 引用预填 Sheet1!$A$1:$B$2。
  sheet().setActiveSelection(sheet().getRange(0, 0, 2, 2))
  grid.ribbon('define-name')
  let box = dialog()
  expect(box.ref.value).toBe('Sheet1!$A$1:$B$2')
  expect(box.name.value).toBe('')
  box.name.value = '汇总区'
  box.add.click()
  expect(box.error.textContent).toBe('')
  expect(liveNames().map(row => row.name)).toEqual(['RateMark', '旧名', '汇总区'])

  // use-in-formula：空单元格插入 =汇总区；非空单元格拒绝覆盖。
  sheet().setActiveSelection(sheet().getRange(4, 0))
  grid.ribbon('use-in-formula:汇总区')
  const inserted = sheet().getRange(4, 0)
  expect(String(inserted.getFormula() ?? '')).toContain('汇总区')
  await vi.waitFor(() => expect(draft.operations).toEqual(expect.arrayContaining([
    expect.objectContaining({ kind: 'applyCellEdits' }),
  ])))
  expect(JSON.stringify(draft.operations)).toContain('汇总区')

  sheet().setActiveSelection(sheet().getRange(0, 0))
  grid.ribbon('use-in-formula:汇总区')
  expect(document.querySelector('.workbook-feedback')!.textContent).toContain('空单元格')
  expect(sheet().getRange(0, 0).getValue()).toBe('数据')
  current.view?.dispose()
})

it('definedNamesPlan diff semantics: adds, ref changes (in-place rename-safe), removes, case-only rename is a no-op and scoped/reserved entries are ignored', () => {
  expect(definedNamesPlan([], [{ name: 'A', refersTo: 'S!$A$1' }])).toEqual({ sets: [{ name: 'A', refersTo: 'S!$A$1' }] })
  expect(definedNamesPlan([{ name: 'A', refersTo: 'S!$A$1' }], [])).toEqual({ removes: ['A'] })
  // 同名（大小写不敏感）换引用：按 baseline 原名原地替换。
  expect(definedNamesPlan([{ name: 'rate', refersTo: 'S!$A$1' }], [{ name: 'RATE', refersTo: 'S!$B$2' }]))
    .toEqual({ sets: [{ name: 'rate', refersTo: 'S!$B$2' }] })
  // 纯大小写改名（引用不变）：不产生操作，避免引擎 replace 留旧条目。
  expect(definedNamesPlan([{ name: 'rate', refersTo: 'S!$A$1' }], [{ name: 'RATE', refersTo: 'S!$A$1' }])).toEqual({})
  // 同一次 live 里的重复（大小写不同）名只保留首个，避免引擎“同一次操作中重复定义”。
  expect(definedNamesPlan([], [
    { name: 'dup', refersTo: 'S!$A$1' }, { name: 'DUP', refersTo: 'S!$B$2' },
  ])).toEqual({ sets: [{ name: 'dup', refersTo: 'S!$A$1' }] })
  // 非法名（含 _xlnm.）：引擎不能写也不删，保持原样。
  expect(definedNamesPlan([{ name: '_xlnm.Print_Area', refersTo: 'S!$A$1' }], [])).toEqual({})
  // 工作表级scope与全局同样保留，依稳定工作表身份区分。
  const scopedWorkbook = {
    getDefinedNames: () => [
      { getName: () => 'local', getFormulaOrRefString: () => 'S!$A$1', getLocalSheetId: () => 'sheet-0' },
      { getName: () => 'global', getFormulaOrRefString: () => 'S!$B$1', getLocalSheetId: () => 'AllDefaultWorkbook' },
      { getName: () => 'plain', getFormulaOrRefString: () => '=S!$C$1' },
    ],
  }
  expect(liveDefinedNames(scopedWorkbook as never)).toEqual([{ name: 'local', refersTo: 'S!$A$1', scopeSheetId: 'sheet-0' }, { name: 'global', refersTo: 'S!$B$1' }, { name: 'plain', refersTo: 'S!$C$1' }])
  // 组合差分 → 协议 op。
  expect(definedNamesPlanOperation([{ name: 'gone', refersTo: 'S!$A$1' }], [{ name: 'new', refersTo: 'S!$B$2' }]))
    .toEqual({ kind: 'applyDefinedNames', plan: { sets: [{ name: 'new', refersTo: 'S!$B$2' }], removes: ['gone'] } })
  expect(definedNamesPlanOperation([], [])).toBeUndefined()
})

it('absoluteRangeRef quotes sheet names and anchors the selection absolutely', () => {
  expect(absoluteRangeRef('Sheet1', 0, 0, 0, 0)).toBe('Sheet1!$A$1')
  expect(absoluteRangeRef('Sheet1', 0, 0, 1, 1)).toBe('Sheet1!$A$1:$B$2')
  expect(absoluteRangeRef('经营 报表', 1, 25, 3, 26)).toBe(`'经营 报表'!$Z$2:$AA$4`)
  expect(absoluteRangeRef("it's", 0, 0, 0, 0)).toBe(`'it''s'!$A$1`)
})

it('engine protocol applies sets and removals to workbook.xml and the bridge plan matches', async () => {
  const source = await fixture()
  const added = await applyWorkbookOperations(source, [
    { kind: 'applyDefinedNames', plan: { sets: [{ name: '税率', refersTo: 'Sheet1!$B$2' }, { name: '城市', refersTo: 'Sheet1!$A$2' }] } },
  ])
  // 引擎逐个前置插入 definedName：读回顺序与 sets 相反，既有名保持在后。
  expect((await readWorkbook(added)).definedNames).toEqual([
    { name: '城市', refersTo: 'Sheet1!$A$2' }, { name: '税率', refersTo: 'Sheet1!$B$2' },
    { name: 'RateMark', refersTo: 'Sheet1!$B$3' }, { name: '旧名', refersTo: 'Sheet1!$B$2' },
  ])
  const removed = await applyWorkbookOperations(added, [{ kind: 'applyDefinedNames', plan: { removes: ['税率'] } }])
  expect((await readWorkbook(removed)).definedNames).toEqual([
    { name: '城市', refersTo: 'Sheet1!$A$2' },
    { name: 'RateMark', refersTo: 'Sheet1!$B$3' }, { name: '旧名', refersTo: 'Sheet1!$B$2' },
  ])
})

it('creates and updates a sheet-scoped name independently from the same global name, then saves and restores it', async () => {
  const source = await applyDefinedNames(await applySheetEdits(await createBlankWorkbook(), { renames: [], additions: [{ name: 'Other' }], removals: [], order: ['Sheet1', 'Other'] }),
    { sets: [{ name: 'Rate', refersTo: '10' }, { name: 'Rate', refersTo: '20', scopeSheetName: 'Other' }] })
  const storage = store(), draft = new NativeDraft(identity, storage)
  let downloaded: Uint8Array | undefined
  const save = async (request: NativeSaveRequest) => {
    downloaded = await applyWorkbookOperations(source, request.operations)
    return { revision: 2, revisionRegistered: true, artifacts: { xlsx: { downloadUrl: '/names.xlsx' } }, validation: { issues: [] } }
  }
  const current = await open(source, draft, save)
  grid.ribbon('name-manager-open')
  const box = dialog(), scope = document.querySelector<HTMLSelectElement>('[aria-label="名称作用域"]')!
  expect([...scope.options].map(option => option.textContent)).toEqual(['工作簿', 'Sheet1', 'Other'])
  const sheetId = grid.api.getActiveWorkbook().getSheetByName('Sheet1').getSheetId()
  scope.value = sheetId
  box.name.value = 'Rate'; box.ref.value = '30'; box.add.click()
  expect(box.error.textContent).toBe('')
  expect(liveNames()).toContainEqual({ name: 'Rate', refersTo: '30', scopeSheetId: sheetId })
  await vi.waitFor(() => expect(namesOperation(draft.operations)?.plan.sets).toEqual([{ name: 'Rate', refersTo: '30', scopeSheetName: 'Sheet1' }]))
  history('undo')
  await vi.waitFor(() => expect(draft.operations).toEqual([]))
  history('redo')
  await vi.waitFor(() => expect(namesOperation(draft.operations)?.plan.sets).toHaveLength(1))
  current.view?.dispose()
  const restored = new NativeDraft(identity, storage)
  const reopened = await open(source, restored, save)
  expect(liveNames().filter(row => row.name === 'Rate')).toHaveLength(3)
  grid.ribbon('name-manager-open')
  const selected = dialog(), local = liveNames().find(row => row.name === 'Rate' && row.scopeSheetId === 'sheet-0')!
  selected.list.value = [...selected.list.options].find(option => option.textContent?.includes('Sheet1'))!.value
  selected.list.dispatchEvent(new Event('change'))
  expect(document.querySelector<HTMLSelectElement>('[aria-label="名称作用域"]')!.disabled).toBe(true)
  selected.ref.value = '40'; selected.update.click()
  expect(selected.error.textContent).toBe('')
  expect(liveNames()).toContainEqual({ ...local, refersTo: '40' })
  reopened.shell.save.click()
  await vi.waitFor(() => expect(reopened.shell.statusLabel.textContent).toContain('已保存修订 2'))
  expect((await readWorkbook(downloaded!)).definedNames).toEqual(expect.arrayContaining([
    { name: 'Rate', refersTo: '10' }, { name: 'Rate', refersTo: '20', scopeSheetName: 'Other' }, { name: 'Rate', refersTo: '40', scopeSheetName: 'Sheet1' },
  ]))
  reopened.view?.dispose()
})


it.each([
  { mode: 'insert', targetId: 'sheet-0', before: '$A$1', row: '$A$2', after: '$B$2' },
  { mode: 'delete', targetId: 'sheet-0', before: '$B$2', row: '$B$1', after: '$A$1' },
  { mode: 'delete-inactive', targetId: 'sheet-1', before: '$B$2', row: '$B$1', after: '$A$1' },
])('keeps local name $mode row and column shifts in their owning sheet through undo, draft restore and real save', async ({ mode, targetId, before, row, after }) => {
  const source = await applyDefinedNames(await applySheetEdits(await fixture(), { renames: [], additions: [{ name: 'Other' }], removals: [], order: ['Sheet1', 'Other'] }),
    { sets: [{ name: 'Local', refersTo: before, scopeSheetName: 'Sheet1' }, { name: 'Local', refersTo: before, scopeSheetName: 'Other' }] })
  const storage = store(), draft = new NativeDraft(identity, storage)
  let downloaded: Uint8Array | undefined
  const save = async (request: NativeSaveRequest) => {
    downloaded = await applyWorkbookOperations(source, request.operations)
    return { revision: 2, revisionRegistered: true, artifacts: { xlsx: { downloadUrl: '/names.xlsx' } }, validation: { issues: [] } }
  }
  const current = await open(source, draft, save)
  const otherId = targetId === 'sheet-0' ? 'sheet-1' : 'sheet-0'
  const target = () => grid.api.getActiveWorkbook().getSheetBySheetId(targetId)
  const local = (id: string) => liveNames().find(row => row.name === 'Local' && row.scopeSheetId === id)?.refersTo
  if (mode === 'insert') target().insertRowsBefore(0, 1)
  else target().deleteRows(0, 1)
  expect(local(targetId)).toBe(row)
  expect(local(otherId)).toBe(before)
  history('undo')
  expect(local(targetId)).toBe(before)
  expect(local(otherId)).toBe(before)
  history('redo')
  if (mode === 'insert') target().insertColumnsBefore(0, 1)
  else target().deleteColumns(0, 1)
  expect(local(targetId)).toBe(after)
  expect(local(otherId)).toBe(before)
  await vi.waitFor(() => expect(draft.operations.some(op => op.kind === 'applyRowColumnOps')).toBe(true))
  expect(namesOperation(draft.operations)).toBeUndefined()
  current.view?.dispose()
  const restored = new NativeDraft(identity, storage)
  const reopened = await open(source, restored, save)
  expect(local(targetId)).toBe(after)
  expect(local(otherId)).toBe(before)
  reopened.shell.save.click()
  await vi.waitFor(() => expect(reopened.shell.statusLabel.textContent).toContain('已保存修订 2'))
  const saved = await readWorkbook(downloaded!)
  expect(saved.definedNames).toEqual(expect.arrayContaining([
    { name: 'Local', refersTo: after, scopeSheetName: targetId === 'sheet-0' ? 'Sheet1' : 'Other' },
    { name: 'Local', refersTo: before, scopeSheetName: targetId === 'sheet-0' ? 'Other' : 'Sheet1' },
  ]))
  if (targetId === 'sheet-1') expect(saved.definedNames).toEqual(expect.arrayContaining([
    { name: 'RateMark', refersTo: 'Sheet1!$B$3' }, { name: '旧名', refersTo: 'Sheet1!$B$2' },
  ]))
  reopened.view?.dispose()
})
