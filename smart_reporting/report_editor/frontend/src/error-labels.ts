import { ReportEditorApiError } from './api'

// 导出改为后台任务后会出现更多具体错误码；按错误码给出可操作的提示，
// 不能让 409/504 等状态码统一落成“保存冲突”“操作失败”。
const CODE_LABELS: Record<string, string> = {
  report_editor_revision_stale: '已有更新版本 · 请打开最新版本的编辑链接',
  report_editor_revision_conflict: '新版本已存在 · 请重新载入',
  report_editor_export_running: '当前版本正在导出 · 请等待完成',
  report_editor_export_busy: '导出任务较多 · 请稍后重试',
  report_editor_export_timeout: '导出超时 · 请稍后重试',
  report_editor_export_missing: '导出任务已失效 · 请重新导出',
  report_artifact_validation_failed: '导出验收未通过',
}

export function errorLabel(error: unknown): string {
  if (error instanceof ReportEditorApiError) {
    const label = CODE_LABELS[error.code]
    if (label) return label
    if (error.status === 409) return '保存冲突'
    if (error.status === 410) return '会话已过期'
  }
  if (error instanceof TypeError) return '无法连接报告服务'
  return '操作失败'
}
