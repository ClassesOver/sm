import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { IconAiPanel, IconClose, IconNewChat, IconSparkle, IconStop } from './vendor/genoffice-docs/apps/docs/src/renderer/components/icons'
import { createImeEnterGuard } from './vendor/genoffice-docs/packages/ui/src/ime-enter'
import './office-assistant-panel.css'

export function createOfficeNewChatButton() {
  const button = document.createElement('button')
  button.type = 'button'
  button.className = 'office-assistant-new-chat'
  button.title = '新对话'
  button.setAttribute('aria-label', button.title)
  button.innerHTML = renderToStaticMarkup(createElement(IconNewChat, {size:16}))
  return button
}

/** 对齐 GenOffice 的 header / ai-chat / composer 三段侧栏；保留已有任务控制器。 */
export function bindOfficeAssistantPanel(panel: HTMLElement, parts: {
  title: HTMLElement; help: HTMLElement; input: HTMLTextAreaElement
  start: HTMLButtonElement; cancel: HTMLButtonElement; close: HTMLButtonElement
  controls?: HTMLElement; scope?: HTMLSelectElement; headerAction?: HTMLButtonElement
  queue?: HTMLElement; onQueue?(): void
  onClose?(): void
}) {
  const {title,help,input,start,cancel,close,controls} = parts
  const scope = parts.scope ?? input.form?.querySelector<HTMLSelectElement>('select') ?? undefined
  const originalForm = start.form ?? input.form
  if (originalForm) { originalForm.id ||= 'office-ai-form-' + crypto.randomUUID(); start.setAttribute('form', originalForm.id) }
  panel.classList.add('office-assistant-layout')
  const header = document.createElement('header'); header.className = 'office-assistant-header'
  const icon = document.createElement('span'); icon.className = 'office-assistant-icon'; icon.innerHTML = renderToStaticMarkup(createElement(IconAiPanel,{size:20}))
  close.classList.add('office-assistant-close'); close.setAttribute('aria-label','关闭助手'); close.title = '关闭助手（Esc）'
  close.innerHTML = renderToStaticMarkup(createElement(IconClose,{size:18}))
  header.append(icon,title)
  if (parts.headerAction) header.append(parts.headerAction)
  header.append(close);panel.prepend(header)
  const details = document.createElement('details');details.className = 'office-assistant-details'
  const summary = document.createElement('summary');summary.textContent = '阅读范围与限制'
  details.append(summary,help)
  help.classList.add('office-assistant-help')
  const toolbar = document.createElement('div');toolbar.className = 'office-assistant-toolbar'
  if (controls) { controls.classList.add('office-assistant-presets'); toolbar.append(controls) }
  if (scope) { const oldLabel = scope.closest('label'); const label = document.createElement('label');label.className = 'office-assistant-scope';label.append(scope.getAttribute('aria-label')?.includes('授权') ? '授权范围' : '阅读范围',scope);toolbar.append(label); if (oldLabel && !oldLabel.querySelector('input,textarea,select,button')) oldLabel.remove() }
  toolbar.append(details)
  input.placeholder ||= '输入问题或补充要求…'
  const actions = document.createElement('div');actions.className = 'office-assistant-actions'
  start.querySelector('svg')?.remove();start.prepend(svg(IconSparkle))
  cancel.querySelector('svg')?.remove();cancel.prepend(svg(IconStop))
  const composer = document.createElement('div'); composer.className = 'office-assistant-composer'
  if (parts.queue) composer.append(parts.queue)
  const inputLabel = input.closest('label')
  composer.append(inputLabel && !inputLabel.querySelector('select') ? inputLabel : input)
  actions.append(start,cancel);composer.append(actions)
  const body = document.createElement('div'); body.className = 'office-assistant-body'
  body.tabIndex=0;body.setAttribute('role','region');body.setAttribute('aria-label','助手结果与工具进度')
  const readKeys=(event:KeyboardEvent)=>{
    if(event.target!==body||event.isComposing||event.altKey||event.ctrlKey||event.metaKey||event.shiftKey||body.scrollHeight<=body.clientHeight||!['Home','End'].includes(event.key))return
    event.preventDefault();body.scrollTop=event.key==='Home'?0:body.scrollHeight
  }
  body.addEventListener('keydown',readKeys)
  // GenOffice AiPanel.tsx (f8c17004): follow replies within 48px of the end;
  // preserve the reader's position when they scroll up. Model picker omitted.
  let stickToBottom = true, panelDisposed = false
  let followFrame: number | undefined
  const onBodyScroll = () => { stickToBottom = body.scrollHeight - body.scrollTop - body.clientHeight < 48 }
  const resetFollowing = () => { stickToBottom = true }
  const contentObserver = new MutationObserver(() => {
    if (stickToBottom) body.scrollTop = body.scrollHeight
  })
  contentObserver.observe(body, {childList:true,subtree:true,characterData:true})
  body.addEventListener('scroll',onBodyScroll,{passive:true})
  parts.headerAction?.addEventListener('click',resetFollowing)
  for (const node of [...panel.childNodes]) if (node !== header) body.append(node)
  panel.append(toolbar,body,composer)
  // 部分控制器在绑定外壳后才挂载工具进度，仍归入中间滚动区。
  const observer = new MutationObserver(() => {
    for (const node of [...panel.childNodes]) if (![header,toolbar,body,composer].includes(node as HTMLElement)) body.append(node)
  })
  observer.observe(panel,{childList:true})
  let trigger: HTMLElement | null = null
  function svg(component: typeof IconSparkle) {
    const holder = document.createElement('span');holder.innerHTML = renderToStaticMarkup(createElement(component,{size:16}));return holder.firstElementChild!
  }
  function closePanel() {
    parts.onClose?.(); panel.hidden = true
    const fallback = panel.parentElement?.querySelector<HTMLButtonElement>('.office-ai-entry:not(:disabled)')
    const target = trigger?.isConnected ? trigger : fallback
    target?.focus({preventScroll:true})
  }
  const ime = createImeEnterGuard()
  input.addEventListener('compositionstart', ime.handleCompositionStart)
  input.addEventListener('compositionend', ime.handleCompositionEnd)
  const onInputKey = (event: KeyboardEvent) => {
    if (event.defaultPrevented || ime.isImeConfirm(event)) return
    if (event.key !== 'Enter' || event.shiftKey || event.ctrlKey || event.altKey || event.metaKey) return
    event.preventDefault()
    event.stopPropagation()
    if (event.repeat) return
    if (!start.disabled) start.click()
    else if (!cancel.disabled && input.value.trim()) parts.onQueue?.()
  }
  input.addEventListener('keydown', onInputKey)
  const onKeyDown = (event: KeyboardEvent) => {
    if (event.key !== 'Escape' || event.defaultPrevented || ime.isImeConfirm(event)) return
    event.preventDefault()
    event.stopPropagation()
    if (event.repeat) return
    if (!cancel.hidden && !cancel.disabled) cancel.click()
    else closePanel()
  }
  close.addEventListener('click',closePanel);panel.addEventListener('keydown',onKeyDown)
  return {
    beforeTask() { resetFollowing() },
    beforeOpen() {
      const active = document.activeElement
      if (active instanceof HTMLElement && active !== document.body && !panel.contains(active)) trigger = active
      if (followFrame !== undefined) cancelAnimationFrame(followFrame)
      followFrame = requestAnimationFrame(() => { followFrame=undefined; if (!panelDisposed && !panel.hidden && stickToBottom) body.scrollTop = body.scrollHeight })
    },
    dispose() {
      panelDisposed = true
      if (followFrame !== undefined) cancelAnimationFrame(followFrame)
      contentObserver.disconnect()
      body.removeEventListener('scroll', onBodyScroll)
      parts.headerAction?.removeEventListener('click', resetFollowing)
      observer.disconnect()
      close.removeEventListener('click', closePanel)
      panel.removeEventListener('keydown', onKeyDown)
      input.removeEventListener('keydown', onInputKey)
      input.removeEventListener('compositionstart', ime.handleCompositionStart)
      input.removeEventListener('compositionend', ime.handleCompositionEnd)
      body.removeEventListener('keydown', readKeys)
    },
  }
}
