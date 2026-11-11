import { formulaReferencesSheet, worksheetReferencesSheet } from '@sheets-web/xlsx-engine/sheets-edit'
import { extractElements } from '@sheets-web/xlsx-engine/xml'
import { normalizeInternalSheetFormula } from './workbook-internal-formula'

export type DataValidationRemovalSource = { readOnlyReason?: string; sourceXml: string }

/** 当前DV以live公式为准；未投影来源仅扫描可信原始DV块。 */
export function assertDataValidationSheetRemoval(workbook: any, subUnitId?: string, sourceForSheet?: (sheetId: string) => DataValidationRemovalSource | undefined): void {
  const target = subUnitId ? workbook?.getSheetBySheetId(subUnitId) : workbook?.getActiveSheet()
  if (!target) return
  const name = target.getSheetName()
  const references = (formula: unknown, type: unknown) => {
    if (typeof formula !== 'string' || type === 'list' && !formula.startsWith('=')) return false
    return formulaReferencesSheet(normalizeInternalSheetFormula(formula, workbook.getId(), name), name)
  }
  for (const sheet of workbook.getSheets()) {
    if (sheet.getSheetId() === target.getSheetId()) continue
    const source = sourceForSheet?.(sheet.getSheetId())
    if (source?.readOnlyReason && (typeof source.sourceXml !== 'string' || [...source.sourceXml.matchAll(/<([\w.-]+):dataValidations?\b/g)].some(match => match[1] !== 'x14')))
      throw new Error(`工作表 "${sheet.getSheetName()}" 的数据验证来源无法完整核对，请同步后重试删除。`)
    const raw = source?.readOnlyReason ? [...extractElements(source.sourceXml, 'dataValidations'), ...extractElements(source.sourceXml, 'x14:dataValidations')].join('') : ''
    if ([...raw.matchAll(/<([\w.-]+):(formula[12]|f)\b/g)].some(match => match[1] !== (match[2] === 'f' ? 'xm' : 'x14')))
      throw new Error(`工作表 "${sheet.getSheetName()}" 的数据验证来源无法完整核对，请同步后重试删除。`)
    if ((sheet.getDataValidations?.() ?? []).some(({ rule }: any) => references(rule.formula1, rule.type) || references(rule.formula2, rule.type)) || raw && worksheetReferencesSheet(raw, name))
      throw new Error(`工作表 "${sheet.getSheetName()}" 的数据验证仍引用 "${name}"，已拒绝删除。`)
  }
}
