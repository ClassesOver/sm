import { Schema } from '@milkdown/kit/prose/model'
import { EditorState } from '@milkdown/kit/prose/state'
import { describe, expect, it } from 'vitest'

import { findDocumentMatches, replaceDocumentMatches } from './search-document'

const schema = new Schema({
  nodes: {
    doc: { content: 'paragraph+' },
    paragraph: { content: 'text*', toDOM: () => ['p', 0] },
    text: {},
  },
  marks: { strong: { toDOM: () => ['strong', 0] } },
})

function documentOf(...paragraphs: Array<Array<[string, boolean?]>>) {
  return schema.node(
    'doc',
    null,
    paragraphs.map((parts) =>
      schema.node(
        'paragraph',
        null,
        parts.map(([text, strong]) => schema.text(text, strong ? [schema.mark('strong')] : [])),
      ),
    ),
  )
}

describe('document search', () => {
  it('matches rendered text rather than Markdown syntax and skips protocol markers', () => {
    const doc = documentOf([['收入', true], ['增长，收入持平']], [['[[section:revenue]]']])

    const matches = findDocumentMatches(doc, '收入')

    expect(matches.map(({ from, to }) => doc.textBetween(from, to))).toEqual(['收入', '收入'])
    expect(findDocumentMatches(doc, '**')).toEqual([])
    expect(findDocumentMatches(doc, 'revenue')).toEqual([])
  })

  it('replaces exactly the selected match and keeps its formatting', () => {
    const doc = documentOf([['收入', true], ['增长，收入持平']])
    const state = EditorState.create({ doc })
    const [first] = findDocumentMatches(doc, '收入')

    const next = state.apply(replaceDocumentMatches(state.tr, [first], '营收'))

    expect(next.doc.textContent).toBe('营收增长，收入持平')
    expect(next.doc.firstChild?.firstChild?.marks.map((mark) => mark.type.name)).toEqual(['strong'])
  })

  it('replaces all matches in one transaction without shifting positions', () => {
    const doc = documentOf([['收入与收入']], [['收入']])
    const state = EditorState.create({ doc })

    const next = state.apply(
      replaceDocumentMatches(state.tr, findDocumentMatches(doc, '收入'), '总营业收入'),
    )

    expect(next.doc.textContent).toBe('总营业收入与总营业收入总营业收入')
    expect(findDocumentMatches(next.doc, '收入')).toHaveLength(3)
  })

  it('deletes matches when the replacement is empty', () => {
    const doc = documentOf([['收入（万元）']])
    const state = EditorState.create({ doc })

    const next = state.apply(
      replaceDocumentMatches(state.tr, findDocumentMatches(doc, '（万元）'), ''),
    )

    expect(next.doc.textContent).toBe('收入')
  })
})
