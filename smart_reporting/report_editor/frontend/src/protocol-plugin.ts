import { Fragment, Slice, type Node as ProseNode } from '@milkdown/kit/prose/model'
import { Plugin, PluginKey } from '@milkdown/kit/prose/state'
import { Decoration, DecorationSet, type EditorView } from '@milkdown/kit/prose/view'
import { $prose } from '@milkdown/kit/utils'

import { findProtocolMarkers, groupProtocolMarkers, protocolMarkersUnchanged } from './protocol'
import type { TraceSources } from './api'
import { analysisLabel, citationLabel } from './evidence-relations'

const protocolMarkerPluginKey = new PluginKey<DecorationSet>('SMART_REPORT_PROTOCOL_MARKERS')

function markerDecorations(doc: ProseNode, sources?: TraceSources): DecorationSet {
  const decorations: Decoration[] = []
  doc.descendants((node, position) => {
    if (!node.isText || !node.text) return
    for (const group of groupProtocolMarkers(node.text)) {
      const marker = group[0]
      const references = [...new Map(group.map(item => [`${item.kind}:${item.value}`, { kind: item.kind, value: item.value }])).values()]
      const title = references.length > 1 ? `查看 ${references.length} 个来源`
        : marker.kind === 'analysis' ? `查看${analysisLabel(marker.value, sources)}的来源` : `查看${citationLabel(marker.value, sources)}`
      decorations.push(
        Decoration.inline(position + marker.start, position + group.at(-1)!.end, {
          class: `report-protocol-marker ${[...new Set(group.map(item => `report-${item.kind}-marker`))].join(' ')}`,
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
  return new Plugin<DecorationSet>({
    key: protocolMarkerPluginKey,
    state: {
      init: (_config, state) => markerDecorations(state.doc),
      apply: (transaction, previous) => {
        const registered = transaction.getMeta(protocolMarkerPluginKey) as TraceSources | undefined
        if (registered) sources = registered
        return transaction.docChanged || registered ? markerDecorations(transaction.doc, sources) : previous
      },
    },
    filterTransaction: (transaction, state) =>
      !transaction.docChanged ||
      protocolMarkersUnchanged(state.doc.textContent, transaction.doc.textContent),
    props: {
      transformCopied: slice => new Slice(stripCopiedMarkers(slice.content), slice.openStart, slice.openEnd),
      decorations: (state) => protocolMarkerPluginKey.getState(state) ?? DecorationSet.empty,
    },
  })
})

export function updateProtocolSourceLabels(view: EditorView, sources: TraceSources): void {
  view.dispatch(view.state.tr.setMeta(protocolMarkerPluginKey, sources).setMeta('addToHistory', false))
}
