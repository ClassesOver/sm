import type { Node as ProseNode } from '@milkdown/kit/prose/model'
import { Plugin, PluginKey } from '@milkdown/kit/prose/state'
import { Decoration, DecorationSet } from '@milkdown/kit/prose/view'
import { $prose } from '@milkdown/kit/utils'

import { findDocumentMatches } from './search-document'

export interface SearchHighlightSpec {
  query: string
  current: number
}

export const searchHighlightPluginKey = new PluginKey<DecorationSet>(
  'SMART_REPORT_SEARCH_HIGHLIGHT',
)

function searchDecorations(doc: ProseNode, query: string, current: number): DecorationSet {
  const decorations = findDocumentMatches(doc, query).map((match, index) =>
    Decoration.inline(match.from, match.to, {
      class: `search-match${index === current ? ' search-match-active' : ''}`,
    }),
  )
  return DecorationSet.create(doc, decorations)
}

// ProseMirror 管理的 DOM 不允许外部直接改写（MutationObserver 会立即回滚），
// 搜索高亮必须以 decoration 方式渲染，由插件状态驱动。
export const searchHighlightPlugin = $prose(() => {
  let spec: SearchHighlightSpec = { query: '', current: 0 }
  return new Plugin<DecorationSet>({
    key: searchHighlightPluginKey,
    state: {
      init: (_config, state) => searchDecorations(state.doc, spec.query, spec.current),
      apply: (transaction, previous) => {
        const next = transaction.getMeta(searchHighlightPluginKey) as
          | SearchHighlightSpec
          | undefined
        if (next) spec = next
        if (next || transaction.docChanged) {
          return searchDecorations(transaction.doc, spec.query, spec.current)
        }
        return previous
      },
    },
    props: {
      decorations: (state) => searchHighlightPluginKey.getState(state) ?? DecorationSet.empty,
    },
  })
})
