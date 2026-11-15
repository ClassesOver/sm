import type { Editor } from '@tiptap/core'
import { DOMSerializer } from '@tiptap/pm/model'
import type { Transaction } from '@tiptap/pm/state'
import { buttonClasses } from './button'

/** GenOffice Word's split view is a read-only copy with independent scrolling. */
export function createDocxSplitPane(options: {
  host: HTMLElement
  editor: Editor
  onVisibilityChange(visible: boolean): void
  onError(error: unknown): void
}) {
  const { editor, host } = options
  const doc = host.ownerDocument
  const serializer = DOMSerializer.fromSchema(editor.schema)
  let pane: HTMLElement | undefined, content: HTMLElement | undefined
  let opener: HTMLElement | undefined, timer: ReturnType<typeof setTimeout> | undefined, disposed = false

  function refreshLayout() {
    if (!content || editor.isDestroyed) return
    content.style.cssText = editor.view.dom.style.cssText
    const watermark = editor.view.dom.getAttribute('data-watermark')
    if (watermark) content.dataset.watermark = watermark
    else delete content.dataset.watermark
    content.querySelector('.docx-picture-watermark-preview')?.remove()
    const picture = editor.view.dom.querySelector('.docx-picture-watermark-preview')
    if (picture) content.prepend(picture.cloneNode(true))
  }

  function refresh() {
    if (!content || editor.isDestroyed) return
    try {
      const fragment = serializer.serializeFragment(editor.state.doc.content, { document: doc })
      // This is a view of the document, without duplicate bookmark ids or live controls.
      for (const element of fragment.querySelectorAll('[id],[contenteditable],[tabindex],a[href]')) {
        element.removeAttribute('id')
        element.removeAttribute('contenteditable')
        element.removeAttribute('tabindex')
        if (element.matches('a[href]')) element.removeAttribute('href')
      }
      content.replaceChildren(fragment)
      refreshLayout()
    } catch (error) { options.onError(error) }
  }

  function scheduleRefresh() {
    if (timer !== undefined) clearTimeout(timer)
    timer = setTimeout(refresh, 300)
  }
  const onTransaction = ({ transaction }: { transaction: Transaction }) => {
    if (transaction.docChanged) scheduleRefresh()
  }

  function close(restoreFocus: boolean) {
    if (!pane) return
    clearTimeout(timer)
    timer = undefined
    editor.off('transaction', onTransaction)
    pane.remove()
    pane = content = undefined
    if (!disposed) options.onVisibilityChange(false)
    if (restoreFocus && opener?.isConnected) opener.focus({ preventScroll: true })
    opener = undefined
  }

  function toggle() {
    if (disposed || editor.isDestroyed) return
    if (pane) { close(true); return }
    opener = doc.activeElement instanceof HTMLElement ? doc.activeElement : undefined
    pane = doc.createElement('section')
    pane.className = 'docx-split-pane'
    pane.setAttribute('aria-label', '拆分窗格')
    const header = doc.createElement('header')
    const title = doc.createElement('span')
    title.textContent = '拆分窗格（只读预览，可独立滚动）'
    const closeButton = doc.createElement('button')
    closeButton.type = 'button'
    closeButton.className = buttonClasses('quiet', true)
    closeButton.textContent = '×'
    closeButton.setAttribute('aria-label', '取消拆分')
    closeButton.onclick = () => close(true)
    const scroll = doc.createElement('div')
    scroll.className = 'docx-split-scroll'
    scroll.tabIndex = 0
    scroll.setAttribute('aria-label', '拆分预览内容')
    content = doc.createElement('article')
    content.className = 'doc-page ProseMirror docx-split-content'
    content.setAttribute('contenteditable', 'false')
    const zoom = doc.createElement('div')
    zoom.className = 'doc-zoom'
    zoom.append(content); scroll.append(zoom); header.append(title, closeButton); pane.append(header, scroll); host.append(pane)
    editor.on('transaction', onTransaction)
    refresh()
    options.onVisibilityChange(true)
  }

  return { get visible() { return !!pane }, toggle, refreshLayout, dispose() { disposed = true; close(false) } }
}
