import { TextDecoration } from '@univerjs/core'
import { isValidFormat } from 'numfmt'
import type { WorkbookModel } from '@sheets-web/xlsx-engine'
import { createModal } from './modal'
import { logicalStyleOf, toUniverStyle, type UniverStyleData } from './workbook-vendor/core/style-map'
import { readBackSnapshot } from './workbook-vendor/grid/sync'
import { diffToEdits } from './workbook-vendor/core/session-core'
import type { WorkbookOperation } from './workbook-draft'

export type FormatValue<T> = { kind: 'value'; value: T } | { kind: 'mixed' } | { kind: 'unavailable'; reason: string }
export interface WorkbookFormatState {
  fontFamily: FormatValue<string>
  fontSize: FormatValue<number>
  bold: FormatValue<boolean>
  italic: FormatValue<boolean>
  underline: FormatValue<boolean>
  doubleUnderline: FormatValue<boolean>
  strikethrough: FormatValue<boolean>
  fontColor: FormatValue<string>
  fillColor: FormatValue<string>
  numberFormat: FormatValue<string>
}
export interface FormatRange {
  getRow(): number
  getColumn(): number
  getHeight(): number
  getWidth(): number
  getCellStyleData?(): UniverStyleData | null
  setNumberFormat(pattern: string): unknown
}
export interface FormatSheet {
  getSheetId?(): string
  getSheetName?(): string
  getSelection(): { getActiveRange(): FormatRange | null } | null
  getRange(row: number, column: number): { getCellStyleData?(): UniverStyleData | null }
}
export interface FormatWorkbook {
  getId?(): string
  getWorkbook?(): unknown
  getActiveSheet(): FormatSheet | null
  getSheetBySheetId?(id: string): FormatSheet | null
}
export const FORMAT_CELL_BUDGET = 10_000
const keys = ['fontFamily', 'fontSize', 'bold', 'italic', 'underline', 'doubleUnderline', 'strikethrough', 'fontColor', 'fillColor', 'numberFormat'] as const
const unavailable = (reason: string): WorkbookFormatState => Object.fromEntries(keys.map(key => [key, { kind: 'unavailable', reason }])) as unknown as WorkbookFormatState

/** Public composed single-cell styles, aggregated independently for each property.
 * The model supplies XLSX defaults, never fabricated Arial/12/black/yellow values.
 * An incomplete source projection remains explicitly unknown.
 */
export function selectedWorkbookFormat(workbook: FormatWorkbook | null, model?: WorkbookModel): WorkbookFormatState {
  const sheet = workbook?.getActiveSheet(), range = sheet?.getSelection()?.getActiveRange()
  if (!sheet || !range) return unavailable('请先选择单元格或区域')
  const count = range.getHeight() * range.getWidth()
  if (!Number.isSafeInteger(count) || count < 1 || count > FORMAT_CELL_BUDGET) return unavailable('选区超出格式状态读取预算，请缩小到一万个单元格以内')
  const source = model?.sheets.find(item => item.name === sheet.getSheetName?.())
  if (source?.rotationReadOnlyReason) return unavailable('来源包含尚未完整投影的继承样式，当前格式不可判定')
  const baseline = model ? toUniverStyle(logicalStyleOf(model.styles, model.styles.cellXfs[0], model.themePalette) ?? {}) : {}
  let result: WorkbookFormatState | undefined
  for (let row = 0; row < range.getHeight(); row++) for (let col = 0; col < range.getWidth(); col++) {
    const cell = sheet.getRange(range.getRow() + row, range.getColumn() + col)
    if (!cell.getCellStyleData) return unavailable('当前网格未提供可读取的组合样式')
    const style = { ...baseline, ...cell.getCellStyleData() }
    const value = <T>(v: T | undefined): FormatValue<T> => v === undefined ? { kind: 'unavailable', reason: '来源格式未完整投影，当前值不可判定' } : { kind: 'value', value: v }
    const current: WorkbookFormatState = {
      fontFamily: value(style.ff), fontSize: value(style.fs), bold: value(style.bl === 1), italic: value(style.it === 1),
      underline: value(style.ul?.s === 1 && style.ul.t !== TextDecoration.DOUBLE),
      doubleUnderline: value(style.ul?.s === 1 && style.ul.t === TextDecoration.DOUBLE),
      strikethrough: value(style.st?.s === 1),
      fontColor: value(style.cl?.rgb ?? 'auto'), fillColor: value(style.bg?.rgb ?? 'none'),
      numberFormat: value(style.n?.pattern ?? 'General'),
    }
    if (!result) { result = current; continue }
    for (const key of keys) {
      const before = result[key], after = current[key]
      if (before.kind === 'unavailable') continue
      if (after.kind === 'unavailable') (result[key] as FormatValue<unknown>) = after
      else if (before.kind === 'value' && after.kind === 'value' && before.value !== after.value) (result[key] as FormatValue<unknown>) = { kind: 'mixed' }
    }
  }
  return result ?? unavailable('请先选择单元格或区域')
}

