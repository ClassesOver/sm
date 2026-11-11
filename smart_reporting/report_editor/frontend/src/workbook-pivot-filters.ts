import { readWorkbook, parseRange, formatAddress } from '@sheets-web/xlsx-engine'
import { buildPivotLayout } from '@sheets-web/xlsx-engine/pivot-layout'
import { formatCodeFor } from '@sheets-web/xlsx-engine/style-read'
import { createPivotEntrySource } from '@sheets-web/xlsx-engine/pivot-source'
import { readXmlAttribute } from '@sheets-web/xlsx-engine/xml'
import type { PivotConfig, WorkbookPivot } from './workbook-pivot'
import { supportsOwnedPivotControls } from '@sheets-web/xlsx-engine/pivot-controls'

export interface PivotFilterField {
  name: string
  axis: 'row' | 'column'
  level: number
  timeline: boolean
  members: { value: string; date?: string }[]
}

/** 明确区分成员筛选与原生控件保存；工作表浮层复用相同的透视保存事务。 */
export const PIVOT_FILTER_SAVE_NOTICE = '默认保存筛选结果与成员选择。勾选原生控件后同时保存 Excel 控件、缓存和位置；支持在工作表控件中筛选，位置和尺寸通过此对话框编辑。原生时间线仅支持带日期格式的数值日期，刷新时按原区间筛选新增日期；ISO 日期文本仍可进行成员筛选，新增成员需重新筛选。'

function validDate(value: string): string | undefined {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return undefined
  const date = new Date(value + 'T00:00:00.000Z')
  return Number.isFinite(date.getTime()) && date.toISOString().slice(0, 10) === value ? value : undefined
}

function serialDate(value: number, epoch1904: boolean): string | undefined {
  if (!Number.isFinite(value) || value < 0 || !epoch1904 && Math.floor(value) === 60) return undefined
  const days = Math.floor(value)
  const epoch = epoch1904 ? Date.UTC(1904, 0, 1) : Date.UTC(1899, 11, 31)
  const date = new Date(epoch + (days - (!epoch1904 && days > 60 ? 1 : 0)) * 86400000)
  if (!Number.isFinite(date.getTime()) || date.getUTCFullYear() > 9999) return undefined
  return validDate(date.toISOString().slice(0, 10))
}

export async function readPivotFilterFields(bytes: Uint8Array, pivot: WorkbookPivot): Promise<PivotFilterField[]> {
  if (pivot.readonlyReason) throw new Error(pivot.readonlyReason)
  const source = await createPivotEntrySource(bytes)
  if ((await source.paths()).some(path => /^xl\/(?:slicerCaches|timelineCaches|slicers|timelines)\//.test(path)) && !await supportsOwnedPivotControls(bytes)) throw new Error('工作簿含现有 Excel 切片器/时间线控件，当前入口无法同步其控件状态，请在 Excel 中编辑。')
  const workbook = await readWorkbook(bytes), sheet = workbook.sheets.find(sheet => sheet.name === pivot.sourceSheetName)
  if (!sheet) throw new Error('透视表来源工作表不存在')
  const area = parseRange(pivot.sourceRange)
  if (area.endRow - area.startRow > 10000 || area.endColumn - area.startColumn >= 200) throw new Error('透视表来源最多10000条数据、200列')
  const grid = []
  for (let row = area.startRow; row <= area.endRow; row++) {
    const cells = []
    for (let column = area.startColumn; column <= area.endColumn; column++) cells.push(sheet.cells[formatAddress(row, column)]?.value ?? null)
    grid.push(cells)
  }
  const layout = buildPivotLayout(grid, { rowFields: pivot.rowFields, columnField: pivot.columnFields, values: pivot.values, groupings: pivot.groupings })
  const workbookXml = await source.readText('xl/workbook.xml')
  const epoch1904 = /^(?:1|true)$/.test(readXmlAttribute(workbookXml.match(/<(?:\w+:)?workbookPr\b[^>]*>/)?.[0] ?? '', 'date1904') ?? '')
  return (['row', 'column'] as const).flatMap(axis => {
    const names = axis === 'row' ? pivot.rowFields : pivot.columnFields
    const levels = axis === 'row' ? layout.definition.rowLevelItems : layout.definition.colLevelItems ?? []
    return names.map((name, level) => {
      const column = area.startColumn + layout.definition.fieldNames.indexOf(name), dates = new Map<string, string | undefined>()
      for (let row = area.startRow + 1; row <= area.endRow; row++) {
        const cell = sheet.cells[formatAddress(row, column)], value = cell?.value, key = String(value ?? '')
        let date: string | undefined
        if (typeof value === 'string') date = validDate(value)
        else if (typeof value === 'number') {
          const xf = workbook.styles.cellXfs[cell?.styleIndex ?? 0]
          const format = xf ? formatCodeFor(workbook.styles, xf).replace(/"[^"]*"|\[[^\]]*\]|\\./g, '') : ''
          if (/[dy]/i.test(format)) date = serialDate(value, epoch1904)
        }
        dates.set(key, dates.has(key) && dates.get(key) !== date ? undefined : date)
      }
      const grouped = pivot.groupings?.some(grouping => grouping.field === name)
      const members = (levels[level] ?? []).map(value => ({ value, ...(!grouped && dates.get(value) ? { date: dates.get(value)! } : {}) }))
      return { name, axis, level, members, timeline: members.some(member => member.date) && members.every(member => member.value === '' || member.date) }
    })
  })
}

export function pivotMemberFilterConfig(pivot: PivotConfig, fields: PivotFilterField[], name: string, selected: string[]): PivotConfig {
  const field = fields.find(field => field.name === name)
  if (!field) throw new Error('请选择现有行字段或列字段')
  if (!selected.length) throw new Error('至少选择一个成员；清除筛选请使用“全选”')
  if (selected.some(value => !field.members.some(member => member.value === value))) throw new Error('透视表成员已变化，请重新打开筛选')
  const next = structuredClone(pivot), allowed = new Set(selected)
  const hidden = { row: pivot.rowFields.map((_, level) => [...(pivot.hiddenMembers?.row?.[level] ?? [])]), column: pivot.columnFields.map((_, level) => [...(pivot.hiddenMembers?.column?.[level] ?? [])]) }
  hidden[field.axis][field.level] = field.members.filter(member => !allowed.has(member.value)).map(member => member.value)
  next.hiddenMembers = hidden
  return next
}

export function pivotTimelineFilterConfig(pivot: PivotConfig, fields: PivotFilterField[], name: string, from: string, to: string): PivotConfig {
  if (!validDate(from) || !validDate(to)) throw new Error('请输入有效日期，格式为 YYYY-MM-DD')
  if (from > to) throw new Error('开始日期不能晚于结束日期')
  const field = fields.find(field => field.name === name)
  if (!field?.timeline) throw new Error('请选择日期字段；支持 ISO 日期文本或有日期格式的 Excel 日期序列')
  const selected = field.members.filter(member => member.date && member.date >= from && member.date <= to).map(member => member.value)
  if (!selected.length) throw new Error('所选日期区间没有匹配成员')
  return pivotMemberFilterConfig(pivot, fields, name, selected)
}
