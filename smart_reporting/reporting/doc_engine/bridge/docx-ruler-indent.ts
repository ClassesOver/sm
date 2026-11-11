/** 标尺的绝对段落缩进；源尺规位置已换算为有符号整数twips。 */
export interface DocxRulerIndentValues { leftTwips?: number; firstLineTwips?: number }
export function normalizeDocxRulerIndent(value: unknown): DocxRulerIndentValues {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('标尺缩进值无效')
  const fields = Object.entries(value)
  if (!fields.length || fields.some(([key, n]) => !['leftTwips', 'firstLineTwips'].includes(key)
    || typeof n !== 'number' || !Number.isSafeInteger(n) || n < -14400 || n > 14400)) throw new Error('标尺缩进值无效')
  return Object.fromEntries(fields)
}
