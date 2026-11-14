/** Adapter for fixed-source Format Cells command batches. Reuse engine style
 * edits and the existing package draft/replay path, including protection flags
 * which have no native Univer style property. Validate the whole batch first. */
import { formatAddress, type CellEdit, type WorkbookModel } from '@sheets-web/xlsx-engine'
import { workbookStyleEditSchema, type WorkbookStyleEdit } from '@sheets-web/xlsx-engine/edit-schemas'
import { captureNumberFormatTarget, validateNumberFormat, type FormatWorkbook } from './workbook-format'
import { fromUniverStyle, logicalStyleOf, toUniverStyle, type UniverStyleData } from './workbook-vendor/core/style-map'
import { draftFromSelection, type FormatCellsDraft, type TriState } from './vendor/genoffice-sheets-format/format-cells'

export function validateFormatCellsBudget(operations: readonly Record<string, unknown>[]): void {
  if (operations.length > 500 || new TextEncoder().encode(JSON.stringify(operations)).length > 10 * 1024 * 1024) throw new Error('单元格格式超出草稿预算，请缩小选区或先保存当前修改')
}

export type FormatCellsTarget = NonNullable<ReturnType<typeof captureNumberFormatTarget>>
export function validateFormatCellsTarget(target: FormatCellsTarget | undefined, workbook: FormatWorkbook | null, editable: boolean): asserts target is FormatCellsTarget {
  if (!editable) throw new Error('当前工作簿不可编辑或正在保存')
  if (!target || !workbook || target.workbook.getWorkbook?.() !== workbook.getWorkbook?.() ||
      !target.sheetId || !workbook.getSheetBySheetId?.(target.sheetId) ||
      target.row !== target.range.getRow() || target.column !== target.range.getColumn() ||
      target.height !== target.range.getHeight() || target.width !== target.range.getWidth()) throw new Error('原选区已失效，请重新打开单元格格式')
}

/** Each field aggregates independently; a mixed value is unchanged, never the
 * top-left cell's format applied accidentally to the rest of the selection. */
export function selectedFormatCellsDraft(target: FormatCellsTarget, model: WorkbookModel): FormatCellsDraft {
  const source = model.sheets.find(sheet => sheet.name === target.sheet.getSheetName?.())
  if (!source || source.rotationReadOnlyReason) throw new Error('来源包含尚未完整投影的继承样式，暂不能安全编辑格式')
  const baseline = toUniverStyle(logicalStyleOf(model.styles, model.styles.cellXfs[0], model.themePalette) ?? {})
  const styles: UniverStyleData[] = [], protections: { locked: boolean; hidden: boolean }[] = []
  for (let row = target.row; row < target.row + target.height; row++) for (let column = target.column; column < target.column + target.width; column++) {
    const cell = target.sheet.getRange(row, column)
    if (!cell.getCellStyleData) throw new Error('网格未提供可读取的组合样式')
    styles.push({ ...baseline, ...cell.getCellStyleData() })
    const xf = model.styles.cellXfs[source.cells[formatAddress(row, column)]?.styleIndex ?? 0]
    protections.push(xf?.protection ?? { locked: true, hidden: false })
  }
  const common = <T>(items: T[]): T | undefined => items.every(value => value === items[0]) ? items[0] : undefined
  const tri = (values: boolean[]): TriState => { const value = common(values); return value === undefined ? '' : value ? 'on' : 'off' }
  const logical = styles.map(fromUniverStyle)
  const draft = draftFromSelection(null)
  const rotation = common(logical.map(style => style.textRotation))
  return {
    ...draft,
    pattern: common(styles.map(style => style.n?.pattern ?? 'General')) ?? '',
    family: common(styles.map(style => style.ff)) ?? '',
    size: String(common(styles.map(style => style.fs)) ?? ''),
    bold: tri(styles.map(style => style.bl === 1)), italic: tri(styles.map(style => style.it === 1)),
    underline: tri(styles.map(style => style.ul?.s === 1)), strike: tri(styles.map(style => style.st?.s === 1)),
    fontColor: common(styles.map(style => style.cl?.rgb?.toLowerCase())) ?? '',
    fill: common(styles.map(style => style.bg?.rgb?.toLowerCase())) ?? '',
    hAlign: common(logical.map(style => style.hAlign)) ?? '',
    vAlign: common(logical.map(style => style.vAlign)) ?? '',
    wrapText: tri(styles.map(style => style.tb === 2)),
    rotation: rotation === undefined ? '' : ({ 0: '0', 45: '45', 135: '-45', 90: '90', 180: '-90', 255: 'vertical' } as Record<number, string>)[rotation] ?? '',
    indent: String(common(logical.map(style => style.indent ?? 0)) ?? ''),
    locked: tri(protections.map(value => value.locked)), hidden: tri(protections.map(value => value.hidden)),
  }
}

