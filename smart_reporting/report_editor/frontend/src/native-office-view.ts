import type { createNativeApi, NativeContextResponse } from './native-api'
import type { NativeOperation } from './native-draft'
import { NativeDraft } from './native-draft'
import type { EditorShell } from './shell'

/** 文件身份与保存走独立原生修订，网格和画布复用现有编辑组件。 */
export function createNativeOfficeTransport(options: {
  api: ReturnType<typeof createNativeApi>; context: NativeContextResponse; draft: NativeDraft
}) {
  const { api, context, draft } = options
  const sourceSha256 = context.context.sourceFile.sha256
  async function save(payload: Record<string, unknown>, format: 'xlsx' | 'pptx') {
    if (payload.expectedSha256 !== sourceSha256) throw new Error('文件来源已变化，请重新打开')
    if (draft.closed || draft.saving) throw new Error('当前修订正在保存或已关闭')
    const { expectedSha256: _expected, chartEdits, imageEdits, ...changes } = payload
    if ([chartEdits, imageEdits].some(value => value !== undefined && (!Array.isArray(value) || value.length))) throw new Error('上传文件不支持报告图表或配图候选登记')
    const operations = format === 'xlsx' || Array.isArray(payload.operations)
      ? payload.operations as NativeOperation[] : [{ kind: 'editSlides', ...changes }]
    draft.setOperations(operations)
    const request = draft.beginSave()
    try {
      const result = await api.save(request)
      draft.saveCompleted(result)
      return { ...result, [format]: result.artifacts[format] ?? {} }
    } catch (error) { draft.saveFailed(); throw error }
  }
  return {
    async workbook<T>(path: string, payload?: unknown): Promise<T> {
      if (path !== 'save' || !payload || typeof payload !== 'object') throw new Error('上传工作簿未开放该操作')
      return await save(payload as Record<string, unknown>, 'xlsx') as T
    },
    async slides<T>(path: string, init?: RequestInit): Promise<T> {
      const payload = typeof init?.body === 'string' ? JSON.parse(init.body) as Record<string, unknown> : undefined
      if (path === 'save' && payload) return await save(payload, 'pptx') as T
      if (path === 'deck') {
        // 恢复操作先由原生预览接口校验；画布仍以原始对象身份为基准，避免再次应用尺寸/版式后改号。
        if (draft.dirty) await api.preview({ expectedSha256: sourceSha256, operations: draft.operations })
        const result = await api.preview({ expectedSha256: sourceSha256, operations: [] })
        return { ...result.model, reportId: context.context.documentId, revision: context.context.revision, sha256: sourceSha256 } as T
      }
      if (path === 'render-tree') {
        if (payload && payload.expectedSha256 !== sourceSha256) throw new Error('幻灯片来源已变化')
        return await api.renderTree({ expectedSha256: sourceSha256,
          operations: payload ? (payload.operations as NativeOperation[] | undefined) ?? [{ kind: 'editSlides', edits: payload.edits ?? [] }] : [] }) as T
      }
      throw new Error('上传幻灯片未开放该操作')
    },
  }
}

export async function createNativeOfficeView(shell: EditorShell, options: {
  api: ReturnType<typeof createNativeApi>; context: NativeContextResponse; draft: NativeDraft
}) {
  if (!options.context.editingEnabled) throw new Error('在线编辑暂未开放，可下载原件')
  const transport = createNativeOfficeTransport(options)
  if (options.context.context.format === 'xlsx') {
    const { createWorkbookEditorView } = await import('./workbook-main')
    return await createWorkbookEditorView(shell, { native: true, draft: options.draft, request: transport.workbook,
      file: async () => ({ bytes: await options.api.file(), sha256: options.context.context.sourceFile.sha256 }) })
  }
  const { createSlidesEditorView } = await import('./slides-main')
  const view = createSlidesEditorView(shell.editor, { save: shell.save, download: shell.exportPptx, native: true, request: transport.slides, draft: options.draft })
  try { await view.ready; return view } catch (error) { view.dispose(); throw error }
}
