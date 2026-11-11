import { afterEach, expect, it } from 'vitest'
import { ICommandService, IUniverInstanceService, IUndoRedoService, LocaleType, Univer, UniverInstanceType } from '@univerjs/core'
import { FUniver } from '@univerjs/core/lib/facade'
import { UniverSheetsPlugin } from '@univerjs/sheets'
import '@univerjs/sheets/facade'
import { installWorkbookSparklines } from './workbook-sparklines'
const instances: Univer[] = []
afterEach(() => instances.splice(0).forEach(item => item.dispose()))
function setup(existing: any[] = [], sourceSheetId?: (name: string) => string | undefined) {
  const univer = new Univer({ locale: LocaleType.EN_US, locales: { [LocaleType.EN_US]: {} } })
  instances.push(univer); univer.registerPlugin(UniverSheetsPlugin)
  univer.createUnit(UniverInstanceType.UNIVER_SHEET, { id: 'book', name: 'book', appVersion: '0.25.1', locale: LocaleType.EN_US,
    sheetOrder: ['data', 'other'], sheets: Object.fromEntries(['data', 'other'].map(id => [id, { id, name: id === 'data' ? 'Data' : 'Other', rowCount: 1000, columnCount: 16384, cellData: {} }])) })
  const api = FUniver.newAPI(univer), injector = univer.__getInjector()
  injector.get(IUniverInstanceService).focusUnit('book')
  const book = api.getActiveWorkbook()!, sheet = book.getActiveSheet()!
  book.setActiveRange(sheet.getRange('B2:D3'))
  let readonly = false, protectedSheet = false
  const displays = new Map<string, any[]>(), controller = installWorkbookSparklines({ univer, univerAPI: api }, {
    readonly: () => readonly, protectedSheet: () => protectedSheet, sourceSheetId,
    existing: id => id === 'data' ? existing : [], refresh: (id, specs) => displays.set(id, [...specs]),
  })
  return { api, book, sheet, controller, displays, injector, setReadonly: () => { readonly = true }, setProtected: () => { protectedSheet = true } }
}
it.each(['line', 'column', 'stacked'] as const)('adds %s per row with absolute refs and official undo/redo', async type => {
  const c = setup(); c.controller.add(type, '#aabbcc')
  expect(c.controller.operations()).toEqual([{ kind: 'appendSheetSparklines', sheetName: 'Data', groups: [{ type, color: '#aabbcc', cells: [
    { cell: 'E2', sourceRef: "Data!$B$2:$D$2" }, { cell: 'E3', sourceRef: "Data!$B$3:$D$3" },
  ] }] }])
  expect(c.displays.get('data')).toEqual([2, 3].map(row => ({ kind: type === 'stacked' ? 'winLoss' : type, color: '#aabbcc', target: `E${row}`, source: `B${row}:D${row}` })))
  await c.api.undo(); expect(c.controller.operations()).toEqual([])
  await c.api.redo(); expect(c.controller.operations()[0]?.groups?.[0]?.type).toBe(type); c.controller.dispose()
})
it('binds rename, rename undo, deletion and deletion undo to stable sheet id', async () => {
  const c = setup(); c.controller.add('line'); await c.sheet.setName("业绩 O'Brien")
  expect(c.controller.operations()[0]?.groups?.[0]?.cells[0]?.sourceRef).toBe("'业绩 O''Brien'!$B$2:$D$2")
  await c.api.undo(); expect(c.controller.operations()[0]?.sheetName).toBe('Data')
  await c.book.deleteSheet(c.sheet); expect(c.controller.operations()).toEqual([])
  await c.api.undo(); expect(c.controller.operations()).toHaveLength(1); c.controller.dispose()
})
it.each(['B2:B3', 'B1:D201', 'XFC2:XFD3'])('rejects selection %s before history writes', range => {
  const c = setup(); c.book.setActiveRange(c.sheet.getRange(range))
  expect(() => c.controller.add('line')).toThrow(); expect(c.controller.operations()).toEqual([])
  expect(c.injector.get(IUndoRedoService).pitchTopUndoElement()).toBeNull(); c.controller.dispose()
})
it('rejects existing and session occupied hosts preserving raw objects', () => {
  const raw = [{ kind: 'line', source: 'A2:C2', target: '$E$2', color: '#123456', markers: true }], before = structuredClone(raw)
  const c = setup(raw); expect(() => c.controller.add('line')).toThrow('迷你图'); expect(raw).toEqual(before); c.controller.dispose()
  const d = setup(); d.controller.add('line'); expect(() => d.controller.add('column')).toThrow('迷你图')
  expect(d.controller.operations()[0]?.groups).toHaveLength(1); d.controller.dispose()
})
it('removes an existing host through journal and official undo/redo', async () => {
  const c = setup([{ kind: 'line', source: '$A$2:$C$2', target: 'E2' }])
  c.book.setActiveRange(c.sheet.getRange('E2'))
  c.controller.remove()
  expect(c.controller.operations()).toEqual([{ kind: 'removeSheetSparklines', sheetName: 'Data', targets: ['E2'] }])
  expect(c.displays.get('data')).toEqual([])
  await c.api.undo(); expect(c.controller.operations()).toEqual([])
  await c.api.redo(); expect(c.controller.operations()).toEqual([{ kind: 'removeSheetSparklines', sheetName: 'Data', targets: ['E2'] }])
  c.controller.dispose()
})
it('edits an existing host group through journal and official undo/redo', async () => {
  const c = setup([{ kind: 'line', source: '$A$2:$C$2', target: 'E2', color: '#112233' }])
  c.book.setActiveRange(c.sheet.getRange('E2'))
  c.controller.edit({ type: 'stacked', color: '#aabbcc' })
  expect(c.controller.operations()).toEqual([{ kind: 'editSheetSparklineGroup', sheetName: 'Data', target: 'E2', type: 'stacked', color: '#aabbcc' }])
  expect(c.displays.get('data')?.[0]).toMatchObject({ kind: 'winLoss', color: '#aabbcc' })
  await c.api.undo(); expect(c.controller.operations()).toEqual([])
  await c.api.redo(); expect(c.controller.operations()[0]?.kind).toBe('editSheetSparklineGroup')
  c.controller.dispose()
})
it('rejects readonly, protected, stale selection/session and disposed commits', () => {
  for (const reject of ['readonly', 'protected', 'selection', 'session', 'disposed']) {
    const c = setup(), plan = c.controller.prepare('line')
    if (reject === 'readonly') c.setReadonly()
    if (reject === 'protected') c.setProtected()
    if (reject === 'selection') c.book.setActiveRange(c.sheet.getRange('A1:C1'))
    if (reject === 'session') { c.book.setActiveRange(c.sheet.getRange('A10:C10')); c.controller.add('column'); c.book.setActiveRange(c.sheet.getRange('B2:D3')) }
    if (reject === 'disposed') c.controller.dispose()
    expect(() => plan.commit()).toThrow(); if (reject !== 'disposed') c.controller.dispose()
  }
})
it('resets journal after materialized draft restore without duplicating existing objects', () => {
  const c = setup(); c.controller.add('stacked'); c.controller.reset()
  expect(c.controller.operations()).toEqual([]); expect(c.controller.display('data')).toEqual([]); c.controller.dispose()
})
it('guards structural edits only on spark sheets and releases after undo', async () => {
  const c = setup(), command = { id: 'sheet.command.insert-row', params: { subUnitId: 'data' } }
  expect(() => c.controller.assertStructure(command)).not.toThrow(); c.controller.add('line')
  for (const id of ['sheet.command.insert-row', 'sheet.command.remove-col', 'sheet.command.insert-range-move-right', 'sheet.mutation.move-range']) {
    expect(() => c.controller.assertStructure({ id, params: { subUnitId: 'data' } })).toThrow('迷你图')
    expect(() => c.controller.assertStructure({ id, params: { subUnitId: 'other' } })).not.toThrow()
  }
  expect(() => c.controller.assertStructure({ id: 'sheet.command.set-range-values' })).not.toThrow()
  await c.api.undo(); expect(() => c.controller.assertStructure(command)).not.toThrow(); c.controller.dispose()
})
it('rejects foreign mutation params', () => {
  const c = setup(); expect(c.injector.get(ICommandService).syncExecuteCommand('sheet.mutation.native-sparkline-add', { unitId: 'book', sheetId: 'data', entries: [] })).toBe(false)
  expect(c.controller.operations()).toEqual([]); c.controller.dispose()
})
it('rejects moving spark cells across sheets using official from/to identities', () => {
  const c = setup(); c.controller.add('line')
  expect(() => c.controller.assertStructure({ id: 'sheet.command.move-range', params: { fromSubUnitId: 'other', toSubUnitId: 'data' } })).toThrow('迷你图')
  expect(() => c.controller.assertStructure({ id: 'sheet.command.move-range', params: { fromSubUnitId: 'other', toSubUnitId: 'other' } })).not.toThrow()
  c.controller.dispose()
})
it('rejects a prepared plan after official cell mutation or materialized reload reset', () => {
  const c = setup(), plan = c.controller.prepare('line')
  c.sheet.getRange('B2').setValue(42)
  expect(() => plan.commit()).toThrow('变化')
  const resetPlan = c.controller.prepare('line'); c.controller.reset()
  expect(() => resetPlan.commit()).toThrow('变化')
  expect(c.controller.operations()).toEqual([]); c.controller.dispose()
})
it('serializes consecutive additions into <=200-host batches without reordering', () => {
  const c = setup()
  c.book.setActiveRange(c.sheet.getRange('B1:D150')); c.controller.add('line')
  c.book.setActiveRange(c.sheet.getRange('B151:D300')); c.controller.add('column')
  const ops = c.controller.operations()
  expect(ops).toHaveLength(2)
  expect(ops.map(op => op.groups!.reduce((sum, group) => sum + group.cells.length, 0))).toEqual([150, 150])
  expect(ops.flatMap(op => op.groups!.flatMap(group => group.cells.map(cell => cell.cell)))).toEqual(Array.from({ length: 300 }, (_, row) => `E${row + 1}`))
  c.controller.dispose()
})
it.each(['A1', 'TRUE', 'R1C1'])('quotes ambiguous final sheet name %s using shared engine rules', async name => {
  const c = setup(); c.controller.add('line'); await c.sheet.setName(name)
  expect(c.controller.operations()[0]?.groups?.[0]?.cells[0]?.sourceRef).toBe(`'${name}'!$B$2:$D$2`)
  c.controller.dispose()
})
it('guards a cross-sheet spark source before row, column and cell shifts while allowing ordinary values', () => {
  const c = setup([{ kind: 'line', target: 'E2', source: '$A$1:$C$1', sourceSheet: 'Other' }])
  for (const id of ['sheet.command.insert-row', 'sheet.mutation.remove-col', 'sheet.command.insert-range-move-right', 'sheet.command.delete-range-move-up', 'sheet.command.move-range']) {
    expect(() => c.controller.assertStructure({ id, params: { subUnitId: 'other' } })).toThrow('迷你图')
  }
  expect(() => c.controller.assertStructure({ id: 'sheet.command.set-range-values', params: { subUnitId: 'other' } })).not.toThrow()
  c.controller.dispose()
})
it('binds cross-sheet sources before the first rename and preserves identity through rename undo', async () => {
  const raw = [{ kind: 'line', target: 'E2', source: '$A$1:$C$1', sourceSheet: 'Other' }], before = structuredClone(raw), c = setup(raw)
  const source = c.book.getSheetBySheetId('other')!
  await source.setName('改名后的来源')
  const command = { id: 'sheet.command.insert-range-move-down', params: { subUnitId: 'other' } }
  expect(() => c.controller.assertStructure(command)).toThrow('迷你图')
  await c.api.undo(); expect(() => c.controller.assertStructure(command)).toThrow('迷你图')
  expect(raw).toEqual(before); c.controller.dispose()
})
it('does not block unrelated sheets and refreshes source bindings on materialized restore', async () => {
  const raw = [{ kind: 'line', target: 'E2', source: '$A$1:$C$1', sourceSheet: 'Other' }], c = setup(raw)
  const third = c.book.insertSheet('Unrelated')
  expect(() => c.controller.assertStructure({ id: 'sheet.command.insert-row', params: { subUnitId: third.getSheetId() } })).not.toThrow()
  await c.book.getSheetBySheetId('other')!.setName('Restored source')
  raw[0]!.sourceSheet = 'Restored source'; c.controller.reset()
  expect(() => c.controller.assertStructure({ id: 'sheet.command.insert-row', params: { subUnitId: 'other' } })).toThrow('迷你图')
  raw.splice(0); c.controller.reset()
  expect(() => c.controller.assertStructure({ id: 'sheet.command.insert-row', params: { subUnitId: 'other' } })).not.toThrow()
  c.controller.dispose()
})
it('uses the baseline source identity resolver when the live sheet name has already changed', () => {
  const c = setup([{ kind: 'line', target: 'E2', source: '$A$1:$C$1', sourceSheet: 'Original source' }], name => name === 'Original source' ? 'other' : undefined)
  expect(() => c.controller.assertStructure({ id: 'sheet.command.insert-range-move-right', params: { subUnitId: 'other' } })).toThrow('迷你图')
  c.controller.dispose()
})
