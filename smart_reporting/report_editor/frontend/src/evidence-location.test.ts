import { Schema } from '@milkdown/kit/prose/model'
import { EditorState } from '@milkdown/kit/prose/state'
import { describe, expect, it } from 'vitest'
import { createEvidenceLocationPlugin, evidenceLocationKey, evidenceLocationTransaction, findEvidenceTableCell, findEvidenceChartImage, findProtocolMarkerElement } from './evidence-location'

describe('protocol marker lookup', () => {
  it('matches section and citation markers exactly instead of by substring', () => {
    const root = document.createElement('div')
    root.innerHTML = '<span class="report-section-marker">[[section:income_trend]]</span>' +
      '<span class="report-section-marker">[[section:income]]</span>' +
      '<span class="report-citation-marker">[[citation:sub-abc]]</span>'
    expect(findProtocolMarkerElement(root, '.report-section-marker', 'section', 'income')?.textContent)
      .toBe('[[section:income]]')
    expect(findProtocolMarkerElement(root, '.report-citation-marker', 'citation', 'sub-ab')).toBeUndefined()
    expect(findProtocolMarkerElement(root, '.report-section-marker', 'citation', 'income')).toBeUndefined()
  })
})

describe('evidence chart target', () => {
  const base = 'https://example.test/reports/v1/editor/report-1/1/asset/'
  it('locates only an adjacent caption paragraph', () => {
    const root = document.createElement('div')
    root.innerHTML = '<div class="milkdown-image-block"><img src="chart.png"></div><p><em>图表：收入趋势</em></p>'
    expect(findEvidenceChartImage(root, 'chart.png', base, true)).toBe(root.lastElementChild)
    root.lastElementChild!.textContent = '普通正文'
    expect(findEvidenceChartImage(root, 'chart.png', base, true)).toBeNull()
  })
  it('ignores images with unparsable sources instead of aborting the lookup', () => {
    const root = document.createElement('div')
    root.innerHTML = '<p><img src="http://[broken"></p><div class="milkdown-image-block"><img src="chart.png"></div>'
    expect(findEvidenceChartImage(root, 'chart.png', base)).toBe(root.lastElementChild)
    expect(findEvidenceChartImage(root, 'http://[broken', base)).toBeNull()
  })
  it('matches resolved exact image source and returns its editor block', () => {
    const root = document.createElement('div')
    root.innerHTML = '<div class="milkdown-image-block"><img src="./chart%20real.png"></div><p><img src="other/chart%20real.png"></p>'
    expect(findEvidenceChartImage(root, 'chart real.png', base)).toBe(root.firstElementChild)
    expect(findEvidenceChartImage(root, 'missing.png', base)).toBeNull()
  })
  it('rejects duplicate images and ignores drag previews', () => {
    const root = document.createElement('div')
    root.innerHTML = '<div class="drag-preview"><img src="chart.png"></div><p><img src="chart.png"></p>'
    expect(findEvidenceChartImage(root, 'chart.png', base)).toBe(root.lastElementChild)
    root.insertAdjacentHTML('beforeend', '<p><img src="chart.png"></p>')
    expect(findEvidenceChartImage(root, 'chart.png', base)).toBeNull()
  })
})

describe('evidence table target', () => {
  const location = { rowKey: 'row:cur', columnKey: 'income_total', rowIndex: 1, columnIndex: 1, rowLabel: '本期', text: '3,600' }
  const markup = '<p><span class="report-table-marker">[[table:tbl-1]]</span></p>' +
    '<table><tbody><tr><th></th><th>income_total</th></tr><tr><td>上期</td><td><p>9,999</p></td></tr>' +
    '<tr><td>本期</td><td><p>3,600</p></td></tr></tbody></table>'
  function root(html = markup) {
    const element = document.createElement('div')
    element.innerHTML = html
    return element
  }

  it.each([false, true])('uses current row metadata with table wrapper=%s', wrapped => {
    const element = root(wrapped ? markup.replace('<table>', '<div class="tableWrapper"><table>').replace('</table>', '</table></div>') : markup)
    const target = findEvidenceTableCell(element, 'tbl-1', location)
    expect(target).toBe(element.querySelector('tr:last-child td:last-child p'))
    expect(target?.textContent).toBe('3,600')
    expect(findEvidenceTableCell(element, 'tbl', location)).toBeNull()
  })

  it.each([
    { rowIndex: 0 }, { rowIndex: -1 }, { rowIndex: 1.5 }, { columnIndex: 0 },
    { columnIndex: 2 }, { columnKey: 'renamed' }, { rowLabel: 'changed' }, { text: '3,800' },
  ])('rejects mismatched or invalid metadata %j', change => {
    expect(findEvidenceTableCell(root(), 'tbl-1', { ...location, ...change })).toBeNull()
  })

  it('rejects missing, duplicate, or detached table markers', () => {
    expect(findEvidenceTableCell(root(''), 'tbl-1', location)).toBeNull()
    expect(findEvidenceTableCell(root(markup + markup), 'tbl-1', location)).toBeNull()
    expect(findEvidenceTableCell(root(markup.replace('</p><table>', '</p><p>正文</p><table>')), 'tbl-1', location)).toBeNull()
  })

  it('ignores Milkdown drag preview tables but rejects multiple editable tables', () => {
    const wrapped = markup.replace('<table>', '<div class="milkdown-table-block"><div class="drag-preview"><table><tbody></tbody></table></div><table>') + '</div>'
    expect(findEvidenceTableCell(root(wrapped), 'tbl-1', location)?.textContent).toBe('3,600')
    const multiple = markup.replace('<table>', '<div><table></table><table>').replace('</tbody></table>', '</tbody></table></div>')
    expect(findEvidenceTableCell(root(multiple), 'tbl-1', location)).toBeNull()
  })
})

