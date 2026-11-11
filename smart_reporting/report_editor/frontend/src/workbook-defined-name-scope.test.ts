import { expect, it } from 'vitest'
import { applyDefinedNameAction, definedNamesPlan, liveDefinedNames } from './workbook-defined-names'

it('keeps same-named global and local entries distinct and resolves stable IDs at save', () => {
  const entry = (scope?: string) => ({ getName: () => 'Rate', getFormulaOrRefString: () => '2', getLocalSheetId: () => scope })
  expect(liveDefinedNames({ getDefinedNames: () => [entry(), entry('first'), entry('second')] } as any)).toEqual([
    { name: 'Rate', refersTo: '2' }, { name: 'Rate', refersTo: '2', scopeSheetId: 'first' }, { name: 'Rate', refersTo: '2', scopeSheetId: 'second' },
  ])
  expect(definedNamesPlan([], [{ name: 'Rate', refersTo: '2', scopeSheetId: 'first' }], [{ id: 'first', name: 'Renamed' }])).toEqual({ sets: [{ name: 'Rate', refersTo: '2', scopeSheetName: 'Renamed' }] })
})

it('calculates local precedence and explicit sheet names from real XLSX including repeated cached formulas', async () => {
  const { applyDefinedNames, createBlankWorkbook, readWorkbook } = await import('@sheets-web/xlsx-engine')
  const { applyWorkbookOperations } = await import('../../../reporting/workbook_engine/bridge/operations')
  const { Univer, LocaleType, IUniverInstanceService } = await import('@univerjs/core')
  const { UniverSheetsPlugin } = await import('@univerjs/sheets')
  const { UniverFormulaEnginePlugin, IFormulaCurrentConfigService, IFormulaRuntimeService, Lexer, AstTreeBuilder, Interpreter, BaseReferenceObject, ArrayValueObject } = await import('@univerjs/engine-formula')
  const { FUniver } = await import('@univerjs/core/lib/facade')
  await import('@univerjs/sheets/facade')
  const { buildWorkbookData } = await import('./workbook-vendor/core/univer-data')
  const { loadWorkbookData } = await import('./workbook-vendor/grid/sync')
  const { installDefinedNameScopes } = await import('./workbook-defined-name-scope')
  const bytes = await applyWorkbookOperations(await createBlankWorkbook(), [{ kind: 'applySheetEdits', plan: {
    renames: [], additions: [{ name: 'Other Sheet' }, { name: 'Fallback' }], removals: [], order: ['Sheet1', 'Other Sheet', 'Fallback'],
  } }])
  const source = await applyDefinedNames(bytes, { sets: [
    { name: 'Rate', refersTo: '10' }, { name: 'Rate', refersTo: '20', scopeSheetName: 'Sheet1' }, { name: 'Rate', refersTo: '30', scopeSheetName: 'Other Sheet' },
    { name: 'Loop', refersTo: 'Loop', scopeSheetName: 'Sheet1' },
    { name: 'Relative', refersTo: 'A1', scopeSheetName: 'Other Sheet' }, { name: 'Chain', refersTo: 'Relative', scopeSheetName: 'Other Sheet' },
  ] })
  const model = await readWorkbook(source), univer = new Univer({ locale: LocaleType.EN_US, locales: { [LocaleType.EN_US]: {} } })
  let installed: ReturnType<typeof installDefinedNameScopes> | undefined
  try {
    univer.registerPlugin(UniverSheetsPlugin); univer.registerPlugin(UniverFormulaEnginePlugin)
    const api = FUniver.newAPI(univer), runtime = { univer, univerAPI: api }
    loadWorkbookData(runtime as any, buildWorkbookData(model, 'scope', 'scope'))
    univer.__getInjector().get(IUniverInstanceService).focusUnit('scope')
    installed = installDefinedNameScopes(runtime)
    expect(liveDefinedNames(api.getActiveWorkbook()!)).toHaveLength(6)
    const injector = univer.__getInjector(), config = injector.get(IFormulaCurrentConfigService)
    api.getActiveWorkbook()!.getSheetBySheetId('sheet-0')!.getRange(0, 0).setValue(111)
    api.getActiveWorkbook()!.getSheetBySheetId('sheet-1')!.getRange(0, 0).setValue(222)
    config.loadDataLite()
    const calculate = (sheetId: string, formula: string) => {
      config.setExecuteUnitId('scope'); config.setExecuteSubUnitId(sheetId)
      injector.get(IFormulaRuntimeService).setCurrent(5, 5, 100, 100, sheetId, 'scope')
      const tree = injector.get(Lexer).treeBuilder(formula)
      const ast = injector.get(AstTreeBuilder).parse(tree as any)
      const result = injector.get(Interpreter).execute({ node: ast, refOffsetX: 0, refOffsetY: 0 })
      const value = result instanceof BaseReferenceObject ? result.toArrayValueObject() : result
      return value instanceof ArrayValueObject ? value.getArrayValue()[0]?.[0]?.getValue() : value.getValue()
    }
    expect(calculate('sheet-0', '=Rate+1')).toBe(21)
    expect(calculate('sheet-1', '=Rate+1')).toBe(31)
    expect(calculate('sheet-2', '=Rate+1')).toBe(11)
    expect(calculate('sheet-0', "='Other Sheet'!Rate+1")).toBe(31)
    expect(calculate('sheet-1', '=Sheet1!Rate+1')).toBe(21)
    expect(calculate('sheet-0', "='Other Sheet'!A1+1")).toBe(223)
    expect(calculate('sheet-0', "='other sheet'!Relative+1")).toBe(223)
    expect(calculate('sheet-0', "='Other Sheet'!Chain+1")).toBe(223)
    expect(calculate('sheet-0', '=Loop')).toBe('#NAME?')
    expect(calculate('sheet-1', '="Rate"')).toBe('Rate')
  } finally { installed?.dispose(); univer.dispose() }
})

