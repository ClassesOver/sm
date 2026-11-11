import { expect, it } from 'vitest'
import { installDataValidationStructure } from './workbook-data-validation-structure'

it('preserves workbook-like string literals and the exact undo formula', () => {
  let interceptor: any
  const rule = { uid: 'r', type: 'custom', formula1: '=IF(B2="[x]",1,0)', ranges: [{ startRow: 0, endRow: 0, startColumn: 0, endColumn: 0 }] }
  const sheet = { getSheetId: () => 's', getSheetName: () => 'Sheet1', getDataValidations: () => [{ rule }] }
  const other = { getSheetId: () => 'o', getSheetName: () => 'Other', getDataValidations: () => [] }
  const service = { interceptCommand: (value: any) => { interceptor = value; return { dispose() {} } } }
  const workbook = { getId: () => 'x', getSheets: () => [sheet, other], getActiveSheet: () => sheet, getSheetBySheetId: (id: string) => id === 'o' ? other : sheet }
  installDataValidationStructure({ univer: { __getInjector: () => ({ get: () => service }) }, univerAPI: { getActiveWorkbook: () => workbook } })
  const run = (subUnitId: string) => interceptor.getMutations({ id: 'sheet.command.insert-row', params: { subUnitId, range: { startRow: 0, endRow: 0, startColumn: 0, endColumn: 9 } } })
  expect(run('o')).toEqual({ redos: [], undos: [] })
  const moved = run('s')
  expect(moved.redos[0].params.payload.payload.formula1).toBe('=IF(B3="[x]",1,0)')
  expect(moved.undos[0].params.payload.payload.formula1).toBe(rule.formula1)
})

it('recognizes only actual official CF follower parameter objects across redo and undo', async () => {
  const { SetConditionalRuleMutation, DeleteConditionalRuleMutation } = await import('@univerjs/sheets-conditional-formatting')
  const redo = { unitId: 'u', subUnitId: 's', cfId: 'r', rule: { ranges: [{ startRow: 2, endRow: 4, startColumn: 0, endColumn: 0 }] } }
  const undo = { unitId: 'u', subUnitId: 's', cfId: 'r' }
  const service = { interceptCommand: () => ({ dispose() {} }), onCommandExecute: (_command?: unknown) => ({ redos: [{ id: SetConditionalRuleMutation.id, params: redo }], undos: [{ id: DeleteConditionalRuleMutation.id, params: undo }] }) }
  const original = service.onCommandExecute
  const workbook = { getId: () => 'u', getSheets: () => [], getActiveSheet: () => null, getTableList: () => [] }
  const controller = installDataValidationStructure({ univer: { __getInjector: () => ({ get: () => service }) }, univerAPI: { getActiveWorkbook: () => workbook } })
  try {
    service.onCommandExecute({ id: 'sheet.command.insert-row', params: {} } as never)
    expect(controller.ownsMutation(redo)).toBe(true)
    expect(controller.ownsMutation(undo)).toBe(true)
    expect(controller.ownsMutation({ ...redo, source: 'patched' })).toBe(false)
    expect(controller.ownsMutation({ ...undo })).toBe(false)
  } finally { controller.dispose() }
  expect(service.onCommandExecute).toBe(original)
})

