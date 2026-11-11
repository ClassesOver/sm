import { createModal } from './modal'

export function createTableCreateDialog(root: HTMLElement, create: (sheetId: string, range: string, hasHeaders: boolean) => void) {
  let target: { sheetId: string; range: string } | undefined
  const modal = createModal({ root, label: '创建表格', closeLabel: '关闭创建表格',
    overlayClass: 'workbook-ribbon-format-overlay', cardClass: 'workbook-ribbon-format-dialog', content: `
    <h2>创建表格</h2><form class="workbook-ribbon-format-form">
      <label>表格范围<input type="text" aria-label="表格范围" autocomplete="off" aria-describedby="table-create-help table-create-error"></label>
      <label><input type="checkbox" aria-label="表包含标题" checked>表包含标题</label>
      <p id="table-create-help">输入单元格范围，例如 A1:D12。未包含标题时会为数据添加标题行。</p>
      <p id="table-create-error" class="workbook-ribbon-format-error" role="alert"></p>
      <div class="workbook-ribbon-format-actions"><button type="button" data-action="cancel">取消</button><button type="submit">确定</button></div>
    </form>` })
  const input = modal.card.querySelector<HTMLInputElement>('[aria-label="表格范围"]')!
  const headers = modal.card.querySelector<HTMLInputElement>('[aria-label="表包含标题"]')!
  const error = modal.card.querySelector<HTMLElement>('[role="alert"]')!
  modal.card.querySelector('[data-action="cancel"]')!.addEventListener('click', modal.close)
  modal.card.querySelector('form')!.addEventListener('submit', event => {
    event.preventDefault()
    try {
      if (!target) throw new Error('请重新选择工作表')
      create(target.sheetId, input.value, headers.checked)
      modal.close()
    } catch (cause) { error.textContent = (cause as Error).message; input.setAttribute('aria-invalid', 'true'); input.focus() }
  })
  return {
    open(captured: { sheetId: string; range: string }) {
      target = { ...captured }; input.value = captured.range; headers.checked = true
      error.textContent = ''; input.removeAttribute('aria-invalid'); modal.open(input)
    },
    dispose: modal.remove,
  }
}