it('uses real scoped facade actions with undo/redo and saves a restored draft without crossing scopes', async () => {
  const { Univer, LocaleType, IUniverInstanceService } = await import('@univerjs/core')
  const { UniverSheetsPlugin } = await import('@univerjs/sheets')
  const { UniverFormulaEnginePlugin } = await import('@univerjs/engine-formula')
  const { FUniver } = await import('@univerjs/core/lib/facade')
  await import('@univerjs/sheets/facade')
  const { applyDefinedNameAction, definedNamesPlanOperation, createNameManagerDialog, definedNameKey } = await import('./workbook-defined-names')
  const { applyWorkbookOperations } = await import('../../../reporting/workbook_engine/bridge/operations')
  const { createBlankWorkbook, readWorkbook } = await import('@sheets-web/xlsx-engine')
  const { buildWorkbookData } = await import('./workbook-vendor/core/univer-data')
  const { loadWorkbookData } = await import('./workbook-vendor/grid/sync')
  const source = await applyWorkbookOperations(await createBlankWorkbook(), [{ kind: 'applySheetEdits', plan: { additions: [{ name: 'Other' }], renames: [], removals: [], order: ['Sheet1', 'Other'] } }])
  const model = await readWorkbook(source), univer = new Univer({ locale: LocaleType.EN_US, locales: { [LocaleType.EN_US]: {} } })
  const { installDefinedNameScopes } = await import('./workbook-defined-name-scope')
  let installed: ReturnType<typeof installDefinedNameScopes> | undefined
  let dialog: ReturnType<typeof createNameManagerDialog> | undefined
  try {
    univer.registerPlugin(UniverSheetsPlugin); univer.registerPlugin(UniverFormulaEnginePlugin)
    const api = FUniver.newAPI(univer)
    loadWorkbookData({ univer, univerAPI: api } as any, buildWorkbookData(model, 'scope-actions', 'scope'))
    univer.__getInjector().get(IUniverInstanceService).focusUnit('scope-actions')
    installed = installDefinedNameScopes({ univer, univerAPI: api })
    let workbook = api.getActiveWorkbook()!
    const rows = () => liveDefinedNames(workbook)!
    const sheets = () => workbook.getSheets().map(sheet => ({ id: sheet.getSheetId(), name: sheet.getSheetName() }))
    const apply = (action: any) => applyDefinedNameAction(workbook, action, rows())
    expect(apply({ kind: 'add', name: 'ScopedRate', ref: '10' })).toBeNull()
    expect(apply({ kind: 'add', name: 'ScopedRate', ref: '20', scopeSheetId: 'sheet-0' })).toBeNull()
    expect(apply({ kind: 'add', name: 'ScopedRate', ref: '30', scopeSheetId: 'sheet-1' })).toBeNull()
    expect(rows()).toHaveLength(3)
    await api.undo(); expect(rows()).toHaveLength(2)
    await api.redo(); expect(rows()).toHaveLength(3)
    expect(apply({ kind: 'add', name: 'scopedrate', ref: '90', scopeSheetId: 'sheet-0' })).toContain('冲突')
    expect(apply({ kind: 'update', originalName: 'ScopedRate', name: 'RenamedScopedRate', ref: '21', scopeSheetId: 'sheet-0' })).toBeNull()
    await api.undo(); expect(rows()).toContainEqual({ name: 'ScopedRate', refersTo: '20', scopeSheetId: 'sheet-0' })
    await api.redo(); expect(rows()).toContainEqual({ name: 'RenamedScopedRate', refersTo: '21', scopeSheetId: 'sheet-0' })
    expect(apply({ kind: 'remove', name: 'ScopedRate', scopeSheetId: 'sheet-1' })).toBeNull()
    await api.undo(); expect(rows()).toHaveLength(3)
    await api.redo(); expect(rows()).toHaveLength(2)
    const operation = definedNamesPlanOperation(model.definedNames ?? [], rows(), sheets())!
    const restored = JSON.parse(JSON.stringify([operation]))
    const reopened = await readWorkbook(await applyWorkbookOperations(source, restored))
    expect(reopened.definedNames).toEqual(expect.arrayContaining([{ name: 'ScopedRate', refersTo: '10' }, { name: 'RenamedScopedRate', refersTo: '21', scopeSheetName: 'Sheet1' }]))
    expect(reopened.definedNames).toHaveLength(2)
    // AI采纳/撤销、草稿重放会销毁并重建同unit的新core；installer仍须作用于新实例。
    const oldCore = workbook.getWorkbook()
    loadWorkbookData({ univer, univerAPI: api } as any, buildWorkbookData(reopened, 'scope-actions', 'scope'))
    univer.__getInjector().get(IUniverInstanceService).focusUnit('scope-actions')
    const recreated = api.getActiveWorkbook()!
    expect(recreated.getWorkbook()).not.toBe(oldCore)
    expect(applyDefinedNameAction(recreated, { kind: 'add', name: 'ScopedRate', ref: '99', scopeSheetId: 'sheet-1' }, liveDefinedNames(recreated)!)).toBeNull()
    await api.undo()
    expect(liveDefinedNames(recreated)).toHaveLength(2)
    await api.redo()
    expect(liveDefinedNames(recreated)).toHaveLength(3)

    workbook = recreated
    document.body.innerHTML = '<main></main>'
    dialog = createNameManagerDialog(document.querySelector('main')!, { rows, sheets, apply })
    dialog.open()
    const scope = document.querySelector<HTMLSelectElement>('[aria-label="名称作用域"]')!
    expect([...scope.options].map(option => option.value)).toEqual(['', 'sheet-0', 'sheet-1'])
    const list = document.querySelector<HTMLSelectElement>('.workbook-defined-name-list')!
    expect([...list.options].map(option => option.value)).toContain('ScopedRate')
    list.value = definedNameKey({ name: 'RenamedScopedRate', scopeSheetId: 'sheet-0' }); list.dispatchEvent(new Event('change'))
    expect(scope.value).toBe('sheet-0'); expect(scope.disabled).toBe(true)
  } finally { installed?.dispose(); dialog?.dispose(); univer.dispose(); document.body.replaceChildren() }
})