it('replaces official split followers with a complete ordered source plan before publishing structural mutations', async () => {
  const { AddConditionalRuleMutation, DeleteConditionalRuleMutation } = await import('@univerjs/sheets-conditional-formatting')
  const current = [
    { cfId: 'high', stopIfTrue: true, ranges: [{ startRow: 0, endRow: 3, startColumn: 1, endColumn: 1 }], rule: { type: 'highlightCell', subType: 'formula', value: '=TRUE', style: {} } },
    { cfId: 'parent', stopIfTrue: false, ranges: [{ startRow: 0, endRow: 3, startColumn: 1, endColumn: 1 }], rule: { type: 'highlightCell', subType: 'formula', value: '=Source!A1>0', style: {} } },
  ]
  const stale = { id: AddConditionalRuleMutation.id, params: { unitId: 'foreign', subUnitId: 's', rule: { cfId: 'wrong' } } }
  const unrelated = { id: 'sheet.mutation.set-range-values', params: { keep: true } }
  const result = { redos: [stale, unrelated] as any[], undos: [stale] as any[], preRedos: [stale] as any[], preUndos: [stale] as any[] }
  const service = { interceptCommand: () => ({ dispose() {} }), onCommandExecute: (_command?: unknown) => result }
  const source = { getSheetId: () => 'source', getSheetName: () => 'Source', getDataValidations: () => [], getConditionalFormattingRules: () => [] }
  const other = { getSheetId: () => 'other', getSheetName: () => 'Other', getDataValidations: () => [], getConditionalFormattingRules: () => current }
  const workbook = { getId: () => 'u', getSheets: () => [source, other], getActiveSheet: () => source, getSheetBySheetId: (id: string) => id === 'source' ? source : other, getTableList: () => [] }
  const controller = installDataValidationStructure({ univer: { __getInjector: () => ({ get: () => service }) }, univerAPI: { getActiveWorkbook: () => workbook } })
  try {
    service.onCommandExecute({ id: 'sheet.command.insert-row', params: { unitId: 'u', subUnitId: 'source', range: { startRow: 1, endRow: 1, startColumn: 0, endColumn: 25 } } })
    expect(result.redos).toContain(unrelated)
    expect(result.preRedos).toEqual([]); expect(result.preUndos).toEqual([])
    const additions = result.redos.filter(mutation => mutation.id === AddConditionalRuleMutation.id)
    expect(additions).toHaveLength(3)
    expect(additions.at(-1)!.params.rule.cfId).toBe('high')
    expect(result.redos.filter(mutation => mutation.id === DeleteConditionalRuleMutation.id)).toHaveLength(2)
    for (const mutation of [...result.redos, ...result.undos].filter(mutation => mutation.id !== unrelated.id)) {
      expect(mutation.params.unitId).toBe('u'); expect(controller.ownsMutation(mutation.params)).toBe(true)
    }
    expect(controller.ownsMutation(stale.params)).toBe(false)
  } finally { controller.dispose() }
})

it.each(['insert-row', 'set-worksheet-name'])('leaves the whole official result untouched when %s has a CF plan that cannot be represented', async command => {
  const { AddConditionalRuleMutation } = await import('@univerjs/sheets-conditional-formatting')
  const original = { redos: [{ id: AddConditionalRuleMutation.id, params: { unitId: 'u', marker: 'untouched' } }], undos: [] }
  const frozen = structuredClone(original)
  const service = { interceptCommand: () => ({ dispose() {} }), onCommandExecute: (_command?: unknown) => original }
  const rule = { cfId: 'r', ranges: [{ startRow: 0, endRow: 3, startColumn: 0, endColumn: 0 }], stopIfTrue: false, rule: { type: 'highlightCell', subType: 'timePeriod', style: {} } }
  const source = { getSheetId: () => 'source', getSheetName: () => 'Source', getDataValidations: () => [], getConditionalFormattingRules: () => [rule] }
  const workbook = { getId: () => 'u', getSheets: () => [source], getActiveSheet: () => source, getSheetBySheetId: () => source, getTableList: () => [] }
  const controller = installDataValidationStructure({ univer: { __getInjector: () => ({ get: () => service }) }, univerAPI: { getActiveWorkbook: () => workbook } })
  try {
    expect(() => service.onCommandExecute({ id: `sheet.command.${command}`, params: { unitId: 'u', subUnitId: 'source', name: 'Renamed', range: { startRow: 1, endRow: 1, startColumn: 0, endColumn: 25 } } })).toThrow()
    expect(original).toEqual(frozen)
    expect(controller.ownsMutation(original.redos[0]!.params)).toBe(false)
  } finally { controller.dispose() }
})

