import { createNativeApi, type NativeAISelection } from './native-api'
import { NativeDraft } from './native-draft'
import { bindNativeSession } from './native-session'
import { createEditorShell } from './shell'
import { toolbarMode } from './viewport'
import { bindNativeAI } from './native-ai'
import {
  createIcons, Database, FileDown, FileText, Focus, History, Keyboard, MoreHorizontal,
  PanelLeft, Save, Search, Share2, Settings2, X,
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
  root.querySelector<HTMLElement>('.revision-label')!.textContent = `${context.format.toUpperCase()} · 修订 ${revision}`
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
  let session: ReturnType<typeof bindNativeSession> | undefined
  const options = { api, context: response, draft, onDraftChange: () => session?.update(), onSelectionChange: (selection: NativeAISelection[]) => ai?.setSelection(selection) }
  let view
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
  session = bindNativeSession(shell, { api, draft, format: context.format, view, editingEnabled: response.editingEnabled })
  if (response.aiEnabled && response.editingEnabled && (context.format === 'docx' || response.pdfTextEnabled)) {
    ai = bindNativeAI(shell.editor.parentElement ?? root, { api, draft, view, format: context.format, onDraftChange: () => session?.update() })
  }
  if (!response.editingEnabled) {
    shell.save.disabled = true
    shell.exportWord.disabled = true
    shell.exportPdf.disabled = true
  }
  window.addEventListener('pagehide', () => { ai?.dispose(); session?.dispose() }, { once: true })
}
