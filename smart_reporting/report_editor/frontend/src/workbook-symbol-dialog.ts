// 固定源 f8c17004 apps/sheets/src/renderer/SymbolDialog.tsx（Insert ▸ 符号）：分类网格，点击符号追加到活动单元格，
// 对话框保持打开以便连续插入，“关闭”退出。符号表与 appendSymbol 语义逐项照搬；分类名取固定源 i18n/dialogs/zh.ts。
import { createModal } from './modal'

/** 固定源 appendSymbol：追加到单元格现有内容；数字与布尔值转为文本（与 Excel 符号对话框一致）。 */
export function appendSymbol(existing: string | number | boolean | null | undefined, char: string): string {
  if (existing === null || existing === undefined || existing === '') return char
  return `${String(existing)}${char}`
}

export const WORKBOOK_SYMBOL_CATEGORIES: readonly { readonly label: string; readonly symbols: readonly string[] }[] = [
  { label: '货币/常用', symbols: ['€', '£', '¥', '¢', '₩', '₽', '₹', '©', '®', '™', '§', '¶', '†', '‡', '•', '…', '°', '‰', '№', '¿'] },
  { label: '数学', symbols: ['±', '×', '÷', '≠', '≈', '≤', '≥', '∞', '√', '∑', '∏', '∫', '∂', '∆', 'π', 'µ', '∈', '∉', '⊂', '⊃', '∩', '∪', '∀', '∃', '∅', '∝', '∴', '∵', '⊥', '∥'] },
  { label: '箭头', symbols: ['←', '→', '↑', '↓', '↔', '↕', '⇐', '⇒', '⇑', '⇓', '⇔', '↗', '↘', '↙', '↖', '↩', '↪', '⇄', '⇅', '↦'] },
  { label: '希腊字母', symbols: ['α', 'β', 'γ', 'δ', 'ε', 'ζ', 'η', 'θ', 'λ', 'μ', 'π', 'ρ', 'σ', 'τ', 'φ', 'χ', 'ψ', 'ω', 'Α', 'Β', 'Γ', 'Δ', 'Θ', 'Λ', 'Σ', 'Φ', 'Ω'] },
  { label: '几何/其它', symbols: ['★', '☆', '●', '○', '◆', '◇', '■', '□', '▲', '△', '▼', '▽', '✓', '✗', '☑', '☐', '♠', '♣', '♥', '♦', '♪', '♫', '☀', '☁', '☂', '☎'] },
]
const ALL_SYMBOLS = new Set(WORKBOOK_SYMBOL_CATEGORIES.flatMap(category => category.symbols))
let symbolDialogId = 0

/** 活动单元格的当前内容；公式与富文本单独标出。 */
export interface SymbolTargetCell { value: string | number | boolean | null | undefined; formula?: string | null; richText?: boolean }

/**
 * 计算追加后的单元格值。与固定源的差异：公式单元格与富文本单元格不追加——固定源以计算结果覆盖公式、
 * 以纯文本覆盖富文本格式，会静默丢失来源内容；这里拒绝并给出原因。结果须在 Excel 单元格 32767 字符上限内。
 */
export function symbolInsertion(cell: SymbolTargetCell, char: string): string {
  if (!ALL_SYMBOLS.has(char)) throw new Error('不支持的符号')
  if (cell.formula) throw new Error('活动单元格含公式；追加符号会覆盖公式，请选择普通单元格')
  if (cell.richText) throw new Error('活动单元格含富文本格式；追加符号会丢失分段格式，请选择普通单元格')
  const next = appendSymbol(cell.value, char)
  if (next.length > 32767) throw new Error('单元格文本超过 32767 个字符上限')
  return next
}