it.each(['insert-range-move-right', 'insert-range-move-down', 'delete-range-move-left', 'delete-range-move-up'])('normalizes CF for %s before the base mutation while retaining DV/table followers', async command => {
  const { AddConditionalRuleMutation, DeleteConditionalRuleMutation, SetConditionalRuleMutation } = await import('@univerjs/sheets-conditional-formatting')
  const horizontal = command.endsWith('right') || command.endsWith('left')
  const range = horizontal ? { startRow: 1, endRow: 1, startColumn: 0, endColumn: 3 } : { startRow: 0, endRow: 3, startColumn: 1, endColumn: 1 }
  const current = [{ cfId: 'original', ranges: [range], stopIfTrue: true, rule: { type: 'highlightCell', subType: 'formula', value: '=TRUE', style: {} } }]
  const stale = { id: SetConditionalRuleMutation.id, params: { unitId: 'u', subUnitId: 's', cfId: 'wrong' } }
  const dv = { id: 'data-validation.mutation.updateRule', params: { preserve: 'dv' } }
  const table = { id: 'sheet.mutation.set-sheet-table', params: { preserve: 'table' } }
  const result = { redos: [stale, dv, table] as any[], undos: [stale] as any[] }
  const before = structuredClone(result)
  const service = { interceptCommand: () => ({ dispose() {} }), onCommandExecute: (_command?: unknown) => result }
  const sheet = { getSheetId: () => 's', getSheetName: () => 'Source', getDataValidations: () => [], getConditionalFormattingRules: () => current }
  const workbook = { getId: () => 'u', getSheets: () => [sheet], getActiveSheet: () => sheet, getSheetBySheetId: () => sheet, getTableList: () => [] }
  let reject = true
  const controller = installDataValidationStructure({ univer: { __getInjector: () => ({ get: () => service }) }, univerAPI: { getActiveWorkbook: () => workbook } }, () => { if (reject) throw Error('budget') })
  const execute = () => service.onCommandExecute({ id: `sheet.command.${command}`, params: { unitId: 'u', subUnitId: 's', range: { startRow: 1, endRow: 1, startColumn: 1, endColumn: 1 } } })
  try {
    expect(execute).toThrow('数据验证结构迁移预检失败')
    expect(result).toEqual(before)
    expect(controller.ownsMutation(stale.params)).toBe(false)
    reject = false
    execute()
    expect(result.redos).toContain(dv); expect(result.redos).toContain(table)
    expect(result.redos).not.toContain(stale)
    expect(result.redos.some(mutation => mutation.id === AddConditionalRuleMutation.id)).toBe(true)
    expect(controller.ownsMutation(dv.params)).toBe(true)
    expect(controller.ownsMutation(table.params)).toBe(true)
    for (const mutation of [...result.redos, ...result.undos]) expect(controller.ownsMutation(mutation.params)).toBe(true)
    const apply = (rules: any[], mutations: any[]) => {
      for (const mutation of mutations) {
        if (mutation.id === DeleteConditionalRuleMutation.id) rules = rules.filter(rule => rule.cfId !== mutation.params.cfId)
        else if (mutation.id === AddConditionalRuleMutation.id) rules.unshift(structuredClone(mutation.params.rule))
      }
      return rules
    }
    // 四个官方cells command均在登记历史前reverse整个undo批次，line command保持正序。
    expect(apply(apply(structuredClone(current), result.redos), [...result.undos].reverse())).toEqual(current)
  } finally { controller.dispose() }
})

it('registers raw-style command lifecycle hooks and disposes them with the collector', () => {
  let before: any, after: any, released = 0
  const service = { interceptCommand: () => ({ dispose() { released++ } }), onCommandExecute: (_command: any) => ({ redos: [], undos: [] }),
    beforeCommandExecuted: (listener: any) => { before = listener; return { dispose() { released++ } } },
    onCommandExecuted: (listener: any) => { after = listener; return { dispose() { released++ } } } }
  const sheet = { getSheetId: () => 's', getSheetName: () => 'Source', getSheet: () => ({ getCellRaw: () => ({ v: 2 }) }) }
  const workbook = { getId: () => 'u', getActiveSheet: () => sheet, getSheets: () => [sheet], getSheetBySheetId: () => sheet, getTableList: () => [] }
  const controller = installDataValidationStructure({ univer: { __getInjector: () => ({ get: () => service }) }, univerAPI: { getActiveWorkbook: () => workbook } })
  const range = { startRow: 1, endRow: 1, startColumn: 0, endColumn: 0 }, command = { id: 'sheet.command.insert-range-move-down', params: { range } }
  try {
    before(command)
    const nested = { id: 'sheet.command.set-range-values', params: { unitId: 'u', subUnitId: 's', range, cellValue: { 1: { 0: { s: { bg: { rgb: '#FFFF00' } } } } } } }
    service.onCommandExecute(nested)
    expect(nested.params.cellValue[1][0]).toBeNull()
    after(command)
  } finally { controller.dispose() }
  expect(released).toBe(3)
})

