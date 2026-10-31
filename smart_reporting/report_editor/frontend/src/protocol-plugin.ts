import { Fragment, Slice, type Node as ProseNode } from '@milkdown/kit/prose/model'
import { Plugin, PluginKey, type EditorState, type Transaction } from '@milkdown/kit/prose/state'
import { Decoration, DecorationSet, type EditorView } from '@milkdown/kit/prose/view'
import { $prose } from '@milkdown/kit/utils'

import { findProtocolMarkers, groupProtocolMarkers, protocolMarkersUnchanged } from './protocol'
import type { TraceSources } from './api'
import { analysisLabel, citationLabel } from './evidence-relations'

const protocolMarkerPluginKey = new PluginKey<DecorationSet>('SMART_REPORT_PROTOCOL_MARKERS')
/** 正在预览来源的标记（标记组起点的文档位置）。高亮必须经由装饰绘制：直接改标记 DOM 的 class 会被
 * ProseMirror 视为外部改动并重绘该段，高亮随即丢失、原元素也被替换。 */
const ACTIVE_MARKER_META = 'smartReportActiveProtocolMarker'

/** 来源标记后的光标落点：标记是不可编辑的内联装饰，紧随其后的文档位置会被映射进标记文字内部，
 * 浏览器随即把光标或选区收拢（段末输入被吞掉，键盘选中标记后的文字得到空选区）。每组标记后加一个空部件，
 * 取 side: -1（位于该位置之前），该位置便落在部件之后的可编辑处；段落以标记结尾时，ProseMirror 还会因此补上原生段末光标占位。 */
export const PROTOCOL_CARET_ANCHOR = 'protocol-caret-anchor'

function caretAnchor(): HTMLElement {
  const anchor = document.createElement('span')
  anchor.className = 'report-protocol-caret-anchor'
  return anchor
}

export const TABLE_PROTOCOL_EDIT_META = 'SMART_REPORT_TABLE_PROTOCOL_EDIT'

function tableProtocolMarkersOnlyChanged(before: string, after: string, tableId: string): boolean {
  const beforeMarkers = findProtocolMarkers(before)
    .filter(marker => marker.kind === 'table' || marker.kind === 'table-close')
  const afterMarkers = findProtocolMarkers(after)
    .filter(marker => marker.kind === 'table' || marker.kind === 'table-close')
  if (beforeMarkers.length !== afterMarkers.length || beforeMarkers.length < 2) return false
  const changed = beforeMarkers
    .map((marker, index) => ({ before: marker, after: afterMarkers[index] }))
    .filter(pair => pair.before.raw !== pair.after.raw)
  const target = afterMarkers.filter(marker => marker.value === tableId)
  return target.length === 2 &&
    target[0].kind === 'table' && target[1].kind === 'table-close' &&
    changed.length === 2 &&
    changed.every(pair => pair.after.value === tableId) &&
    changed.some(pair => pair.after.kind === 'table') &&
    changed.some(pair => pair.after.kind === 'table-close')
}

function tableProtocolMarkerPairChanged(before: string, after: string): boolean {
  const beforeMarkers = findProtocolMarkers(before).filter(marker => marker.kind === 'table' || marker.kind === 'table-close')
  const afterMarkers = findProtocolMarkers(after).filter(marker => marker.kind === 'table' || marker.kind === 'table-close')
  if (beforeMarkers.length !== afterMarkers.length) return false
  const changed = beforeMarkers.map((marker, index) => ({ before: marker, after: afterMarkers[index] }))
    .filter(pair => pair.before.raw !== pair.after.raw)
  return changed.length === 2 &&
    changed[0].before.value === changed[1].before.value &&
    changed[0].after.value === changed[1].after.value &&
    new Set(changed.map(pair => pair.before.kind)).size === 2 &&
    new Set(changed.map(pair => pair.after.kind)).size === 2
}

export function protocolMarkerTransactionAllowed(transaction: Transaction, state: EditorState): boolean {
  if (!transaction.docChanged || protocolMarkersUnchanged(state.doc.textContent, transaction.doc.textContent)) return true
  const tableEdit = transaction.getMeta(TABLE_PROTOCOL_EDIT_META) as { tableId?: string } | undefined
  if (tableEdit?.tableId !== undefined && tableProtocolMarkersOnlyChanged(
    state.doc.textContent, transaction.doc.textContent, String(tableEdit.tableId),
  )) return true
  // prosemirror-history marks undo/redo transactions with its stable PluginKey name.
  // Only the exact paired table-marker transition is accepted, so history cannot
  // use this exception to mutate any other protected protocol marker.
  return transaction.getMeta('history$') !== undefined &&
    tableProtocolMarkerPairChanged(state.doc.textContent, transaction.doc.textContent)
}

