import { expect, it } from 'vitest'
import { restoredSectionHfOperations, sectionHfLinkOperation } from './docx-hf-sections'
import type { DocxSectionAnchor } from './docx-operations'

const settings = { pageWidth: 12240, pageHeight: 15840, marginTop: 1440, marginRight: 1440, marginBottom: 1440, marginLeft: 1440, orientation: 'portrait', columns: 1 } as DocxSectionAnchor['settings']
const parts = { 'header.default': { relationshipsSha256: 'graph-sha', ownRelationshipsSha256: 'own-graph-sha', ownRId: 'r2', ownPath: 'word/header2.xml', ownPartSha256: 'own-sha', ownerSectionId: 's1', rId: 'r2', path: 'word/header2.xml', expectedPartSha256: 'part-sha', linked: false, text: 'second', hasPageNumber: false, editable: true } }
const sections = [{ sectionId: 's0', expectedSectionSha256: 'x0', settings, headersFooters: { parts: {} } }, { sectionId: 's1', expectedSectionSha256: 'x1', settings, headersFooters: { parts } }]
it('anchors link drafts to the full original own and inherited identity', () => {
  const operation = sectionHfLinkOperation(sections[1]!, 'header', 'default', true)
  expect(restoredSectionHfOperations([operation], sections)).toEqual([operation])
  expect(() => restoredSectionHfOperations([operation, { kind: 'insertSectionBreak' }], sections)).toThrow('先保存')
  for (const field of ['expectedOwnRId', 'expectedOwnPartSha256', 'expectedOwnerSectionId', 'expectedRId', 'expectedPartSha256', 'expectedRelationshipsSha256', 'expectedOwnRelationshipsSha256']) {
    expect(() => restoredSectionHfOperations([{ ...operation, [field]: 'foreign' }], sections)).toThrow('身份')
  }
  expect(() => restoredSectionHfOperations([{ ...operation, sectionId: 's0', expectedSectionSha256: 'x0' }], sections)).toThrow()
  expect(() => restoredSectionHfOperations([operation], [sections[0]!, { ...sections[1]!, headersFooters: { parts: { 'header.default': { ...parts['header.default'], editable: false, readOnlyReason: 'relations' } } } }])).toThrow()
})

it('rejects a recovered unlink that would copy a complex owner introduced by an earlier link draft', () => {
  const first = { ...sections[0]!, headersFooters: { parts: { 'header.default': { ...parts['header.default'], ownerSectionId: 's0', ownRId: 'r0', rId: 'r0', editable: false, readOnlyReason: 'internal relationships' } } } }
  const second = sections[1]!
  const third = { ...second, sectionId: 's2', expectedSectionSha256: 'x2', headersFooters: { parts: { 'header.default': { ...parts['header.default'], ownRId: null, ownPath: null, ownPartSha256: 'empty', linked: true } } } }
  const snapshots = [first, second, third]
  const operations = [sectionHfLinkOperation(second, 'header', 'default', true), sectionHfLinkOperation(third, 'header', 'default', false)]
  expect(() => restoredSectionHfOperations(operations, snapshots)).toThrow('复杂关系')
})


it('validates after-link content against the planned original copy source and rejects unmatched flags', () => {
  const first = { ...sections[0]!, headersFooters: { parts: { 'header.default': { ...parts['header.default'], ownerSectionId: 's0', ownRId: 'r0', rId: 'r0', expectedPartSha256: 'source0' } } } }
  const second = { ...sections[1]!, headersFooters: { parts: { 'header.default': { ...parts['header.default'], ownRId: null, ownPath: null, linked: true } } } }
  const snapshots = [first, second], link = sectionHfLinkOperation(second, 'header', 'default', false)
  const edit = { kind: 'setHeaderFooter', sectionId: 's1', expectedSectionSha256: 'x1', part: 'header', variant: 'default', expectedPartSha256: 'source0', text: 'new own', pageNumber: false, afterLink: true }
  expect(restoredSectionHfOperations([link, edit], snapshots)).toEqual([link, edit])
  expect(() => restoredSectionHfOperations([edit], snapshots)).toThrow()
  expect(() => restoredSectionHfOperations([link, { ...edit, expectedPartSha256: 'foreign' }], snapshots)).toThrow('身份')
  expect(() => restoredSectionHfOperations([link, { ...edit, afterLink: false }], snapshots)).toThrow()
})