it('collects rename CF in the same ordered command history without trusting official followers', async () => {
  const { AddConditionalRuleMutation } = await import('@univerjs/sheets-conditional-formatting')
  const current = [
    { cfId: 'high', ranges: [{ startRow: 0, endRow: 3, startColumn: 1, endColumn: 1 }], stopIfTrue: true, rule: { type: 'highlightCell', subType: 'formula', value: '=TRUE', style: {} } },
    { cfId: 'parent', ranges: [{ startRow: 0, endRow: 3, startColumn: 1, endColumn: 1 }], stopIfTrue: false, rule: { type: 'highlightCell', subType: 'formula', value: '=Source!A1>0', style: {} } },
  ]
  const stale = { id: AddConditionalRuleMutation.id, params: { unitId: 'foreign', subUnitId: 'other', rule: { cfId: 'wrong' } } }
  const result = { redos: [stale] as any[], undos: [] as any[] }
  const service = { interceptCommand: () => ({ dispose() {} }), onCommandExecute: (_command: any) => result }
  const source = { getSheetId: () => 'source', getSheetName: () => 'Source', getConditionalFormattingRules: () => [] }
  const other = { getSheetId: () => 'other', getSheetName: () => 'Other', getConditionalFormattingRules: () => current }
  const workbook = { getDefinedNames: () => [], getId: () => 'u', getActiveSheet: () => source, getSheets: () => [source, other], getSheetBySheetId: () => source, getTableList: () => [] }
  const controller = installDataValidationStructure({ univer: { __getInjector: () => ({ get: () => service }) }, univerAPI: { getActiveWorkbook: () => workbook } })
  try {
    service.onCommandExecute({ id: 'sheet.command.set-worksheet-name', params: { unitId: 'u', subUnitId: 'source', name: "财务 O'Brien" } })
    expect(result.redos).not.toContain(stale)
    const additions = result.redos.filter(mutation => mutation.id === AddConditionalRuleMutation.id).map(mutation => mutation.params.rule).reverse()
    expect(additions.map(rule => rule.cfId)).toEqual(['high', 'parent'])
    expect(additions[1].rule.value).toBe("='财务 O''Brien'!A1>0")
    expect(result.undos.filter(mutation => mutation.id === AddConditionalRuleMutation.id).map(mutation => mutation.params.rule).reverse()).toEqual(current)
    for (const mutation of [...result.redos, ...result.undos]) expect(controller.ownsMutation(mutation.params)).toBe(true)
    expect(controller.ownsMutation(stale.params)).toBe(false)
  } finally { controller.dispose() }
})

it('rejects referenced sheet removal before original collectors and preserves unrelated deletion results', () => {
  let calls = 0, sourceChecks = 0, formula = '=Source!A1>0'
  const result = { redos: [{ id: 'untouched', params: {} }], undos: [] }
  const service = { interceptCommand: () => ({ dispose() {} }), onCommandExecute: (_command: any) => { calls++; return result } }
  const source = { getSheetId: () => 'source', getSheetName: () => 'Source' }
  const other = { getSheetId: () => 'other', getSheetName: () => 'Other', getConditionalFormattingRules: () => [{ rule: { type: 'highlightCell', subType: 'formula', value: formula } }] }
  const workbook = { getDefinedNames: () => [], getId: () => 'u', getActiveSheet: () => source, getSheets: () => [source, other], getSheetBySheetId: () => source, getTableList: () => [] }
  const controller = installDataValidationStructure({ univer: { __getInjector: () => ({ get: () => service }) }, univerAPI: { getActiveWorkbook: () => workbook } }, undefined, () => { sourceChecks++ })
  try {
    expect(() => service.onCommandExecute({ id: 'sheet.command.remove-sheet', params: { subUnitId: 'source' } })).toThrow('条件格式仍引用')
    expect(calls).toBe(0); expect(sourceChecks).toBe(1); expect(controller.ownsMutation(result.redos[0].params)).toBe(false)
    formula = '=TRUE'
    expect(service.onCommandExecute({ id: 'sheet.command.remove-sheet', params: { subUnitId: 'source' } })).toBe(result)
    expect(calls).toBe(1); expect(sourceChecks).toBe(2)
  } finally { controller.dispose() }
})

it('rejects current data-validation dependencies before invoking original removal collectors', () => {
  let calls = 0
  const service = { interceptCommand: () => ({ dispose() {} }), onCommandExecute: (_command: any) => { calls++; return { redos: [], undos: [] } } }
  const source = { getSheetId: () => 'source', getSheetName: () => 'Source' }
  const rule = { type: 'list', formula1: '=Source!A1:A5' }
  const other = { getSheetId: () => 'other', getSheetName: () => 'Other', getDataValidations: () => [{ rule }] }
  const workbook = { getDefinedNames: () => [], getId: () => 'u', getActiveSheet: () => source, getSheets: () => [source, other], getSheetBySheetId: () => source, getTableList: () => [] }
  const controller = installDataValidationStructure({ univer: { __getInjector: () => ({ get: () => service }) }, univerAPI: { getActiveWorkbook: () => workbook } })
  try {
    expect(() => service.onCommandExecute({ id: 'sheet.command.remove-sheet', params: { subUnitId: 'source' } })).toThrow('数据验证仍引用')
    expect(calls).toBe(0)
    rule.formula1 = 'Source!A1'
    service.onCommandExecute({ id: 'sheet.command.remove-sheet', params: { subUnitId: 'source' } });expect(calls).toBe(1)
  } finally { controller.dispose() }
})

