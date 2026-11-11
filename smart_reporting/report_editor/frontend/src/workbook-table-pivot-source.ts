import { pivotCacheReadsFromTable } from '@sheets-web/xlsx-engine/pivot-cache-source'
import { pivotFieldRenameReason, type PivotFieldRenameSupport } from '@sheets-web/xlsx-engine/pivot-source-field-rename'

export type TableColumnChangeReason = (table: any, nextNames: readonly string[], nextStartColumn?: number) => string | undefined

// 使用实际文件缓存，不把尚未进入缓存的新列也锁死，确保新增列仍可撤销。
export function tablePivotColumnChangeReason(table: any, nextNames: readonly string[], caches: readonly string[] | Error | undefined, aliases?: readonly string[], nextStartColumn = table.range?.startColumn ?? 0, support?: PivotFieldRenameSupport | Error): string | undefined {
  const oldStart = table.range?.startColumn ?? 0
  const removed = table.columns.map((column: any) => column.displayName as string).filter((name: string, index: number) => nextNames[oldStart + index - nextStartColumn] !== name)
  const sourceNames = aliases ?? [table.name]
  if (!removed.length || !sourceNames.length) return
  if (!caches) return '透视表来源正在同步，请稍后重试字段修改'
  if (caches instanceof Error) return caches.message
  if (support && !(support instanceof Error) && nextStartColumn === oldStart && table.columns.length === support.fieldNames.length && nextNames.length === support.fieldNames.length) {
    return pivotFieldRenameReason(support, nextNames)
  }
  try {
    for (const xml of caches) if (sourceNames.some(name => pivotCacheReadsFromTable(xml, name, removed))) {
      if (support instanceof Error) return '透视缓存仍引用此表格字段，当前不能自动迁移：' + support.message
      return '透视缓存仍引用此表格字段，不能移除或更名；请先调整或删除依赖透视表'
    }
  } catch (error) { return (error as Error).message }
}
