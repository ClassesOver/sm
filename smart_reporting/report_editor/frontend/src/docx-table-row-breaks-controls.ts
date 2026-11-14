import { createModal } from './modal'
import { buttonClasses } from './button'

/** 混合初值保持indeterminate，只有明确操作才提交布尔值。 */
export function openDocxRowBreaksDialog(root: HTMLElement, initial: boolean | null, top: number, bottom: number, apply: (allowBreak: boolean | undefined) => void) {
  const modal = createModal({ root, label: '行跨页', cardClass: 'docx-table-property-dialog', closeLabel: '关闭行跨页', onRequestClose: () => modal.remove(), content: `
    <h2>行跨页</h2><form><p>第 ${top + 1}${bottom > top + 1 ? `–${bottom}` : ''} 行</p>
      <label><input type="checkbox" data-action="allow-break">允许行内跨页</label>
      ${initial === null ? '<p>多个值：所选行的跨页设置不同，未操作时保持原值。</p>' : ''}
      <p>应用于所选完整行；跨行合并单元格按来源选择范围处理。超出整页的长行仍可能被分页器拆分。</p>
      <p role="alert"></p><button type="button" data-action="cancel" class="${buttonClasses('secondary')}">取消</button><button type="submit" class="${buttonClasses('primary')}">确定</button></form>` })
  const input = modal.card.querySelector<HTMLInputElement>('[data-action="allow-break"]')!
  input.checked = initial ?? false; input.indeterminate = initial === null; input.setAttribute('aria-checked', initial === null ? 'mixed' : String(initial))
  let touched = false
  input.addEventListener('change', () => { touched = true; input.indeterminate = false; input.setAttribute('aria-checked', String(input.checked)) })
  modal.card.querySelector('[data-action="cancel"]')!.addEventListener('click', modal.remove)
  modal.card.querySelector('form')!.addEventListener('submit', event => {
    event.preventDefault()
    try { apply(!touched || input.checked === initial ? undefined : input.checked); modal.remove() }
    catch (error) { modal.card.querySelector('[role="alert"]')!.textContent = error instanceof Error ? error.message : String(error) }
  })
  modal.open(input)
}

/** 边距不可用时仍允许进入独立行跨页区域，不为其开放边距写入。 */
export function openDocxRowPropertiesMenu(root: HTMLElement, marginsReason: string, rowReason: string | null, openRows: () => void, alignment?: { reason: string | null; open: () => void }) {
  const modal = createModal({ root, label: '表格属性选项', closeLabel: '关闭表格属性选项', onRequestClose: () => modal.remove(), content: `
    <h2>表格属性选项</h2><button type="button" data-action="margins" disabled>单元格边距</button><p data-margins-reason></p>
    <button type="button" data-action="row-breaks">行跨页</button><p data-row-reason></p>${alignment ? '<button type="button" data-action="table-alignment">整表对齐</button><p data-alignment-reason></p>' : ''}` })
  modal.card.querySelector('[data-margins-reason]')!.textContent = marginsReason
  modal.card.querySelector('[data-row-reason]')!.textContent = rowReason
  const button = modal.card.querySelector<HTMLButtonElement>('[data-action="row-breaks"]')!
  button.disabled = rowReason !== null
  button.addEventListener('click', () => { modal.remove(); openRows() })
  if (alignment) {
    const align = modal.card.querySelector<HTMLButtonElement>('[data-action="table-alignment"]')!
    align.disabled = alignment.reason !== null; modal.card.querySelector('[data-alignment-reason]')!.textContent = alignment.reason
    align.addEventListener('click', () => { modal.remove(); alignment.open() })
  }
  modal.open(button.disabled ? modal.card.querySelector<HTMLButtonElement>('[data-action="table-alignment"]') ?? button : button)
}
