import { expect, it } from 'vitest'
import { Schema } from '@tiptap/pm/model'
import { docxOperations, replayDocxOperations, type DocxAnchor, type DocxPmNode } from './docx-operations'

const schema = new Schema({ nodes: {
  doc: { content: 'docTable+' }, text: {},
  docParagraph: { content: 'text*', attrs: { docxIndex: { default: null } } },
  docTable: { content: 'docTableRow+', tableRole: 'table', attrs: { docxIndex: { default: 0 }, colWidthsPct: { default: [50, 50] }, nativeTableCellShape: { default: null } } },
  docTableRow: { content: 'docTableCell*', tableRole: 'row' },
  docTableCell: { content: 'docParagraph+', tableRole: 'cell', attrs: { colspan: { default: 1 }, rowspan: { default: 1 }, colwidth: { default: null } } },
} })
const anchor = { docxIndex: 0, blockId: 'table', expectedObjectSha256: 'sha', editable: false,
  cellShapeEditable: true, cellShapeWidthsTwips: [1500, 1500],
  cellShapeCells: [0, 1].flatMap(top => [0, 1].map(left => ({ top, left, bottom: top + 1, right: left + 1, physicalRow: top, physicalColumn: left }))),
} as DocxAnchor
const source = schema.nodeFromJSON({ type: 'doc', content: [{ type: 'docTable', content: [0, 1].map(r => ({ type: 'docTableRow', content: [0, 1].map(c => ({ type: 'docTableCell', attrs: { colwidth: [100] }, content: [{ type: 'docParagraph', attrs: { docxIndex: r * 2 + c }, content: [{ type: 'text', text: `${r}:${c}` }] }] })) })) }] }).toJSON() as DocxPmNode
const merge = { kind: 'mergeTableCells', rect: { top: 0, left: 0, bottom: 2, right: 2 } }
const operation = { kind: 'reshapeTableCells', blockId: 'table', expectedObjectSha256: 'sha', steps: [merge] }

it('replays a signed merge intent and collects the same operation without accepting extra edits', () => {
  const edited = replayDocxOperations(source, [operation], [anchor], undefined, schema)
  expect(edited.content![0]!.content![0]!.content).toHaveLength(1)
  expect(edited.content![0]!.content![0]!.content![0]!.attrs).toMatchObject({ colspan: 2, rowspan: 2 })
  expect(edited.content![0]!.content![0]!.content![0]!.content!.map(p => p.content![0]!.text)).toEqual(['0:0', '0:1', '1:0', '1:1'])
  expect(docxOperations(source, edited, [anchor], undefined, schema)).toEqual([operation])
  const changed = structuredClone(edited)
  changed.content![0]!.content![0]!.content![0]!.content![0]!.content![0]!.text = 'unrecorded edit'
  expect(() => docxOperations(source, changed, [anchor], undefined, schema)).toThrow()
})

it('rejects stale identity, unsigned capability, unknown fields and same-table mixed drafts', () => {
  for (const op of [{ ...operation, expectedObjectSha256: 'wrong' }, { ...operation, xml: '<w:tbl/>' }, { ...operation, steps: [{ ...merge, xml: 'forged' }] }]) {
    expect(() => replayDocxOperations(source, [op], [anchor], undefined, schema)).toThrow()
  }
  expect(() => replayDocxOperations(source, [operation], [{ ...anchor, cellShapeEditable: false } as DocxAnchor], undefined, schema)).toThrow()
  expect(() => replayDocxOperations(source, [operation, operation], [anchor], undefined, schema)).toThrow()
})
