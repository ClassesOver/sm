import type { Node as ProseNode } from '@milkdown/kit/prose/model'
import { Plugin, PluginKey } from '@milkdown/kit/prose/state'
import { Decoration, DecorationSet } from '@milkdown/kit/prose/view'
import { $prose } from '@milkdown/kit/utils'

export interface SearchHighlightSpec {
  query: string
  current: number
}

export const searchHighlightPluginKey = new PluginKey<DecorationSet>(
  'SMART_REPORT_SEARCH_HIGHLIGHT',
)

function searchDecorations(doc: ProseNode, query: string, current: number): DecorationSet {
  const decorations: Decoration[] = []
  if (!query) return DecorationSet.create(doc, decorations)
  let index = 0
  doc.descendants((node, position) => {
    if (!node.isText || !node.text) return
    const value = node.text
    let found = value.indexOf(query)
    while (found >= 0) {
      decorations.push(
        Decoration.inline(position + found, position + found + query.length, {
          class: `search-match${index === current ? ' search-match-active' : ''}`,
        }),
      )
      index += 1
      found = value.indexOf(query, found + query.length)
    }
  })
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
