import { formatSheetQualifier } from '@sheets-web/xlsx-engine/sheets-edit'

/** 仅去掉确切runtime unitId，表名大小写等价；字符串和其他外簿保持原样。 */
export function normalizeInternalSheetFormula(formula: string, unitId: string, sheetName: string): string {
  const prefix = `[${unitId}]`
  return formula.split('"').map((segment, index) => index % 2 ? segment : segment.replace(
    /('(?:[^']|'')+'|\[[^\]]+\][\p{L}_][\p{L}\p{N}_.]*)!/gu,
    (full, qualifier: string) => {
      const decoded = qualifier.startsWith("'") ? qualifier.slice(1, -1).replaceAll("''", "'") : qualifier
      return decoded.startsWith(prefix) && decoded.slice(prefix.length).toUpperCase() === sheetName.toUpperCase()
        ? `${formatSheetQualifier(sheetName)}!` : full
    },
  )).join('"')
}
