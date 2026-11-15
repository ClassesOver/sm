// Floating selection entry adapted from GenOffice Docs AiAskPopover.
import type { Editor } from '@tiptap/core'
import { MAX_EDIT_QUEUE_INSTRUCTION, type DocxEditQueue } from './docx-edit-queue'
import { AI_QUEUE_ANCHOR_CLICK, queueAnchorRange } from './vendor/genoffice-docs/apps/docs/src/renderer/editor/ai-queue-anchors'
import { setInactiveSelectionShown } from './vendor/genoffice-docs/apps/docs/src/renderer/editor/inactive-selection'
import { zh } from './vendor/genoffice-docs/apps/docs/src/renderer/i18n/ai/zh'

export function mountDocxAskPopover(editor: Editor, queue: DocxEditQueue, host: HTMLElement, canEdit: () => boolean) {
  type State = { selection: Editor['state']['selection']; doc: Editor['state']['doc'] } | { id: string }
  let state: State | undefined
  const button = (label: string, action: () => void) => {
    const element = document.createElement('button')
    element.type = 'button'; element.textContent = label; element.onclick = action
    return element
  }
  const trigger = button(zh.aiAskBtn, () => {
    if (canEdit() && queue.canAnnotate()) open({ selection: editor.state.selection, doc: editor.state.doc })
  })
  trigger.dataset.action = 'word-ai-annotation'
  trigger.setAttribute('aria-haspopup', 'dialog')
  trigger.addEventListener('mousedown', event => event.preventDefault())
  const popup = document.createElement('div')
  popup.className = 'docx-ask-popover'
  popup.setAttribute('role', 'dialog')
  trigger.hidden = popup.hidden = true
  const title = document.createElement('strong')
  const input = document.createElement('input')
  input.maxLength = MAX_EDIT_QUEUE_INSTRUCTION; input.placeholder = zh.aiAskPlaceholder
  input.setAttribute('aria-label', zh.aiAskPlaceholder)
  const error = document.createElement('span'); error.setAttribute('role', 'status')
  const chips = document.createElement('div')
  for (const text of [zh.aiChipPolish, zh.aiChipShorten, zh.aiChipExpand, zh.aiChipFixGrammar]) {
    chips.append(button(text, () => { input.value = text; input.focus() }))
  }
  const actions = document.createElement('div')
  const remove = button('删除', () => {
    if (state && 'id' in state && canEdit()) queue.remove([state.id])
    close(true)
  })
  const apply = button(zh.aiAskQueue, () => commit(true))
  actions.append(button('关闭', () => close(true)), remove, apply)
  popup.append(title, input, chips, error, actions)
  host.append(trigger, popup)

  function close(focus = false) {
    if (!state) return
    state = undefined; popup.hidden = true
    setInactiveSelectionShown(editor, false)
    if (focus) editor.view.focus()
  }
  function update() {
    trigger.hidden = true
    if (!canEdit()) { close(); return }
    const range = state
      ? 'id' in state ? queueAnchorRange(editor.state, state.id) : state.doc === editor.state.doc ? state.selection : null
      : editor.isFocused && queue.canAnnotate() ? editor.state.selection : null
    if (!range) { close(); return }
    try {
      const end = editor.view.coordsAtPos(range.to)
      if (state) {
        const start = editor.view.coordsAtPos(range.from), height = popup.offsetHeight || 150
        popup.style.left = Math.max(8, Math.min(start.left, end.left, innerWidth - 348)) + 'px'
        popup.style.top = Math.max(8, end.bottom + height + 16 > innerHeight ? start.top - height - 8 : end.bottom + 8) + 'px'
      } else {
        const viewport = editor.view.dom.closest('.editor-scroll')?.getBoundingClientRect()
        if (viewport && (end.bottom <= viewport.top || end.top >= viewport.bottom)) return
        trigger.style.left = Math.max(8, Math.min(end.right + 6, innerWidth - 106)) + 'px'
        trigger.style.top = Math.max(8, Math.min(end.bottom + 4, innerHeight - 38)) + 'px'
        trigger.hidden = false
      }
    } catch { close() }
  }
  function open(next: State) {
    const item = 'id' in next ? queue.items().find(entry => entry.id === next.id && !entry.stale) : undefined
    if ('id' in next && !item) return
    state = next
    title.textContent = item ? zh.aiAskEditTitle : zh.aiAskTitle
    popup.setAttribute('aria-label', title.textContent)
    input.value = item?.instruction ?? ''; error.textContent = ''
    popup.hidden = false; chips.hidden = !!item; remove.hidden = !item
    apply.textContent = item ? zh.aiAskUpdate : zh.aiAskQueue
    setInactiveSelectionShown(editor, !item)
    update()
    if (!popup.hidden) { input.focus(); input.select() }
  }
  function commit(focus: boolean) {
    const text = input.value.trim()
    if (!state || !text || !canEdit()) { close(focus); return }
    try {
      if ('id' in state) {
        if (queue.items().some(item => item.id === (state as {id:string}).id && !item.stale)) queue.update(state.id, text)
      } else if (state.doc === editor.state.doc) queue.add(text, state.selection)
      close(focus)
    } catch (failure) { error.textContent = failure instanceof Error ? failure.message : String(failure) }
  }
  const outside = (event: PointerEvent) => {
    if (state && !event.composedPath().includes(popup)) commit(false)
  }
  const anchorClick = (event: Event) => {
    const id = (event as CustomEvent<{qid?: string}>).detail?.qid
    if (id && canEdit()) open({ id })
  }
  popup.addEventListener('keydown', event => {
    if (event.isComposing || event.keyCode === 229) return
    if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); close(true) }
    else if (event.key === 'Enter' && event.target === input) { event.preventDefault(); commit(true) }
  })
  const hide = () => { trigger.hidden = true }
  editor.on('transaction', update); editor.on('focus', update); editor.on('blur', hide)
  document.addEventListener('pointerdown', outside, true)
  window.addEventListener(AI_QUEUE_ANCHOR_CLICK, anchorClick)
  window.addEventListener('scroll', update, true); window.addEventListener('resize', update)
  return () => {
    editor.off('transaction', update); editor.off('focus', update); editor.off('blur', hide)
    document.removeEventListener('pointerdown', outside, true)
    window.removeEventListener(AI_QUEUE_ANCHOR_CLICK, anchorClick)
    window.removeEventListener('scroll', update, true); window.removeEventListener('resize', update)
    close()
    trigger.remove(); popup.remove()
  }
}
