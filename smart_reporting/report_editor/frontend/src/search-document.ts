import type { Node as ProseNode } from '@milkdown/kit/prose/model'
import type { Transaction } from '@milkdown/kit/prose/state'

import { findProtocolMarkers } from './protocol'

export interface SearchMatch {
  from: number
  to: number
}

// 搜索计数、高亮和替换必须共享同一组文档位置；否则 Markdown 语法、转义或协议标记
// 会让“第 N 个匹配”在高亮与替换之间指向不同文本。
export function findDocumentMatches(doc: ProseNode, query: string): SearchMatch[] {
  const matches: SearchMatch[] = []
  if (!query) return matches
  doc.descendants((node, position) => {
    if (!node.isText || !node.text) return
    const value = node.text
    const markers = findProtocolMarkers(value)
    let found = value.indexOf(query)
    while (found >= 0) {
      const end = found + query.length
      if (!markers.some((marker) => found < marker.end && end > marker.start)) {
        matches.push({ from: position + found, to: position + end })
      }
      found = value.indexOf(query, end)
    }
  })
  return matches
}

// 从后往前替换，保证前面匹配的位置不受已替换文本长度影响；insertText 保留原文本标记。
export function replaceDocumentMatches(
  transaction: Transaction,
  matches: SearchMatch[],
  replacement: string,
): Transaction {
  for (const match of [...matches].sort((left, right) => right.from - left.from)) {
    transaction.insertText(replacement, match.from, match.to)
  }
  return transaction
}
