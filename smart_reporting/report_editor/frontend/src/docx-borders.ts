import type { Editor } from '@tiptap/core'
import { closeHistory } from '@tiptap/pm/history'
import { highlightTarget } from './docx-highlight'
import { DOCX_SHADING_COLORS } from './docx-shading'

// GenOffice f8c17004 table-borders.ts pen defaults (borderColor '000000', borderSz
// 4 eighth-points = 0.5pt) plus generate.ts pBdr sides (top/left/bottom/right);
// paragraphs only ever write w:val="single" lines (generate.ts formatPPrChildren).
export const DOCX_BORDER_COLORS = DOCX_SHADING_COLORS
/** single line style is the only paragraph border the strict bridge writes; other
 *  OOXML line styles (double, dashed, art…) fail closed in the bridge. */
export const DOCX_BORDER_VAL = 'single'
export const DOCX_BORDER_WIDTHS_PT = [0.5, 0.75, 1.5, 2.25, 3] as const
export type DocxBorderSide = 'top' | 'bottom' | 'left' | 'right'
/** canonical PM subset string order (parse-props.ts paraBordersOf: t,b,l,r) */
export const DOCX_BORDER_SIDE_CHARS: Record<DocxBorderSide, string> = { top: 't', bottom: 'b', left: 'l', right: 'r' }
const SIDE_ORDER = ['t', 'b', 'l', 'r'] as const
export interface DocxBorderLine { color?: string; szPt?: number; spacePt?: number }
/** per-position line definitions or a null clear, mirroring the bridge protocol. */
export type DocxBorderSpec = Array<{ side: DocxBorderSide; val: string; color?: string; szPt?: number; spacePt?: number }>

const sideOf = (char: string): DocxBorderSide =>
  (Object.keys(DOCX_BORDER_SIDE_CHARS) as DocxBorderSide[]).find(side => DOCX_BORDER_SIDE_CHARS[side] === char)!
const canonical = (chars: string) => [...chars].sort((left, right) => SIDE_ORDER.indexOf(left as 't') - SIDE_ORDER.indexOf(right as 't'))

/** Strict protocol form: per-position single lines or a null clear (saved drafts). */
export function safeDocxBorderSpec(value: unknown): DocxBorderSpec | null {
  if (value === null) return null
  if (!Array.isArray(value) || !value.length || value.length > 4) throw new Error('段落边框无效；仅支持上、下、左、右的单实线组合')
  const seen = new Set<string>()
  const spec = value.map(entry => {
    if (!entry || typeof entry !== 'object' || Array.isArray(entry)) throw new Error('段落边框无效；仅支持上、下、左、右的单实线组合')
    const line = entry as Record<string, unknown>
    if (Object.keys(line).some(key => !['side', 'val', 'color', 'szPt', 'spacePt'].includes(key))) throw new Error('段落边框字段无效')
    if (typeof line.side !== 'string' || !(line.side in DOCX_BORDER_SIDE_CHARS) || seen.has(line.side)) throw new Error('段落边框位置无效；仅支持上、下、左、右')
    seen.add(line.side)
    if (line.val !== DOCX_BORDER_VAL) throw new Error('段落边框线型无效；仅支持单实线')
    if (line.color !== undefined && line.color !== null && (typeof line.color !== 'string' || !/^[0-9a-fA-F]{6}$/.test(line.color))) throw new Error('段落边框颜色无效；仅支持六位十六进制 RGB 或 auto')
    if (line.szPt !== undefined && line.szPt !== null && (typeof line.szPt !== 'number' || !Number.isFinite(line.szPt) || line.szPt <= 0 || line.szPt > 12 || !Number.isInteger(line.szPt * 8))) throw new Error('段落边框宽度无效；仅支持 0–12pt 的八分之一点整数倍')
    if (line.spacePt !== undefined && line.spacePt !== null && (typeof line.spacePt !== 'number' || !Number.isInteger(line.spacePt) || (line.spacePt as number) < 0 || (line.spacePt as number) > 31)) throw new Error('段落边框边距无效；仅支持 0–31pt 的整数')
    return {
      side: line.side as DocxBorderSide,
      val: DOCX_BORDER_VAL,
      ...(typeof line.color === 'string' ? { color: line.color.toUpperCase() } : {}),
      ...(typeof line.szPt === 'number' ? { szPt: line.szPt } : {}),
      ...(typeof line.spacePt === 'number' ? { spacePt: line.spacePt } : {}),
    }
  })
  spec.sort((left, right) => SIDE_ORDER.indexOf(DOCX_BORDER_SIDE_CHARS[left.side] as 't') - SIDE_ORDER.indexOf(DOCX_BORDER_SIDE_CHARS[right.side] as 't'))
  return spec
}

/** Strict Home-menu pen input: canonical "tblr" subset plus one line look; null
 *  clears the direct w:pBdr. Expands to the same per-position protocol form. */
