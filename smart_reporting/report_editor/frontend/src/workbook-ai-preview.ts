import { buttonClasses } from './button'
import type { WorkbookProposal } from './workbook-draft'

const operationLabels: Record<string, string> = {
  applyCellEdits: '单元格内容与样式', applySheetMerges: '合并布局', applySheetEdits: '工作表结构',
  applyRowColumnOps: '行列结构', applyDvRules: '数据验证', applyCfRules: '条件格式', applySheetNotes: '批注',
  addPivot: '新增透视表', applyColumnWidths: '列宽', applyRowHeights: '行高', applyPageSetups: '打印设置',
  applyTableAdditions: '新增数据表', refreshPivotCaches: '刷新透视缓存', applyPivotLayoutExpansions: '透视布局',
  expandPivotOutputs: '透视输出', applyDefinedNames: '命名区域', protectSheet: '工作表保护',
  protectWorkbookStructure: '工作簿结构保护', setThemePart: '主题', sortRange: '排序',
}
function cellAddress(row: number, column: number) {
  let letters = ''
  for (let value = column + 1; value > 0; value = Math.floor((value - 1) / 26)) letters = String.fromCharCode(65 + (value - 1) % 26) + letters
  return `${letters}${row + 1}`
}
export function renderWorkbookProposal(proposal: WorkbookProposal, target: HTMLElement) {
  const summary = document.createElement('p'); summary.textContent = proposal.summary
  const changes = document.createElement('ul'); changes.className = 'ai-proposal-changes'
  for (const operation of proposal.operations) {
    const item = document.createElement('li')
    const heading = document.createElement('h4')
    heading.textContent = `${operationLabels[String(operation.kind)] ?? '工作簿修改'}${typeof operation.sheetName === 'string' ? ` · ${operation.sheetName}` : ''}`
    item.append(heading)
    if (operation.kind === 'applyCellEdits' && Array.isArray(operation.edits)) {
      const edits = operation.edits
      const table = document.createElement('table'); table.className = 'ai-workbook-changes'
      const caption = document.createElement('caption'); caption.textContent = `涉及 ${edits.length} 个单元格`
      const head = document.createElement('thead'); head.innerHTML = '<tr><th scope="col">位置</th><th scope="col">修改内容</th></tr>'
      const body = document.createElement('tbody')
      let page = 0
      const pageSize = 50
      const pager = document.createElement('div'); pager.className = 'ai-workbook-pagination'
      const previous = document.createElement('button'); previous.type = 'button'; previous.textContent = '上一页'
      const next = document.createElement('button'); next.type = 'button'; next.textContent = '下一页'
      previous.className = next.className = buttonClasses('quiet')
      const status = document.createElement('span'); status.setAttribute('role', 'status'); status.setAttribute('aria-live', 'polite')
      pager.append(previous, status, next); pager.hidden = edits.length <= pageSize
      const renderPage = () => {
        body.replaceChildren()
        for (const edit of edits.slice(page * pageSize, (page + 1) * pageSize)) {
          const row = document.createElement('tr'); const address = document.createElement('td'); const value = document.createElement('td')
          address.textContent = `${edit.sheetName} · ${cellAddress(edit.row, edit.column)}`
          const fields: string[] = []
          if (edit.writeValue) fields.push(edit.cell?.formula ? `公式：${edit.cell.formula}` : `值：${edit.cell?.value ?? '清空'}`)
          if (edit.styleReset) fields.push('重置样式')
          if (edit.style) fields.push('更新单元格样式')
          if (edit.rich) fields.push('更新富文本格式')
          value.textContent = fields.join('；') || '更新单元格'
          row.append(address, value); body.append(row)
        }
        previous.disabled = page === 0; next.disabled = (page + 1) * pageSize >= edits.length
        status.textContent = `第 ${page + 1} / ${Math.max(1, Math.ceil(edits.length / pageSize))} 页 · ${edits.length} 项`
      }
      previous.addEventListener('click', () => { if (page > 0) { --page; renderPage() } })
      next.addEventListener('click', () => { if (!next.disabled) { ++page; renderPage() } })
      renderPage()
      const scroll = document.createElement('div'); scroll.className = 'ai-workbook-table-scroll'; scroll.tabIndex = 0; scroll.setAttribute('role', 'region'); scroll.setAttribute('aria-label', '单元格修改明细')
      table.append(caption, head, body); scroll.append(table); item.append(scroll, pager)
    }
    // Preserve the old complete operation view, including unsupported preview fields.
    const details = document.createElement('details'); const label = document.createElement('summary'); label.textContent = '完整修改明细'
    const raw = document.createElement('pre')
    details.addEventListener('toggle', () => { if (details.open && !raw.textContent) raw.textContent = JSON.stringify(operation, null, 2) })
    details.append(label, raw); item.append(details); changes.append(item)
  }
  if (!proposal.operations.length) { const note = document.createElement('li'); note.textContent = '没有需要应用的变化'; changes.append(note) }
  target.replaceChildren(summary, changes)
}
