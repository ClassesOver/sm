/** FontDialog 的作者属性；显示用 twins 不进入 DOCX 保存协议。 */
export const DOCX_FONT_PROPERTIES = ['fontAscii', 'eastAsiaFont', 'dstrike', 'caps', 'vanishOwn', 'charScalePct', 'charSpacingTwips', 'positionHalfPoints', 'kernHalfPoints'] as const
export const DOCX_FONT_DISPLAY = ['nativeFontDialog', 'charScaleEm', 'charScaleX', 'kern', 'vanish', 'eaSlotEmpty'] as const
export function docxFontProperties(spec: Record<string, unknown>): Record<string, unknown> {
  const out: Record<string, unknown> = {}
  for (const key of DOCX_FONT_PROPERTIES) if (key in spec) {
    const value = spec[key]
    if (value !== null) {
      const valid = ['fontAscii', 'eastAsiaFont'].includes(key) ? typeof value === 'string' && !!value.trim() && value.length <= 128 && !/[\x00-\x1f\x7f]/.test(value)
        : ['dstrike', 'vanishOwn'].includes(key) ? typeof value === 'boolean'
        : key === 'caps' ? ['all', 'small', 'none'].includes(String(value)) && typeof value === 'string'
        : typeof value === 'number' && Number.isSafeInteger(value) && (key === 'charScalePct' ? value >= 1 && value <= 600
          : key === 'charSpacingTwips' ? value >= -31680 && value <= 31680
          : key === 'positionHalfPoints' ? value >= -3168 && value <= 3168 : value >= 0 && value <= 3276)
      if (!valid) throw new Error('字体高级属性值无效')
    }
    out[key] = value
  }
  return out
}
