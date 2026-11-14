import { createModal } from './modal'
import { buttonClasses } from './button'

export function openDocxColumnWidthDialog(root: HTMLElement, initialWidthTwips: number, apply: (widthTwips: number) => void) {
  const modal = createModal({ root, label: '列宽', cardClass: 'docx-table-property-dialog', closeLabel: '关闭列宽', onRequestClose: () => modal.remove(), content: `
    <h2>列宽</h2><form novalidate>
      <label>列宽（twip）<input aria-label="列宽（twip）" type="number" min="1" max="31680" step="1"></label>
      <p role="alert"></p><button type="button" data-action="cancel" class="${buttonClasses('secondary')}">取消</button>
      <button type="submit" class="${buttonClasses('primary')}">确定</button></form>` })
  const input = modal.card.querySelector<HTMLInputElement>('input')!
  input.value = String(initialWidthTwips)
  modal.card.querySelector('[data-action="cancel"]')!.addEventListener('click', modal.remove)
  modal.card.querySelector('form')!.addEventListener('submit', event => {
    event.preventDefault()
    try {
      const width = Number(input.value)
      if (!input.value.trim() || !Number.isSafeInteger(width) || width < 1 || width > 31680) throw new Error('列宽须为 1–31680 的整数 twip')
      apply(width); modal.remove()
    } catch (error) { modal.card.querySelector('[role="alert"]')!.textContent = error instanceof Error ? error.message : String(error) }
  })
  modal.open(input)
}