/** Formula result application can infer the source cell's number format. It is
 * rendering/calculation state, not a user format edit. Strip only that incoming
 * component before Univer merges the result, so the cell's existing explicit
 * format (including General), other style fields and formula result are kept.
 * Clone payload rows/cells/styles: the engine may retain these objects for replay.
 */
export function omitCalculatedNumberFormats(
  command: { id: string; params?: any; options?: { [key: string]: unknown } },
  snapshot: unknown,
): boolean {
  if (command.id !== 'sheet.mutation.set-range-values' || command.options?.fromFormula !== true || command.options?.applyFormulaCalculationResult !== true) return false
  const params = command.params
  if (!params?.cellValue || typeof params.cellValue !== 'object') return true
  const styles = (snapshot as { styles?: Record<string, UniverStyleData> } | null)?.styles ?? {}
  const values: Record<string, Record<string, any>> = {}
  for (const [row, cells] of Object.entries(params.cellValue as Record<string, Record<string, any>>)) {
    if (!cells || typeof cells !== 'object') { values[row] = cells; continue }
    const next: Record<string, any> = {}
    for (const [column, cell] of Object.entries(cells)) {
      const style = typeof cell?.s === 'string' ? styles[cell.s] : cell?.s
      if (!style || typeof style !== 'object' || !Object.hasOwn(style, 'n')) { next[column] = cell; continue }
      const { n: _calculatedNumberFormat, ...otherStyle } = style
      next[column] = { ...cell, s: otherStyle }
    }
    values[row] = next
  }
  // Keep params identity because the public event shares it with the command
  // handler. Only replace the cellValue subtree, leaving trigger/metadata intact.
  params.cellValue = values
  return true
}

export function validateNumberFormat(pattern: unknown): string {
  if (typeof pattern !== 'string' || !pattern.trim() || pattern.length > 255 || /[\x00-\x1f\x7f]/.test(pattern)) throw new Error('格式代码须为 1–255 个字符，且不能包含控制字符')
  if (!isValidFormat(pattern)) throw new Error('数字格式代码无效，请检查引号、方括号和格式分节')
  return pattern // Spaces and quoted literals are significant; do not trim.
}

export interface NumberFormatTarget {
  workbook: FormatWorkbook
  sheet: FormatSheet
  sheetId?: string
  range: FormatRange
  row: number
  column: number
  height: number
  width: number
}
export function captureNumberFormatTarget(workbook: FormatWorkbook | null): NumberFormatTarget | undefined {
  const sheet = workbook?.getActiveSheet(), range = sheet?.getSelection()?.getActiveRange()
  if (!workbook || !sheet || !range) return undefined
  const row = range.getRow(), column = range.getColumn(), height = range.getHeight(), width = range.getWidth()
  if (![row, column, height, width].every(Number.isSafeInteger) || row < 0 || column < 0 || height < 1 || width < 1) return undefined
  if (height * width > FORMAT_CELL_BUDGET) throw new Error('选区超出数字格式预算，请缩小到一万个单元格以内')
  return { workbook, sheet, sheetId: sheet.getSheetId?.(), range, row, column, height, width }
}
export function applyCapturedNumberFormat(target: NumberFormatTarget | undefined, workbook: FormatWorkbook | null, pattern: string, editable: boolean): void {
  validateNumberFormat(pattern)
  if (!editable) throw new Error('当前工作簿不可编辑或正在保存')
  const sameWorkbook = target && workbook && (target.workbook.getWorkbook && workbook.getWorkbook ? target.workbook.getWorkbook() === workbook.getWorkbook() : target.workbook === workbook)
  if (!target || !sameWorkbook || target.sheetId && !workbook?.getSheetBySheetId?.(target.sheetId)) throw new Error('原选区已失效，请重新选择单元格或区域')
  if (target.row !== target.range.getRow() || target.column !== target.range.getColumn() || target.height !== target.range.getHeight() || target.width !== target.range.getWidth()) throw new Error('原选区已变化，请重新打开数字格式')
  if (target.range.setNumberFormat(pattern) === false) throw new Error('数字格式未应用')
}