const schema = new Schema({ nodes: {
  doc: { content: 'paragraph+' }, paragraph: { content: 'text*', toDOM: () => ['p', 0] }, text: {},
} })

describe('evidence editor location', () => {
  it.each(['table_cell', 'list_item'])('locates text inside a nested %s without selecting its container', (kind) => {
    const nestedSchema = new Schema({ nodes: {
      doc: { content: 'block+' },
      paragraph: { content: 'text*', group: 'block', toDOM: () => ['p', 0] },
      table: { content: 'table_row+', group: 'block', toDOM: () => ['table', ['tbody', 0]] },
      table_row: { content: 'table_cell+', toDOM: () => ['tr', 0] },
      table_cell: { content: 'paragraph+', toDOM: () => ['td', 0] },
      bullet_list: { content: 'list_item+', group: 'block', toDOM: () => ['ul', 0] },
      list_item: { content: 'paragraph+', toDOM: () => ['li', 0] },
      text: {},
    } })
    const paragraph = nestedSchema.node('paragraph', null, nestedSchema.text('收入3600'))
    const child = nestedSchema.node(kind, null, paragraph)
    const container = kind === 'table_cell'
      ? nestedSchema.node('table', null, nestedSchema.node('table_row', null, child))
      : nestedSchema.node('bullet_list', null, child)
    const doc = nestedSchema.node('doc', null, container)
    let position = 0
    doc.descendants((node, from) => { if (node.isText) position = from })
    const state = EditorState.create({ doc, plugins: [createEvidenceLocationPlugin()] })
    const located = state.apply(evidenceLocationTransaction(state, position))
    expect(located.selection.$from.parent.type.name).toBe('paragraph')
    expect(located.selection.from).toBe(position)
    const decorations = evidenceLocationKey.getState(located)!.find()
    expect(decorations).toHaveLength(1)
    expect(doc.nodeAt(decorations[0].from)?.type.name).toBe('paragraph')
    const edited = located.apply(located.tr.insertText('新'))
    expect(edited.doc.textContent).toBe('新收入3600')
    expect(edited.doc.firstChild?.type.name).toBe(container.type.name)
    expect(evidenceLocationKey.getState(edited)!.find()).toHaveLength(1)
  })

  it('sets a real selection and highlights its block without changing the document', () => {
    const doc = schema.node('doc', null, [schema.node('paragraph', null, schema.text('收入')), schema.node('paragraph', null, schema.text('正文'))])
    const state = EditorState.create({ doc, plugins: [createEvidenceLocationPlugin()] })
    const transaction = evidenceLocationTransaction(state, 5)
    const located = state.apply(transaction)
    expect(located.doc).toBe(doc)
    expect(located.selection.from).toBe(5)
    expect(transaction.getMeta('addToHistory')).toBe(false)
    expect(evidenceLocationKey.getState(located)?.find().map(({ from, to }) => [from, to])).toEqual([[4, 8]])
    const edited = located.apply(located.tr.insertText('新'))
    expect(edited.doc.textContent).toBe('收入新正文')
    expect(evidenceLocationKey.getState(edited)?.find().map(({ from, to }) => [from, to])).toEqual([[4, 9]])
    const cleared = edited.apply(edited.tr.setMeta(evidenceLocationKey, null))
    expect(evidenceLocationKey.getState(cleared)?.find()).toEqual([])
    expect(cleared.doc).toBe(edited.doc)
    expect(cleared.selection.eq(edited.selection)).toBe(true)
  })
})
