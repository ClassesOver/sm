export const DOCX_LINE_SPACING_FIELDS = ['lineSpacing', 'lineRule', 'lineRawTwips'] as const
type LinePatch = { lineSpacing?: number | null; lineRule?: 'exact' | 'atLeast' | null; lineRawTwips?: number | null }

/** 倍数与固定/最小行距互斥；范围和倍数精度沿用源 ParagraphDialog。 */
export function docxLineSpacingPatch(values: Record<string, unknown>): LinePatch | null {
  const { lineSpacing, lineRule, lineRawTwips } = values
  if (DOCX_LINE_SPACING_FIELDS.every(key => values[key] === undefined)) return {}
  if (lineRule === 'exact' || lineRule === 'atLeast') {
    if (lineSpacing !== undefined || typeof lineRawTwips !== 'number' || !Number.isSafeInteger(lineRawTwips)
      || lineRawTwips < 20 || lineRawTwips > 31680) return null
    return { lineSpacing: null, lineRule, lineRawTwips }
  }
  if (lineRule !== undefined || lineRawTwips !== undefined || typeof lineSpacing !== 'number'
    || !Number.isFinite(lineSpacing) || lineSpacing < 0.06 || lineSpacing > 132
    || lineSpacing !== Math.round(lineSpacing * 100) / 100) return null
  return { lineSpacing, lineRule: null, lineRawTwips: null }
}
