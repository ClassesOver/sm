/**
 * Data ▸ Sort ▸ Custom Sort (fixed source GenOffice f8c17004 `ExcelShell.tsx`
 * SortDialog 1452-1530, `App.tsx` sortColumnOptions 5476-5485 and
 * `ribbon-actions.ts` 'sort-custom' 1978-2003): up to three levels (column +
 * ascending/descending, "then by" may be none) and a "my data has headers"
 * flag (default on), run as the official `sheet.command.sort-range` over the
 * selection captured when the dialog opened. Values, styles and notes move
 * in-grid; the save diff picks the result up like the one-click sort.
 */
import { formatAddress } from '@sheets-web/xlsx-engine'
import { createModal } from './modal'

export const NO_SORT_LEVEL = -1
export const SORT_LEVELS = 3
/** Fixed source caps the column choices at 26. */
export const SORT_COLUMN_LIMIT = 26
export interface SortRange { startRow: number; endRow: number; startColumn: number; endColumn: number }
export interface SortLevel { colIndex: number; order: 'asc' | 'desc' }

export function sortColumnOptions(range: SortRange): { label: string; colIndex: number }[] {
  const width = Math.min(range.endColumn - range.startColumn + 1, SORT_COLUMN_LIMIT)
  return Array.from({ length: width }, (_, offset) => ({ label: `列 ${formatAddress(0, range.startColumn + offset).replace(/\d+$/, '')}`, colIndex: range.startColumn + offset }))
}

/** Levels → official orderRules; empty levels drop, a column used twice keeps its first level. */
export function sortOrderRules(range: SortRange, levels: readonly SortLevel[]): { colIndex: number; type: 'asc' | 'desc' }[] {
  const rules: { colIndex: number; type: 'asc' | 'desc' }[] = []
  for (const level of levels) {
    if (level.colIndex === NO_SORT_LEVEL) continue
    if (level.colIndex < range.startColumn || level.colIndex > range.endColumn) throw new Error('排序列不在所选区域内')
    if (!rules.some(rule => rule.colIndex === level.colIndex)) rules.push({ colIndex: level.colIndex, type: level.order })
  }
  if (!rules.length) throw new Error('请至少选择一个排序依据')
  return rules
}

export function createSortDialog(root: HTMLElement, apply: (range: SortRange, hasTitle: boolean, rules: { colIndex: number; type: 'asc' | 'desc' }[]) => void) {
  let range: SortRange | undefined
  const levels = Array.from({ length: SORT_LEVELS }, (_, index) => `
    <div class="workbook-ribbon-sort-level" data-sort-level="${index}">
      <span>${index === 0 ? '主要关键字' : '次要关键字'}</span>
      <select class="workbook-ribbon-select" data-sort-column aria-label="${index === 0 ? '排序依据' : `然后依据 ${index}`}"></select>
      <select class="workbook-ribbon-select" data-sort-order aria-label="次序"><option value="asc">升序</option><option value="desc">降序</option></select>
    </div>`).join('')
  const modal = createModal({ root, label: '自定义排序', overlayClass: 'workbook-ribbon-format-overlay', cardClass: 'workbook-ribbon-format-dialog workbook-ribbon-sort-dialog', closeLabel: '关闭', content: `
    <h2>排序</h2><form class="workbook-ribbon-format-form">
      <label class="workbook-ribbon-sort-header"><input type="checkbox" data-sort-header checked>数据包含标题</label>
      ${levels}
      <p class="workbook-ribbon-format-error" role="alert"></p>
      <div class="workbook-ribbon-format-actions"><button type="button" class="workbook-ribbon-format-cancel">取消</button><button type="submit" class="workbook-ribbon-format-apply">确定</button></div>
    </form>` })
  const error = modal.card.querySelector<HTMLElement>('[role="alert"]')!
  const header = modal.card.querySelector<HTMLInputElement>('[data-sort-header]')!
  const rows = [...modal.card.querySelectorAll<HTMLElement>('[data-sort-level]')]
  modal.card.querySelector('.workbook-ribbon-format-cancel')!.addEventListener('click', modal.close)
  modal.card.querySelector('form')!.addEventListener('submit', event => {
    event.preventDefault()
    try {
      if (!range) throw new Error('请先选择要排序的区域')
      const chosen = rows.map(row => ({
        colIndex: Number(row.querySelector<HTMLSelectElement>('[data-sort-column]')!.value),
        order: row.querySelector<HTMLSelectElement>('[data-sort-order]')!.value as 'asc' | 'desc',
      }))
      apply(range, header.checked, sortOrderRules(range, chosen)); modal.close()
    } catch (cause) { error.textContent = (cause as Error).message }
  })
  return {
    open(captured: SortRange) {
      if (captured.endRow - captured.startRow < 1) throw new Error('请选择至少两行数据后再排序')
      range = captured
      const columns = sortColumnOptions(captured)
      rows.forEach((row, index) => {
        const select = row.querySelector<HTMLSelectElement>('[data-sort-column]')!
        select.replaceChildren(...[...(index > 0 ? [{ label: '（无）', colIndex: NO_SORT_LEVEL }] : []), ...columns].map(column => {
          const option = document.createElement('option'); option.value = String(column.colIndex); option.textContent = column.label; return option
        }))
        select.value = String(index === 0 ? columns[0]!.colIndex : NO_SORT_LEVEL)
        row.querySelector<HTMLSelectElement>('[data-sort-order]')!.value = 'asc'
      })
      header.checked = true; error.textContent = ''
      modal.open(rows[0]!.querySelector('select')!)
    },
    dispose: modal.remove,
  }
}
