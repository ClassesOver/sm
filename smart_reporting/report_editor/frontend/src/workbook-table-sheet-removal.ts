import { decodeXmlText, extractElements, readXmlAttribute, sectionInner } from '@sheets-web/xlsx-engine/xml'
import { unprojectedCellFormulaNodes } from './workbook-cell-formula-removal'
import type { DefinedNameRemovalSource } from './workbook-defined-name-removal'

export type TableSheetRemovalSource = DefinedNameRemovalSource & {
  tables: readonly { name: string; displayName: string }[]
  readOnlyReason?: string
  retainedNames?: readonly string[]
  worksheet?: (sheetId: string) => { xml: string; conditionalFormattingIncomplete?: boolean; dataValidationIncomplete?: boolean } | undefined
}

/** 与文件侧TableName[检查一致；当前可编辑投影使用live，未投影部分使用可信来源。 */
export function assertTableSheetRemoval(workbook: any, subUnitId: string | undefined, source: TableSheetRemovalSource): void {
  const target = subUnitId ? workbook?.getSheetBySheetId(subUnitId) : workbook?.getActiveSheet()
  if (!target) return
  if (source.readOnlyReason) throw new Error(`表格来源无法完整核对：${source.readOnlyReason}`)
  if (typeof workbook.getTableList !== 'function') throw new Error('表格来源正在同步，请稍后重试删除')
  const retained = new Set(source.retainedNames?.map(name => name.toLowerCase()))
  const names = new Set(source.tables.flatMap(table => [table.name, table.displayName]).filter(name => !retained.has(name.toLowerCase())))
  for (const table of workbook.getTableList()) if (table.subUnitId === target.getSheetId() && !retained.has(table.name.toLowerCase())) names.add(table.name)
  if (!names.size) return
  const references = (value: unknown): string | undefined => {
    if (typeof value === 'string') return [...names].find(name => value.toLowerCase().includes(`${name}[`.toLowerCase()))
    if (!value || typeof value !== 'object') return undefined
    for (const item of Object.values(value)) { const name = references(item); if (name) return name }
  }
  const reject = (value: unknown, location: string) => {
    const name = references(value)
    if (name) throw new Error(`${location} 仍引用表格 "${name}"，已拒绝删除。`)
  }
  for (const sheet of workbook.getSheets()) {
    if (sheet.getSheetId() === target.getSheetId()) continue
    const location = `工作表 "${sheet.getSheetName()}"`
    sheet.getSheet().getCellMatrix().forValue((row: number, column: number, cell: any) => {
      if (!cell?.f && !cell?.si) return
      const formula = sheet.getRange(row, column).getFormula() || cell.f
      if (typeof formula !== 'string' || !formula) throw new Error(`${location} 的共享公式无法完整读取，请同步后重试删除。`)
      reject(formula, location)
    })
    reject((sheet.getConditionalFormattingRules?.() ?? []).map((rule: any) => rule.rule), location)
    reject((sheet.getDataValidations?.() ?? []).map(({ rule }: any) => [rule.formula1, rule.formula2]), location)
    const raw = source.worksheet?.(sheet.getSheetId())
    if (raw) {
      reject(unprojectedCellFormulaNodes(raw.xml).join(''), location)
      if (raw.conditionalFormattingIncomplete) reject([...extractElements(raw.xml, 'conditionalFormatting'), ...extractElements(raw.xml, 'x14:conditionalFormatting')], location)
      if (raw.dataValidationIncomplete) reject([...extractElements(raw.xml, 'dataValidations'), ...extractElements(raw.xml, 'x14:dataValidations')], location)
    }
  }
  for (const entry of workbook.getDefinedNames()) {
    if (entry.getLocalSheetId?.() === target.getSheetId()) continue
    reject(entry.getFormulaOrRefString(), `定义名称 "${entry.getName()}"`)
  }
  const sheetNames = extractElements(sectionInner(source.workbookXml, 'sheets') ?? '', 'sheet').map(node => decodeXmlText(readXmlAttribute(node, 'name') ?? ''))
  for (const node of extractElements(sectionInner(source.workbookXml, 'definedNames') ?? '', 'definedName')) {
    const tag = node.match(/^<[^>]*>/)?.[0] ?? '', name = decodeXmlText(readXmlAttribute(tag, 'name') ?? ''), local = readXmlAttribute(tag, 'localSheetId')
    const scopeName = local === undefined ? undefined : /^\d+$/.test(local) ? sheetNames[Number(local)] : undefined
    if (scopeName === target.getSheetName()) continue
    const scopeId = scopeName === undefined ? undefined : workbook.getSheets().find((sheet: any) => sheet.getSheetName() === scopeName)?.getSheetId()
    if (name.toLowerCase().startsWith('_xlnm.') || source.unprojectedNames?.some(entry => entry.name.toLowerCase() === name.toLowerCase() && entry.scopeSheetId === scopeId))
      reject(decodeXmlText(node.match(/^[^>]*>([\s\S]*?)<\/definedName>$/)?.[1] ?? ''), `未完整投影的定义名称 "${name}"`)
  }
}
