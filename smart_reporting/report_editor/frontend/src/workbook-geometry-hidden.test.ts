import { spawnSync } from 'node:child_process'
import { independentPython } from './test-independent-python'
import { afterEach, expect, it } from 'vitest'
import { Univer, UniverInstanceType, LocaleType, IUniverInstanceService } from '@univerjs/core'
import { FUniver } from '@univerjs/core/lib/facade'
import { UniverSheetsPlugin } from '@univerjs/sheets'
import '@univerjs/sheets/facade'
import { createBlankWorkbook, readWorkbook } from '@sheets-web/xlsx-engine'
import { assemblePackage, createBufferEntrySource } from '@sheets-web/xlsx-engine/zip'
import { setColumnWidthsXml } from '@sheets-web/xlsx-engine/geometry'
import { applyStructuralOp, type StructuralOp } from '@sheets-web/xlsx-engine/structural'
import { applyWorkbookOperations } from '../../../reporting/workbook_engine/bridge/operations'
import { buildWorkbookData } from './workbook-vendor/core/univer-data'
import { readBackSnapshot } from './workbook-vendor/grid/sync'
import { geometryChanges } from './workbook-vendor/core/data-tools'
import { workbookOutlineOperations } from './workbook-outline'

const path = 'xl/worksheets/sheet1.xml'
const univers: Univer[] = []
afterEach(() => univers.splice(0).forEach(univer => univer.dispose()))
async function fixture() {
  const bytes = await createBlankWorkbook(), source = await createBufferEntrySource(bytes)
  const xml = (await source.readText(path)).replace('<sheetData/>', '<cols><col min="3" max="3" hidden="1" width="13" customWidth="1"/></cols><sheetData/>')
  return (await assemblePackage(bytes, { replaced: new Map([[path, xml]]), added: new Map(), addedBinary: new Map(), removedEntries: [], addedEntries: [], touchedEntries: [path] })).buffer
}
const xmlOf = async (bytes: Uint8Array) => (await createBufferEntrySource(bytes)).readText(path)

it('preserves column attributes through a width-only ZIP write, and explicit unhide still wins', async () => {
  const source = await fixture()
  const resized = await applyWorkbookOperations(source, [{ kind: 'applyColumnWidths', sheetName: 'Sheet1', entries: [{ index: 2, widthChars: 20 }] }])
  expect((await readWorkbook(resized)).sheets[0]!.columns[0]).toMatchObject({ start: 3, width: 20, hidden: true })
  const unhidden = await applyWorkbookOperations(resized, [
    { kind: 'applySheetOutline', sheetName: 'Sheet1', columns: [{ index: 2, level: 0, collapsed: false, hidden: false }] },
    { kind: 'applyColumnWidths', sheetName: 'Sheet1', entries: [{ index: 2, widthChars: 22 }] },
  ])
  expect((await readWorkbook(unhidden)).sheets[0]!.columns[0]).toMatchObject({ start: 3, width: 22, hidden: false })
  const span = '<worksheet><cols><col min="1" max="5" width="9" bestFit="1" hidden="1" style="2" outlineLevel="2" collapsed="1"/></cols><sheetData></sheetData></worksheet>'
  const xml = setColumnWidthsXml(span, [{ index: 1, widthChars: 20 }, { index: 3, widthChars: 24 }])
  for (const column of [2, 4]) {
    const tag = xml.match(new RegExp(`<col min="${column}"[^>]*/>`))![0]
    expect(tag).toContain('hidden="1"'); expect(tag).toContain('style="2"'); expect(tag).toContain('outlineLevel="2"'); expect(tag).toContain('collapsed="1"'); expect(tag).not.toContain('bestFit=')
  }
  expect(xml).toContain('<col min="3" max="3" width="9" bestFit="1" hidden="1" style="2" outlineLevel="2" collapsed="1"/>')
})

