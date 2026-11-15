import { z } from 'zod'
import { applyDvRules, dateToSerial, DvEditError, type DvCellArea, type DvWireRule } from './data-validation'
import { readDataValidations } from './data-validation-read'
import { formatAddress, parseRange } from './cell-address'
import { offsetFormulaRefs } from './conditional-formatting-offset-source'
import { parseSheetElements, resolveWorksheetPath } from './workbook-read'
import { readXmlAttribute } from './xml'
import { assemblePackage, createBufferEntrySource } from './zip'

/// Replace a fully modeled worksheet snapshot; retain every unrelated part.
export async function replaceSheetDataValidations(
  bytes: Uint8Array, sheetName: string, rules: readonly DvWireRule[],
): Promise<Uint8Array> {
  return editSheetDataValidations(bytes, sheetName, () => rules)
}

async function editSheetDataValidations(
  bytes: Uint8Array, sheetName: string,
  edit: (current: readonly DvWireRule[], workbook: string) => readonly DvWireRule[],
): Promise<Uint8Array> {
  const source = await createBufferEntrySource(bytes)
  const workbook = await source.readText('xl/workbook.xml')
  const sheet = parseSheetElements(workbook).find(item => item.name === sheetName)
  if (!sheet?.relationshipId) throw new DvEditError(`工作表 ${sheetName} 不存在`)
  const path = await resolveWorksheetPath(source, sheet.relationshipId)
  const xml = await source.readText(path)
  const current = readDataValidations(xml)
  if (current.readOnlyReason) throw new DvEditError(current.readOnlyReason)
  const updated = applyDvRules(xml, edit(current.rules, workbook))
  if (updated === xml) return bytes
  return (await assemblePackage(bytes, {
    replaced: new Map([[path, updated]]), added: new Map(), addedBinary: new Map(),
    removedEntries: [], addedEntries: [], touchedEntries: [path],
  })).buffer
}

const cellRange = z.string().regex(/^[A-Z]{1,3}[1-9][0-9]{0,6}(?::[A-Z]{1,3}[1-9][0-9]{0,6})?$/)
const xmlText = z.string().regex(/^[^\u0000-\u0008\u000b\u000c\u000e-\u001f\ufffe\uffff]*$/)
const isoDate = z.string().regex(/^\d{4}-\d{2}-\d{2}$/)
const sourceRule = z.discriminatedUnion('kind', [
  z.object({ kind: z.literal('list'), values: z.array(xmlText.min(1).max(255)).min(1).max(100) }).strict(),
  z.object({ kind: z.literal('listRef'), range: cellRange }).strict(),
  z.object({ kind: z.literal('numberBetween'), min: z.number().finite(), max: z.number().finite() }).strict(),
  z.object({ kind: z.literal('dateBetween'), start: isoDate, end: isoDate }).strict(),
  z.object({ kind: z.literal('checkbox') }).strict(),
  z.object({ kind: z.literal('formula'), formula: xmlText.startsWith('=').min(2).max(8192) }).strict(),
])
const sourceValidationOperation = z.object({
  kind: z.literal('applyDataValidationSource'), sheetName: z.string().min(1).max(31),
  range: cellRange, validation: sourceRule.nullable(),
}).strict()

function gridRange(ref: string): DvCellArea {
  const area = parseRange(ref)
  if (area.endRow >= 1048576 || area.endColumn >= 16384) throw new DvEditError('数据验证范围超出工作表')
  return area
}

function toWireRule(rule: z.infer<typeof sourceRule>, date1904: boolean): Record<string, unknown> {
  switch (rule.kind) {
    case 'list': {
      const formula1 = rule.values.join(',')
      if (formula1.startsWith('=') || rule.values.some(value => /[,\r\n]/.test(value)) ||
          formula1.replaceAll('"', '""').length > 255) {
        throw new DvEditError('列表值无法保存为 Excel 内联列表，请引用单元格区域。')
      }
      return { type: 'list', formula1, showDropDown: true }
    }
    case 'listRef': {
      const area = gridRange(rule.range)
      const absolute = (row: number, column: number) => formatAddress(row, column).replace(/^([A-Z]+)(\d+)$/, '$$$1$$$2')
      return { type: 'list', formula1: `=${absolute(area.startRow, area.startColumn)}:${absolute(area.endRow, area.endColumn)}`, showDropDown: true }
    }
    case 'numberBetween':
      if (rule.min > rule.max) throw new DvEditError('数据验证数字上下限颠倒。')
      return { type: 'decimal', operator: 'between', formula1: String(rule.min), formula2: String(rule.max) }
    case 'dateBetween': {
      const first = dateToSerial(rule.start, date1904), last = dateToSerial(rule.end, date1904)
      if (first === undefined || last === undefined || first < 0 || first > last) {
        throw new DvEditError('数据验证日期无效或上下限颠倒。')
      }
      return { type: 'date', operator: 'between', formula1: String(first), formula2: String(last) }
    }
    case 'checkbox': return { type: 'checkbox' }
    case 'formula': return { type: 'custom', formula1: rule.formula }
  }
}

function subtractValidationArea(area: DvCellArea, cut: DvCellArea): DvCellArea[] {
  const startRow = Math.max(area.startRow, cut.startRow), endRow = Math.min(area.endRow, cut.endRow)
  const startColumn = Math.max(area.startColumn, cut.startColumn), endColumn = Math.min(area.endColumn, cut.endColumn)
  if (startRow > endRow || startColumn > endColumn) return [area]
  return [
    { ...area, endRow: startRow - 1 },
    { ...area, startRow, endRow, endColumn: startColumn - 1 },
    { ...area, startRow, endRow, startColumn: endColumn + 1 },
    { ...area, startRow: endRow + 1 },
  ].filter(piece => piece.startRow <= piece.endRow && piece.startColumn <= piece.endColumn)
}

export async function applyDataValidationSource(bytes: Uint8Array, raw: unknown): Promise<Uint8Array> {
  const { sheetName, range, validation } = sourceValidationOperation.parse(raw)
  const target = gridRange(range)
  return editSheetDataValidations(bytes, sheetName, (current, workbook) => {
    const remaining = current.flatMap(({ ranges, rule }): DvWireRule[] => {
      const kept = ranges.flatMap(area => subtractValidationArea(area, target))
      const anchor = kept[0]
      if (!anchor) return []
      const rowDelta = anchor.startRow - ranges[0]!.startRow
      const colDelta = anchor.startColumn - ranges[0]!.startColumn
      if (!rowDelta && !colDelta) return [{ ranges: kept, rule }]
      const rebased = { ...rule }
      for (const key of ['formula1', 'formula2']) {
        const formula = rebased[key]
        if (typeof formula === 'string' && formula.startsWith('=')) {
          rebased[key] = offsetFormulaRefs(formula, rowDelta, colDelta)
        }
      }
      return [{ ranges: kept, rule: rebased }]
    })
    if (validation) {
      const properties = workbook.match(/<workbookPr\b[^>]*>/)?.[0] ?? ''
      const date1904 = /^(?:1|true)$/.test(readXmlAttribute(properties, 'date1904') ?? '')
      remaining.push({ ranges: [target], rule: toWireRule(validation, date1904) })
    }
    return remaining
  })
}