export function markerDecorations(doc: ProseNode, sources?: TraceSources, active: number | null = null): DecorationSet {
  const decorations: Decoration[] = []
  doc.descendants((node, position) => {
    if (node.type.name === 'paragraph') {
      const markers = findProtocolMarkers(node.textContent)
      let onlyText = true
      node.forEach(child => { if (!child.isText) onlyText = false })
      if (onlyText && markers.length && markers.every(marker => marker.kind === 'table' || marker.kind === 'table-close')
        && !markers.reduce((text, marker) => text.replace(marker.raw, ''), node.textContent).trim()) {
        // 依文档内容识别纯协议段落；光标部件、separator、trailingBreak
        // 都由编辑器后插入，不能用 DOM 的 :only-child 判断是否还有正文。
        decorations.push(Decoration.node(position, position + node.nodeSize, { class: 'report-table-protocol-paragraph' }))
      }
    }
    if (!node.isText || !node.text) return
    for (const group of groupProtocolMarkers(node.text)) {
      decorations.push(Decoration.widget(position + group.at(-1)!.end, caretAnchor, { side: -1, key: PROTOCOL_CARET_ANCHOR }))
      const marker = group[0]
      const references = [...new Map(group.map(item => [`${item.kind}:${item.value}`, { kind: item.kind, value: item.value }])).values()]
      const title = references.length > 1 ? `查看 ${references.length} 个来源`
        : marker.kind === 'analysis' ? `查看${analysisLabel(marker.value, sources)}的来源` : `查看${citationLabel(marker.value, sources)}`
      decorations.push(
        Decoration.inline(position + marker.start, position + group.at(-1)!.end, {
          class: `report-protocol-marker ${[...new Set(group.map(item => `report-${item.kind}-marker`))].join(' ')}${position + marker.start === active ? ' source-marker-active' : ''}`,
          'data-marker-kind': marker.kind,
          'data-marker-value': marker.value,
          ...(['analysis', 'citation'].includes(marker.kind) ? {
            role: 'button', tabindex: '0',
            title, 'aria-label': title,
            'data-marker-count': String(references.length),
            'data-marker-references': JSON.stringify(references),
            ...(references.length > 1 ? { 'aria-haspopup': 'dialog' } : {}),
          } : {}),
          contenteditable: 'false',
        }),
      )
    }
  })
  return DecorationSet.create(doc, decorations)
}

// 只处理复制的Slice，正文和持久化协议保持不变；继续使用Milkdown原生Markdown/HTML序列化。
function stripCopiedMarkers(fragment: Fragment): Fragment {
  const nodes: ProseNode[] = []
  fragment.forEach(node => {
    if (node.isText) {
      let text = node.text!
      for (const marker of findProtocolMarkers(text).reverse()) text = text.slice(0, marker.start) + text.slice(marker.end)
      if (text) nodes.push(node.type.schema.text(text, node.marks))
    } else {
      const attrs = typeof node.attrs.id === 'string' && findProtocolMarkers(node.attrs.id).length
        ? { ...node.attrs, id: null } : node.attrs
      nodes.push(node.type.create(attrs, node.isLeaf ? undefined : stripCopiedMarkers(node.content), node.marks))
    }
  })
  return Fragment.fromArray(nodes)
}

export const protocolMarkerPlugin = $prose(() => {
  let sources: TraceSources | undefined
  let active: number | null = null
  return new Plugin<DecorationSet>({
    key: protocolMarkerPluginKey,
    state: {
      init: (_config, state) => markerDecorations(state.doc),
      apply: (transaction, previous) => {
        const registered = transaction.getMeta(protocolMarkerPluginKey) as TraceSources | undefined
        if (registered) sources = registered
        const activeMeta = transaction.getMeta(ACTIVE_MARKER_META) as { position: number | null } | undefined
        if (activeMeta) active = activeMeta.position
        else if (active !== null && transaction.docChanged) active = transaction.mapping.map(active)
        return transaction.docChanged || registered || activeMeta ? markerDecorations(transaction.doc, sources, active) : previous
      },
    },
    filterTransaction: protocolMarkerTransactionAllowed,
    props: {
      transformCopied: slice => new Slice(stripCopiedMarkers(slice.content), slice.openStart, slice.openEnd),
      decorations: (state) => protocolMarkerPluginKey.getState(state) ?? DecorationSet.empty,
    },
  })
})

export function updateProtocolSourceLabels(view: EditorView, sources: TraceSources): void {
  view.dispatch(view.state.tr.setMeta(protocolMarkerPluginKey, sources).setMeta('addToHistory', false))
}

/** 高亮正在预览来源的标记；返回其文档位置，供关闭预览后重新找到标记（高亮重绘会替换标记元素）。 */
export function activateProtocolMarker(view: EditorView, marker: HTMLElement): number | null {
  if (!view.dom.contains(marker)) return null
  const position = view.posAtDOM(marker, 0)
  view.dispatch(view.state.tr.setMeta(ACTIVE_MARKER_META, { position }).setMeta('addToHistory', false))
  return position
}

export function deactivateProtocolMarker(view: EditorView): void {
  view.dispatch(view.state.tr.setMeta(ACTIVE_MARKER_META, { position: null }).setMeta('addToHistory', false))
}

/** 按文档位置找到当前渲染的标记元素。 */
export function protocolMarkerElement(view: EditorView, position: number): HTMLElement | null {
  if (position < 0 || position >= view.state.doc.content.size) return null
  const { node, offset } = view.domAtPos(position + 1)
  const element = node.nodeType === Node.ELEMENT_NODE ? (node as Element).childNodes[offset] ?? node : node
  const found = (element instanceof Element ? element : element.parentElement)?.closest<HTMLElement>('.report-protocol-marker')
  return found && view.dom.contains(found) ? found : null
}
