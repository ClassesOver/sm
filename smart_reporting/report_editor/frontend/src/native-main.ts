import { createNativeApi, type NativeAISelection, type NativeAIReviewSelection, type NativeAINoteSelection } from './native-api'
import { mountBinaryRefresh } from './binary-refresh'
import { NativeDraft } from './native-draft'
import { bindNativeSession } from './native-session'
import { createEditorShell } from './shell'
import { toolbarMode } from './viewport'
import { bindNativeAI } from './native-ai'
import { bindNativeWordAssistant } from './native-word-assistant'
import {
  createElement, createIcons, Database, FileDown, FileText, Focus, History, Keyboard, MessageCircle, MoreHorizontal,
  PanelLeft, Save, Search, Share2, Settings2, Sparkles, X,
} from 'lucide'
import './native.css'

export async function startNativeEditor() {
  const root = document.querySelector<HTMLElement>('#app')
  if (!root) throw new Error('原生编辑入口缺少容器')
  const match = /^\/reports\/v1\/native\/([^/]+)\/(\d+)\/?$/.exec(window.location.pathname)
  if (!match) throw new Error('原生编辑路径无效')
  const documentId = decodeURIComponent(match[1])
  const revision = Number(match[2])
  root.textContent = '正在核验文档身份'
  const response = await createNativeApi(documentId, revision).context()
  const context = response.context
  if (context.documentId !== documentId || context.revision !== revision) throw new Error('文档身份与打开路径不一致')
  const shell = createEditorShell(root, toolbarMode(window.innerWidth), context.format)
  createIcons({ icons: { Database, FileDown, FileText, Focus, History, Keyboard, MoreHorizontal, PanelLeft, Save, Search, Share2, Settings2, X } })
  root.dataset.nativeEditor = 'true'
  const api = createNativeApi(documentId, revision, response.csrfToken)
  // 读取 Storage 属性也可能被浏览器禁用；延迟到草稿内部的异常兜底中执行。
  const draft = new NativeDraft({ documentId, revision, sourceSha256: context.sourceFile.sha256, scope: context.scope }, {
    getItem: key => window.localStorage.getItem(key),
    setItem: (key, value) => window.localStorage.setItem(key, value),
    removeItem: key => window.localStorage.removeItem(key),
  })
  root.querySelector<HTMLElement>('.revision-label')!.textContent = `${context.format === 'docx' ? 'Word' : context.format.toUpperCase()} · 修订 ${revision}`
  root.querySelector<HTMLElement>('.structure-status')!.textContent = '编辑后内容待重新核验'
  root.querySelector<HTMLElement>('.current-section')!.textContent = '独立文件修订'
  root.querySelector<HTMLElement>('.doc-metrics')!.textContent = `${(context.sourceFile.size / 1024).toFixed(1)} KiB`
  shell.statusLabel.textContent = '正在载入文档'
  const original = document.createElement('a')
  original.href = `${window.location.pathname.replace(/\/$/, '')}/api/file`
  original.textContent = '下载原件'
  original.download = `report.${context.format}`
  original.referrerPolicy = 'no-referrer'
  root.querySelector('.toolbar-group-output')?.append(original)
  if (context.format === 'xlsx' || context.format === 'pptx') {
    try {
      const { createNativeOfficeView } = await import('./native-office-view')
      const office = await createNativeOfficeView(shell, { api, context: response, draft })
      window.addEventListener('pagehide', () => office?.dispose(), { once: true })
    } catch (error) {
      shell.statusLabel.textContent = error instanceof Error ? error.message : '文件编辑器载入失败，可下载原件'
      shell.save.disabled = true
    }
    shell.editor.setAttribute('aria-busy', 'false')
    shell.status.setAttribute('aria-busy', 'false')
    return
  }
  let ai: ReturnType<typeof bindNativeAI> | undefined
  let wordReader: ReturnType<typeof bindNativeWordAssistant> | undefined
  let session: ReturnType<typeof bindNativeSession> | undefined
  let wordDock: {dispose(): void} | undefined
  let pdfMutationPending = false
  const options = { api, context: response, draft, onAssistant: response.wordReadAIEnabled || response.aiEnabled && response.editingEnabled ? () => { if (wordReader) wordReader.open('ask'); else ai?.open() } : undefined, onNoteAI: (selection:NativeAINoteSelection,instruction?:string,beforeText?:string)=>ai?.openNotes(selection,instruction,beforeText), onReviewAI: (selection: NativeAIReviewSelection, instruction?: string) => ai?.openReview(selection,instruction), onDraftChange: () => session?.update(), onMutationStateChange: (pending: boolean) => { pdfMutationPending = pending; refresh?.update() }, mutationBlocked: () => refreshing, onSelectionChange: (selection: NativeAISelection[]) => {
    ai?.setSelection(selection)
  }, flushForFileOperation: async () => {
    if (!session) throw new Error('编辑会话尚未就绪')
    return session.flushForFileOperation()
  } }
  let refresh: ReturnType<typeof mountBinaryRefresh> | undefined
  let refreshing = false
  let loaded = false
  let view: Awaited<ReturnType<typeof import('./pdf-main')['createPdfEditorView']>> | Awaited<ReturnType<typeof import('./docx-main')['createDocxEditorView']>>
  const viewMutationPending = () => pdfMutationPending || loaded && 'mutationPending' in view && view.mutationPending
  if (context.origin === 'report' && (context.format === 'pdf' || context.format === 'docx')
    && response.contextSha256 && /^[a-f0-9]{64}$/.test(response.contextSha256)) {
    const host = root.querySelector<HTMLElement>('.report-meta')?.parentElement ?? root
    refresh = mountBinaryRefresh(host, {route: location.pathname.replace(/\/$/, ''), reportId: context.documentId,
      revision, format: context.format, contextSha256: response.contextSha256, sha256: context.sourceFile.sha256}, response.dataRefresh,
      {submit: api.refreshSubmit, status: api.refreshStatus, delivery: api.refreshDelivery}, {
        saving: () => draft.saving || session?.preparing === true || ai?.accepting === true || viewMutationPending(),
        blocked: () => !loaded || draft.closed || draft.saving || session?.preparing === true || ai?.accepting === true || viewMutationPending(),
        flush: () => { if (view && 'flushPendingEdits' in view) view.flushPendingEdits?.() }, dirty: () => draft.dirty,
        save: async () => { await session?.save('save') },
        setRefreshing: value => { refreshing = value; if (loaded) view.setSaving(value || draft.saving || session?.preparing === true); session?.update(false); ai?.update() },
      })
  }
  try {
    view = context.format === 'pdf'
    ? await (await import('./pdf-main')).createPdfEditorView(shell, options)
    : await (await import('./docx-main')).createDocxEditorView(shell, options)
  } catch (error) {
    shell.statusLabel.textContent = error instanceof Error ? error.message : '文档载入失败，可下载原件'
    shell.editor.textContent = '预览不可用，请下载原件查看。'
    shell.editor.setAttribute('aria-busy', 'false')
    shell.status.setAttribute('aria-busy', 'false')
    for (const button of [shell.save, shell.exportWord, shell.exportPdf]) button.disabled = true
    return
  }
  shell.editor.setAttribute('aria-busy', 'false')
  shell.status.setAttribute('aria-busy', 'false')
  shell.statusLabel.textContent = response.editingEnabled ? '文档已载入' : '在线编辑暂未开放，可下载原件'
  loaded = true
  view.setSaving(refreshing)
  session = bindNativeSession(shell, { api, draft, format: context.format, view, editingEnabled: response.editingEnabled, refreshBusy: () => refreshing, onStateChange: () => refresh?.update() })
  refresh?.update()
  if (response.aiEnabled && response.editingEnabled && (context.format === 'docx' || response.pdfTextEnabled)) {
    ai = bindNativeAI(shell.editor.parentElement ?? root, { api, draft, view, format: context.format, onDraftChange: () => session?.update(), locked: () => refreshing, onStateChange: () => refresh?.update() })
  }
  if (context.format === 'docx' && response.wordReadAIEnabled) {
    wordReader = bindNativeWordAssistant(shell.editor.parentElement ?? root, {
      api, draft, selection: () => 'getReadSelection' in view ? view.getReadSelection() : [], flushPendingEdits: () => { if ('flushPendingEdits' in view) view.flushPendingEdits?.() },
    })
  }
  if (context.format === 'docx' && (wordReader || ai)) {
    const { mountOfficeTaskDock } = await import('./office-task-dock')
    const entries = []
    if (wordReader) {
      const panel = root.querySelector<HTMLElement>('.native-word-assistant')!
      entries.push({id:'read', label:'阅读问答', panel, open:()=>wordReader?.open('ask'), close:()=>panel.querySelector<HTMLButtonElement>('[data-word-ai=close]')?.click()})
    }
    if (ai) {
      const panel = root.querySelector<HTMLElement>('.native-ai:not(.native-word-assistant)')!
      entries.push({id:'edit', label:'编辑建议', panel, open:()=>ai?.open(), close:()=>ai?.close()})
    }
    const main = shell.editor.querySelector<HTMLElement>('.docx-navigation-layout') ?? shell.editor
    const dock = mountOfficeTaskDock(main, entries, {label:'Word AI 助手'})
    wordDock = dock
    for (const entry of entries) {
      const button = document.createElement('button'); button.type = 'button'; button.className = 'office-ai-entry'; button.dataset.action = `word-${entry.id}-ai`
      button.append(createElement(entry.id === 'read' ? MessageCircle : Sparkles, {'aria-hidden':'true',width:18,height:18}), document.createTextNode(entry.label))
      button.onclick = () => dock.open(entry.id)
      root.querySelector('.toolbar-group-edit-view')?.append(button)
    }
  }
  if (!response.editingEnabled) {
    shell.save.disabled = true
    shell.exportWord.disabled = true
    shell.exportPdf.disabled = true
  }
  window.addEventListener('pagehide', () => { wordDock?.dispose(); ai?.dispose(); wordReader?.dispose(); session?.dispose() }, { once: true })
}
