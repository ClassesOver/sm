import { createElement } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { flushSync } from 'react-dom'
import type { Editor } from '@tiptap/core'
import type { SectionSettings, TabStop } from '@genoffice/docx-engine'
import { Ruler, rulerDims } from './vendor/genoffice-docs/apps/docs/src/renderer/components/Ruler'
import './docx-ruler.css'

export type RulerWriteKind = 'tabs' | 'indentLeft' | 'indentFirstLine' | 'indentHanging' | 'indentRight' | 'indents' | 'margins'
type Options = {
  editor: Editor
  container: HTMLElement
  getSection(): SectionSettings
  getZoom?(): number
  extendedIndents?: boolean
  editableTabs?: boolean
  onTabStopsChange?(stops: TabStop[] | null): void
  onIndentsChange?(attrs: { indentRight?: number; indentLeft?: number; indentFirstLine?: number }): void
  onMarginsChange?(margins: { left: number; right: number }): void
  readOnlyReason?(kind: RulerWriteKind): string | null
  onError?(error: unknown): void
}
const unsupported: Partial<Record<RulerWriteKind, string>> = {
  tabs: '制表位尚未接入可靠的 DOCX 保存协议，当前仅显示',
  indentLeft: '左缩进保存仅支持固定步长，当前源尺规拖动暂不可用',
  indentFirstLine: '首行缩进尚未接入 DOCX 保存协议，当前仅显示',
  indentHanging: '悬挂缩进尚未接入 DOCX 保存协议，当前仅显示',
}

