import { createModal } from './modal'
import { parseConsolidateReference, type ConsolidateInput } from './workbook-consolidate'

type Target = { workbookId: string; sheetId: string; row: number; column: number }

/** 固定源ConsolidateDialog：引用列表、未添加输入及左列标签函数范围。 */
export function createConsolidateDialog(root: HTMLElement, apply: (target: Target, input: ConsolidateInput) => void) {
  let target: Target | undefined, references: string[] = []
  const modal = createModal({ root, label: '合并计算', closeLabel: '关闭合并计算',
    overlayClass: 'workbook-ribbon-format-overlay', cardClass: 'workbook-ribbon-format-dialog workbook-consolidate-dialog', content: `
    <header><h2>合并计算</h2></header><form class="workbook-ribbon-format-form"><div class="workbook-consolidate-body">
      <label>函数<select aria-label="函数"></select></label>
      <div class="workbook-consolidate-reference"><label>引用位置<input aria-label="引用位置" autocomplete="off" placeholder="Sheet2!A1:C5"></label><button type="button" data-action="add">添加</button></div>
      <div class="workbook-consolidate-list"><span>所有引用位置</span><ul aria-label="所有引用位置" tabindex="0"></ul></div>
      <label><input type="checkbox" aria-label="使用左列标签">使用左列标签</label>
      <p role="region" aria-label="合并计算说明" tabindex="0">按位置或左列标签汇总，结果保留为引用来源的公式。左列标签模式支持求和、计数和平均值；确认时会计入尚未添加的引用输入。</p>
      <p role="status" aria-live="polite" aria-label="合并计算引用状态" tabindex="0"></p><p data-target role="region" aria-label="合并计算范围" tabindex="0"></p><p class="workbook-ribbon-format-error" role="alert" aria-label="合并计算错误" tabindex="0"></p>
      </div><footer class="workbook-ribbon-format-actions"><button type="button" data-action="cancel">取消</button><button type="submit">确定</button></footer>
    </form>` })
  const fn = modal.card.querySelector<HTMLSelectElement>('select')!
  const reference = modal.card.querySelector<HTMLInputElement>('[aria-label="引用位置"]')!
  const leftLabels = modal.card.querySelector<HTMLInputElement>('[type="checkbox"]')!
  const list = modal.card.querySelector('ul')!
  const error = modal.card.querySelector<HTMLElement>('[role="alert"]')!
  const status = modal.card.querySelector<HTMLElement>('[role="status"]')!
  const showError = (message: string) => { error.textContent = message; error.scrollIntoView?.({ block: 'nearest' }) }
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
    list.replaceChildren(...references.map((value, index) => {
      const item = document.createElement('li'); item.dataset.reference = value
      const text = document.createElement('code'); text.textContent = value
      const remove = document.createElement('button'); remove.type = 'button'; remove.textContent = '删除'; remove.setAttribute('aria-label', `删除引用 ${value}`)
      remove.addEventListener('click', () => {
        references = references.filter(entry => entry !== value); refreshList()
        const buttons = list.querySelectorAll<HTMLButtonElement>('button')
        ;(buttons[Math.min(index, buttons.length - 1)] ?? reference).focus()
      })
      item.append(text, remove); return item
    }))
    status.textContent = `已添加 ${references.length} 个引用。`
  }
  const add = () => {
    const pending = reference.value.trim()
    if (!pending) return
    if (!parseConsolidateReference(pending)) { showError(`引用位置无效：${pending}`); return }
    if (!references.includes(pending)) references.push(pending)
    reference.value = ''; error.textContent = ''; refreshList(); list.scrollTop = list.scrollHeight
  }
  modal.card.querySelector('[data-action="add"]')!.addEventListener('click', add)
  reference.addEventListener('keydown', event => { if (event.isComposing || event.keyCode === 229 || event.defaultPrevented) return; if (event.key === 'Enter') { event.preventDefault(); add() } })
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
    } catch (cause) { showError((cause as Error).message) }
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
