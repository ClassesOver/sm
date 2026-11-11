import { afterEach, expect, it } from 'vitest'
import { mkdtemp, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { resolve, join } from 'node:path'
import { spawnSync } from 'node:child_process'
import { applyCellEdits, createBlankWorkbook, readWorkbook } from '@sheets-web/xlsx-engine'
import { applyWorkbookOperations } from '../../../reporting/workbook_engine/bridge/operations'
import { workbookFilterOperations, type FilterCriteriaData, type FilterSheet, type FilterWorkbook } from './workbook-filters'
import { independentPython } from './test-independent-python'
import { NativeDraft, type NativeOperation } from './native-draft'

/** Mimics the documented facade: getFilter/getCriteria from the pinned FFilter. */
function facade(
  live: { range: [number, number, number, number]; columns: Record<number, { values?: string[]; blank?: boolean; customs?: { and?: boolean | number; customFilters: { val: string; operator?: string }[] } }> } | null,
  options: { filteredOut?: number[]; snapshot?: { sheets: Record<string, { rowData?: Record<number, { hd?: number }> }> } } = {},
): FilterWorkbook {
  const sheet: FilterSheet = {
    getSheetId: () => 'sheet-0', getSheetName: () => 'Sheet1',
    getFilter: () => {
      if (!live) return null
      const [startRow, startColumn, height, width] = live.range
      return {
        getRange: () => ({ getRow: () => startRow, getColumn: () => startColumn, getHeight: () => height, getWidth: () => width }),
        getColumnFilterCriteria: (column: number): FilterCriteriaData | null => {
          const criteria = live.columns[column - startColumn]
          if (!criteria) return null
          return {
            ...(criteria.values ? { filters: { ...(criteria.blank ? { blank: true } : {}), filters: criteria.values } } : criteria.blank ? { filters: { blank: true } } : {}),
            ...(criteria.customs ? { customFilters: criteria.customs } : {}),
          }
        },
        ...(options.filteredOut ? { getFilteredOutRows: () => options.filteredOut! } : {}),
      }
    },
  }
  return {
    getId: () => 'book', getWorkbook: () => ({}), getSheets: () => [sheet],
    ...(options.snapshot ? { getSnapshot: () => options.snapshot } : {}),
  }
}

const modelWithFilter = async (
  columns: Record<number, { values?: string[]; blank?: boolean; customs?: { and?: boolean; customFilters: { val: string; operator?: string }[] } }>,
  hiddenRows?: number[],
) => {
  let bytes = await applyCellEdits(await createBlankWorkbook(), [
    { sheetName: 'Sheet1', row: 0, column: 0, writeValue: true, cell: { value: '部门' } },
    { sheetName: 'Sheet1', row: 1, column: 0, writeValue: true, cell: { value: '乙' } },
    { sheetName: 'Sheet1', row: 2, column: 0, writeValue: true, cell: { value: '甲' } },
  ])
  const columnsPayload = Object.entries(columns).map(([offset, criteria]) => ({ colId: Number(offset), ...criteria }))
  if (columnsPayload.length) bytes = await applyWorkbookOperations(bytes, [{ kind: 'applySheetFilter', sheetName: 'Sheet1', filter: { range: { startRow: 0, endRow: 2, startColumn: 0, endColumn: 0 }, columns: columnsPayload }, ...(hiddenRows ? { hiddenRows } : {}) }])
  return readWorkbook(bytes)
}

afterEach(() => document.body.replaceChildren())

it.each([undefined, false, 0])('keeps OR and single custom filters JSON-safe for NativeDraft (and=%s)', async and => {
  const model = await modelWithFilter({})
  const operations = workbookFilterOperations(model, facade({ range: [0, 0, 3, 1], columns: {
    0: { customs: { and, customFilters: [{ val: '甲' }, { val: '乙', operator: 'notEqual' }] } },
  } }))
  const storage = { getItem: () => null, setItem() {}, removeItem() {} }
  const draft = new NativeDraft({ documentId: 'filter', revision: 1, sourceSha256: 'a'.repeat(64),
    scope: { database: 'test', companyId: 'c', userId: 'u', threadId: 't' } }, storage)
  draft.setOperations(operations as NativeOperation[])
  expect(draft.operations).toEqual(operations)
  const customs = (draft.operations[0] as any).filter.columns[0].customs
  expect(Object.hasOwn(customs, 'and')).toBe(false)
})

it('emits nothing when the live filter matches the source snapshot', async () => {
  const model = await modelWithFilter({ 0: { values: ['甲'] } })
  expect(workbookFilterOperations(model, facade({ range: [0, 0, 3, 1], columns: { 0: { values: ['甲'] } } }))).toEqual([])
})

it('diffs criteria changes and removal as declarative snapshots', async () => {
  const model = await modelWithFilter({ 0: { values: ['甲'] } })
  expect(workbookFilterOperations(model, facade({ range: [0, 0, 3, 1], columns: { 0: { customs: { customFilters: [{ val: '5', operator: 'greaterThan' }] } } } }))).toEqual([
    { kind: 'applySheetFilter', sheetName: 'Sheet1', filter: { range: { startRow: 0, endRow: 2, startColumn: 0, endColumn: 0 }, columns: [{ colId: 0, customs: { filters: [{ val: '5', operator: 'greaterThan' }] } }] } },
  ])
  expect(workbookFilterOperations(model, facade(null))).toEqual([
    { kind: 'applySheetFilter', sheetName: 'Sheet1', filter: null },
  ])
  const plain = await modelWithFilter({})
  expect(workbookFilterOperations(plain, facade({ range: [0, 0, 3, 1], columns: { 0: { blank: true } } }))).toEqual([
    { kind: 'applySheetFilter', sheetName: 'Sheet1', filter: { range: { startRow: 0, endRow: 2, startColumn: 0, endColumn: 0 }, columns: [{ colId: 0, blank: true }] } },
  ])
})

it('surfaces the engine refusal for unsupported source conditions', async () => {
  const model = await modelWithFilter({ 0: { values: ['甲'] } })
  model.sheets[0]!.filter!.readOnlyReason = '筛选含颜色、图标、前十或动态条件，暂不能编辑回写'
  expect(() => workbookFilterOperations(model, facade({ range: [0, 0, 3, 1], columns: { 0: { values: ['甲'] } } }))).toThrow('暂不能编辑回写')
})

it('v2: declares grid row visibility (filter cache + manual hides) with the filter snapshot', async () => {
  // 源筛选无隐藏行；网格 getFilteredOutRows 报告行 2 → 声明可见性落盘。
  const model = await modelWithFilter({ 0: { values: ['甲'] } })
  expect(workbookFilterOperations(model, facade(
    { range: [0, 0, 3, 1], columns: { 0: { values: ['甲'] } } },
    { filteredOut: [2] },
  ))).toEqual([
    { kind: 'applySheetFilter', sheetName: 'Sheet1', filter: { range: { startRow: 0, endRow: 2, startColumn: 0, endColumn: 0 }, columns: [{ colId: 0, values: ['甲'] }] }, hiddenRows: [2] },
  ])
  // 条件不变且可见性一致（源缓存隐藏行 2 ＝ 网格筛选隐藏行 2）→ 不产生操作。
  const cachedModel = await modelWithFilter({ 0: { values: ['甲'] } }, [2])
  expect(workbookFilterOperations(cachedModel, facade(
    { range: [0, 0, 3, 1], columns: { 0: { values: ['甲'] } } },
    { filteredOut: [2] },
  ))).toEqual([])
  // 手动隐藏行 1（快照 rowData）＋网格筛选隐藏行 2 → 声明并集，保留手动隐藏。
  expect(workbookFilterOperations(cachedModel, facade(
    { range: [0, 0, 3, 1], columns: { 0: { values: ['甲'] } } },
    { filteredOut: [2], snapshot: { sheets: { 'sheet-0': { rowData: { 1: { hd: 1 } } } } } },
  ))).toEqual([
    { kind: 'applySheetFilter', sheetName: 'Sheet1', filter: { range: { startRow: 0, endRow: 2, startColumn: 0, endColumn: 0 }, columns: [{ colId: 0, values: ['甲'] }] }, hiddenRows: [1, 2] },
  ])
  // 条件变化时一并声明当前可见性；标题行不进入声明。
  expect(workbookFilterOperations(cachedModel, facade(
    { range: [0, 0, 3, 1], columns: { 0: { values: ['乙'] } } },
    { filteredOut: [1, 2], snapshot: { sheets: { 'sheet-0': { rowData: {} } } } },
  ))).toEqual([
    { kind: 'applySheetFilter', sheetName: 'Sheet1', filter: { range: { startRow: 0, endRow: 2, startColumn: 0, endColumn: 0 }, columns: [{ colId: 0, values: ['乙'] }] }, hiddenRows: [1, 2] },
  ])
})

it('v2: removing the filter re-shows its cached hidden rows and keeps manual hides', async () => {
  // 源文件缓存隐藏行 1；网格已无筛选（行 1 重新可见）→ 声明可见性取消隐藏。
  const bytes = await applyWorkbookOperations(await applyCellEdits(await createBlankWorkbook(), [
    { sheetName: 'Sheet1', row: 0, column: 0, writeValue: true, cell: { value: '部门' } },
    { sheetName: 'Sheet1', row: 1, column: 0, writeValue: true, cell: { value: '乙' } },
  ]), [
    { kind: 'applySheetFilter', sheetName: 'Sheet1', filter: { range: { startRow: 0, endRow: 1, startColumn: 0, endColumn: 0 }, columns: [{ colId: 0, values: ['乙'] }] }, hiddenRows: [1] },
  ])
  const model = await readWorkbook(bytes)
  expect(model.sheets[0]!.rows.some(row => row.row === 2 && row.hidden)).toBe(true)
  // 网格移除筛选后行 1 重新可见（快照无隐藏行）→ 声明可见性取消其隐藏。
  expect(workbookFilterOperations(model, facade(null, { snapshot: { sheets: { 'sheet-0': { rowData: {} } } } }))).toEqual([
    { kind: 'applySheetFilter', sheetName: 'Sheet1', filter: null, hiddenRows: [], visibilityRange: { startRow: 0, endRow: 1, startColumn: 0, endColumn: 0 } },
  ])
  // 可见性未变化（源缓存隐藏行 1 仍在快照中）→ 维持 v1 的纯 filter: null。
  expect(workbookFilterOperations(model, facade(null, { snapshot: { sheets: { 'sheet-0': { rowData: { 1: { hd: 1 } } } } } }))).toEqual([
    { kind: 'applySheetFilter', sheetName: 'Sheet1', filter: null },
  ])
  // 无快照读取能力 → 退回 v1（不写可见性）。
  expect(workbookFilterOperations(model, facade(null))).toEqual([
    { kind: 'applySheetFilter', sheetName: 'Sheet1', filter: null },
  ])
})

it('v2: persists filter-hidden rows and survives an openpyxl row-visibility readback', async () => {
  const bytes = await applyWorkbookOperations(await applyCellEdits(await createBlankWorkbook(), [
    { sheetName: 'Sheet1', row: 0, column: 0, writeValue: true, cell: { value: '部门' } },
    { sheetName: 'Sheet1', row: 1, column: 0, writeValue: true, cell: { value: '乙' } },
    { sheetName: 'Sheet1', row: 2, column: 0, writeValue: true, cell: { value: '甲' } },
  ]), [
    { kind: 'applySheetFilter', sheetName: 'Sheet1', filter: { range: { startRow: 0, endRow: 2, startColumn: 0, endColumn: 0 }, columns: [{ colId: 0, values: ['乙'] }] }, hiddenRows: [1, 2] },
  ])
  const dir = await mkdtemp(join(tmpdir(), 'xlsx-filterrows-'))
  const file = resolve(dir, 'filter-rows.xlsx')
  await writeFile(file, bytes)
  const checked = spawnSync(independentPython(), ['-I', '-c',
    "import json,openpyxl,sys; w=openpyxl.load_workbook(sys.argv[1]); s=w.active; print(json.dumps({'filter': str(s.auto_filter.ref), 'hidden': [r for r,d in s.row_dimensions.items() if d.hidden]}))", file], { encoding: 'utf8' })
  expect(checked.status, checked.stderr).toBe(0)
  expect(JSON.parse(checked.stdout)).toEqual({ filter: 'A1:A3', hidden: [2, 3] })
  console.info(`Independent openpyxl verified filter row visibility XLSX: ${file}`)
})

it('dateGroups round-trips the bridge but front-end diffs refuse to overwrite it', async () => {
  // server 路径：dateGroups 经桥 schema 严格校验后写回并读回。
  const bytes = await applyWorkbookOperations(await applyCellEdits(await createBlankWorkbook(), [
    { sheetName: 'Sheet1', row: 0, column: 0, writeValue: true, cell: { value: '日期' } },
  ]), [
    {
      kind: 'applySheetFilter', sheetName: 'Sheet1',
      filter: {
        range: { startRow: 0, endRow: 2, startColumn: 0, endColumn: 0 },
        columns: [{ colId: 0, dateGroups: [{ year: 2024, month: 1, dateTimeGrouping: 'month' }] }],
      },
    },
  ])
  const model = await readWorkbook(bytes)
  expect(model.sheets[0]!.filter!.readOnlyReason).toBeUndefined()
  expect(model.sheets[0]!.filter!.columns).toEqual([
    { colId: 0, dateGroups: [{ year: 2024, month: 1, dateTimeGrouping: 'month' }] },
  ])
  // 前端边界：pinned Univer 的 IFilterColumn 没有 dateGroups，网格差分无法
  // 保留该条件——含日期分组的源筛选如实拒绝回写，而不是落盘时静默丢弃。
  expect(() => workbookFilterOperations(model, facade({ range: [0, 0, 3, 1], columns: {} })))
    .toThrow(/仅服务端路径可写 dateGroups/)
  // 该筛选不灌入网格：网格无筛选＝用户未触碰，保留文件筛选且不阻断无关修改的保存。
  expect(workbookFilterOperations(model, facade(null))).toEqual([])
  // 桥层同样拒绝非法组合：日期分组与自定义条件同列、粒度链不完整。
  const range = { startRow: 0, endRow: 2, startColumn: 0, endColumn: 0 }
  await expect(applyWorkbookOperations(bytes, [{
    kind: 'applySheetFilter', sheetName: 'Sheet1',
    filter: { range, columns: [{ colId: 0, dateGroups: [{ year: 2024, dateTimeGrouping: 'day' }] }] },
  }])).rejects.toThrow()
  await expect(applyWorkbookOperations(bytes, [{
    kind: 'applySheetFilter', sheetName: 'Sheet1',
    filter: { range, columns: [{ colId: 0, dateGroups: [{ year: 2024, month: 1, dateTimeGrouping: 'month' }], customs: { filters: [{ val: '5' }] } }] },
  }])).rejects.toThrow()
})
