import { describe, expect, it } from 'vitest'

import { ReportEditorApiError } from './api'
import { errorLabel } from './error-labels'

describe('errorLabel', () => {
  it.each([
    [new ReportEditorApiError(400, 'report_editor_ai_selection_too_large'), '选择的正文过长，请缩小范围'],
    [new ReportEditorApiError(400, 'report_editor_ai_protocol_marker'), '包含报告协议标记的正文不能使用 AI 改写'],
    [new ReportEditorApiError(502, 'report_editor_ai_failed'), 'AI 改写失败 · 已保留原文'],
    [new ReportEditorApiError(409, 'report_editor_export_running'), '当前版本正在导出 · 请等待完成'],
    [new ReportEditorApiError(504, 'report_editor_export_timeout'), '导出超时 · 请稍后重试'],
    [new ReportEditorApiError(409, 'report_editor_revision_stale'), '已有更新版本 · 请打开最新版本的编辑链接'],
    [new ReportEditorApiError(409, 'report_editor_conflict'), '保存冲突'],
    [new ReportEditorApiError(410, 'report_editor_session_expired'), '会话已过期'],
    [new TypeError('network'), '无法连接报告服务'],
    [new ReportEditorApiError(500, 'unknown'), '操作失败'],
  ])('maps %o to a specific label', (error, label) => {
    expect(errorLabel(error)).toBe(label)
  })
})
