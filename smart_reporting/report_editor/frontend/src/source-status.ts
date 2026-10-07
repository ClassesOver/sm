import type { TraceSubjectInfo, TraceValidation } from './api'

type SubjectStatus = Partial<TraceValidation['subjects'][number]> & {
  status: 'valid' | 'stale' | 'unbound'
}

// 事实页、单元格页和正文预览使用同一登记位置，避免各自猜测引用状态。
export function sourceSubjectStatus(validation: TraceValidation, subject: TraceSubjectInfo): SubjectStatus | undefined {
  if (subject.subjectKind === 'table_cell') {
    const table = validation.tables?.find(item => item.tableId === subject.locator.tableId)
    if (table) {
      const matches = table.locations?.filter(item => item.rowKey === subject.locator.rowKey && item.columnKey === subject.locator.columnKey) ?? []
      const cell = matches.length === 1 ? matches[0] : undefined
      return { status: cell?.status ?? 'unbound', warnings: [] }
    }
  }
  return validation.subjects.find(item => item.subjectId === subject.subjectId)
}