it('keeps structural epoch geometry aligned with real Univer and preserves hidden identity in saved ZIP', async () => {
  const source = await fixture(), model = await readWorkbook(source)
  const univer = new Univer({ locale: LocaleType.ZH_CN, locales: { [LocaleType.ZH_CN]: {} } }); univers.push(univer); univer.registerPlugin(UniverSheetsPlugin)
  univer.createUnit(UniverInstanceType.UNIVER_SHEET, buildWorkbookData(model, 'hidden', 'hidden'))
  const api = FUniver.newAPI(univer), workbook = api.getActiveWorkbook()!, sheet = workbook.getActiveSheet()
  univer.__getInjector().get(IUniverInstanceService).focusUnit(workbook.getId())
  sheet.insertColumnsBefore(1, 1)
  const structure = { kind: 'applyRowColumnOps' as const, sheetName: 'Sheet1', ops: [{ kind: 'insert-cols' as const, index: 1, count: 1 }] }
  const shifted = await applyWorkbookOperations(source, [structure]), baseline = await readWorkbook(shifted)
  expect(baseline.sheets[0]!.columns[0]).toMatchObject({ start: 4, end: 4, hidden: true, width: 13 })
  expect(geometryChanges(baseline, readBackSnapshot(workbook.getSnapshot())).columns).toEqual([])
  expect(await api.undo()).toBe(true)
  expect(geometryChanges(model, readBackSnapshot(workbook.getSnapshot())).columns).toEqual([])
  expect(sheet.getSheet().getColVisible(2)).toBe(false)
  expect(await api.redo()).toBe(true)
  expect(geometryChanges(baseline, readBackSnapshot(workbook.getSnapshot())).columns).toEqual([])
  expect(sheet.getSheet().getColVisible(3)).toBe(false)
  // 官方 Univer 忽略隐藏列的 resize；独立宽度 writer 仍须保留隐藏状态。
  const resized = await applyWorkbookOperations(shifted, [{ kind: 'applyColumnWidths', sheetName: 'Sheet1', entries: [{ index: 3, widthChars: 20 }] }])
  expect((await readWorkbook(resized)).sheets[0]!.columns[0]).toMatchObject({ start: 4, width: 20, hidden: true })
  sheet.showColumns(3, 1)
  sheet.setColumnWidths(3, 1, 145)
  const geometry = geometryChanges(baseline, readBackSnapshot(workbook.getSnapshot()))
  expect(geometry.columns).toEqual([{ sheet: 'Sheet1', index: 3, widthChars: 20 }])
  const unhidden = await applyWorkbookOperations(shifted, [
    ...workbookOutlineOperations(baseline, workbook),
    ...geometry.columns.map(change => ({ kind: 'applyColumnWidths' as const, sheetName: change.sheet, entries: [{ index: change.index, widthChars: change.widthChars }] })),
  ])
  expect((await readWorkbook(unhidden)).sheets[0]!.columns[0]).toMatchObject({ start: 4, width: 20, hidden: false })
  const deleted = await applyWorkbookOperations(resized, [{ kind: 'applyRowColumnOps', sheetName: 'Sheet1', ops: [{ kind: 'remove-cols', index: 1, count: 1 }] }])
  expect((await readWorkbook(deleted)).sheets[0]!.columns[0]).toMatchObject({ start: 3, width: 20, hidden: true })
  expect(await xmlOf(deleted)).toContain('hidden="1"')
  const checked = spawnSync(independentPython(), ['-I', '-c', `import base64,json,sys
from io import BytesIO
from openpyxl import load_workbook
p=json.load(sys.stdin)
print(json.dumps({k: [(c.min,c.max,c.width,c.hidden) for c in load_workbook(BytesIO(base64.b64decode(v))).active.column_dimensions.values()] for k,v in p.items()}))`], {
    input: JSON.stringify({ shifted: Buffer.from(shifted).toString('base64'), resized: Buffer.from(resized).toString('base64'), unhidden: Buffer.from(unhidden).toString('base64'), deleted: Buffer.from(deleted).toString('base64') }), encoding: 'utf8',
  })
  expect(checked.status, checked.stderr).toBe(0)
  expect(JSON.parse(checked.stdout)).toEqual({ shifted: [[4, 4, 13, true]], resized: [[4, 4, 20, true]], unhidden: [[4, 4, 20, false]], deleted: [[3, 3, 20, true]] })

})

