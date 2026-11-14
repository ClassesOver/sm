import './docx-styles-pane.css'
import { createRoot } from 'react-dom/client'
import type { Editor } from '@tiptap/core'
import { previewFontSettings, type ParsedDocFull, type StyleInfo, type StyleUpsert } from '@genoffice/docx-engine'
import { docStyleCss } from './vendor/genoffice-docs/apps/docs/src/renderer/doc-style-css'
import type { DocxAnchor } from './docx-operations'
import { commitDocxNativeOperations, docxNativeOperationsOf } from './docx-native-history'
import { StylesPane } from './docx-styles-pane-source'
import { registerStylesPaneContext, stylesPaneFormatState } from './docx-styles-pane-adapter'
import { stylesPaneOperations, stylesPaneStyles, stylesPaneSelectionEditable, type StylesPaneModel } from './docx-styles-pane-operations'

export function createDocxStylesPane(options: { editor: Editor; host: HTMLElement; toolbar: HTMLElement; parsed: ParsedDocFull; anchors: DocxAnchor[]; model?: StylesPaneModel; canEdit: () => boolean; onError: (error: unknown) => void; onCss: (css: string) => void }) {
  const { editor, host, toolbar, parsed, model } = options
  const container = document.createElement('div'); container.className = 'docx-styles-pane-host'; host.querySelector('.docx-navigation-layout')!.append(container)
  const root = createRoot(container), button = document.createElement('button'); button.type = 'button'; button.className = 'rb-btn'; button.textContent = '样式窗格'; button.dataset.action = 'styles-pane'; button.setAttribute('aria-expanded','false'); toolbar.append(button)
  let open = false, disposed = false, liveStyles = new Map(parsed.styles), pendingKey = '', request = 0
  const source = parsed.styles as Map<string, StyleInfo>
  const release = registerStylesPaneContext(editor, { anchors: options.anchors, source, onError: options.onError })
  const pending = () => stylesPaneOperations(docxNativeOperationsOf(editor.getJSON()), source, model)
  const upsert = (up: StyleUpsert): string | null => {
    try {
      if (!model?.editable || !options.canEdit() || !editor.isEditable) throw new Error('当前来源样式不可编辑或正在保存')
      if (Object.keys(up).every(key => key === 'styleId')) return null
      const operations = docxNativeOperationsOf(editor.getJSON()), old = operations.find(op => op.kind === 'upsertStyle' && (op.upsert as StyleUpsert).styleId === up.styleId)?.upsert as StyleUpsert | undefined
      const merged: StyleUpsert = { ...old, ...up, ...(old?.rPr || up.rPr ? { rPr: { ...old?.rPr, ...up.rPr } } : {}), ...(old?.pPr || up.pPr ? { pPr: { ...old?.pPr, ...up.pPr } } : {}) }
      const next = [...operations.filter(op => !(op.kind === 'upsertStyle' && (op.upsert as StyleUpsert).styleId === up.styleId)), { kind: 'upsertStyle', expectedStylesSha256: model.expectedStylesSha256, upsert: merged }]
      stylesPaneOperations(next, source, model)
      commitDocxNativeOperations(editor, next, options.canEdit)
      return null
    } catch (error) { options.onError(error); return error instanceof Error ? error.message : String(error) }
  }
  const render = () => {
    if (disposed) return
    const styleGroup = toolbar.querySelector<HTMLElement>('[data-action="paragraph-style"]')?.parentElement
    if (styleGroup && button.parentElement !== styleGroup) styleGroup.append(button)
    container.hidden = !open; button.setAttribute('aria-expanded', String(open))
    if (!open) { root.render(null); return }
    const operations = pending(), metadata = stylesPaneStyles(source, operations), styles = new Map(liveStyles)
    for (const [id, info] of metadata) if (!styles.has(id) || operations.some(op => (op.upsert as StyleUpsert).styleId === id)) styles.set(id, { ...styles.get(id), ...info, display: styles.get(id)?.display })
    root.render(<StylesPane editor={editor} styles={styles} docDefaults={parsed.docDefaults} fs={stylesPaneFormatState(editor, styles)} canEdit={!!model?.editable && options.canEdit() && editor.isEditable && stylesPaneSelectionEditable(editor, options.anchors)} pending={Object.fromEntries(operations.map(op => [(op.upsert as StyleUpsert).styleId, op.upsert as StyleUpsert]))} onUpsert={upsert} onNotice={message => options.onError(new Error(message))} onClose={() => { open = false; render(); button.focus() }} />)
  }
  const refresh = () => {
    if (disposed) return
    const operations = pending(), key = JSON.stringify(operations)
    if (key !== pendingKey) {
      pendingKey = key; const id = ++request
      if (!operations.length) { liveStyles = new Map(source); editor.storage.listNumbering.styles = liveStyles; options.onCss(docStyleCss(parsed)) }
      else void previewFontSettings(parsed, operations.map(op => op.upsert as StyleUpsert)).then(result => {
        if (disposed || id !== request || key !== JSON.stringify(pending())) return
        liveStyles = new Map(result.styles); editor.storage.listNumbering.styles = liveStyles
        options.onCss(docStyleCss({ ...parsed, styles: result.styles })); render()
        editor.commands.setMeta('native-styles-preview', true)
      }).catch(error => { if (!disposed && id === request) options.onError(error) })
    }
    render()
  }
  button.addEventListener('click', () => { open = !open; refresh() })
  editor.on('transaction', refresh); editor.on('selectionUpdate', render)
  refresh()
  return { refresh, open() { open = true; refresh() }, dispose() { disposed = true; request++; editor.off('transaction', refresh); editor.off('selectionUpdate', render); release(); root.unmount(); container.remove(); button.remove() } }
}
