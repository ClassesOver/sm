import type { ProtectedRangeState } from '@sheets-web/xlsx-engine/protection'
import type { EditableRange } from './workbook-editable-ranges'
import { createModal } from './modal'

type Input = { sheetName: string; ranges: readonly EditableRange[]; selection?: string; protected?: boolean }

/** 只在确认时提交定义，取消不会改变文件或草稿。 */
export function createEditableRangesDialog(root: HTMLElement, apply: (sheetName: string, ranges: ProtectedRangeState[]) => Promise<void>) {
  let input: Input, busy = false, readonly = false
  const modal = createModal({ root, label: '允许用户编辑区域', closeLabel: '关闭允许用户编辑区域', variant: 'wide', overlayClass: 'workbook-ribbon-format-overlay', cardClass: 'workbook-ribbon-format-dialog', onRequestClose: () => { if (!busy) modal.close() }, content:
    '<h2>允许用户编辑区域</h2><p>定义不带密码的允许编辑区域；启用工作表保护后，区域内可编辑值和公式。区域引用可用空格分隔多个范围，例如 B2:C4 E2:E4。</p><form class="workbook-ribbon-format-form"><div data-ranges></div><button type="button" data-action="add">新增区域</button><p role="alert" class="workbook-ribbon-format-error"></p><div class="workbook-ribbon-format-actions"><button type="button" data-action="cancel">取消</button><button type="submit" class="workbook-ribbon-format-apply">确定</button></div></form>' })
  const rows = modal.card.querySelector<HTMLElement>('[data-ranges]')!, error = modal.card.querySelector<HTMLElement>('[role="alert"]')!
  const controls = () => modal.card.querySelectorAll<HTMLInputElement | HTMLButtonElement>('input,button')
  const renumber = () => rows.querySelectorAll<HTMLElement>('[data-range]').forEach((row, index) => {
    row.querySelector<HTMLInputElement>('[data-name]')!.setAttribute('aria-label', `区域名称 ${index + 1}`)
    row.querySelector<HTMLInputElement>('[data-ref]')!.setAttribute('aria-label', `区域引用 ${index + 1}`)
  })
  const add = (range: ProtectedRangeState) => {
    const row = document.createElement('div');row.dataset.range = ''
    const nameLabel = document.createElement('label');nameLabel.textContent = '名称'
    const name = document.createElement('input');name.dataset.name = '';name.value = range.name;nameLabel.append(name)
    const refLabel = document.createElement('label');refLabel.textContent = '单元格区域'
    const ref = document.createElement('input');ref.dataset.ref = '';ref.value = range.sqref;refLabel.append(ref)
    const remove = document.createElement('button');remove.type = 'button';remove.textContent = '删除区域'
    remove.addEventListener('click', () => { if (!busy && !readonly) { row.remove();renumber() } })
    row.append(nameLabel, refLabel, remove);rows.append(row);renumber()
  }
  modal.card.querySelector('[data-action="add"]')!.addEventListener('click', () => { if (!busy && !readonly) add({ name: '', sqref: input.selection ?? 'A1' }) })
  modal.card.querySelector('[data-action="cancel"]')!.addEventListener('click', () => { if (!busy) modal.close() })
  modal.card.querySelector('form')!.addEventListener('submit', event => {
    event.preventDefault();if (busy || readonly) return
    const ranges = [...rows.querySelectorAll<HTMLElement>('[data-range]')].map(row => ({ name: row.querySelector<HTMLInputElement>('[data-name]')!.value.trim(), sqref: row.querySelector<HTMLInputElement>('[data-ref]')!.value.trim() }))
    busy = true;controls().forEach(control => { control.disabled = true });error.textContent = ''
    void apply(input.sheetName, ranges).then(modal.close, cause => { error.textContent = (cause as Error).message }).finally(() => { busy = false;controls().forEach(control => { control.disabled = false }) })
  })
  return {
    open(value: Input) {
      if (busy) return
      input = value;rows.replaceChildren();value.ranges.forEach(add)
      const reason = value.protected ? '请先撤销工作表保护，再定义允许编辑区域。' : value.ranges.find(range => range.readonlyReason)?.readonlyReason
      readonly = Boolean(reason);error.textContent = reason ?? ''
      controls().forEach(control => { control.disabled = readonly })
      modal.closeButton!.disabled = false
      modal.card.querySelector<HTMLButtonElement>('[data-action="cancel"]')!.disabled = false
      modal.open(rows.querySelector('input'))
    },
    dispose: modal.remove,
  }
}