it('moves column definition ranges like fixed source, retains attributes, and rejects overlapping definitions', () => {
  const source = '<worksheet><cols><col max="5" min="3" hidden="1" width="11" style="2"/><col min="8" max="9" width="22"/></cols><sheetData></sheetData></worksheet>'
  const apply = (op: StructuralOp) => applyStructuralOp(source, op, 'Sheet1')
  expect(apply({ kind: 'insert-cols', index: 3, count: 2 })).toContain('<col max="7" min="3" hidden="1" width="11" style="2"/>')
  expect(apply({ kind: 'insert-cols', index: 2, count: 2 })).toContain('<col max="7" min="5" hidden="1" width="11" style="2"/>')
  const cut = apply({ kind: 'remove-cols', index: 3, count: 3 })
  expect(cut).toContain('<col max="3" min="3" hidden="1" width="11" style="2"/>'); expect(cut).toContain('<col min="5" max="6" width="22"/>')
  const removed = apply({ kind: 'remove-cols', index: 1, count: 8 })
  expect(removed).not.toContain('<col ')
  expect(apply({ kind: 'insert-cols', index: 6, count: 1 })).not.toMatch(/<col[^>]*min="7"/)
  const overlap = source.replace('min="8" max="9"', 'min="4" max="9"')
  expect(() => setColumnWidthsXml(overlap, [{ index: 3, widthChars: 20 }])).toThrow(/重叠|overlap/)
  expect(() => applyStructuralOp(overlap, { kind: 'insert-cols', index: 1, count: 1 }, 'Sheet1')).toThrow(/重叠|overlap/)
})

it('patches single-quoted spaced column attributes without duplicate names and independently reads the ZIP', async () => {
  const original = "<worksheet><cols><col max = '5' min = '3' width = '13' customWidth = '1' bestFit = '1' hidden = '1' style = '0' outlineLevel = '2' collapsed = '1' data-extra = 'preserved'/></cols><sheetData></sheetData></worksheet>"
  const edited = setColumnWidthsXml(original, [{ index: 3, widthChars: 20 }])
  const doc = new DOMParser().parseFromString(edited, 'application/xml')
  expect(doc.querySelector('parsererror')).toBeNull()
  const target = doc.querySelector('col[min="4"]')!
  expect(target).not.toBeNull()
  expect(target.getAttribute('max')).toBe('4'); expect(target.getAttribute('width')).toBe('20.0000')
  expect(target.getAttribute('hidden')).toBe('1'); expect(target.getAttribute('data-extra')).toBe('preserved')
  expect(target.hasAttribute('bestFit')).toBe(false)
  expect(doc.querySelector('col[min="3"]')!.getAttribute('width')).toBe('13')
  expect(doc.querySelector('col[min="5"]')!.getAttribute('hidden')).toBe('1')
  const moved = applyStructuralOp(original, { kind: 'insert-cols', index: 1, count: 1 }, 'Sheet1')
  const movedDoc = new DOMParser().parseFromString(moved, 'application/xml')
  expect(movedDoc.querySelector('col')!.getAttribute('min')).toBe('4')
  expect(movedDoc.querySelector('col')!.getAttribute('max')).toBe('6')
  const source = await fixture(), sourceXml = await xmlOf(source)
  const xml = sourceXml.replace(/<cols>[\s\S]*?<\/cols>/, original.match(/<cols>[\s\S]*?<\/cols>/)![0].replace(" data-extra = 'preserved'", ''))
  const bytes = (await assemblePackage(source, { replaced: new Map([[path, xml]]), added: new Map(), addedBinary: new Map(), removedEntries: [], addedEntries: [], touchedEntries: [path] })).buffer
  const saved = await applyWorkbookOperations(bytes, [{ kind: 'applyColumnWidths', sheetName: 'Sheet1', entries: [{ index: 3, widthChars: 20 }] }])
  const checked = spawnSync(independentPython(), ['-I', '-c', `import base64,json,sys
from io import BytesIO
from openpyxl import load_workbook
s=load_workbook(BytesIO(base64.b64decode(sys.stdin.read()))).active
print(json.dumps([(c.min,c.max,c.width,c.hidden,c.outlineLevel,c.collapsed) for c in s.column_dimensions.values()]))`], { input: Buffer.from(saved).toString('base64'), encoding: 'utf8' })
  expect(checked.status, checked.stderr).toBe(0)
  expect(JSON.parse(checked.stdout)).toEqual([[3, 3, 13, true, 2, true], [4, 4, 20, true, 2, true], [5, 5, 13, true, 2, true]])
  for (const attrs of ["min='0' max='3'", "min='2' max='1'", "min='1.5' max='3'", "min='1' max='16385'", "max='3'"]) {
    const invalid = `<worksheet><cols><col ${attrs} hidden='1'/></cols><sheetData></sheetData></worksheet>`
    expect(() => setColumnWidthsXml(invalid, [{ index: 1, widthChars: 20 }])).toThrow(/范围|range/)
  }
})
