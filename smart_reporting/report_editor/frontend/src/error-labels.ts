import { ReportEditorApiError } from './api'

// 导出改为后台任务后会出现更多具体错误码；按错误码给出可操作的提示，
// 不能让 409/504 等状态码统一落成“保存冲突”“操作失败”。
const CODE_LABELS: Record<string, string> = {
  report_editor_ai_review_pending: '请先完成 AI 候选的接受或拒绝，再保存或导出',
  report_editor_ai_selection_required: '请先选择需要改写的正文',
  report_editor_ai_action_invalid: '报告 AI 改写动作无效',
  report_editor_ai_selection_too_large: '选择的正文过长，请缩小范围',
  report_editor_ai_protocol_marker: '包含报告协议标记的正文不能使用 AI 改写',
  report_editor_ai_failed: 'AI 改写失败 · 已保留原文',
  report_editor_ai_empty_stream: 'AI 改写未返回内容 · 已保留原文',
  report_editor_revision_stale: '已有更新版本 · 请打开最新版本的编辑链接',
  report_editor_revision_conflict: '新版本已存在 · 请重新载入',
  report_editor_export_running: '当前版本正在导出 · 请等待完成',
  report_editor_export_busy: '导出任务较多 · 请稍后重试',
  report_editor_export_timeout: '导出超时 · 请稍后重试',
  report_editor_export_missing: '导出任务已失效 · 请重新导出',
  report_editor_chart_ai_busy: '这张图已有改图任务在进行 · 请等待完成',
  report_editor_chart_ai_rate_limited: '改图次数已达每小时上限 · 请稍后再试',
  report_editor_chart_ai_timeout: '改图超时已取消 · 原图不受影响',
  report_editor_chart_ai_missing: '改图任务已失效 · 请重新发起',
  report_editor_chart_ai_unavailable: 'AI 改图当前不可用',
  report_editor_chart_ai_failed: '改图失败 · 原图不受影响',
  report_editor_chart_ai_skipped: '改图要求超出可用数据范围 · 详见跳过说明',
  report_editor_chart_ai_base_changed: '图片已变化 · 请刷新后重新发起改图',
  report_artifact_validation_failed: '导出验收未通过',
  report_artifact_unavailable: '报告文件未生成或无法读取 · 无法签发下载链接',
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
