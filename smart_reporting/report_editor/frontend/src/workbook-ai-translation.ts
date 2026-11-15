import { formatAddress } from '@sheets-web/xlsx-engine/cell-address'
import type { NativeOperation } from './native-draft'
import type { WorkbookAISelection } from './workbook-native-ai'

// GenOffice ExcelShell.tsx TRANSLATE_LANGUAGES and zh.ts appTranslatePrompt.
export const workbookTranslationLanguages = [
  'English', '简体中文', '繁體中文', '日本語', '한국어', 'Español', 'Français',
  'Deutsch', 'Português', 'Русский', 'العربية',
] as const
export type WorkbookTranslationLanguage = typeof workbookTranslationLanguages[number]

export const workbookTranslationPrompt = (language: WorkbookTranslationLanguage) =>
  `把当前选中区域的文本翻译成${language},并把译文写回原单元格。只翻译普通文本；保留公式、数值、空白单元格和格式。`

export function requireWorkbookTranslation(
  operations: NativeOperation[], selection: WorkbookAISelection,
  cells: Record<string, { value?: unknown; formula?: string }>,
) {
  const seen = new Set<string>()
  const invalid = () => new Error('翻译候选只能替换选区内原有的普通文本，请重新生成。')
  for (const operation of operations) {
    if (operation.kind !== 'applyCellEdits' || !Array.isArray(operation.edits)) throw invalid()
    for (const edit of operation.edits) {
      if (edit?.sheetName !== selection.sheetName || !Number.isInteger(edit.row) || !Number.isInteger(edit.column) ||
          edit.row < selection.startRow || edit.row > selection.endRow || edit.column < selection.startColumn ||
          edit.column > selection.endColumn || edit.writeValue !== true || edit.style !== undefined ||
          typeof edit.cell?.value !== 'string' || !edit.cell.value.trim() || edit.cell.formula != null) throw invalid()
      const address = formatAddress(edit.row, edit.column)
      const original = cells[address]
      if (typeof original?.value !== 'string' || !original.value.trim() || original.formula || seen.has(address)) throw invalid()
      seen.add(address)
    }
  }
  if (!seen.size) throw invalid()
}
