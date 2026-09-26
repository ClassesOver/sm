import { describe, expect, it } from 'vitest'

import { ReportEditorApiError } from './api'
import { errorLabel } from './error-labels'

describe('errorLabel', () => {
  it.each([
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