it('drops removed-sheet scopes from the baseline without deleting a same-named global', () => {
  expect(definedNamesPlan([{ name: 'NamedValue', refersTo: '10' }, { name: 'NamedValue', refersTo: '20', scopeSheetName: 'Deleted' }],
    [{ name: 'NamedValue', refersTo: '10' }], [{ id: 'first', name: 'Kept' }])).toEqual({})
})

it('shifts unqualified local references with real row commands and keeps one-step undo', async () => {
  const { Univer, LocaleType, IUniverInstanceService } = await import('@univerjs/core')
  const { UniverSheetsPlugin } = await import('@univerjs/sheets')
  const { UniverFormulaEnginePlugin } = await import('@univerjs/engine-formula')
  const { UniverSheetsFormulaPlugin } = await import('@univerjs/sheets-formula')
  const { FUniver } = await import('@univerjs/core/lib/facade')
  await import('@univerjs/sheets/facade')
  const { applyDefinedNames, createBlankWorkbook, readWorkbook } = await import('@sheets-web/xlsx-engine')
  const { buildWorkbookData } = await import('./workbook-vendor/core/univer-data')
  const { loadWorkbookData } = await import('./workbook-vendor/grid/sync')
  const { installDefinedNameScopes } = await import('./workbook-defined-name-scope')
  const { applySheetEdits } = await import('@sheets-web/xlsx-engine/sheet-ops')
  const two = await applySheetEdits(await createBlankWorkbook(), { renames: [], removals: [], additions: [{ name: 'Other' }], order: ['Sheet1', 'Other'] })
  const model = await readWorkbook(await applyDefinedNames(two, { sets: [{ name: 'Local', refersTo: '$A$1', scopeSheetName: 'Sheet1' }, { name: 'Local', refersTo: '$A$1', scopeSheetName: 'Other' }, { name: 'FutureRef', refersTo: '$B$2', scopeSheetName: 'Other' }] }))
  const univer = new Univer({ locale: LocaleType.EN_US, locales: { [LocaleType.EN_US]: {} } })
  let installed: ReturnType<typeof installDefinedNameScopes> | undefined
  try {
    univer.registerPlugin(UniverSheetsPlugin); univer.registerPlugin(UniverFormulaEnginePlugin); univer.registerPlugin(UniverSheetsFormulaPlugin)
    const api = FUniver.newAPI(univer), runtime = { univer, univerAPI: api }
    loadWorkbookData(runtime as any, buildWorkbookData(model, 'local-shift', 'scope'))
    univer.__getInjector().get(IUniverInstanceService).focusUnit('local-shift')
    installed = installDefinedNameScopes(runtime)
    const workbook = api.getActiveWorkbook()!, sheet = workbook.getActiveSheet()!
    sheet.insertRowsBefore(0, 1)
    expect(liveDefinedNames(workbook)).toContainEqual({ name: 'Local', refersTo: '$A$2', scopeSheetId: 'sheet-0' })
    expect(liveDefinedNames(workbook)).toContainEqual({ name: 'Local', refersTo: '$A$1', scopeSheetId: 'sheet-1' })
    await api.undo()
    expect(liveDefinedNames(workbook)).toContainEqual({ name: 'Local', refersTo: '$A$1', scopeSheetId: 'sheet-0' })
    await api.redo()
    expect(liveDefinedNames(workbook)).toContainEqual({ name: 'Local', refersTo: '$A$2', scopeSheetId: 'sheet-0' })
    sheet.deleteRows(0, 1)
    expect(liveDefinedNames(workbook)).toContainEqual({ name: 'FutureRef', refersTo: '$B$2', scopeSheetId: 'sheet-1' })
    expect(liveDefinedNames(workbook)).toContainEqual({ name: 'Local', refersTo: '$A$1', scopeSheetId: 'sheet-0' })
    expect(liveDefinedNames(workbook)).toContainEqual({ name: 'Local', refersTo: '$A$1', scopeSheetId: 'sheet-1' })
    await api.undo()
    expect(liveDefinedNames(workbook)).toContainEqual({ name: 'Local', refersTo: '$A$2', scopeSheetId: 'sheet-0' })
    expect(liveDefinedNames(workbook)).toContainEqual({ name: 'Local', refersTo: '$A$1', scopeSheetId: 'sheet-1' })
    sheet.insertColumnsBefore(0, 1)
    expect(liveDefinedNames(workbook)).toContainEqual({ name: 'Local', refersTo: '$B$2', scopeSheetId: 'sheet-0' })
    sheet.deleteColumns(0, 1)
    expect(liveDefinedNames(workbook)).toContainEqual({ name: 'FutureRef', refersTo: '$B$2', scopeSheetId: 'sheet-1' })
    for (const scopeSheetId of ['sheet-0', 'sheet-1']) expect(applyDefinedNameAction(workbook, { kind: 'update', originalName: 'Local', name: 'Local', ref: '$B$2', scopeSheetId }, liveDefinedNames(workbook)!)).toBeNull()
    expect(applyDefinedNameAction(workbook, { kind: 'add', name: 'GlobalQualified', ref: 'Sheet1!$B$3' }, liveDefinedNames(workbook)!)).toBeNull()
    expect(applyDefinedNameAction(workbook, { kind: 'add', name: 'OtherQualified', ref: 'Other!$B$3' }, liveDefinedNames(workbook)!)).toBeNull()
    const other = workbook.getSheetByName('Other')!
    expect(workbook.getActiveSheet()!.getSheetId()).toBe('sheet-0')
    other.deleteRows(0, 1)
    expect(liveDefinedNames(workbook)).toContainEqual({ name: 'GlobalQualified', refersTo: 'Sheet1!$B$3' })
    expect(liveDefinedNames(workbook)).toContainEqual({ name: 'OtherQualified', refersTo: 'Other!$B$2' })
    expect(liveDefinedNames(workbook)).toContainEqual({ name: 'Local', refersTo: '$B$1', scopeSheetId: 'sheet-1' })
    expect(liveDefinedNames(workbook)).toContainEqual({ name: 'Local', refersTo: '$B$2', scopeSheetId: 'sheet-0' })
    other.deleteColumns(0, 1)
    expect(liveDefinedNames(workbook)).toContainEqual({ name: 'GlobalQualified', refersTo: 'Sheet1!$B$3' })
    expect(liveDefinedNames(workbook)).toContainEqual({ name: 'OtherQualified', refersTo: 'Other!$A$2' })
    expect(liveDefinedNames(workbook)).toContainEqual({ name: 'Local', refersTo: '$A$1', scopeSheetId: 'sheet-1' })
    expect(liveDefinedNames(workbook)).toContainEqual({ name: 'Local', refersTo: '$B$2', scopeSheetId: 'sheet-0' })
    expect(workbook.getActiveSheet()!.getSheetId()).toBe('sheet-0')
  } finally { installed?.dispose(); univer.dispose() }
})

