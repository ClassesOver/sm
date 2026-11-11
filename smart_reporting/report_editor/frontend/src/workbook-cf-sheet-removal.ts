import { formulaReferencesSheet, worksheetReferencesSheet } from '@sheets-web/xlsx-engine/sheets-edit'
import { extractElements } from '@sheets-web/xlsx-engine/xml'
import type { ConditionalFormattingSnapshot } from '@sheets-web/xlsx-engine/conditional-formatting-read'

export type ConditionalFormattingRemovalSource = Pick<ConditionalFormattingSnapshot, 'issues' | 'sourceXml'>

/** 删除前检查存续CF；完整投影以当前编辑为准，不完整来源仅扫描原始CF块。 */
export function assertConditionalFormattingSheetRemoval(workbook: any, subUnitId?: string, sourceForSheet?: (sheetId: string) => ConditionalFormattingRemovalSource | undefined): void {
  const target = subUnitId ? workbook?.getSheetBySheetId(subUnitId) : workbook?.getActiveSheet()
  if (!target) return
  const name = target.getSheetName()
  const references = (value: unknown): boolean => {
    if (Array.isArray(value)) return value.some(references)
    if (!value || typeof value !== 'object') return false
    const item = value as Record<string, unknown>
    return ((item.type === 'formula' || item.subType === 'formula') && typeof item.value === 'string' && formulaReferencesSheet(item.value, name))
      || Object.values(item).some(references)
  }
  for (const sheet of workbook.getSheets()) {
    if (sheet.getSheetId() === target.getSheetId()) continue
    const source = sourceForSheet?.(sheet.getSheetId())
    const raw = source?.issues.length ? [...extractElements(source.sourceXml, 'conditionalFormatting'), ...extractElements(source.sourceXml, 'x14:conditionalFormatting')].join('') : ''
    if ((sheet.getConditionalFormattingRules?.() ?? []).some((rule: any) => references(rule.rule)) || raw && worksheetReferencesSheet(raw, name))
      throw new Error(`工作表 "${sheet.getSheetName()}" 的条件格式仍引用 "${name}"，已拒绝删除。`)
  }
}
