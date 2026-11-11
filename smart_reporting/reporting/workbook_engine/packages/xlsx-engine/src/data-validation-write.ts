import { applyDvRules, DvEditError, type DvWireRule } from './data-validation'
import { readDataValidations } from './data-validation-read'
import { parseSheetElements, resolveWorksheetPath } from './workbook-read'
import { assemblePackage, createBufferEntrySource } from './zip'

/// Replace a fully modeled worksheet snapshot; retain every unrelated part.
export async function replaceSheetDataValidations(
  bytes: Uint8Array, sheetName: string, rules: readonly DvWireRule[],
): Promise<Uint8Array> {
  const source = await createBufferEntrySource(bytes)
  const sheet = parseSheetElements(await source.readText('xl/workbook.xml')).find(item => item.name === sheetName)
  if (!sheet?.relationshipId) throw new DvEditError(`工作表 ${sheetName} 不存在`)
  const path = await resolveWorksheetPath(source, sheet.relationshipId)
  const xml = await source.readText(path)
  const current = readDataValidations(xml)
  if (current.readOnlyReason) throw new DvEditError(current.readOnlyReason)
  const updated = applyDvRules(xml, rules)
  return (await assemblePackage(bytes, {
    replaced: new Map([[path, updated]]), added: new Map(), addedBinary: new Map(),
    removedEntries: [], addedEntries: [], touchedEntries: [path],
  })).buffer
}