it('removes owned local names in the sheet history and restores exact scoped metadata on undo', async () => {
  const { Univer, LocaleType, IUniverInstanceService } = await import('@univerjs/core')
  const { UniverSheetsPlugin } = await import('@univerjs/sheets')
  const { UniverFormulaEnginePlugin, IDefinedNamesService } = await import('@univerjs/engine-formula')
  const { FUniver } = await import('@univerjs/core/lib/facade')
  await import('@univerjs/sheets/facade')
  const { createBlankWorkbook, readWorkbook } = await import('@sheets-web/xlsx-engine')
  const { applyWorkbookOperations } = await import('../../../reporting/workbook_engine/bridge/operations')
  const { buildWorkbookData } = await import('./workbook-vendor/core/univer-data')
  const { loadWorkbookData } = await import('./workbook-vendor/grid/sync')
  const { installDefinedNameScopes } = await import('./workbook-defined-name-scope')
  const bytes = await applyWorkbookOperations(await createBlankWorkbook(), [{ kind: 'applySheetEdits', plan: { additions: [{ name: 'Other' }, { name: 'Third' }], renames: [], removals: [], order: ['Sheet1', 'Other', 'Third'] } }, { kind: 'applyDefinedNames', plan: { sets: [{ name: 'Rate', refersTo: 'Sheet1!A1', scopeSheetName: 'Sheet1' }, { name: 'Rate', refersTo: '1' }, { name: 'Rate', refersTo: '2', scopeSheetName: 'Third' }] } }])
  const univer = new Univer({ locale: LocaleType.EN_US, locales: { [LocaleType.EN_US]: {} } })
  let installed: ReturnType<typeof installDefinedNameScopes> | undefined
  try {
    univer.registerPlugin(UniverSheetsPlugin); univer.registerPlugin(UniverFormulaEnginePlugin)
    const api = FUniver.newAPI(univer), runtime = { univer, univerAPI: api }
    loadWorkbookData(runtime as any, buildWorkbookData(await readWorkbook(bytes), 'owned-name', 'owned-name'))
    univer.__getInjector().get(IUniverInstanceService).focusUnit('owned-name');installed = installDefinedNameScopes(runtime)
    const workbook = api.getActiveWorkbook()!, names = univer.__getInjector().get(IDefinedNamesService)
    const map = () => structuredClone(names.getDefinedNameMap(workbook.getId()) ?? {})
    const before = map(), owned = Object.values(before).find((entry: any) => entry.localSheetId === 'sheet-0')!
    const remove = (id: string) => api.syncExecuteCommand('sheet.command.remove-sheet', { unitId: workbook.getId(), subUnitId: id })
    expect(remove('sheet-0')).toBe(true)
    expect(map()[owned.id]).toBeUndefined()
    expect(Object.values(map()).map((entry: any) => entry.formulaOrRefString).sort()).toEqual(['1', '2'])
    expect(await api.undo()).toBe(true);expect(map()).toEqual(before)
    expect(await api.redo()).toBe(true);expect(map()[owned.id]).toBeUndefined()
    expect(remove('sheet-1')).toBe(true);expect(workbook.getSheets().map(s => s.getSheetName())).toEqual(['Third'])
    expect(Object.values(map()).map((entry: any) => entry.formulaOrRefString).sort()).toEqual(['1', '2'])
  } finally { installed?.dispose();univer.dispose() }
})
