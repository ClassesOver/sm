export {}

const isSlidesPath = window.location.pathname.includes('/reports/v1/slides/')
const isWorkbookPath = window.location.pathname.includes('/reports/v1/workbooks/')
const isNativePath = window.location.pathname.includes('/reports/v1/native/')
if (isNativePath) {
  await import('./style.css')
  const { startNativeEditor } = await import('./native-main')
  await startNativeEditor().catch(error => {
    const root = document.querySelector<HTMLElement>('#app')
    if (root) root.textContent = error instanceof Error ? error.message : '原生文档载入失败，请重新打开'
  })
} else if (isWorkbookPath) {
  await import('./style.css')
  const { createEditorShell } = await import('./shell')
  const { toolbarMode } = await import('./viewport')
  const { createWorkbookEditorView } = await import('./workbook-main')
  const root = document.querySelector<HTMLElement>('#app')!
  const shell = createEditorShell(root, toolbarMode(window.innerWidth), 'xlsx')
  const { createIcons, Download, Save, Keyboard } = await import('lucide')
  createIcons({ icons: { Download, Save, Keyboard } })
  await createWorkbookEditorView(shell)
} else if (!isSlidesPath) {
  await import('./main')
} else {
  const { createIcons, Download, FileDown, FileText, Keyboard, MoreHorizontal, PanelLeft, Save, Settings2, X } = await import('lucide')
  await import('./style.css')
  await import('./slides.css')
  const { createEditorShell } = await import('./shell')
  const { toolbarMode } = await import('./viewport')
  const { createSlidesEditorView } = await import('./slides-main')
  const root = document.querySelector<HTMLElement>('#app') ?? document.querySelector<HTMLElement>('#slides-app')
  if (!root) throw new Error('report editor root is missing')
  const shell = createEditorShell(root, toolbarMode(window.innerWidth), 'pptx')
  createIcons({ icons: { Download, FileDown, FileText, Keyboard, MoreHorizontal, PanelLeft, Save, Settings2, X } })
  const loadState = document.createElement('section')
  loadState.className = 'editor-load-state'
  loadState.setAttribute('role', 'status')
  loadState.textContent = '正在打开幻灯片'
  shell.editor.append(loadState)
  createSlidesEditorView(shell.editor, { save: shell.save, download: shell.exportPptx })
  loadState.remove()
}
