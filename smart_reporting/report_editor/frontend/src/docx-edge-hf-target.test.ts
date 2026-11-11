import { expect, it } from 'vitest'
import { resolveDocxEdgeHfTarget } from './docx-edge-hf-target'
import { slicePaginationSnapshot } from './vendor/genoffice-docs/apps/docs/src/renderer/pagination-snapshot'
import type { SectionInfo, SectionSettings } from '@genoffice/docx-engine'

const settings: SectionSettings = { pageWidth: 3000, pageHeight: 1500, orientation: 'portrait', marginTop: 0, marginBottom: 0, marginLeft: 0, marginRight: 0, pageBorder: false, columns: 1, headerDist: 0, footerDist: 0 }
const hf = { header: null, footer: null, headerFirst: null, footerFirst: null, headerEven: null, footerEven: null, titlePg: false, evenOddHf: true }
const sections = [{ sectionId: 'first', expectedSectionSha256: 'first-sha' }, { sectionId: 'last', expectedSectionSha256: 'last-sha' }]
const parsed = (index: number, extra: Partial<SectionInfo> = {}): SectionInfo => ({ settings, startType: 'nextPage', firstBlockIndex: index, lastBlockIndex: index, sectPrXml: '', titlePg: false, headerRefs: {}, footerRefs: {}, ...extra })
const cut = (start: number, end: number, pageNo: number) => ({ start, end, pageNo, section: 0 })

it('chooses source first-page header and last logical even footer using actual sliced section restart', () => {
  const live = [parsed(0), parsed(1, { pageNumberStart: 12 })]
  const { cuts } = slicePaginationSnapshot({ section: settings, sections: live, live, hf, hfParts: {}, colMode: 'none', colFlow: null, blocks: [{ top: 0, height: 30, section: 0 }, { top: 30, height: 30, section: 1 }], flowH: 60, factor: 1 })
  const facts = { sections, cuts, titlePg: true, evenOddHf: true }
  expect(resolveDocxEdgeHfTarget('header', facts)).toEqual({ ...sections[0], sectionIndex: 0, part: 'header', variant: 'first', pageCount: 2, lastPageNo: 12 })
  expect(resolveDocxEdgeHfTarget('footer', facts)).toEqual({ ...sections[1], sectionIndex: 1, part: 'footer', variant: 'even', pageCount: 2, lastPageNo: 12 })
})

it('uses first footer only on a single visible title page and preserves logical odd/even semantics', () => {
  const one = { sections, cuts: [cut(0, 10, 12)], titlePg: true, evenOddHf: true }
  expect(resolveDocxEdgeHfTarget('footer', one).variant).toBe('first')
  expect(resolveDocxEdgeHfTarget('footer', { ...one, titlePg: false }).variant).toBe('even')
  expect(resolveDocxEdgeHfTarget('footer', { ...one, titlePg: false, evenOddHf: false }).variant).toBe('default')
  expect(resolveDocxEdgeHfTarget('footer', { ...one, cuts: [cut(0, 10, 11)], titlePg: false }).variant).toBe('default')
})

it('uses source visible-page counting for parity duplicate starts', () => {
  const facts = { sections, cuts: [cut(0, 30, 1), cut(0, 30, 2)], titlePg: true, evenOddHf: true }
  expect(resolveDocxEdgeHfTarget('footer', facts)).toMatchObject({ pageCount: 1, lastPageNo: 2, variant: 'first' })
})

it('rejects missing or invalid measured facts rather than guessing default', () => {
  const facts = { sections, cuts: [cut(0, 10, 1)], titlePg: false, evenOddHf: false }
  expect(() => resolveDocxEdgeHfTarget('footer', { ...facts, cuts: [] })).toThrow()
  expect(() => resolveDocxEdgeHfTarget('header', { ...facts, sections: [] })).toThrow()
  expect(() => resolveDocxEdgeHfTarget('footer', { ...facts, cuts: [cut(0, 10, NaN)] })).toThrow()
  expect(() => resolveDocxEdgeHfTarget('footer', { ...facts, sections: [{ sectionId: '', expectedSectionSha256: 'sha' }] })).toThrow()
})
