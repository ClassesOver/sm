// GenOffice Apache-2.0, fixed f8c17004 FontDialog.tsx: source attribute and per-run transaction helpers.
import type { Selection, Transaction } from '@tiptap/pm/state'
import { charScaleEm, wordKerns } from './vendor/genoffice-docs/apps/docs/src/renderer/line-metrics'
type SpacingMode = 'normal' | 'expanded' | 'condensed'
type PositionMode = 'normal' | 'raised' | 'lowered'
export interface CharSpacingState {
  scalePct: number
  spacing: SpacingMode
  spacingPt: number
  position: PositionMode
  positionPt: number
  kern: boolean
  kernPt: number
}

export function charSpacingFromAttrs(
  attrs: Record<string, unknown>,
  fallbackSizePt: number,
): CharSpacingState {
  const twips = attrs.charSpacingTwips
  const spacingTwips = typeof twips === 'number' ? twips : 0
  const half = attrs.positionHalfPoints
  const positionHalf = typeof half === 'number' ? half : 0
  const kernHalf = attrs.kernHalfPoints
  const scale = attrs.charScalePct
  return {
    scalePct: typeof scale === 'number' && scale > 0 ? scale : 100,
    spacing: spacingTwips > 0 ? 'expanded' : spacingTwips < 0 ? 'condensed' : 'normal',
    spacingPt: spacingTwips ? Math.abs(spacingTwips) / 20 : 1,
    position: positionHalf > 0 ? 'raised' : positionHalf < 0 ? 'lowered' : 'normal',
    positionPt: positionHalf ? Math.abs(positionHalf) / 2 : 3,
    kern: typeof kernHalf === 'number' && kernHalf > 0,
    kernPt: typeof kernHalf === 'number' && kernHalf > 0 ? kernHalf / 2 : fallbackSizePt,
  }
}

/** docTextStyle attrs for the advanced fields the user touched */
export function charSpacingAttrs(
  state: CharSpacingState,
  touched: ReadonlySet<string>,
  prior: Record<string, unknown>,
  sizeHalfPoints: number,
): Record<string, unknown> {
  const out: Record<string, unknown> = {}
  if (touched.has('scale')) {
    const pct = Math.round(state.scalePct)
    out.charScalePct = pct > 0 && pct !== 100 ? pct : null
    // the display twins are recomputed per text node by setTextStyleWithScale
    out.charScaleX = null
    out.charScaleEm = null
  }
  if (touched.has('spacing')) {
    const twips = Math.round(state.spacingPt * 20)
    out.charSpacingTwips =
      state.spacing === 'normal' || !twips ? null : state.spacing === 'condensed' ? -twips : twips
  }
  if (touched.has('position')) {
    const half = Math.round(state.positionPt * 2)
    out.positionHalfPoints =
      state.position === 'normal' || !half ? null : state.position === 'lowered' ? -half : half
  }
  if (touched.has('kern')) {
    const half = state.kern ? Math.max(1, Math.round(state.kernPt * 2)) : null
    // an explicit 0 switches kerning off when the style asked for it
    const kernHalfPoints = half ?? (prior.kernHalfPoints != null ? 0 : null)
    out.kernHalfPoints = kernHalfPoints
    out.kern = wordKerns(kernHalfPoints ?? undefined, sizeHalfPoints) ?? null
  }
  return out
}

/**
 * setMark('docTextStyle') for the dialog: merges `attrs` over each text node's
 * existing mark in every selection range (a table CellSelection is several) and,
 * when the scale changed, recomputes that node's w:w letter-spacing
 * approximation in the same step, so one undo reverts it all.
 */
export function setTextStyleWithScale(
  tr: Transaction,
  ranges: ReadonlyArray<{ from: number; to: number }>,
  attrs: Record<string, unknown>,
): boolean {
  const type = tr.doc.type.schema.marks.docTextStyle
  if (ranges.every((r) => r.from === r.to)) {
    // same base as setMark: the pending stored marks, else the marks at the caret
    const base = (tr.storedMarks ?? tr.selection.$from.marks()).find((m) => m.type === type)
    const merged = { ...(base?.attrs ?? {}), ...attrs }
    if ('charScalePct' in attrs) {
      // text not typed yet: assume Latin glyph widths
      const pct = merged.charScalePct as number | null
      merged.charScaleEm = pct && pct !== 100 ? charScaleEm('x', pct) : null
    }
    tr.addStoredMark(type.create(merged))
    return true
  }
  for (const { from, to } of ranges) {
    tr.doc.nodesBetween(from, to, (node, pos) => {
      if (!node.isText || !node.text) return
      const merged = { ...(node.marks.find((m) => m.type === type)?.attrs ?? {}), ...attrs }
      if ('charScalePct' in attrs) {
        const pct = merged.charScalePct as number | null
        merged.charScaleEm = pct && pct !== 100 ? charScaleEm(node.text, pct) : null
      }
      tr.addMark(Math.max(pos, from), Math.min(pos + node.nodeSize, to), type.create(merged))
    })
  }
  return true
}

/** the selection's ranges as plain positions (CellSelection = one per cell) */
export function selectionRanges(sel: Selection): Array<{ from: number; to: number }> {
  return sel.ranges.map((r) => ({ from: r.$from.pos, to: r.$to.pos }))
}

/** Font-tab values the dialog edits; `touched` keys: fontLatin, fontEastAsia, size, color, vertAlign */
export interface FontTabState {
  fontLatin: string
  fontEastAsia: string
  sizePt: number
  colorHex: string
  vertAlign: string
}

/** docTextStyle attrs for the Font-tab fields the user touched */
export function fontTabAttrs(
  state: FontTabState,
  touched: ReadonlySet<string>,
): Record<string, unknown> {
  const out: Record<string, unknown> = {}
  // each picker writes only its own rFonts slot; empty means inherit
  if (touched.has('fontLatin')) out.fontAscii = state.fontLatin || null
  if (touched.has('fontEastAsia')) {
    out.font = state.fontEastAsia || null
    out.eastAsiaFont = state.fontEastAsia || null
    out.eaSlotEmpty = state.fontEastAsia ? false : null
  }
  if (touched.has('size')) out.sizeHalfPoints = Math.round(state.sizePt * 2)
  if (touched.has('color')) out.color = state.colorHex.replace('#', '').toUpperCase()
  if (touched.has('vertAlign')) out.vertAlign = state.vertAlign || null
  return out
}

