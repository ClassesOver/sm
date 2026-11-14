import { docxLineSpacingPatch, DOCX_LINE_SPACING_FIELDS } from './docx-line-spacing'

export const DOCX_PARAGRAPH_FLAGS = ['widowControl', 'keepNext', 'keepLines', 'suppressLineNumbers', 'pageBreakBefore', 'contextualSpacing'] as const
export type DocxParagraphProperties = Record<string, number | string | boolean>
/** 完整段落对话框只提交显式改动；旧工具栏协议的边界保持独立。 */
export function normalizeDocxParagraphProperties(value: unknown): DocxParagraphProperties {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('段落属性无效')
  const values = value as DocxParagraphProperties, entries = Object.entries(values)
  const numbers = ['indentLeft', 'indentRight', 'indentFirstLine', 'indentFirstLineChars', 'spaceBefore', 'spaceAfter', 'outlineLevel']
  if (!entries.length || entries.some(([key, n]) => {
    if ((DOCX_PARAGRAPH_FLAGS as readonly string[]).includes(key)) return typeof n !== 'boolean'
    if (key === 'align') return typeof n !== 'string' || !['left', 'center', 'right', 'justify'].includes(n)
    if ((DOCX_LINE_SPACING_FIELDS as readonly string[]).includes(key)) return false
    if (!numbers.includes(key) || typeof n !== 'number' || !Number.isSafeInteger(n)) return true
    return key === 'outlineLevel' ? n < 0 || n > 9 : key === 'indentFirstLineChars' ? n < 0 || n > 10000
      : key.startsWith('space') ? n < 0 || n > 31680 : n < -14400 || n > 14400
  }) || docxLineSpacingPatch(values) === null
    || values.indentFirstLineChars !== undefined && (values.indentFirstLine === undefined || Number(values.indentFirstLine) < 0)) throw new Error('段落属性值或字段无效')
  return { ...values }
}
