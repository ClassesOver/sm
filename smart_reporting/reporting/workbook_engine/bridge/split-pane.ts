// 视图 ▸ 拆分窗口：本地适配。固定源 GenOffice f8c17004 的 ExcelShell 视图 ▸ 窗口组只有冻结窗格，没有拆分窗口，
// Univer 0.25.1 也没有拆分视口，所以这里只提供可核验的一项：取消文件中已有的拆分窗格（Excel 中再次点击“拆分”即取消）。
// 以当前读取到的拆分窗格为来源身份；写后回读确认 pane 已移除，其余 sheetView 属性与部件不变。
import { z } from 'zod'
import { assemblePackage, createBufferEntrySource } from '../packages/xlsx-engine/src/zip'
import { parseSheetElements, readWorkbook, resolveWorksheetPath } from '../packages/xlsx-engine/src/workbook-read'

const splitPane = z.object({
  xSplitTwips: z.number().finite().nonnegative(),
  ySplitTwips: z.number().finite().nonnegative(),
  topLeftCell: z.string().regex(/^[A-Z]{1,3}[1-9][0-9]{0,6}$/).optional(),
}).strict()

export const removeSheetSplitPaneSchema = z.object({
  kind: z.literal('removeSheetSplitPane'),
  sheetName: z.string().min(1).max(31),
  expected: splitPane,
}).strict()

const same = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b)

export async function removeSheetSplitPane(input: Uint8Array, op: unknown): Promise<Uint8Array> {
  const parsed = removeSheetSplitPaneSchema.parse(op)
  const sheet = (await readWorkbook(input)).sheets.find(entry => entry.name === parsed.sheetName)
  if (!sheet) throw new Error('workbook_split_pane_sheet_missing')
  if (!sheet.splitPane) throw new Error('workbook_split_pane_missing')
  // 对象键顺序由读取侧固定；来源身份不一致即拒绝，避免在已变化的视图上移除。
  if (!same(sheet.splitPane, parsed.expected)) throw new Error('workbook_split_pane_identity_changed')
  const source = await createBufferEntrySource(input)
  const element = parseSheetElements(await source.readText('xl/workbook.xml')).find(entry => entry.name === parsed.sheetName)
  if (!element?.relationshipId) throw new Error('workbook_split_pane_sheet_missing')
  const path = await resolveWorksheetPath(source, element.relationshipId)
  const xml = await source.readText(path)
  const view = xml.match(/<sheetView\b(?:[^>]*[^/>])?>[\s\S]*?<\/sheetView>/)
  if (!view || view.index === undefined || !/<pane\b/.test(view[0])) throw new Error('workbook_split_pane_missing')
  // 只移除第一个 sheetView 的 pane 及其按窗格限定的 selection；与 page-setup.ts setFrozenPane 的清理规则一致。
  const cleaned = view[0].replace(/<pane\b[^>]*\/?>(?:[\s\S]*?<\/pane>)?/, '').replace(/<selection\b[^>]*\bpane="[^"]*"[^>]*?(?:\/>|>[\s\S]*?<\/selection\s*>)/g, '')
  const next = xml.slice(0, view.index) + cleaned + xml.slice(view.index + view[0].length)
  const bytes = (await assemblePackage(input, {
    replaced: new Map([[path, next]]), added: new Map(), addedBinary: new Map(),
    removedEntries: [], addedEntries: [], touchedEntries: [path],
  })).buffer
  const after = (await readWorkbook(bytes)).sheets.find(entry => entry.name === parsed.sheetName)
  if (!after || after.splitPane || after.freeze) throw new Error('workbook_split_pane_readback_failed')
  return bytes
}
