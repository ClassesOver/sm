import { expect, it } from 'vitest'
import { replayDocxOperations, type DocxAnchor } from './docx-operations'

it('rejects row-height and same-section layout or section-break drafts before projection', () => {
  const height = { kind: 'setTableRowHeights', blockId: 'table', expectedObjectSha256: 'sha', steps: [{ top: 0, bottom: 1, heightTwips: 600 }] }
  const anchor = { blockId: 'table', rowHeightSectionId: 'section' } as DocxAnchor
  const layout = { kind: 'setSectionLayout', sectionId: 'section', expectedSectionSha256: 'section-sha', values: { marginTop: 2500 } }
  for (const operations of [[height, layout], [layout, height], [height, { kind: 'insertSectionBreak' }]]) {
    expect(() => replayDocxOperations({ type: 'doc' }, operations, [anchor])).toThrow(/行高与/)
  }
})
