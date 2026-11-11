import { createModal } from './modal'
import type { GoalSeekInput, GoalSeekResult } from './workbook-goal-seek'

type Target = { workbookId: string; sheetId: string }

/** 固定源GoalSeekDialog：求解后保留结果；运行中不提供取消。 */
export function createGoalSeekDialog(root: HTMLElement, solve: (target: Target, input: GoalSeekInput) => Promise<GoalSeekResult>) {
  let target: Target | undefined, busy = false, disposed = false
  const modal = createModal({ root, label: '单变量求解', closeLabel: '关闭单变量求解',
    overlayClass: 'workbook-ribbon-format-overlay', cardClass: 'workbook-ribbon-format-dialog',
    onRequestClose: () => { if (!busy) modal.close() }, content: `
    <h2>单变量求解</h2><form class="workbook-ribbon-format-form">
      <label>目标公式单元格<input aria-label="目标公式单元格" autocomplete="off" placeholder="B5"></label>
      <label>目标值<input aria-label="目标值" autocomplete="off" placeholder="0"></label>
      <label>可变单元格<input aria-label="可变单元格" autocomplete="off" placeholder="B2"></label>
      <p>调整一个输入值，使公式结果接近目标值。成功后保留求解值；未找到解时恢复原输入。</p>
      <p role="status" aria-live="polite"></p><p class="workbook-ribbon-format-error" role="alert"></p>
      <div class="workbook-ribbon-format-actions"><button type="button" data-action="cancel">关闭</button><button type="submit">求解</button></div>
    </form>` })
  const [setCell, toValue, byCell] = [...modal.card.querySelectorAll<HTMLInputElement>('input')]
  const submit = modal.card.querySelector<HTMLButtonElement>('[type="submit"]')!
  const close = modal.card.querySelector<HTMLButtonElement>('[data-action="cancel"]')!
  const status = modal.card.querySelector<HTMLElement>('[role="status"]')!
  const error = modal.card.querySelector<HTMLElement>('[role="alert"]')!
  const fields = [setCell!, toValue!, byCell!]
  const valid = () => [setCell!, byCell!].every(input => /^[A-Za-z]{1,3}\d{1,7}$/.test(input.value.trim())) && toValue!.value.trim() !== ''
  const refresh = () => {
    modal.overlay.setAttribute('aria-busy', String(busy))
    fields.forEach(input => { input.disabled = busy })
    submit.disabled = busy || !valid(); close.disabled = busy
    if (modal.closeButton) modal.closeButton.disabled = busy
  }
  fields.forEach(input => input.addEventListener('input', refresh))
  close.addEventListener('click', () => { if (!busy) modal.close() })
  modal.card.querySelector('form')!.addEventListener('submit', async event => {
    event.preventDefault()
    if (busy || !target || !valid()) return
    const goal = Number(toValue!.value)
    if (!Number.isFinite(goal)) { error.textContent = '目标值必须为有限数值'; return }
    busy = true; error.textContent = ''; status.textContent = '正在求解'; refresh()
    try {
      const result = await solve({ ...target }, { setCell: setCell!.value.trim().toUpperCase(), toValue: goal, byCell: byCell!.value.trim().toUpperCase() })
      const round = (value: number) => Number.isFinite(value) ? String(Number(value.toFixed(6))) : '—'
      if (!disposed) status.textContent = result.found
        ? `找到解：${round(result.solution)}，公式结果：${round(result.reached)}。`
        : `未找到解，已恢复原输入。最后尝试：${round(result.solution)}，公式结果：${round(result.reached)}。`
    } catch (cause) {
      if (!disposed) { error.textContent = (cause as Error).message; status.textContent = '' }
    } finally { busy = false; if (!disposed) refresh() }
  })
  return {
    open(captured: Target & { setCell: string }) {
      if (busy || disposed) return
      target = { workbookId: captured.workbookId, sheetId: captured.sheetId }
      setCell!.value = captured.setCell; toValue!.value = ''; byCell!.value = ''
      error.textContent = ''; status.textContent = ''; refresh(); modal.open(setCell)
    },
    dispose() { disposed = true; modal.remove() },
  }
}
