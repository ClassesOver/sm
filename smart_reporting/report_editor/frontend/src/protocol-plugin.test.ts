import { Schema } from '@milkdown/kit/prose/model'
import { EditorState, Plugin } from '@milkdown/kit/prose/state'
import { EditorView } from '@milkdown/kit/prose/view'
import { history, redo, undo } from '@milkdown/kit/prose/history'
import { describe, expect, it } from 'vitest'

import { markerDecorations, PROTOCOL_CARET_ANCHOR, protocolMarkerTransactionAllowed, TABLE_PROTOCOL_EDIT_META } from './protocol-plugin'

const schema = new Schema({
  nodes: { doc: { content: 'block+' }, paragraph: { group: 'block', content: 'inline*', toDOM: () => ['p', 0] },
    text: { group: 'inline' }, hard_break: { inline: true, group: 'inline', toDOM: () => ['br'] } },
  marks: { strong: { toDOM: () => ['strong', 0] } },
})
const paragraph = (...content: Parameters<typeof schema.node>[2][]) => schema.node('paragraph', null, content.flat() as never)

function caretAnchors(doc: ReturnType<typeof schema.node>): number[] {
  return markerDecorations(doc).find().filter(item => item.spec.key === PROTOCOL_CARET_ANCHOR).map(item => item.from)
}

describe('protocol marker caret anchors', () => {
  it('段落以来源标记结尾时，在段末留出可输入的光标落点（位于落点之前，光标在其后）', () => {
    const text = '华东营收为 12,450 万元。[[citation:sub-fixture-001]]'
    const doc = schema.node('doc', null, [paragraph(schema.text(text))])
    // 段落内容从位置 1 开始，段末位置为 1 + 文本长度。
    expect(caretAnchors(doc)).toEqual([1 + text.length])
    const anchor = markerDecorations(doc).find().find(item => item.spec.key === PROTOCOL_CARET_ANCHOR)!
    expect(anchor.spec.side).toBeLessThan(0)
  })

  it('标记后紧跟正文时同样留出落点，使标记后的文字可被光标与选区定位', () => {
    const before = '收入[[citation:sub-1]]'
    const doc = schema.node('doc', null, [paragraph(schema.text(`${before}同比增长。`)), paragraph(schema.text('没有来源标记的段落'))])
    expect(caretAnchors(doc)).toEqual([1 + before.length])
  })

  it('相邻标记合并为一组，只在整组之后留一个落点', () => {
    const first = '营收[[citation:sub-1]]'
    const second = '成本[[analysis:a-1]][[citation:sub-2]]'
    const doc = schema.node('doc', null, [paragraph(schema.text(first)), paragraph(schema.text(second))])
    expect(caretAnchors(doc)).toEqual([1 + first.length, first.length + 2 + 1 + second.length])
  })

  it('正在预览来源的标记由装饰带上高亮类，其他标记不带', () => {
    const first = '营收[[citation:sub-1]]'
    const second = '成本[[citation:sub-2]]'
    const doc = schema.node('doc', null, [paragraph(schema.text(first)), paragraph(schema.text(second))])
    const secondStart = first.length + 2 + 1 + '成本'.length
    const activeTexts = (active: number | null) => {
      const view = new EditorView(document.createElement('div'), {
        state: EditorState.create({ doc }), decorations: () => markerDecorations(doc, undefined, active),
      })
      const texts = [...view.dom.querySelectorAll('.source-marker-active')].map(node => node.textContent)
      view.destroy()
      return texts
    }
    expect(activeTexts(secondStart)).toEqual(['[[citation:sub-2]]'])
    expect(activeTexts(null)).toEqual([])
  })
})

describe('table marker replacement history', () => {
  it('allows the exact paired marker change to undo and redo', () => {
    const before = schema.node('doc', null, [paragraph(schema.text('[[table:old]]')), paragraph(schema.text('内容')), paragraph(schema.text('[[/table:old]]'))])
    let state = EditorState.create({
      schema,
      doc: before,
      plugins: [history(), new Plugin({ filterTransaction: protocolMarkerTransactionAllowed })],
    })
    const dispatch = (transaction: Parameters<typeof state.apply>[0]) => { state = state.apply(transaction) }
    const after = schema.node('doc', null, [paragraph(schema.text('[[table:new]]')), paragraph(schema.text('内容')), paragraph(schema.text('[[/table:new]]'))])
    dispatch(state.tr.replaceWith(0, state.doc.content.size, after.content).setMeta(TABLE_PROTOCOL_EDIT_META, { tableId: 'new' }))
    expect(state.doc.textContent).toContain('table:new')
    expect(undo(state, dispatch)).toBe(true)
    expect(state.doc.textContent).toContain('table:old')
    expect(redo(state, dispatch)).toBe(true)
    expect(state.doc.textContent).toContain('table:new')
  })
})
