import type { Node as ProseNode } from '@milkdown/kit/prose/model'
import { Plugin, PluginKey } from '@milkdown/kit/prose/state'
import { Decoration, DecorationSet } from '@milkdown/kit/prose/view'
import { $prose } from '@milkdown/kit/utils'

import { findProtocolMarkers, protocolMarkersUnchanged } from './protocol'

const protocolMarkerPluginKey = new PluginKey<DecorationSet>('SMART_REPORT_PROTOCOL_MARKERS')

function markerDecorations(doc: ProseNode): DecorationSet {
  const decorations: Decoration[] = []
  doc.descendants((node, position) => {
    if (!node.isText || !node.text) return
    for (const marker of findProtocolMarkers(node.text)) {
      decorations.push(
        Decoration.inline(position + marker.start, position + marker.end, {
          class: `report-protocol-marker report-${marker.kind}-marker`,
          'data-marker-label': marker.kind === 'citation' ? '引用' : '',
          contenteditable: 'false',
        }),
      )
    }
  })
  return DecorationSet.create(doc, decorations)
}

export const protocolMarkerPlugin = $prose(() => {
  return new Plugin<DecorationSet>({
    key: protocolMarkerPluginKey,
    state: {
      init: (_config, state) => markerDecorations(state.doc),
      apply: (transaction, previous) =>
        transaction.docChanged ? markerDecorations(transaction.doc) : previous,
    },
    filterTransaction: (transaction, state) =>
      !transaction.docChanged ||
      protocolMarkersUnchanged(state.doc.textContent, transaction.doc.textContent),
    props: {
      decorations: (state) => protocolMarkerPluginKey.getState(state) ?? DecorationSet.empty,
    },
  })
})
