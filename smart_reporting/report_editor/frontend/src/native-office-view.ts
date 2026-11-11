import { bindNativeOfficeAssistant } from './native-office-assistant'
import { createOfficeAIEntry } from './office-ai-entry'
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
  const format = options.context.context.format === 'xlsx' ? 'xlsx' : 'pptx'
  let reader: ReturnType<typeof bindNativeOfficeAssistant> | undefined
  let assistantRequested = false
  let openEditAssistant = () => {}
  const onAssistant = options.context.officeReadAIEnabled ? () => {
    if (reader) reader.open()
    else assistantRequested = true
  } : options.context.aiEnabled ? () => openEditAssistant() : undefined
  const attach = async (view: {dispose(): void; officeEditAssistant?: {panel:HTMLElement;open():void;close():void}; officeReadContext?: (scope: 'document' | 'selection') => Promise<import('./native-api').NativeOfficeReadContext>}) => {
    reader = options.context.officeReadAIEnabled ? bindNativeOfficeAssistant(shell.editor.parentElement ?? shell.editor, {
      api: options.api, draft: options.draft, format,
      context: async scope => {
        if (!options.context.editingEnabled) {
          if (scope === 'selection') throw new Error('当前为原件阅读模式，请使用整篇阅读')
          return {operations:[],selection:null}
        }
        if (!view.officeReadContext) throw new Error('编辑器尚未就绪，无法同步当前草稿')
        return await view.officeReadContext(scope)
      },
    }) : undefined
    if (assistantRequested) { assistantRequested = false; reader?.open() }
    const entry = reader && !options.context.editingEnabled ? createOfficeAIEntry(onAssistant) : undefined
    if (entry) {
      entry.type='button';entry.dataset.action='office-read-ai'
      ;(shell.editor.closest('#app')?.querySelector('.toolbar-group-output') ?? shell.editor.parentElement ?? shell.editor).append(entry)
    }
    const {mountOfficeTaskDock}=await import('./office-task-dock')
    const panels:import('./office-task-dock').OfficeTaskEntry[]=[]
    const readPanel=(shell.editor.parentElement??shell.editor).querySelector<HTMLElement>('.native-office-assistant')
    if(reader&&readPanel)panels.push({id:'read',label:'阅读问答',panel:readPanel,open:()=>reader?.open(),close:()=>readPanel.querySelector<HTMLButtonElement>('.office-assistant-close')?.click()})
    if(view.officeEditAssistant){const edit=view.officeEditAssistant;panels.push({id:'edit',label:'编辑选区',panel:edit.panel,open:()=>edit.open(),close:()=>edit.close()})}
    const main=shell.editor.querySelector<HTMLElement>(format==='xlsx'?'.workbook-grid-frame':'.slides-workspace')??shell.editor
    const dock=panels.length?mountOfficeTaskDock(main,panels,{label:(format==='xlsx'?'XLSX':'PPTX')+' AI 助手侧栏'}):undefined
    openEditAssistant = () => dock?.open('edit')
    const editEntry=view.officeEditAssistant?createOfficeAIEntry(()=>dock?.open('edit')):undefined
    if(editEntry){editEntry.dataset.action='office-edit-ai';editEntry.setAttribute('aria-label','AI 编辑');editEntry.title='AI 编辑';const caption=editEntry.querySelector('span');if(caption)caption.textContent='AI 编辑';else editEntry.append('AI 编辑');(shell.editor.closest('#app')?.querySelector('.toolbar-group-output')??shell.editor.parentElement??shell.editor).append(editEntry)}
    return {dispose(){dock?.dispose();reader?.dispose();entry?.remove();editEntry?.remove();view.dispose()}}
  }
  if (!options.context.editingEnabled) {
    shell.editor.textContent='可直接阅读已核验原件，或下载原件查看。'
    shell.save.disabled=true
    shell.statusLabel.textContent='原件阅读模式'
    return attach({dispose(){}})
  }
  const transport = createNativeOfficeTransport(options)
  if (options.context.context.format === 'xlsx') {
    const { createWorkbookEditorView } = await import('./workbook-main')
    const { createWorkbookNativeAIClient } = await import('./workbook-native-ai')
    const view = await createWorkbookEditorView(shell, { native: true, draft: options.draft, request: transport.workbook, onAssistant,
      ...(options.context.aiEnabled ? { nativeAI: createWorkbookNativeAIClient(options.context.context.documentId, options.context.context.revision, options.context.csrfToken) } : {}),
      file: async () => ({ bytes: await options.api.file(), path: options.context.context.sourceFile.path, sha256: options.context.context.sourceFile.sha256 }) })
    if (!view) throw new Error('工作簿载入失败')
    return attach(view)
  }
  const { createSlidesEditorView } = await import('./slides-main')
  const { createSlidesNativeAIClient } = await import('./slides-native-ai')
  const view = createSlidesEditorView(shell.editor, { save: shell.save, download: shell.exportPptx, native: true, request: transport.slides, draft: options.draft, onAssistant,
    ...(options.context.aiEnabled ? { nativeAI: createSlidesNativeAIClient(options.context.context.documentId, options.context.context.revision, options.context.csrfToken) } : {}) })
  try { await view.ready; return attach(view) } catch (error) { view.dispose(); throw error }
}
