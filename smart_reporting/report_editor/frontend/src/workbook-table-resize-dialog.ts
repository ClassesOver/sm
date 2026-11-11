import { createModal } from './modal'

export function createTableResizeDialog(root: HTMLElement, apply: (tableId: string, range: string) => void) {
  let target: { tableId: string; range: string } | undefined
  const modal = createModal({ root, label: '调整表格范围', closeLabel: '关闭调整表格范围',
    overlayClass: 'workbook-ribbon-format-overlay', cardClass: 'workbook-ribbon-format-dialog', content: `
    <h2>调整表格范围</h2><form class="workbook-ribbon-format-form">
      <label>新的表格范围<input type="text" aria-label="新的表格范围" autocomplete="off" aria-describedby="table-resize-help table-resize-error"></label>
      <p id="table-resize-help">输入包含表头与汇总行的单元格范围，例如 A1:D12。</p>
      <p id="table-resize-error" class="workbook-ribbon-format-error" role="alert"></p>
      <div class="workbook-ribbon-format-actions"><button type="button" data-action="cancel">取消</button><button type="submit">确定</button></div>
    </form>` })
  const input = modal.card.querySelector<HTMLInputElement>('input')!
  const error = modal.card.querySelector<HTMLElement>('[role="alert"]')!
  modal.card.querySelector('[data-action="cancel"]')!.addEventListener('click', modal.close)
  modal.card.querySelector('form')!.addEventListener('submit', event => {
    event.preventDefault()
    try {
      if (!target) throw new Error('请重新选择表格')
      apply(target.tableId, input.value)
      modal.close()
    } catch (cause) { error.textContent = (cause as Error).message; input.setAttribute('aria-invalid', 'true'); input.focus() }
  })
  return {
    open(captured: { tableId: string; range: string }) {
      target = { ...captured }; input.value = captured.range
      error.textContent = ''; input.removeAttribute('aria-invalid'); modal.open(input)
    },
    dispose: modal.remove,
  }
}
