import { expect, it } from 'vitest'
import { stagePdfPatternRedactions } from './pdf-redact-find'
import type { SearchIndex } from './genoffice-pdf-search'
import type { PdfPageIdentity } from './pdf-operations'

const cropBox = { x: 0, y: 0, width: 400, height: 300 }
const pages: PdfPageIdentity[] = [0, 1].map(index => ({ pageId: `p${index}`, index, rotation: 0, cropBox, mediaBox: cropBox }))
function entry(text: string, options = {}) {
  return { text, lower: text.toLowerCase(), items: [{ start: 0, end: text.length, x: 30, y: 100, w: text.length * 5, h: 10, ...options }] }
}
it('stages only the selected pattern and skips deleted source pages', () => {
  const index: SearchIndex = [entry('Email sample@example.com and date 2026-11-15'), entry('gone@example.com')]
  const deleted = { kind: 'deletePage', pageId: 'p1' }
  const result = stagePdfPatternRedactions(index, pages, [deleted], ['email'])
  expect(result).toMatchObject({ hits: 1, skipped: 0, capped: false })
  expect(result.operations).toEqual([deleted, { kind: 'redact', pageId: 'p0', rect: [59, 97.5, 151, 110.5] }])
  expect(stagePdfPatternRedactions(index, pages, result.operations, ['email']).operations).toEqual(result.operations)
})
it('skips an entire unsafe multi-run hit and reports limits without partial staging', () => {
  const text = 'staff@example.com'
  const first = entry(text).items[0]
  const split = { ...entry(text), items: [{ ...first, end: 6, w: 30 }, { ...first, start: 6, x: 60, w: 55 }] }
  expect(stagePdfPatternRedactions([{ ...split, items: [split.items[0], { ...split.items[1], rot: true }] }], pages, [], ['email'])).toMatchObject({ hits: 0, skipped: 1, operations: [] })
  expect(stagePdfPatternRedactions([{ ...split, items: [split.items[0], { ...split.items[1], x: 399 }] }], pages, [], ['email'])).toMatchObject({ hits: 0, skipped: 1, operations: [] })
  expect(stagePdfPatternRedactions([{ ...split, items: [split.items[0]] }], pages, [], ['email'])).toMatchObject({ hits: 0, skipped: 1, operations: [] })
  const operations = Array.from({ length: 499 }, (_, i) => ({ kind: 'redact', pageId: 'p0', rect: [1, 1, 4 + i / 10, 4] }))
  expect(stagePdfPatternRedactions([split], pages, operations, ['email'])).toMatchObject({ hits: 0, capped: true, operations })
})
