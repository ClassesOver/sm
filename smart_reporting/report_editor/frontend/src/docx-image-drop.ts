import type { Editor } from '@tiptap/core'
import { TextSelection, type Transaction } from '@tiptap/pm/state'
import type { EditorView } from '@tiptap/pm/view'
import { insertDocxImageFile } from './docx-clipboard'

// Fixed source editor/image-drop.ts: MIME wins; extension fallback is only for empty MIME.
const MIME: Record<string, string> = { png: 'image/png', jpg: 'image/jpeg', jpeg: 'image/jpeg', gif: 'image/gif' }
const ACCEPTED = new Set(Object.values(MIME))
export function droppedDocxImageMime(file: Pick<File, 'name' | 'type'>): string | null {
  if (ACCEPTED.has(file.type)) return file.type
  if (file.type) return null
  const extension = /\.([a-z0-9]+)$/i.exec(file.name)?.[1]?.toLowerCase()
  return extension ? MIME[extension] ?? null : null
}
export interface DocxImageDropOptions {
  editor: Editor
  root: HTMLElement
  locked: () => string | null
  onError: (error: unknown) => void
}

/** OS files only; native image insertion owns decoding, payload limits, paragraph splitting
 * and source identity. Images remain separate native picture paragraphs, never inline atoms.
 */
export function createDocxImageDrop({ editor, root, locked, onError }: DocxImageDropOptions) {
  let disposed = false, generation = 0
  let restorePendingSelection: (() => void) | undefined
  const owns = (event: Event) => !editor.isDestroyed && event.target instanceof Node && root.contains(editor.view.dom) && editor.view.dom.contains(event.target)
  const unavailable = () => disposed || editor.isDestroyed || !editor.isEditable || !!locked() || editor.view.composing
  const dragover = (event: DragEvent) => {
    if (!owns(event) || unavailable() || ![...event.dataTransfer?.items ?? []].some(item => item.kind === 'file' && ACCEPTED.has(item.type))) return
    event.preventDefault()
    if (event.dataTransfer) event.dataTransfer.dropEffect = 'copy'
  }
  const insert = async (files: File[], pos: number, ticket: number) => {
    const originalDoc = editor.state.doc, originalSelection = editor.state.selection
    const nearest = TextSelection.near(originalDoc.resolve(Math.max(0, Math.min(pos, originalDoc.content.size))))
    if (!(nearest instanceof TextSelection) || nearest.$from.depth !== 1 || !nearest.empty || !nearest.$from.parent.isTextblock) {
      onError(new Error('请把图片拖放到正文段落中')); return
    }
    if (unavailable() || ticket !== generation) return
    editor.view.dispatch(editor.state.tr.setSelection(nearest))
    const restore = () => {
      if (!editor.isDestroyed && editor.state.doc === originalDoc && editor.state.selection.eq(nearest)) editor.view.dispatch(editor.state.tr.setSelection(originalSelection))
    }
    restorePendingSelection = restore
    let inserted = 0
    const current = () => ticket === generation && !unavailable()
    // A per-call facade guards the helper's final dispatch after its asynchronous browser decode.
    // No editor/view methods or global decoders are replaced on the live editor.
    const guardedView = new Proxy(editor.view, { get(view, key) {
      if (key === 'dispatch') return (tr: Transaction) => {
        if (!current()) throw new Error('图片读取期间文档编辑状态已变化，请重新拖放')
        view.dispatch(tr)
      }
      const value = Reflect.get(view, key, view)
      return typeof value === 'function' ? value.bind(view) : value
    } }) as EditorView
    const guardedEditor = new Proxy(editor, { get(actual, key) {
      if (key === 'view') return guardedView
      if (key === 'isEditable') return current()
      if (key === 'isDestroyed') return disposed || ticket !== generation || actual.isDestroyed
      const value = Reflect.get(actual, key, actual)
      return typeof value === 'function' ? value.bind(actual) : value
    } }) as Editor
    try {
      for (const file of files) {
        if (!current()) break
        const mime = droppedDocxImageMime(file)
        if (!mime) continue
        const image = file.type ? file : new Blob([file], { type: mime })
        const attemptDoc = editor.state.doc, attemptSelection = editor.state.selection
        let stale = false
        const observe = () => { stale ||= !current() || editor.state.doc !== attemptDoc || !editor.state.selection.eq(attemptSelection) }
        editor.on('transaction', observe); editor.on('update', observe)
        try {
          const previousImages = new Set(editor.state.doc.content.content)
          try { await insertDocxImageFile(guardedEditor, image) }
          finally { editor.off('transaction', observe); editor.off('update', observe) }
          inserted++
          // The native helper leaves a paragraph-end caret before its new block image.
          // Move beyond that image so subsequent OS files retain the source file order.
          let afterImage: number | undefined
          editor.state.doc.forEach((node, at) => { if (node.type.name === 'docProtected' && node.attrs.genImage && !previousImages.has(node)) afterImage = at + node.nodeSize })
          if (afterImage !== undefined && current()) {
            const next = TextSelection.near(editor.state.doc.resolve(afterImage), 1)
            if (next instanceof TextSelection) editor.view.dispatch(editor.state.tr.setSelection(next))
          }
        }
        catch (error) {
          editor.off('transaction', observe); editor.off('update', observe)
          if (!disposed && ticket === generation) onError(error)
          if (stale || !current()) break
        }
      }
    } finally {
      // Never overwrite a user's later caret movement or an intervening edit.
      if (!inserted && ticket === generation) restore()
      if (restorePendingSelection === restore) restorePendingSelection = undefined
    }
  }
  const drop = (event: DragEvent) => {
    if (!owns(event)) return
    const files = [...event.dataTransfer?.files ?? []].filter(file => droppedDocxImageMime(file) !== null)
    if (!files.length) return
    // Handle before ProseMirror's generic file/HTML drop path; even locked image drops must not navigate.
    event.preventDefault(); event.stopPropagation()
    if (unavailable()) return
    const hit = editor.view.posAtCoords({ left: event.clientX, top: event.clientY })
    if (!hit) return
    restorePendingSelection?.()
    const ticket = ++generation
    void insert(files, hit.pos, ticket).catch(error => { if (!disposed && ticket === generation) onError(error) })
  }
  root.addEventListener('dragover', dragover, true)
  root.addEventListener('drop', drop, true)
  return { dispose() {
    if (disposed) return
    restorePendingSelection?.(); restorePendingSelection = undefined
    disposed = true; generation++
    root.removeEventListener('dragover', dragover, true); root.removeEventListener('drop', drop, true)
  } }
}