export function createDocxRuler(options: Options) {
  const { editor, container } = options
  let visible = false, disposed = false, root: Root | null = null, host: HTMLDivElement | null = null
  type Drag = { doc: typeof editor.state.doc; selection: typeof editor.state.selection; section: string; zoom: number; kind: RulerWriteKind; cancelled: boolean }
  let drag: Drag | null = null, renderVersion = 0
  const zoom = () => {
    const value = options.getZoom?.() ?? Number(editor.view.dom.style.zoom || 1)
    return Number.isFinite(value) && value > 0 ? value : 1
  }
  const reason = (kind: RulerWriteKind = 'indents'): string | null => {
    if (disposed || editor.isDestroyed) return '标尺已关闭'
    if (!editor.isEditable) return '当前文档为只读，标尺仅显示'
    const blocked = options.readOnlyReason?.(kind)
    if (blocked) return blocked
    if (unsupported[kind] && !(kind === 'tabs' && options.editableTabs || options.extendedIndents && ['indentLeft', 'indentFirstLine', 'indentHanging'].includes(kind))) return unsupported[kind]!
    if (kind === 'tabs' && zoom() !== 1) return '制表位鼠标坐标暂仅支持100%缩放，请先恢复100%'
    if (kind === 'margins') return options.onMarginsChange ? null : '当前文档不支持页边距写回'
    const { $from, $to } = editor.state.selection
    if ($from.depth !== 1 || $to.depth !== 1 || $from.parent !== $to.parent || !['docParagraph', 'docHeading'].includes($from.parent.type.name)) return '请选择单个原有正文段落或标题，嵌套内容不支持标尺写回'
    if (!Number.isInteger($from.parent.attrs.docxIndex) || $from.parent.attrs.docxIndex < 0) return '新增段落尚无来源锚点，不能通过标尺写回'
    if (kind === 'tabs') return options.onTabStopsChange ? null : '当前文档不支持制表位写回'
    return options.onIndentsChange ? null : '当前文档不支持缩进写回'
  }
  const validDrag = (value: Drag) => !value.cancelled && visible && !disposed && !reason(value.kind)
    && editor.state.doc === value.doc && editor.state.selection.eq(value.selection)
    && JSON.stringify(options.getSection()) === value.section && zoom() === value.zoom
  const cancelDrag = () => {
    if (!drag) return
    drag.cancelled = true
    // 源组件在 mouseup 中移除自己的 document 监听和辅助线；先失效快照，禁止清理过程写回。
    document.dispatchEvent(new MouseEvent('mouseup', { bubbles: true }))
    drag = null
  }
  const commit = (kind: RulerWriteKind, write: () => void) => {
    if (!visible || reason(kind) || (drag && !validDrag(drag))) return
    drag = null
    try { write() } catch (error) { options.onError?.(error) }
    refresh()
  }
  const kindOf = (target: EventTarget | null): RulerWriteKind => {
    const element = target instanceof Element ? target : null
    if (element?.closest('.ruler-margin-handle')) return 'margins'
    for (const [name, kind] of [['right', 'indentRight'], ['left', 'indentLeft'], ['firstLine', 'indentFirstLine'], ['hanging', 'indentHanging']] as const) {
      if (element?.closest('.ruler-ind-' + name)) return kind
    }
    return 'tabs'
  }
  const stop = (event: Event) => { event.preventDefault(); event.stopImmediatePropagation() }
  const capture = (event: Event) => {
    if (event instanceof KeyboardEvent && event.key === 'Tab') return
    const kind = kindOf(event.target)
    if (reason(kind)) { stop(event); return }
    if (event.type === 'mousedown') {
      cancelDrag()
      if (!(event.target instanceof Element) || !event.target.closest('.ruler-tab, .ruler-ind, .ruler-margin-handle')) return
      drag = { doc: editor.state.doc, selection: editor.state.selection, section: JSON.stringify(options.getSection()), zoom: zoom(), kind, cancelled: false }
    }
  }
  const release = () => {
    const current = drag
    queueMicrotask(() => {
      if (!current || drag && drag !== current) return
      // 源拖动直接移动 DOM；即使提交被锁拒绝，也要重建标记恢复真实文档位置。
      drag = null; renderVersion++; refresh()
    })
  }
  const decorate = () => {
    const ruler = host?.querySelector<HTMLElement>('.ruler')
    if (!ruler || !host) return
    ruler.style.zoom = String(zoom())
    host.style.width = rulerDims(options.getSection()).pageWidth / 15 * zoom() + 'px'
    ruler.setAttribute('aria-disabled', String(Boolean(reason('indentRight') && reason('margins'))))
    for (const marker of ruler.querySelectorAll<HTMLElement>('[role="slider"], .ruler-tab-type')) {
      const why = reason(kindOf(marker))
      marker.setAttribute('aria-disabled', String(Boolean(why)))
      marker.title = why ?? marker.getAttribute('data-tip') ?? marker.getAttribute('aria-label') ?? ''
      marker.tabIndex = why ? -1 : 0
      if (marker instanceof HTMLButtonElement) marker.disabled = Boolean(why)
    }
  }
  function refresh() {
    if (disposed || !visible || !root) return
    if (drag && !validDrag(drag)) cancelDrag()
    flushSync(() => root!.render(createElement(Ruler, {
      key: renderVersion, editor, section: options.getSection(), onTabStopsChange: stops => commit('tabs', () => options.onTabStopsChange?.(stops)),
      onIndentsChange: attrs => {
        const fields = Object.keys(attrs)
        if (!fields.length || fields.some(key => !['indentRight', 'indentLeft', 'indentFirstLine'].includes(key))
          || Object.values(attrs).some(value => !Number.isInteger(value) || Math.abs(value!) > 14400)) return
        const kind: RulerWriteKind = fields.includes('indentRight') ? 'indentRight' : fields.length === 2 ? 'indentHanging' : fields.includes('indentLeft') ? 'indentLeft' : 'indentFirstLine'
        if (kind === 'indentRight' && fields.length !== 1) return
        commit(kind, () => options.onIndentsChange?.(attrs))
      },
      onMarginsChange: margins => {
        if (![margins.left, margins.right].every(value => Number.isInteger(value) && value >= 0 && value <= 14400)
          || margins.left + margins.right >= options.getSection().pageWidth) return
        commit('margins', () => options.onMarginsChange?.(margins))
      },
    })))
    decorate()
  }
  const observer = new MutationObserver(refresh)
  observer.observe(editor.view.dom, { attributes: true, attributeFilter: ['style', 'contenteditable'] })
  editor.on('transaction', refresh)
  document.addEventListener('mouseup', release, true)
  return {
    get visible() { return visible }, reason, refresh,
    toggle() {
      if (disposed) return
      if (visible) {
        cancelDrag(); visible = false
        flushSync(() => root?.unmount()); root = null; host?.remove(); host = null
      } else {
        visible = true; host = document.createElement('div'); host.className = 'docx-ruler-host'
        container.before(host); root = createRoot(host)
        for (const type of ['mousedown', 'keydown', 'click', 'dblclick']) host.addEventListener(type, capture, true)
        refresh()
      }
    },
    dispose() {
      if (disposed) return
      cancelDrag(); disposed = true; visible = false; observer.disconnect(); editor.off('transaction', refresh)
      document.removeEventListener('mouseup', release, true)
      flushSync(() => root?.unmount()); root = null; host?.remove(); host = null
    },
  }
}
