import { expect, it } from 'vitest'
import { replayDocxOperations, type DocxAnchor } from './docx-operations'

it('rejects resizing with page layout or section-break drafts before projecting an invalid combined state', () => {
  const width = { kind: 'resizeTableColumns', blockId: 'table', expectedObjectSha256: 'sha', steps: [{ kind: 'distributeTableColumns', left: 0, right: 1 }] }
  const anchor = { blockId: 'table', columnWidthSectionId: 'section' } as DocxAnchor
  const layout = { kind: 'setSectionLayout', sectionId: 'section', expectedSectionSha256: 'section-sha', values: { marginLeft: 2500 } }
  for (const operations of [[width, layout], [layout, width], [width, { kind: 'insertSectionBreak' }]]) {
    expect(() => replayDocxOperations({ type: 'doc' }, operations, [anchor])).toThrow(/列宽与/)
  }
})
