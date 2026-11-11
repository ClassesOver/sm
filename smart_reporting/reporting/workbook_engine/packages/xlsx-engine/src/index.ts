/// @sheets-web/xlsx-engine public API.
/// Browser-safe xlsx read/patch engine ported from genoffice's xlsx-gateway
/// (Uint8Array I/O, no node: imports, no sidecar).

export * from './cell-address'
export * from './cf-read'
export * from './cf-schemas'
export * from './conditional-formatting-read'
export * from './conditional-formatting-snapshot'
export * from './conditional-formatting-schema'
export { cfRuleUnsaveableReason, iconSetSaveable } from './conditional-formatting-source'
export type { CfWireRule as ConditionalFormattingWireRule } from './conditional-formatting-source'
export * from './chart-read'
export * from './defined-names'
export * from './geometry'
export * from './number-format'
export * from './sparklines'
export * from './sparkline-additions'
export * from './chart-data'
export * from './chart-recommend'
export * from './edit-schemas'
export * from './sha256'
export * from './style-color'
export * from './style-read'
export * from './styles-write'
export * from './blank'
export * from './chart-add'
export * from './chart-delete'
export * from './chart-edit'
export * from './csv'
export * from './flash-fill'
export * from './filter-read'
export * from './filters'
export * from './notes'
export * from './note-read'
export * from './sort-range'
export * from './table-add'
export * from './table-read'
export * from './table-edit'
export * from './theme'
export * from './page-setup'
export * from './protection'
export * from './pivot-add'
export * from './pivot-expand'
export * from './pivot-filters'
export * from './pivot-formula'
export * from './pivot-grouping'
export * from './pivot-refresh'
export * from './rules'
export * from './sheets-edit'
export * from './sheet-ops'
export * from './structural'
export * from './cell-shift'
export * from './protection-read'
export * from './workbook-read'
export * from './workbook-write'
export * from './xlsx-escapes'
export * from './zip'
export { shortDateNumFmtId, setSystemShortDate, getSystemShortDate } from './short-date'
export {
  normalizeOoxmlPartPrefix,
  decodeXmlText,
  decodeCellText,
  escapeCellText,
  escapeXmlAttribute,
  escapeXmlText,
  readXmlAttribute,
} from './xml'
export { spillsDynamicArray, withFutureFunctionMarkers } from './future-functions'

export * from './outline'

export { isPivotCacheDefinitionPath, pivotCacheReadsFromSheet, renameSheetInPivotCacheSource } from './pivot-cache-source'

export type { SheetTableSource } from './table-source'