export function createWorkbookSymbolDialog(root: HTMLElement, insert: (char: string) => string) {
  let disposed = false, categoryIndex = 0
  const id = `workbook-symbol-${++symbolDialogId}`
  const modal = createModal({ root, label: '插入符号', closeLabel: '关闭插入符号', overlayClass: 'workbook-ribbon-format-overlay',
    cardClass: 'workbook-ribbon-format-dialog workbook-symbol-dialog', content: `
    <header><h2>插入符号</h2></header>
    <div class="workbook-symbol-body">
      <nav class="workbook-symbol-tabs" role="tablist" aria-label="符号分类"></nav>
      <div id="${id}-panel" role="tabpanel"><div class="workbook-symbol-grid" role="group" aria-label="符号"></div></div>
      <p role="region" aria-label="符号插入说明" tabindex="0">点击符号追加到活动单元格，可连续插入，完成后关闭。方向键选择符号，Enter 或空格插入；Tab 切换区域。</p>
      <p class="workbook-ribbon-format-error" role="alert" aria-label="符号插入错误" tabindex="0"></p>
      <p data-symbol-status role="status" aria-label="符号插入结果" tabindex="0"></p>
    </div>
    <footer class="workbook-ribbon-format-actions"><button type="button" data-symbol-close>关闭</button></footer>` })
  const tabs = modal.card.querySelector<HTMLElement>('.workbook-symbol-tabs')!, grid = modal.card.querySelector<HTMLElement>('.workbook-symbol-grid')!
  const panel = modal.card.querySelector<HTMLElement>('[role="tabpanel"]')!
  const error = modal.card.querySelector<HTMLElement>('[role="alert"]')!, status = modal.card.querySelector<HTMLElement>('[data-symbol-status]')!
  const render = () => {
    tabButtons.forEach((tab, index) => {
      tab.setAttribute('aria-selected', String(index === categoryIndex)); tab.tabIndex = index === categoryIndex ? 0 : -1
    })
    panel.setAttribute('aria-labelledby', tabButtons[categoryIndex]!.id)
    const buttons = WORKBOOK_SYMBOL_CATEGORIES[categoryIndex]!.symbols.map((symbol, index) => {
      const button = document.createElement('button'); button.type = 'button'; button.textContent = symbol; button.title = `插入 ${symbol}`
      button.setAttribute('aria-label', `插入 ${symbol}`); button.dataset.symbol = symbol; button.tabIndex = index === 0 ? 0 : -1
      button.addEventListener('focus', () => buttons.forEach(item => { item.tabIndex = item === button ? 0 : -1 }))
      button.addEventListener('keydown', event => {
        if (event.isComposing || event.keyCode === 229 || event.defaultPrevented) return
        if (event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) return
        const columns = getComputedStyle(grid).gridTemplateColumns.split(' ').filter(Boolean).length || 1
        let next = index
        if (event.key === 'ArrowLeft') next = Math.max(0, index - 1)
        else if (event.key === 'ArrowRight') next = Math.min(buttons.length - 1, index + 1)
        else if (event.key === 'ArrowUp') next = Math.max(0, index - columns)
        else if (event.key === 'ArrowDown') next = Math.min(buttons.length - 1, index + columns)
        else if (event.key === 'Home') next = 0
        else if (event.key === 'End') next = buttons.length - 1
        else return
        event.preventDefault(); buttons[next]!.focus()
      })
      button.addEventListener('click', () => {
        if (disposed) return
        error.textContent = ''
        try { status.textContent = insert(symbol) } catch (cause) { status.textContent = ''; error.textContent = (cause as Error).message }
      })
      return button
    })
    grid.replaceChildren(...buttons)
  }
  const tabButtons = WORKBOOK_SYMBOL_CATEGORIES.map((category, index) => {
    const tab = document.createElement('button'); tab.type = 'button'; tab.textContent = category.label; tab.setAttribute('role', 'tab')
    tab.id = `${id}-tab-${index}`; tab.setAttribute('aria-controls', panel.id); tab.dataset.symbolCategory = String(index)
    tab.addEventListener('click', () => { categoryIndex = index; render() })
    tab.addEventListener('keydown', event => {
      if (event.isComposing || event.keyCode === 229 || event.defaultPrevented) return
      if (event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) return
      if (event.key === 'ArrowLeft') categoryIndex = (index + WORKBOOK_SYMBOL_CATEGORIES.length - 1) % WORKBOOK_SYMBOL_CATEGORIES.length
      else if (event.key === 'ArrowRight') categoryIndex = (index + 1) % WORKBOOK_SYMBOL_CATEGORIES.length
      else if (event.key === 'Home') categoryIndex = 0
      else if (event.key === 'End') categoryIndex = WORKBOOK_SYMBOL_CATEGORIES.length - 1
      else return
      event.preventDefault(); render(); tabButtons[categoryIndex]!.focus()
    })
    return tab
  })
  tabs.append(...tabButtons)
  modal.card.querySelector('[data-symbol-close]')!.addEventListener('click', modal.close)
  return {
    open() { if (disposed) return; error.textContent = ''; status.textContent = ''; render(); modal.open(grid.querySelector('button') ?? undefined) },
    close() { modal.close() },
    dispose() { disposed = true; modal.remove() },
  }
}
