import { createModal } from './modal'

type Target = { workbookId: string; sheetId: string }
type Input = { tableRange: string; rowInputCell: string | null; columnInputCell: string | null; onProgress(done: number, total: number): void }

/** 固定源 DataTableDialog：三字段、静态结果说明、运行进度与原地重试。 */
export function createDataTableDialog(root: HTMLElement, apply: (target: Target, input: Input) => Promise<{ cells: number }>) {
  let target: Target | undefined, busy = false, disposed = false
  const modal = createModal({ root, label: '模拟运算表', closeLabel: '关闭模拟运算表',
    overlayClass: 'workbook-ribbon-format-overlay', cardClass: 'workbook-ribbon-format-dialog',
    onRequestClose: () => { if (!busy) modal.close() }, content: `
    <h2>模拟运算表</h2><form class="workbook-ribbon-format-form">
      <label>表格区域<input aria-label="表格区域" autocomplete="off" placeholder="B4:D8"></label>
      <label>行输入单元格<input aria-label="行输入单元格" autocomplete="off" placeholder="B1"></label>
      <label>列输入单元格<input aria-label="列输入单元格" autocomplete="off" placeholder="A4"></label>
      <p>结果保存为静态值；输入值变化后需要重新运行。先在区域中填写公式及候选值，再指定行输入或列输入单元格。</p>
      <p role="status" aria-live="polite"></p><p class="workbook-ribbon-format-error" role="alert"></p>
      <div class="workbook-ribbon-format-actions"><button type="button" data-action="cancel">关闭</button><button type="submit">确定</button></div>
    </form>` })
  const [range, row, column] = [...modal.card.querySelectorAll<HTMLInputElement>('input')]
  const submit = modal.card.querySelector<HTMLButtonElement>('[type="submit"]')!
  const cancel = modal.card.querySelector<HTMLButtonElement>('[data-action="cancel"]')!
  const status = modal.card.querySelector<HTMLElement>('[role="status"]')!
  const error = modal.card.querySelector<HTMLElement>('[role="alert"]')!
  const fields = [range!, row!, column!]
  const valid = () => /^[A-Za-z]{1,3}\d{1,7}(:[A-Za-z]{1,3}\d{1,7})?$/.test(range!.value.trim())
    && [row!, column!].every(input => !input.value.trim() || /^[A-Za-z]{1,3}\d{1,7}$/.test(input.value.trim()))
    && !!(row!.value.trim() || column!.value.trim())
  const refresh = () => {
    modal.overlay.setAttribute('aria-busy', String(busy))
    fields.forEach(input => { input.disabled = busy })
    submit.disabled = busy || !valid(); cancel.disabled = busy
    if (modal.closeButton) modal.closeButton.disabled = busy
  }
  fields.forEach(input => input.addEventListener('input', refresh))
  cancel.addEventListener('click', () => { if (!busy) modal.close() })
  modal.card.querySelector('form')!.addEventListener('submit', async event => {
    event.preventDefault()
    if (busy || !target || !valid()) return
    busy = true; error.textContent = ''; status.textContent = '正在计算'; refresh()
    try {
      const result = await apply({ ...target }, {
        tableRange: range!.value.trim().toUpperCase(),
        rowInputCell: row!.value.trim().toUpperCase() || null,
        columnInputCell: column!.value.trim().toUpperCase() || null,
        onProgress(done, total) { if (!disposed) status.textContent = `正在计算 ${done} / ${total}` },
      })
      if (!disposed) status.textContent = `已生成 ${result.cells} 个结果（静态值），修改尚未保存。`
    } catch (cause) {
      if (!disposed) { error.textContent = (cause as Error).message; status.textContent = '' }
    } finally { busy = false; if (!disposed) refresh() }
  })
  return {
    open(captured: Target & { range: string }) {
      if (busy || disposed) return
      target = { workbookId: captured.workbookId, sheetId: captured.sheetId }
      range!.value = captured.range; row!.value = ''; column!.value = ''
      error.textContent = ''; status.textContent = ''; refresh(); modal.open(range)
    },
    dispose() { disposed = true; modal.remove() },
  }
}