/** Project the pending format mutation through the same capture/diff used by saves. */
export function validateNumberFormatBudget(snapshot: unknown, model: WorkbookModel, staged: WorkbookOperation[], structuralCount: number, target: NumberFormatTarget, pattern: string): void {
  validateNumberFormat(pattern)
  const data = structuredClone(snapshot) as { sheets: Record<string, { name: string; cellData?: Record<number, Record<number, { s?: string; v?: unknown; f?: string }>> }>; styles: Record<string, UniverStyleData>; sheetOrder: string[] }
  const sheetId = target.sheetId ?? Object.keys(data.sheets).find(id => data.sheets[id]?.name === target.sheet.getSheetName?.())
  const sheet = sheetId ? data.sheets[sheetId] : undefined
  if (!sheet) throw new Error('原选区工作表已失效')
  const styles = data.styles ??= {}
  const styleKeys = new Map<string, string>()
  for (let row = target.row; row < target.row + target.height; row++) for (let column = target.column; column < target.column + target.width; column++) {
    const cells = (sheet.cellData ??= {})[row] ??= {}
    const cell = cells[column] ??= {}
    const previous = cell.s ?? ''
    let id = styleKeys.get(previous)
    if (!id) {
      id = `ribbon-numfmt-${Object.keys(styles).length}`
      while (id in styles) id += '-'
      styles[id] = { ...styles[previous], n: { pattern } }
      styleKeys.set(previous, id)
    }
    cell.s = id
  }
  const edits = diffToEdits(model, readBackSnapshot(data))
  const operations = [...staged, { kind: 'applyCellEdits', edits }]
  if (edits.length > 1_000_000 || operations.length + structuralCount + data.sheetOrder.length * 2 + 1 > 500 || new TextEncoder().encode(JSON.stringify(operations)).length > 10 * 1024 * 1024) throw new Error('数字格式超出本地草稿预算，请缩小选区或先保存当前修改')
}

export function createNumberFormatDialog(root: HTMLElement, options: {
  apply(target: NumberFormatTarget | undefined, pattern: string): void
  initial(): FormatValue<string>
}) {
  let target: NumberFormatTarget | undefined
  const modal = createModal({ root, label: '自定义数字格式', overlayClass: 'workbook-ribbon-format-overlay', cardClass: 'workbook-ribbon-format-dialog', closeLabel: '关闭数字格式', content: `
    <h2>自定义数字格式</h2><form class="workbook-ribbon-format-form">
      <label>格式代码<input class="workbook-ribbon-format-code" maxlength="255" autocomplete="off" spellcheck="false" aria-describedby="workbook-ribbon-format-help workbook-ribbon-format-error"></label>
      <p id="workbook-ribbon-format-help">例如：#,##0.000、0.00%、yyyy-mm-dd。仅修改数字显示，保留值和公式。</p>
      <p id="workbook-ribbon-format-error" class="workbook-ribbon-format-error" role="alert"></p>
      <div class="workbook-ribbon-format-actions"><button type="button" class="workbook-ribbon-format-cancel">取消</button><button type="submit" class="workbook-ribbon-format-apply">应用</button></div>
    </form>` })
  const input = modal.card.querySelector<HTMLInputElement>('input')!
  const error = modal.card.querySelector<HTMLElement>('[role="alert"]')!
  modal.card.querySelector('.workbook-ribbon-format-cancel')!.addEventListener('click', modal.close)
  modal.card.querySelector('form')!.addEventListener('submit', event => {
    event.preventDefault()
    try { options.apply(target, validateNumberFormat(input.value)); modal.close() }
    catch (cause) { error.textContent = (cause as Error).message; input.setAttribute('aria-invalid', 'true'); input.focus() }
  })
  return {
    open(captured: NumberFormatTarget | undefined) {
      target = captured
      const state = options.initial()
      input.value = state.kind === 'value' ? state.value : ''
      input.placeholder = state.kind === 'mixed' ? '选区包含多种数字格式' : state.kind === 'unavailable' ? state.reason : ''
      error.textContent = ''; input.removeAttribute('aria-invalid'); modal.open(input)
    },
    dispose: modal.remove,
  }
}
