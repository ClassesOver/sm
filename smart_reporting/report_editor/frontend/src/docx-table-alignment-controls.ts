import { createModal } from './modal'
import { buttonClasses } from './button'

export type DocxTableAlignment = 'left' | 'center' | 'right'
export function openDocxTableAlignmentDialog(root: HTMLElement, initial: DocxTableAlignment, floating: boolean, apply: (alignment: DocxTableAlignment) => void) {
  const modal = createModal({ root, label: '整表对齐', closeLabel: '关闭整表对齐', onRequestClose: () => modal.remove(), content: `
    <h2>整表对齐</h2><form><label>对齐方式<select aria-label="整表对齐方式"><option value="left">起始侧</option><option value="center">居中</option><option value="right">右对齐</option></select></label>
      <p>作用于整张表格。“起始侧”沿来源删除整表对齐声明，在从右到左的表格中位于右侧；“右对齐”沿来源保存 right 值。</p>
      ${floating ? '<p role="note">当前表格使用浮动或抑制浮动定位。浮动定位优先；对齐值保存后，当前位置仍保持原浮动定位。</p>' : ''}
      <p role="alert"></p><button type="button" data-action="cancel" class="${buttonClasses('secondary')}">取消</button><button type="submit" class="${buttonClasses('primary')}">确定</button></form>` })
  const select = modal.card.querySelector<HTMLSelectElement>('select')!; select.value = initial
  modal.card.querySelector('[data-action="cancel"]')!.addEventListener('click', modal.remove)
  modal.card.querySelector('form')!.addEventListener('submit', event => {
    event.preventDefault()
    try { if (!['left', 'center', 'right'].includes(select.value)) throw new Error('请选择有效的整表对齐方式'); apply(select.value as DocxTableAlignment); modal.remove() }
    catch (error) { modal.card.querySelector('[role="alert"]')!.textContent = error instanceof Error ? error.message : String(error) }
  })
  modal.open(select)
}
