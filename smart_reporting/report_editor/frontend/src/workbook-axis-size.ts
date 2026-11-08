import { createModal } from './modal'
import { columnWidthToPixels, rowHeightToPixels } from './workbook-vendor/core/univer-data'

/**
 * Home ▸ Cells ▸ Format ▸ Row Height… / Column Width…, following GenOffice
 * f8c17004 ExcelShell.tsx AxisSizeDialog and ribbon-actions.ts:1400-1423: a
 * numeric value in file units (points for rows, character widths for columns,
 * a decimal comma accepted) applied to every row/column of the selection
 * through the worksheet facade (setRowHeightsForced / setColumnWidths).
 *
 * Local units/limits: pixels use the same conversions the grid load and the
 * save-side geometry diff use (univer-data rowHeightToPixels /
 * columnWidthToPixels), so a value round-trips to the file. Rows accept
 * 1–409 pt (the engine's applyRowHeights cap; the source allows 409.5) and
 * columns 1–255 characters (the save diff floors widths at 1 character);
 * 0, which Excel uses to hide, stays with the hide commands.
 */
export type SizeAxis = 'row' | 'col'
export const AXIS_LIMITS: Record<SizeAxis, { min: number; max: number; unit: string; label: string }> = {
  row: { min: 1, max: 409, unit: '磅', label: '行高' },
  col: { min: 1, max: 255, unit: '字符', label: '列宽' },
}

export function parseAxisSize(axis: SizeAxis, raw: string): number {
  const limits = AXIS_LIMITS[axis]
  const text = raw.trim().replace(',', '.')
  const value = Number(text)
  if (text === '' || !Number.isFinite(value) || value < limits.min || value > limits.max) throw new Error(`${limits.label}须在 ${limits.min}–${limits.max} ${limits.unit}之间`)
  return Math.round(value * 100) / 100
}

type AxisSheet = {
  getSheetId?(): string
  getSelection(): { getActiveRange(): { getRow(): number; getColumn(): number; getHeight(): number; getWidth(): number } | null } | null
  setRowHeightsForced(startRow: number, numRows: number, height: number): unknown
  setColumnWidths(startColumn: number, numColumns: number, width: number): unknown
}
type AxisWorkbook = { getActiveSheet(): AxisSheet | null; getSheetBySheetId?(id: string): AxisSheet | null }
export interface AxisTarget { axis: SizeAxis; sheetId?: string; start: number; count: number }

export function captureAxisTarget(workbook: AxisWorkbook | null, axis: SizeAxis): AxisTarget | undefined {
  const sheet = workbook?.getActiveSheet(), range = sheet?.getSelection()?.getActiveRange()
  if (!sheet || !range) return undefined
  const start = axis === 'row' ? range.getRow() : range.getColumn()
  const count = axis === 'row' ? range.getHeight() : range.getWidth()
  if (!Number.isSafeInteger(start) || !Number.isSafeInteger(count) || start < 0 || count < 1) return undefined
  return { axis, sheetId: sheet.getSheetId?.(), start, count }
}

export function applyAxisSize(target: AxisTarget | undefined, workbook: AxisWorkbook | null, value: number, editable: boolean): void {
  if (!editable) throw new Error('当前工作簿不可编辑或正在保存')
  const sheet = target?.sheetId && workbook?.getSheetBySheetId ? workbook.getSheetBySheetId(target.sheetId) : workbook?.getActiveSheet()
  if (!target || !sheet) throw new Error('原选区已失效，请重新选择单元格或区域')
  parseAxisSize(target.axis, String(value))
  if (target.axis === 'row') sheet.setRowHeightsForced(target.start, target.count, rowHeightToPixels(value))
  else sheet.setColumnWidths(target.start, target.count, columnWidthToPixels(value))
}

export function createAxisSizeDialog(root: HTMLElement, apply: (target: AxisTarget, value: number) => void) {
  let target: AxisTarget | undefined
  const modal = createModal({ root, label: '行高或列宽', overlayClass: 'workbook-ribbon-format-overlay', cardClass: 'workbook-ribbon-format-dialog workbook-ribbon-axis-dialog', closeLabel: '关闭', content: `
    <h2 class="workbook-ribbon-axis-title"></h2><form class="workbook-ribbon-format-form">
      <label><span class="workbook-ribbon-axis-label"></span><input class="workbook-ribbon-axis-value" type="text" inputmode="decimal" autocomplete="off" aria-describedby="workbook-ribbon-axis-help workbook-ribbon-axis-error"></label>
      <p id="workbook-ribbon-axis-help" class="workbook-ribbon-axis-help"></p>
      <p id="workbook-ribbon-axis-error" class="workbook-ribbon-format-error" role="alert"></p>
      <div class="workbook-ribbon-format-actions"><button type="button" class="workbook-ribbon-format-cancel">取消</button><button type="submit" class="workbook-ribbon-format-apply">确定</button></div>
    </form>` })
  const input = modal.card.querySelector<HTMLInputElement>('input')!
  const error = modal.card.querySelector<HTMLElement>('[role="alert"]')!
  modal.card.querySelector('.workbook-ribbon-format-cancel')!.addEventListener('click', modal.close)
  modal.card.querySelector('form')!.addEventListener('submit', event => {
    event.preventDefault()
    try {
      if (!target) throw new Error('请先选择单元格或区域')
      apply(target, parseAxisSize(target.axis, input.value)); modal.close()
    } catch (cause) { error.textContent = (cause as Error).message; input.setAttribute('aria-invalid', 'true'); input.focus() }
  })
  return {
    open(captured: AxisTarget) {
      target = captured
      const limits = AXIS_LIMITS[captured.axis]
      modal.card.querySelector('.workbook-ribbon-axis-title')!.textContent = limits.label
      modal.card.querySelector('.workbook-ribbon-axis-label')!.textContent = `${limits.label}（${limits.unit}）`
      modal.card.querySelector('.workbook-ribbon-axis-help')!.textContent = `应用到所选的 ${captured.count} ${captured.axis === 'row' ? '行' : '列'}；范围 ${limits.min}–${limits.max} ${limits.unit}。`
      input.value = ''; error.textContent = ''; input.removeAttribute('aria-invalid'); modal.open(input)
    },
    dispose: modal.remove,
  }
}
