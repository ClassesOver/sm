import { formulaReferencesSheet } from '@sheets-web/xlsx-engine/sheets-edit'
import { decodeXmlText, extractElements, readXmlAttribute, sectionInner } from '@sheets-web/xlsx-engine/xml'
import { normalizeInternalSheetFormula } from './workbook-internal-formula'

export type DefinedNameRemovalSource = {
  workbookXml: string
  unprojectedNames?: readonly { name: string; scopeSheetId?: string }[]
}

/** 删除前直接读全量facade；名称管理器过滤内置名称，不能用其列表做依赖校验。 */
export function assertDefinedNameSheetRemoval(workbook: any, subUnitId?: string, source?: DefinedNameRemovalSource): void {
  const target = subUnitId ? workbook?.getSheetBySheetId(subUnitId) : workbook?.getActiveSheet()
  if (!target) return
  const targetId = target.getSheetId(), targetName = target.getSheetName()
  const references = (formula: string) => formulaReferencesSheet(normalizeInternalSheetFormula(formula, workbook.getId(), targetName), targetName)
  if (typeof workbook.getDefinedNames !== 'function') throw new Error('定义名称无法完整读取，请同步后重试删除。')
  for (const entry of workbook.getDefinedNames()) {
    const scope = entry.getLocalSheetId?.()
    if (scope === targetId) continue
    if (scope && scope !== 'AllDefaultWorkbook' && !workbook.getSheetBySheetId(scope)) throw new Error('定义名称的作用域无法完整核对，请同步后重试删除。')
    const name = entry.getName?.(), formula = entry.getFormulaOrRefString?.()
    if (!name || typeof formula !== 'string') throw new Error('定义名称无法完整读取，请同步后重试删除。')
    if (references(formula)) throw new Error(`定义名称 "${name}" 仍引用 "${targetName}"，已拒绝删除。`)
  }
  if (!source) return
  const xml = source.workbookXml
  if (/<[\w.-]+:(?:definedNames|definedName|sheets|sheet)\b/.test(xml)) throw new Error('定义名称来源无法完整核对，请同步后重试删除。')
  const sheets = extractElements(sectionInner(xml, 'sheets') ?? '', 'sheet').map(node => decodeXmlText(readXmlAttribute(node.match(/^<[^>]*>/)?.[0] ?? '', 'name') ?? ''))
  for (const node of extractElements(sectionInner(xml, 'definedNames') ?? '', 'definedName')) {
    const tag = node.match(/^<[^>]*>/)?.[0] ?? '', name = decodeXmlText(readXmlAttribute(tag, 'name') ?? ''), local = readXmlAttribute(tag, 'localSheetId')
    const scopeName = local === undefined ? undefined : /^\d+$/.test(local) ? sheets[Number(local)] : undefined
    if (scopeName === targetName) continue
    const scopeId = scopeName === undefined ? undefined : workbook.getSheets().find((sheet: any) => sheet.getSheetName() === scopeName)?.getSheetId()
    const invalidScope = local !== undefined && (!scopeName || !scopeId)
    const unprojected = source.unprojectedNames?.some(entry => entry.name.toLowerCase() === name.toLowerCase() && entry.scopeSheetId === scopeId)
    if (invalidScope || !name || name.toLowerCase().startsWith('_xlnm.') || unprojected) {
      const formula = decodeXmlText(node.match(/^[^>]*>([\s\S]*?)<\/definedName>$/)?.[1] ?? '')
      if (invalidScope || !name || !formula) throw new Error('定义名称来源或作用域无法完整核对，请同步后重试删除。')
      if (references(formula)) throw new Error(`未完整投影的定义名称 "${name}" 仍引用 "${targetName}"，已拒绝删除。`)
    }
  }
}
