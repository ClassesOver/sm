import { createModal } from './modal'
import { buttonClasses } from './button'

/** 空值或0为自动；指定高度保留来源exact/atLeast规则，不另造行高规则入口。 */
export function openDocxRowHeightDialog(root: HTMLElement, initialHeightTwips: number | null, maxHeightTwips: number, apply: (heightTwips: number | null) => void) {
  const modal = createModal({ root, label: '行高', cardClass: 'docx-table-property-dialog', closeLabel: '关闭行高', onRequestClose: () => modal.remove(), content: `
    <h2>行高</h2><form novalidate>
      <label>行高（twip）<input aria-label="行高（twip）" type="number" min="0" step="1" placeholder="自动"></label>
      <p>留空或输入 0 恢复自动行高；指定值按当前节正文高度截断。</p>
      <p role="alert"></p><button type="button" data-action="cancel" class="${buttonClasses('secondary')}">取消</button>
      <button type="submit" class="${buttonClasses('primary')}">确定</button></form>` })
  const input = modal.card.querySelector<HTMLInputElement>('input')!
  input.value = initialHeightTwips === null ? '' : String(initialHeightTwips)
  input.max = String(maxHeightTwips)
  modal.card.querySelector('[data-action="cancel"]')!.addEventListener('click', modal.remove)
  modal.card.querySelector('form')!.addEventListener('submit', event => {
    event.preventDefault()
    try {
      const empty = !input.value.trim(), height = Number(input.value)
      if (!empty && (!Number.isSafeInteger(height) || height < 0)) throw new Error('行高须为非负整数 twip，或留空恢复自动')
      apply(empty || height === 0 ? null : height); modal.remove()
    } catch (error) { modal.card.querySelector('[role="alert"]')!.textContent = error instanceof Error ? error.message : String(error) }
  })
  modal.open(input)
}