it('rejects ordinary current cell formulas before any original removal collectors', () => {
  let calls = 0
  const service = { interceptCommand: () => ({ dispose() {} }), onCommandExecute: (_command: any) => { calls++; return { redos: [], undos: [] } } }
  const source = { getSheetId: () => 'source', getSheetName: () => 'Source' }
  const cell = { f: '=Source!A1' }
  const other = { getSheetId: () => 'other', getSheetName: () => 'Other', getSheet: () => ({ getCellMatrix: () => ({ forValue: (callback: any) => callback(9000, 2, cell) }) }), getRange: () => ({ getFormula: () => cell.f }) }
  const workbook = { getDefinedNames: () => [], getId: () => 'u', getActiveSheet: () => source, getSheets: () => [source, other], getSheetBySheetId: () => source, getTableList: () => [] }
  const controller = installDataValidationStructure({ univer: { __getInjector: () => ({ get: () => service }) }, univerAPI: { getActiveWorkbook: () => workbook } })
  try {
    expect(() => service.onCommandExecute({ id: 'sheet.command.remove-sheet', params: { subUnitId: 'source' } })).toThrow('单元格公式仍引用')
    expect(calls).toBe(0)
    cell.f = '=1';service.onCommandExecute({ id: 'sheet.command.remove-sheet', params: { subUnitId: 'source' } });expect(calls).toBe(1)
  } finally { controller.dispose() }
})

it('rejects current defined-name references before any original removal collector', () => {
  let calls = 0, formula = 'Source!A1'
  const service = { interceptCommand: () => ({ dispose() {} }), onCommandExecute: (_command: any) => { calls++; return { redos: [], undos: [] } } }
  const source = { getSheetId: () => 'source', getSheetName: () => 'Source' }
  const workbook = { getId: () => 'u', getActiveSheet: () => source, getSheets: () => [source], getSheetBySheetId: () => source, getTableList: () => [], getDefinedNames: () => [{ getName: () => 'Dependency', getFormulaOrRefString: () => formula }] }
  const controller = installDataValidationStructure({ univer: { __getInjector: () => ({ get: () => service }) }, univerAPI: { getActiveWorkbook: () => workbook } })
  try {
    expect(() => service.onCommandExecute({ id: 'sheet.command.remove-sheet', params: { subUnitId: 'source' } })).toThrow('定义名称')
    expect(calls).toBe(0)
    formula = '1';service.onCommandExecute({ id: 'sheet.command.remove-sheet', params: { subUnitId: 'source' } });expect(calls).toBe(1)
  } finally { controller.dispose() }
})

it('rejects actual chart dependencies in the trusted source callback before original collectors', async () => {
  const { assertChartSheetRemoval } = await import('./workbook-chart-sheet-removal')
  let calls = 0, formula = 'Source!A1'
  const service = { interceptCommand: () => ({ dispose() {} }), onCommandExecute: (_command: any) => { calls++;return { redos: [], undos: [] } } }
  const source = { getSheetId: () => 'source', getSheetName: () => 'Source' }, other = { getSheetId: () => 'other', getSheetName: () => 'Other' }
  const workbook = { getId: () => 'u', getDefinedNames: () => [], getSheets: () => [source, other], getActiveSheet: () => source, getSheetBySheetId: () => source, getTableList: () => [] }
  const controller = installDataValidationStructure({ univer: { __getInjector: () => ({ get: () => service }) }, univerAPI: { getActiveWorkbook: () => workbook } }, undefined,
    (command, book) => assertChartSheetRemoval(book, command.params?.subUnitId, () => [{ path: 'xl/charts/chart1.xml', xml: `<chartSpace xmlns="http://schemas.openxmlformats.org/drawingml/2006/chart"><f>${formula}</f></chartSpace>` }]))
  try {
    expect(() => service.onCommandExecute({ id: 'sheet.command.remove-sheet', params: { subUnitId: 'source' } })).toThrow('图表')
    expect(calls).toBe(0)
    formula = 'Other!A1';service.onCommandExecute({ id: 'sheet.command.remove-sheet', params: { subUnitId: 'source' } });expect(calls).toBe(1)
  } finally { controller.dispose() }
})
