import { createModal } from './modal'
import { parseConsolidateReference, type ConsolidateInput } from './workbook-consolidate'

type Target = { workbookId: string; sheetId: string; row: number; column: number }

/** 固定源ConsolidateDialog：引用列表、未添加输入及左列标签函数范围。 */
export function createConsolidateDialog(root: HTMLElement, apply: (target: Target, input: ConsolidateInput) => void) {
  let target: Target | undefined, references: string[] = []
  const modal = createModal({ root, label: '合并计算', closeLabel: '关闭合并计算',
    overlayClass: 'workbook-ribbon-format-overlay', cardClass: 'workbook-ribbon-format-dialog', content: `
    <h2>合并计算</h2><form class="workbook-ribbon-format-form">
      <label>函数<select aria-label="函数"></select></label>
      <label>引用位置<input aria-label="引用位置" autocomplete="off" placeholder="Sheet2!A1:C5"></label>
      <button type="button" data-action="add">添加</button>
      <ul aria-label="所有引用位置"></ul>
      <label><input type="checkbox" aria-label="使用左列标签">使用左列标签</label>
      <p data-target></p><p class="workbook-ribbon-format-error" role="alert"></p>
      <div class="workbook-ribbon-format-actions"><button type="button" data-action="cancel">取消</button><button type="submit">确定</button></div>
    </form>` })
  const fn = modal.card.querySelector<HTMLSelectElement>('select')!
  const reference = modal.card.querySelector<HTMLInputElement>('[aria-label="引用位置"]')!
  const leftLabels = modal.card.querySelector<HTMLInputElement>('[type="checkbox"]')!
  const list = modal.card.querySelector('ul')!
  const error = modal.card.querySelector<HTMLElement>('[role="alert"]')!
  const targetLabel = modal.card.querySelector<HTMLElement>('[data-target]')!
  const functions = [['sum', '求和'], ['count', '计数'], ['average', '平均值'], ['max', '最大值'], ['min', '最小值']]
  const refreshFunctions = () => {
    const selected = leftLabels.checked && ['max', 'min'].includes(fn.value) ? 'sum' : fn.value || 'sum'
    fn.replaceChildren(...functions.filter(([value]) => !leftLabels.checked || !['max', 'min'].includes(value!)).map(([value, label]) => {
      const option = document.createElement('option'); option.value = value!; option.textContent = label!; return option
    }))
    fn.value = selected
  }
  const refreshList = () => {
    list.replaceChildren(...references.map(value => {
      const item = document.createElement('li'); item.dataset.reference = value
      const text = document.createElement('code'); text.textContent = value
      const remove = document.createElement('button'); remove.type = 'button'; remove.textContent = '删除'; remove.setAttribute('aria-label', `删除引用 ${value}`)
      remove.addEventListener('click', () => { references = references.filter(entry => entry !== value); refreshList() })
      item.append(text, remove); return item
    }))
  }
  const add = () => {
    const pending = reference.value.trim()
    if (!pending) return
    if (!parseConsolidateReference(pending)) { error.textContent = `引用位置无效：${pending}`; return }
    if (!references.includes(pending)) references.push(pending)
    reference.value = ''; error.textContent = ''; refreshList()
  }
  modal.card.querySelector('[data-action="add"]')!.addEventListener('click', add)
  reference.addEventListener('keydown', event => { if (event.key === 'Enter') { event.preventDefault(); add() } })
  leftLabels.addEventListener('change', refreshFunctions)
  modal.card.querySelector('[data-action="cancel"]')!.addEventListener('click', modal.close)
  modal.card.querySelector('form')!.addEventListener('submit', event => {
    event.preventDefault()
    try {
      if (!target) throw new Error('请重新选择目标单元格')
      const all = [...references], pending = reference.value.trim()
      if (pending) {
        if (!parseConsolidateReference(pending)) throw new Error(`引用位置无效：${pending}`)
        if (!all.includes(pending)) all.push(pending)
      }
      if (!all.length) throw new Error('请至少添加一个引用位置')
      apply({ ...target }, { fn: fn.value as ConsolidateInput['fn'], references: all, leftLabels: leftLabels.checked })
      modal.close()
    } catch (cause) { error.textContent = (cause as Error).message }
  })
  return {
    open(captured: Target & { defaultReference: string; targetLabel: string }) {
      target = { workbookId: captured.workbookId, sheetId: captured.sheetId, row: captured.row, column: captured.column }
      references = []; leftLabels.checked = false; refreshFunctions(); fn.value = 'sum'; refreshList()
      reference.value = captured.defaultReference; targetLabel.textContent = `输出到 ${captured.targetLabel}，结果为引用来源的公式。`
      error.textContent = ''; modal.open(reference)
    },
    dispose: modal.remove,
  }
}