export function safeDocxBorders(value: unknown): DocxBorderSpec | null {
  if (value === null || value === undefined) return null
  if (typeof value !== 'object' || Array.isArray(value)) throw new Error('段落边框无效；仅支持上、下、左、右的单实线组合')
  const pen = value as Record<string, unknown>
  if (Object.keys(pen).some(key => !['sides', 'color', 'szPt', 'spacePt'].includes(key))) throw new Error('段落边框字段无效')
  if (typeof pen.sides !== 'string' || !/^[t]?[b]?[l]?[r]?$/.test(pen.sides) || !pen.sides) throw new Error('段落边框位置无效；仅支持上、下、左、右的组合')
  if (pen.color !== undefined && pen.color !== null && (typeof pen.color !== 'string' || !/^[0-9a-fA-F]{6}$/.test(pen.color))) throw new Error('段落边框颜色无效；仅支持六位十六进制 RGB 或 auto')
  if (pen.szPt !== undefined && pen.szPt !== null && (typeof pen.szPt !== 'number' || !Number.isFinite(pen.szPt) || pen.szPt <= 0 || pen.szPt > 12 || !Number.isInteger(pen.szPt * 8))) throw new Error('段落边框宽度无效；仅支持 0–12pt 的八分之一点整数倍')
  if (pen.spacePt !== undefined && pen.spacePt !== null && (typeof pen.spacePt !== 'number' || !Number.isInteger(pen.spacePt) || (pen.spacePt as number) < 0 || (pen.spacePt as number) > 31)) throw new Error('段落边框边距无效；仅支持 0–31pt 的整数')
  return canonical(pen.sides).map(char => ({
    side: sideOf(char),
    val: DOCX_BORDER_VAL,
    ...(typeof pen.color === 'string' ? { color: pen.color.toUpperCase() } : {}),
    ...(typeof pen.szPt === 'number' ? { szPt: pen.szPt } : {}),
    ...(typeof pen.spacePt === 'number' ? { spacePt: pen.spacePt } : {}),
  }))
}

/** Canonical per-side look of the paragraph's direct borders from the pinned
 *  schema attrs (borders subset string + borderLines JSON); display reader. */
export function paragraphBorders(node: { attrs?: Record<string, unknown> | null }): DocxBorderSpec | null {
  const sides = node.attrs?.borders
  if (typeof sides !== 'string' || !sides) return null
  let lines: Partial<Record<string, DocxBorderLine>> = {}
  if (typeof node.attrs?.borderLines === 'string' && node.attrs.borderLines) {
    try {
      const parsed = JSON.parse(node.attrs.borderLines)
      if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) lines = parsed
    } catch { lines = {} }
  }
  return canonical(sides).map(char => {
    const line = lines[char] ?? {}
    return {
      side: sideOf(char),
      val: DOCX_BORDER_VAL,
      ...(typeof line.color === 'string' ? { color: line.color } : {}),
      ...(typeof line.szPt === 'number' ? { szPt: line.szPt } : {}),
      ...(typeof line.spacePt === 'number' ? { spacePt: line.spacePt } : {}),
    }
  })
}

/** Rebuild the schema attrs (borders string + borderLines JSON) from the protocol. */
export function docxBorderAttrs(spec: DocxBorderSpec | null): { borders: string | null; borderLines: string | null } {
  if (!spec || !spec.length) return { borders: null, borderLines: null }
  const lines: Partial<Record<string, DocxBorderLine>> = {}
  for (const line of spec) {
    const char = DOCX_BORDER_SIDE_CHARS[line.side]
    if (!char || line.val !== DOCX_BORDER_VAL) throw new Error('段落边框无效；仅支持上、下、左、右的单实线组合')
    lines[char] = {
      ...(typeof line.color === 'string' ? { color: line.color } : {}),
      ...(typeof line.szPt === 'number' ? { szPt: line.szPt } : {}),
      ...(typeof line.spacePt === 'number' ? { spacePt: line.spacePt } : {}),
    }
  }
  return { borders: Object.keys(lines).join(''), borderLines: JSON.stringify(lines) }
}

export function paragraphBordersTarget(editor: Editor, anchors: Parameters<typeof highlightTarget>[1]) {
  return highlightTarget(editor, anchors.map(anchor => ({ ...anchor, editable: anchor.paragraphBordersEditable ?? anchor.editable })), true)
}
/** 独立来源能力与底纹同规，不放宽普通正文editable。 */
export function applyParagraphBorders(editor: Editor, anchors: Parameters<typeof highlightTarget>[1], value: unknown) {
  const spec = safeDocxBorders(value)
  const target = paragraphBordersTarget(editor, anchors)
  if (!editor.isEditable || !target) return false
  const attrs = target.node.attrs
  if (attrs.borderReset || attrs.borderPad) return false
  editor.view.dispatch(closeHistory(editor.state.tr.setNodeMarkup(target.from - 1, undefined, { ...attrs, ...docxBorderAttrs(spec) })))
  editor.commands.focus()
  return true
}
