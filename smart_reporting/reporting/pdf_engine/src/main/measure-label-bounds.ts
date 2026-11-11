import { StandardFontEmbedder } from 'pdf-lib'
import { FontNames } from '@pdf-lib/standard-fonts'

const helvetica = StandardFontEmbedder.for(FontNames.Helvetica)
const num = (value: number) => Math.round(value * 100) / 100

/** Conservative Standard14 ink bounds for the writer's literal, unkerned 9pt Tj. */
export function measureLabelBounds(from: readonly number[], to: readonly number[], label: string): [number, number, number, number] {
  const angle = Math.atan2(to[1]! - from[1]!, to[0]! - from[0]!)
  const tilt = Math.abs(angle) > Math.PI / 2 ? angle + Math.PI : angle
  // Use the actual serialized Tm, including its two-decimal rotation and origin.
  const a = num(Math.cos(tilt)), b = num(Math.sin(tilt)), c = num(-Math.sin(tilt)), d = num(Math.cos(tilt))
  const e = num((from[0]! + to[0]!) / 2), f = num((from[1]! + to[1]!) / 2 + 6)
  const [left, bottom, right, top] = helvetica.font.FontBBox
  let advance = 0, minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity
  for (const char of label) {
    const codePoint = char.codePointAt(0)!
    const glyph = helvetica.encoding.encodeUnicodeCodePoint(codePoint)
    // The pinned writer emits literal low bytes rather than encodeText().
    if (codePoint > 255 || glyph.code !== codePoint) throw new Error('pdf_measure_label_literal_encoding_mismatch')
    // AFM exposes a full-font BBox, not individual glyph ink boxes. Union it at
    // each glyph origin rather than treating average advance as visible ink.
    for (const gx of [left, right]) for (const gy of [bottom, top]) {
      const x = (advance + gx!) * 9 / 1000, y = gy! * 9 / 1000
      const px = a * x + c * y + e, py = b * x + d * y + f
      minX = Math.min(minX, px); minY = Math.min(minY, py)
      maxX = Math.max(maxX, px); maxY = Math.max(maxY, py)
    }
    // Tj has no pair adjustments: widthOfTextAtSize(string) would add kerning.
    const width = helvetica.font.getWidthOfGlyph(glyph.name)
    if (width === undefined) throw new Error('pdf_measure_label_glyph_width_unavailable')
    advance += width
  }
  return [minX, minY, maxX, maxY]
}
