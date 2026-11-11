import type { Editor } from '@tiptap/core'
import { DOCX_CELL_BORDER_MODES, DOCX_CELL_BORDER_STYLES, DOCX_CELL_BORDER_WIDTHS, type DocxCellBorderMode, type DocxCellBorderPen } from '../../../reporting/doc_engine/bridge/docx-cell-borders-spec'
import { applyDocxCellBorders, docxCellBordersUnavailable, type DocxCellBordersAnchor } from './docx-cell-borders'
export function createDocxCellBorderUiState() { return { lastMode: 'bottom' as DocxCellBorderMode, pen: { style: 'single', szEighths: 4, color: '000000' } as DocxCellBorderPen } }
const actions: Record<DocxCellBorderMode, string> = { bottom: 'bottom', top: 'top', left: 'left', right: 'right', none: 'none', all: 'all', outer: 'outer', inner: 'inner', insideH: 'inside-horizontal', insideV: 'inside-vertical', tl2br: 'diagonal-down', tr2bl: 'diagonal-up' }
const labels: Record<DocxCellBorderMode, string> = { bottom: '下框线', top: '上框线', left: '左框线', right: '右框线', none: '无框线', all: '所有框线', outer: '外侧框线', inner: '内侧框线', insideH: '内部横框线', insideV: '内部竖框线', tl2br: '下斜框线', tr2bl: '上斜框线' }
/** pen/最近命令保存在ribbon生命周期state中；改pen不产生文档事务。 */
export function createDocxCellBordersControls(editor: Editor, anchors: readonly DocxCellBordersAnchor[], state: ReturnType<typeof createDocxCellBorderUiState>, onError?: (error: unknown) => void) {
  const element = document.createElement('div'), panel = document.createElement('div')
  element.className = 'rb-split-wrap table-tool-borders'; element.style.cssText = 'display:flex;flex-wrap:wrap;align-content:flex-start;gap:4px;max-width:280px'; panel.className = 'layout-menu'; panel.hidden = true; panel.dataset.rbPanel = ''
  element.addEventListener('mousedown', event => event.preventDefault())
  const button = (action: string, label: string, run: () => void) => {
    const control = document.createElement('button'); control.type = 'button'; control.className = 'rb-icon docx-ribbon-command'; control.dataset.action = action; control.textContent = label; control.setAttribute('aria-label', label)
    control.addEventListener('click', run); return control
  }
  const apply = (mode: DocxCellBorderMode) => { state.lastMode = mode; try { applyDocxCellBorders(editor, mode, state.pen, anchors) } catch (error) { onError?.(error) }; panel.hidden = true }
  const last = button('table-border-apply-last', '应用最近边框', () => apply(state.lastMode)), menu = button('table-border-menu', '边框 ▾', () => { panel.hidden = !panel.hidden; menu.setAttribute('aria-expanded', String(!panel.hidden)) })
  menu.setAttribute('aria-expanded', 'false')
  for (const mode of DOCX_CELL_BORDER_MODES) panel.append(button(`table-border-${actions[mode]}`, labels[mode], () => apply(mode)))
  const style = document.createElement('select'); style.dataset.action = 'table-border-style'; style.setAttribute('aria-label', '边框样式')
  const glyphs = ['─────', '━━━━━', '═════', '≡≡≡≡≡', '┄┄┄┄┄', '╌╌╌╌╌', '─·─·─', '─··─··']
  DOCX_CELL_BORDER_STYLES.forEach((value, index) => { const option = document.createElement('option'); option.value = value; option.textContent = glyphs[index]!; style.append(option) }); style.value = state.pen.style
  style.addEventListener('change', () => { state.pen.style = style.value })
  const width = document.createElement('select'); width.dataset.action = 'table-border-width'; width.setAttribute('aria-label', '边框粗细')
  for (const value of DOCX_CELL_BORDER_WIDTHS) { const option = document.createElement('option'); option.value = String(value); option.textContent = `${value / 8} pt`; width.append(option) }; width.value = String(state.pen.szEighths)
  width.addEventListener('change', () => { state.pen.szEighths = Number(width.value) })
  const color = document.createElement('input'); color.type = 'color'; color.dataset.action = 'table-border-color'; color.setAttribute('aria-label', '边框颜色'); color.value = `#${state.pen.color}`
  color.addEventListener('input', () => { state.pen.color = color.value.slice(1).toUpperCase() })
  const automatic = button('table-border-color-auto', '自动', () => { state.pen.color = '000000'; color.value = '#000000' })
  element.append(last, menu, panel, style, width, color, automatic)
  const sync = () => {
    const reason = docxCellBordersUnavailable(editor, anchors)
    for (const control of element.querySelectorAll<HTMLButtonElement | HTMLSelectElement | HTMLInputElement>('button,select,input')) { const label = control.dataset.borderLabel ?? control.getAttribute('aria-label') ?? ''; control.dataset.borderLabel = label; control.disabled = reason !== null; control.title = reason ?? label; control.setAttribute('aria-label', reason ? `${label}，${reason}` : label) }
    last.title = reason ?? `应用最近边框：${labels[state.lastMode]}`
  }
  sync(); return { element, sync }
}
