import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { IconComment, IconSidebarCollapse } from './vendor/genoffice-slides/components/icons'
import { commentTextError, sourceComments, type CommentEdit, type SlideComment, type SlideComments } from './slides-comments'

interface PaneState { visible: boolean; slideIndex: number; pageNumber: number; source?: SlideComments; edits: CommentEdit[]; locked: boolean; reason?: string }
export function createSlidesCommentsPane(callbacks: {
  onAdd: (items: { slideIndex: number; text: string }[]) => boolean
  onDelete: (slideIndex: number, comment: SlideComment) => void
  onWithdraw: (clientId: string) => void
  onClose: () => void
}) {
  const element = document.createElement('aside')
  element.className = 'slides-comments-pane comments-pane'
  element.setAttribute('aria-label', '经典批注')
  element.hidden = true
  const drafts = new Map<number, string>()
  let state: PaneState | undefined
  let message = ''
  const button = (action: string, label: string, click: () => void) => {
    const control = document.createElement('button'); control.type = 'button'; control.dataset.commentAction = action; control.textContent = label; control.setAttribute('aria-label', label); control.addEventListener('click', click); return control
  }
  const submit = (all: boolean): boolean => {
    if (!state || state.locked) return false
    const pending = [...drafts].filter(([slideIndex, text]) => (all || slideIndex === state!.slideIndex) && (all ? Boolean(text.trim()) : true))
    for (const [, text] of pending) { const error = commentTextError(text); if (error) { message = error; render(); return false } }
    if (!pending.length) return true
    if (!callbacks.onAdd(pending.map(([slideIndex, text]) => ({ slideIndex, text })))) return false
    for (const [slideIndex] of pending) drafts.delete(slideIndex)
    message = ''; render(); return true
  }
  const render = () => {
    if (!state) return
    element.hidden = !state.visible
    if (!state.visible) return
    const source = sourceComments(state.source), reason = state.reason || source.readOnlyReason
    element.replaceChildren()
    const heading = document.createElement('div'); heading.className = 'inspector-heading comments-heading'
    const title = document.createElement('span'); title.textContent = '批注 · 第 ' + state.pageNumber + ' 页'; heading.append(title)
    const close = button('close', '折叠批注窗格', callbacks.onClose); close.innerHTML = renderToStaticMarkup(createElement(IconSidebarCollapse, { size: 15 })); heading.append(close); element.append(heading)
    const list = document.createElement('div'); list.className = 'comments-list'
    if (reason) { const warning = document.createElement('p'); warning.className = 'comments-readonly'; warning.textContent = reason; list.append(warning) }
    const removed = state.edits.filter((edit): edit is Extract<CommentEdit, { kind: 'delete' }> => edit.kind === 'delete' && edit.slideIndex === state!.slideIndex)
    const original = source.items.filter(item => !removed.some(edit => edit.authorId === item.authorId && edit.idx === item.idx))
    const added = state.edits.filter((edit): edit is Extract<CommentEdit, { kind: 'add' }> => edit.kind === 'add' && edit.slideIndex === state!.slideIndex)
    const card = (author: string, initials: string, text: string, dt: string) => {
      const article = document.createElement('article'); article.className = 'comment-card'
      const head = document.createElement('div'); head.className = 'comment-head'
      const avatar = document.createElement('span'); avatar.className = 'comment-avatar'; avatar.textContent = (initials || author).slice(0, 2)
      const meta = document.createElement('span'); meta.className = 'comment-meta'
      const name = document.createElement('span'); name.className = 'comment-author'; name.textContent = author; meta.append(name)
      if (dt) { const date = document.createElement('span'); date.className = 'comment-time'; const parsed = new Date(dt); date.textContent = Number.isNaN(parsed.getTime()) ? dt : parsed.toLocaleString('zh-CN'); meta.append(date) }
      const content = document.createElement('div'); content.className = 'comment-text'; content.textContent = text
      head.append(avatar, meta); article.append(head, content); list.append(article); return { article, head }
    }
    for (const item of original) {
      const row = card(item.author, item.initials, item.text, item.dt)
      row.article.dataset.commentAuthorId = String(item.authorId); row.article.dataset.commentIdx = String(item.idx)
      const remove = button('delete', '删除批注', () => callbacks.onDelete(state!.slideIndex, item)); remove.className = 'comment-del'; remove.disabled = state.locked || !!reason; row.head.append(remove)
    }
    for (const item of added) {
      const row = card('用户', '用', item.text, '待保存'); row.article.dataset.commentClientId = item.clientId
      const withdraw = button('withdraw', '撤回新增批注', () => callbacks.onWithdraw(item.clientId)); withdraw.className = 'comment-del'; withdraw.disabled = state.locked; row.head.append(withdraw)
    }
    if (!original.length && !added.length && !reason) { const empty = document.createElement('div'); empty.className = 'comments-empty'; empty.innerHTML = renderToStaticMarkup(createElement(IconComment, { size: 22 })); const text = document.createElement('p'); text.textContent = '此页暂无经典批注'; empty.append(text); list.append(empty) }
    element.append(list)
    if (drafts.has(state.slideIndex) && !reason) {
      const composer = document.createElement('div'); composer.className = 'comment-new'
      const input = document.createElement('textarea'); input.dataset.commentText = ''; input.rows = 3; input.maxLength = 10000; input.value = drafts.get(state.slideIndex)!; input.placeholder = '输入批注内容…'; input.setAttribute('aria-label', '批注内容'); input.disabled = state.locked
      const status = document.createElement('p'); status.className = 'comments-status'; status.setAttribute('role', 'status'); status.textContent = message
      const post = button('add', '发布批注', () => { submit(false) }); post.className = 'btn-primary'; post.disabled = state.locked || commentTextError(input.value) !== null
      input.addEventListener('input', () => { drafts.set(state!.slideIndex, input.value); const error = commentTextError(input.value); status.textContent = input.value ? error || '保存修订时将一并发布此批注' : ''; post.disabled = state!.locked || error !== null })
      input.addEventListener('keydown', event => { if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) { event.preventDefault(); submit(false) } })
      const cancel = button('cancel', '取消', () => { drafts.delete(state!.slideIndex); message = ''; render() }); cancel.disabled = state.locked
      const actions = document.createElement('div'); actions.className = 'comment-new-actions'; actions.append(cancel, post); composer.append(input, status, actions); element.append(composer)
    } else if (!reason) { const create = button('compose', '新增批注', () => openComposer()); create.className = 'comments-compose'; create.disabled = state.locked; element.append(create) }
  }
  const openComposer = () => {
    if (!state || state.locked) return
    const reason = state.reason || sourceComments(state.source).readOnlyReason
    if (reason) { message = reason; render(); return }
    if (!drafts.has(state.slideIndex)) drafts.set(state.slideIndex, '')
    message = ''; render(); element.querySelector<HTMLTextAreaElement>('[data-comment-text]')?.focus()
  }
  return { element, update(next: PaneState) { state = next; render() }, openComposer, flush: () => submit(true), hasDraft: (slideIndex: number) => Boolean(drafts.get(slideIndex)?.trim()), clearDrafts() { drafts.clear(); message = '' } }
}
