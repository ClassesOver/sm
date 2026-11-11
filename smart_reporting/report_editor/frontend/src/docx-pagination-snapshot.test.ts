import { expect, it } from 'vitest'
import type { SectionInfo, SectionSettings } from '@genoffice/docx-engine'
import { slicePaginationSnapshot } from './vendor/genoffice-docs/apps/docs/src/renderer/pagination-snapshot'
import { restingHfAreaVariant } from './vendor/genoffice-docs/apps/docs/src/renderer/doc-state'

const settings: SectionSettings = { pageWidth: 3000, pageHeight: 1500, orientation: 'portrait', marginTop: 0, marginBottom: 0, marginLeft: 0, marginRight: 0, pageBorder: false, columns: 1, headerDist: 0, footerDist: 0 }
const hf = { header: null, footer: null, headerFirst: null, footerFirst: null, headerEven: null, footerEven: null, titlePg: false, evenOddHf: true }
const section = (first: number, last: number, extra: Partial<SectionInfo> = {}): SectionInfo => ({ settings, startType: 'nextPage', firstBlockIndex: first, lastBlockIndex: last, sectPrXml: '', titlePg: false, headerRefs: {}, footerRefs: {}, ...extra })

it('uses measured flow and source page numbering to identify an even last footer', () => {
  const sections = [section(0, 1, { pageNumberStart: 7 })]
  const snapshot = slicePaginationSnapshot({ section: settings, sections, live: sections, hf, hfParts: {}, colMode: 'none', colFlow: null, blocks: [{ top: 0, height: 60, section: 0 }, { top: 60, height: 60, section: 0 }], flowH: 120, factor: 1 })
  expect(snapshot.cuts.map(cut => cut.pageNo)).toEqual([7, 8])
  expect(restingHfAreaVariant('footer', { titlePg: false, evenOddHf: true, pageCount: snapshot.cuts.length, lastPageNo: snapshot.cuts.at(-1)!.pageNo })).toBe('even')
})

it('honors a later section restart and keeps the last logical page distinct from physical count', () => {
  const sections = [section(0, 0), section(1, 1, { pageNumberStart: 12 })]
  const snapshot = slicePaginationSnapshot({ section: settings, sections, live: sections, hf, hfParts: {}, colMode: 'none', colFlow: null, blocks: [{ top: 0, height: 30, section: 0 }, { top: 30, height: 30, section: 1 }], flowH: 60, factor: 1 })
  expect(snapshot.cuts.map(cut => [cut.section, cut.pageNo])).toEqual([[0, 1], [1, 12]])
})

it('retains a continuous section on the same physical page and selects the first-page footer for a one-page title', () => {
  const sections = [section(0, 0, { titlePg: true }), section(1, 1, { startType: 'continuous' })]
  const snapshot = slicePaginationSnapshot({ section: settings, sections, live: sections, hf: { ...hf, titlePg: true }, hfParts: {}, colMode: 'none', colFlow: null, blocks: [{ top: 0, height: 30, section: 0 }, { top: 30, height: 30, section: 1 }], flowH: 60, factor: 1 })
  expect(snapshot.cuts).toHaveLength(1)
  expect(snapshot.cuts[0]!.pageNo).toBe(1)
  expect(restingHfAreaVariant('footer', { titlePg: true, evenOddHf: true, pageCount: 1, lastPageNo: 1 })).toBe('first')
})