export function formatCellsOperation(target: FormatCellsTarget, commands: readonly string[]): { kind: 'applyCellEdits'; edits: CellEdit[] } {
  const style: WorkbookStyleEdit = {}
  let border: { preset: string; color: string; style: string } | undefined
  const flag = (value: string): boolean => { if (!['on', 'off'].includes(value)) throw new Error('格式开关无效'); return value === 'on' }
  const color = (value: string): string => { if (!/^#[0-9a-f]{6}$/i.test(value)) throw new Error('颜色无效'); return value }
  for (const command of commands) {
    const colon = command.indexOf(':'), key = command.slice(0, colon), value = command.slice(colon + 1)
    switch (key) {
      case 'format': style.numberFormat = validateNumberFormat(value); break
      case 'font-family': style.fontFamily = value; break
      case 'font-size': style.fontSize = Number(value); break
      case 'bold': style.bold = flag(value); break
      case 'italic': style.italic = flag(value); break
      case 'underline': style.underline = flag(value); if (style.underline) style.underlineStyle = 'single'; break
      case 'strike': style.strikethrough = flag(value); break
      case 'font-color': style.fontColor = color(value); break
      case 'fill': style.fillColor = value === 'none' ? null : color(value); break
      case 'align': style.horizontalAlignment = value as WorkbookStyleEdit['horizontalAlignment']; break
      case 'valign': style.verticalAlignment = (value === 'middle' ? 'center' : value) as WorkbookStyleEdit['verticalAlignment']; break
      case 'wrap': style.wrapText = flag(value); break
      case 'rotate': {
        const rotations: Record<string, number> = { '0': 0, '45': 45, '-45': 135, '90': 90, '-90': 180, vertical: 255 }
        if (!(value in rotations)) throw new Error('文字方向无效')
        style.textRotation = rotations[value]; break
      }
      case 'indent': if (!/^\d{1,3}$/.test(value)) throw new Error('缩进必须为 0–250 的整数'); style.indent = Number(value); break
      case 'cellprot': {
        const parts = value.split(':')
        if (parts.length !== 2 || !['', 'locked-on', 'locked-off'].includes(parts[0]!) || !['', 'hidden-on', 'hidden-off'].includes(parts[1]!)) throw new Error('单元格保护标志无效')
        if (parts[0]) style.protectionLocked = parts[0] === 'locked-on'
        if (parts[1]) style.protectionHidden = parts[1] === 'hidden-on'
        break
      }
      case 'border': {
        const [preset, hex, line, ...extra] = value.split(':')
        if (extra.length || !['none', 'all', 'outer', 'thick-outer', 'top', 'bottom', 'left', 'right'].includes(preset!)) throw new Error('边框预设无效')
        // Same engine schema as save, even when the selected preset clears edges.
        workbookStyleEditSchema.parse({ borderTop: { style: line, color: color(hex!) } })
        border = { preset: preset!, color: hex!, style: line! }; break
      }
      default: throw new Error(`不支持的单元格格式命令：${key}`)
    }
  }
  workbookStyleEditSchema.parse(style)
  const sheetName = target.sheet.getSheetName?.()
  if (!sheetName || target.height * target.width > 10_000 || target.height < 1 || target.width < 1) throw new Error('选区超出格式预算')
  const edits: CellEdit[] = []
  for (let r = 0; r < target.height; r++) for (let c = 0; c < target.width; c++) {
    const delta = { ...style }
    if (border) {
      const edge = { style: border.style, color: border.color }
      for (const [key, outside, name] of [
        ['borderTop', r === 0, 'top'], ['borderBottom', r === target.height - 1, 'bottom'],
        ['borderLeft', c === 0, 'left'], ['borderRight', c === target.width - 1, 'right'],
      ] as const) {
        if (border.preset === 'none') delta[key] = null
        else if (border.preset === 'all' || outside && ['outer', 'thick-outer', name].includes(border.preset)) delta[key] = edge as NonNullable<WorkbookStyleEdit['borderTop']>
      }
    }
    if (Object.keys(delta).length) edits.push({ sheetName, row: target.row + r, column: target.column + c, writeValue: false, cell: { value: null }, style: delta })
  }
  return { kind: 'applyCellEdits', edits }
}
