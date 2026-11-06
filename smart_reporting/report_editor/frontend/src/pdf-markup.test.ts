import { pdfPageState } from './pdf-operations'
import { expect, it } from 'vitest'
import { MARKUP_COLORS, quadSetsMatch, viewToPdf } from './genoffice-pdf-annotations'
import { markupSelectionState, togglePdfMarkup, validatePdfMarkup, type PdfMarkupSelection } from './pdf-markup'
const q = [[40, 420, 150, 420, 40, 400, 150, 400]]
const selected: PdfMarkupSelection[] = [{ pageId: 'source:0', quads: q, saved: [] }, { pageId: 'source:2', quads: q, saved: [] }]
it.each(['highlight', 'underline', 'squiggly', 'strikeout'] as const)('adds and toggles pending %s in one complete batch', type => {
  const before = [{ kind: 'rotatePage', pageId: 'source:0', delta: 90 }]
  const added = togglePdfMarkup(selected, before, type, MARKUP_COLORS[type])
  expect(added.slice(1)).toEqual(selected.map(page => ({ kind: 'addMarkup', pageId: page.pageId, markupType: type, quads: q, color: MARKUP_COLORS[type] })))
  expect(markupSelectionState(selected, added, type).active).toBe(true)
  expect(togglePdfMarkup(selected, added, type, MARKUP_COLORS[type])).toEqual(before)
  expect(before).toHaveLength(1)
})
it('does not duplicate existing source markings and refuses their unsupported removal', () => {
  const source = [{ ...selected[0], saved: [{ markupType: 'underline' as const, quads: q, color: MARKUP_COLORS.underline }] }]
  expect(() => togglePdfMarkup(source, [], 'underline', MARKUP_COLORS.underline)).toThrow(/尚不能移除/)
  const mixed = [...source, selected[1]]
  const result = togglePdfMarkup(mixed, [], 'underline', MARKUP_COLORS.underline)
  expect(result).toHaveLength(1); expect(result[0].pageId).toBe('source:2')
  expect(() => togglePdfMarkup(mixed, result, 'underline', MARKUP_COLORS.underline)).toThrow(/尚不能移除/)
})
it('fails atomically on missing selection and record budget overflow', () => {
  expect(() => togglePdfMarkup([], [], 'underline', MARKUP_COLORS.underline)).toThrow()
  const before = Array.from({ length: 499 }, () => ({ kind: 'rotatePage', pageId: 'source:0', delta: 90 }))
  expect(() => togglePdfMarkup(selected, before, 'underline', MARKUP_COLORS.underline)).toThrow(/500/)
  expect(before).toHaveLength(499)
})
it('reuses pinned coordinate matching tolerances and four-direction UserUnit transforms', () => {
  expect(quadSetsMatch(q, [[41, 420, 151, 420, 41, 400, 151, 400]])).toBe(true)
  expect(quadSetsMatch(q, [[50, 420, 160, 420, 50, 400, 160, 400]])).toBe(false)
  const expected = [[20, 200], [30, 30], [100, 40], [90, 210]]
  for (const [index, rotation] of [0, 90, 180, 270].entries()) expect(viewToPdf({ pw: 200, ph: 400, x0: 10, y0: 20, rot: rotation, userUnit: 2 }, 20, 40)).toEqual(expected[index])
})

it('recognizes a legacy pending rectangle highlight instead of duplicating it', () => {
  const legacy = [{ kind: 'highlight', pageId: 'source:0', rect: [40, 400, 150, 420] }]
  expect(markupSelectionState([selected[0]], legacy, 'highlight').active).toBe(true)
  expect(togglePdfMarkup([selected[0]], legacy, 'highlight', MARKUP_COLORS.highlight)).toEqual([])
})

it('validates the complete selection before staging any page', () => {
  const bad = [...selected, { ...selected[0], quads: Array.from({ length: 201 }, () => q[0]) }]
  const before = [{ kind: 'rotatePage', pageId: 'source:0', delta: 90 }]
  expect(() => togglePdfMarkup(bad, before, 'underline', MARKUP_COLORS.underline)).toThrow(/200/)
  expect(before).toHaveLength(1)
})
it.each([{ color: [2, 0, 0] }, { quads: [[1, 2, 3]] }, { quads: [[40, 420, 40, 420, 40, 400, 40, 400]] }, { extra: true }])('rejects malformed stored markup $color $quads $extra', change => {
  expect(() => validatePdfMarkup({ kind: 'addMarkup', pageId: 'source:0', markupType: 'underline', quads: q, color: MARKUP_COLORS.underline, ...change })).toThrow()
})

it('rejects restored markup outside current bounds or after source-page deletion', () => {
  const pages = [{ pageId: 'source:0', index: 0, rotation: 0, mediaBox: { x: 0, y: 0, width: 400, height: 500 }, cropBox: { x: 0, y: 0, width: 400, height: 500 } }]
  const mark = { kind: 'addMarkup', pageId: 'source:0', markupType: 'underline', quads: q, color: MARKUP_COLORS.underline }
  expect(pdfPageState(pages, [mark])).toHaveLength(1)
  expect(() => pdfPageState(pages, [{ ...mark, quads: [[0, 600, 100, 600, 0, 580, 100, 580]] }])).toThrow()
  expect(() => pdfPageState(pages, [{ kind: 'deletePage', pageId: 'source:0' }, mark])).toThrow(/已删除/)
})
