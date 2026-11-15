import type { Editor } from '@tiptap/core'
import { createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { flushSync } from 'react-dom'
import { renderToStaticMarkup } from 'react-dom/server'
import { DOCX_CELL_BORDER_MODES, type DocxCellBorderMode, type DocxCellBorderPen } from '../../../reporting/doc_engine/bridge/docx-cell-borders-spec'
import { applyDocxCellBorders, docxCellBordersUnavailable, type DocxCellBordersAnchor } from './docx-cell-borders'
import { DocxCellBorderPenSource } from './docx-cell-border-pen-source'
import { IconBorderAll, IconBorderBottom, IconBorderDiagonalDown, IconBorderDiagonalUp, IconBorderInner, IconBorderInsideH, IconBorderInsideV, IconBorderLeft, IconBorderNone, IconBorderOuter, IconBorderRight, IconBorderTop, IconCaret } from './vendor/genoffice-docs/apps/docs/src/renderer/components/icons'
import { installPopoverDismiss } from './vendor/genoffice-docs/packages/ui/src/popover-dismiss'
export function createDocxCellBorderUiState() { return { lastMode: 'bottom' as DocxCellBorderMode, pen: { style: 'single', szEighths: 4, color: '000000' } as DocxCellBorderPen } }
const actions: Record<DocxCellBorderMode, string> = { bottom: 'bottom', top: 'top', left: 'left', right: 'right', none: 'none', all: 'all', outer: 'outer', inner: 'inner', insideH: 'inside-horizontal', insideV: 'inside-vertical', tl2br: 'diagonal-down', tr2bl: 'diagonal-up' }
const labels: Record<DocxCellBorderMode, string> = { bottom: '下框线', top: '上框线', left: '左框线', right: '右框线', none: '无框线', all: '所有框线', outer: '外侧框线', inner: '内侧框线', insideH: '内部横框线', insideV: '内部竖框线', tl2br: '下斜框线', tr2bl: '上斜框线' }
const icons = {
  bottom: IconBorderBottom, top: IconBorderTop, left: IconBorderLeft, right: IconBorderRight,
  none: IconBorderNone, all: IconBorderAll, outer: IconBorderOuter, inner: IconBorderInner,
  insideH: IconBorderInsideH, insideV: IconBorderInsideV, tl2br: IconBorderDiagonalDown, tr2bl: IconBorderDiagonalUp,
} satisfies Record<DocxCellBorderMode, typeof IconCaret>
/** pen/最近命令保存在ribbon生命周期state中；改pen不产生文档事务。 */
export function createDocxCellBordersControls(editor: Editor, anchors: readonly DocxCellBordersAnchor[], state: ReturnType<typeof createDocxCellBorderUiState>, onError?: (error: unknown) => void, editable = true) {
  const element = document.createElement('div'), split = document.createElement('div'), panel = document.createElement('div')
  element.className = 'table-tool-group table-tool-borders'
  split.className = 'rb-split-wrap table-split'
  panel.className = 'layout-menu table-autofit-menu'; panel.hidden = true; panel.dataset.rbPanel = ''
  panel.setAttribute('role', 'menu'); panel.setAttribute('aria-label', '边框')
  split.addEventListener('mousedown', event => event.preventDefault())
  const button = (action: string, label: string, run: () => void) => {
    const control = document.createElement('button'); control.type = 'button'; control.className = 'rb-icon docx-ribbon-command'; control.dataset.action = action; control.textContent = label; control.setAttribute('aria-label', label)
    control.addEventListener('click', run); return control
  }
  let dismiss: (() => void) | undefined
  const close = () => {
    dismiss?.(); dismiss = undefined; panel.hidden = true
    menu.classList.remove('active')
    menu.setAttribute('aria-expanded', 'false')
  }
  const paint = (target: HTMLButtonElement, icon: typeof IconCaret, size: number, caption?: string) => {
    target.innerHTML = renderToStaticMarkup(createElement(icon, { size }))
    if (caption) { const text = document.createElement('span'); text.textContent = caption; target.append(text) }
  }
  const unavailable = () => editable ? docxCellBordersUnavailable(editor, anchors) : '当前文档只读'
  const apply = (mode: DocxCellBorderMode) => {
    close()
    if (unavailable()) return
    state.lastMode = mode
    try { applyDocxCellBorders(editor, mode, state.pen, anchors) } catch (error) { onError?.(error) }
    sync()
  }
  const last = button('table-border-apply-last', '应用最近边框', () => apply(state.lastMode))
  const menu = button('table-border-menu', '边框', () => { if (panel.hidden) open(); else close() })
  last.className = 'table-split-main'
  menu.className = 'table-split-caret'
  menu.setAttribute('aria-label', '边框'); menu.setAttribute('aria-expanded', 'false'); menu.setAttribute('aria-haspopup', 'menu')
  paint(menu, IconCaret, 12)
  const entries = DOCX_CELL_BORDER_MODES.map(mode => {
    const item = button(`table-border-${actions[mode]}`, labels[mode], () => { if (!panel.hidden) apply(mode) })
    item.className = ''
    item.setAttribute('role', 'menuitem'); item.tabIndex = -1
    paint(item, icons[mode], 17, labels[mode]); panel.append(item)
    return {mode, item}
  })
  const open = () => {
    if (menu.disabled) return
    panel.hidden = false; menu.classList.add('active'); menu.setAttribute('aria-expanded', 'true')
    dismiss = installPopoverDismiss(close, { inside: () => [split] })
    entries.find(entry => entry.mode === state.lastMode)?.item.focus({ preventScroll: true })
  }
  split.addEventListener('focusout', event => { if (!split.contains(event.relatedTarget as Node | null)) close() })
  split.addEventListener('keydown', event => {
    if (event.defaultPrevented || event.isComposing || event.keyCode === 229) return
    if (panel.hidden) {
      if (event.key === 'ArrowDown') { event.preventDefault(); open() }
      return
    }
    if (event.key === 'Escape') {
      event.preventDefault(); event.stopPropagation(); close(); menu.focus()
      return
    }
    const index = entries.findIndex(({item}) => item === document.activeElement)
    const next = event.key === 'ArrowDown' ? index + 1 : event.key === 'ArrowUp' ? index - 1 : null
    if (next !== null) { event.preventDefault(); entries[(next + entries.length) % entries.length]?.item.focus() }
  })
  const pen = document.createElement('div'); pen.className = 'table-border-opts'
  const penRoot = createRoot(pen)
  split.append(last, menu, panel); element.append(split, pen)
  const refreshPen = (reason: string | null) => flushSync(() => penRoot.render(createElement(DocxCellBorderPenSource, {
    key: reason ? 'locked' : 'editable',
    pen: state.pen,
    reason,
    onChange: next => {
      if (unavailable()) return
      state.pen = next
      refreshPen(null)
    },
  })))
  const sync = () => {
    const reason = unavailable()
    for (const control of split.querySelectorAll('button')) { const label = control.dataset.borderLabel ?? control.getAttribute('aria-label') ?? ''; control.dataset.borderLabel = label; control.disabled = reason !== null; control.title = reason ?? label; control.setAttribute('aria-label', reason ? `${label}，${reason}` : label) }
    last.title = reason ?? `应用最近边框：${labels[state.lastMode]}`
    paint(last, icons[state.lastMode], 18, '边框')
    for (const {mode,item} of entries) item.classList.toggle('active', mode === state.lastMode)
    if (reason) close()
    refreshPen(reason)
  }
  sync(); return { element, sync, dispose(){close();penRoot.unmount()} }
}
