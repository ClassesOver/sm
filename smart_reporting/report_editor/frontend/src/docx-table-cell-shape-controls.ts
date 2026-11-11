import { createModal } from './modal'
import { buttonClasses } from './button'

/** 与来源拆分对话框一致；输入只接受整数，不静默四舍五入。 */
export function openDocxCellSplitDialog(root: HTMLElement, apply: (options: { rows: number; columns: number; mergeFirst: boolean }) => void) {
  const modal = createModal({ root, label: '拆分单元格', closeLabel: '关闭拆分单元格', onRequestClose: () => modal.remove(), content: `
    <h2>拆分单元格</h2><form novalidate>
      <label>列数<input aria-label="列数" type="number" min="1" max="50" step="1" value="2"></label>
      <label>行数<input aria-label="行数" type="number" min="1" max="50" step="1" value="1"></label>
      <label><input type="checkbox" checked>拆分前合并单元格</label>
      <p role="alert"></p><button type="button" data-action="cancel" class="${buttonClasses('secondary')}">取消</button>
      <button type="submit" class="${buttonClasses('primary')}">确定</button></form>` })
  const rows = modal.card.querySelector<HTMLInputElement>('[aria-label="行数"]')!, columns = modal.card.querySelector<HTMLInputElement>('[aria-label="列数"]')!
  modal.card.querySelector('[data-action="cancel"]')!.addEventListener('click', modal.remove)
  modal.card.querySelector('form')!.addEventListener('submit', event => {
    event.preventDefault()
    try {
      const r = Number(rows.value), c = Number(columns.value)
      if (!rows.value.trim() || !columns.value.trim() || !Number.isInteger(r) || !Number.isInteger(c) || r < 1 || c < 1 || r > 50 || c > 50 || (r === 1 && c === 1)) throw new Error('行列数须为 1–50 的整数，且不能同时为 1')
      apply({ rows: r, columns: c, mergeFirst: modal.card.querySelector<HTMLInputElement>('[type="checkbox"]')!.checked })
      modal.remove()
    } catch (error) { modal.card.querySelector('[role="alert"]')!.textContent = error instanceof Error ? error.message : String(error) }
  })
  modal.open(columns)
}
