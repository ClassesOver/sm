import type { TableModel } from '@genoffice/docx-engine'
/** split a contenteditable cell back into paragraph strings */
export function tdParas(td: HTMLElement): string[] {
  // one rendered block per paragraph (below the exact-height / vertical-text
  // wrapper): read them structurally so empty paragraphs survive (innerText
  // drops trailing empty blocks) and NBSP stays document text
  const wrapper = td.children.length === 1 ? td.children[0] : null
  const host = wrapper?.matches('.cell-clip, .cell-vert') ? wrapper : td
  const blocks = Array.from(host.childNodes)
  if (blocks.length > 0 && blocks.every((n) => n instanceof HTMLElement && n.tagName === 'DIV')) {
    return blocks.map((block) => {
      const el = block as HTMLElement
      return (el.innerText ?? el.textContent ?? '').replace(/\n$/, '')
    })
  }
  const text = (td.innerText ?? td.textContent ?? '').replace(/\n+$/, '')
  const paras = text.split('\n')
  if (paras.length === 1 && paras[0].trim() === '') return ['']
  return paras
}

export const sameTableParagraphs = (left: string[], right: string[]) => left.length === right.length && left.every((text, index) => text === right[index])
export const sameTableModel = (left: unknown, right: unknown) => JSON.stringify(left) === JSON.stringify(right)

/** 输入岛全选限定到当前单元格，避免浏览器将选区扩大到外层编辑器。 */
export function selectTableInputContents(event: KeyboardEvent, dom: HTMLElement): void {
  if (!(event.ctrlKey || event.metaKey) || event.altKey || event.key.toLowerCase() !== 'a') return
  const cell = (event.target as HTMLElement | null)?.closest('td[contenteditable="true"]')
  if (!cell || cell.closest('.doc-nested-table') !== dom) return
  event.preventDefault(); event.stopPropagation()
  const range = document.createRange(); range.selectNodeContents(cell)
  const selection = window.getSelection(); selection?.removeAllRanges(); selection?.addRange(range)
}

export function tableInputCells(model: TableModel | null) {
  return model?.rows.flatMap((row, r) => row.flatMap((cell, c) => cell.vMerge === 'continue' ? [] : [{ cell, row: r, column: c }])) ?? []
}
