import { createElement, ChevronRight, ChartNoAxesCombined, CircleCheck, CircleAlert, Sparkles, Table2, X } from 'lucide'
import { buttonClasses } from './button'
import { createModal } from './modal'

type SessionState = 'idle' | 'running' | 'ready' | 'error' | 'applied'
type SourceState = 'checking' | 'updated' | 'error' | 'unavailable'
const stateLabels: Record<SessionState, string> = { idle: '可编辑', running: '处理中', ready: '待确认', error: '需重试', applied: '已采用' }

/** 图与表共享一个非模态侧栏；收起只隐藏界面，任务和会话仍由各编辑器持有。 */
export function createAskAIPanel(root: HTMLElement = document.body) {
  const panel = document.createElement('aside')
  panel.className = 'ask-ai-panel'
  panel.hidden = true
  panel.setAttribute('aria-label', 'Ask AI 图表助手')
  panel.innerHTML = `
    <header class="ask-ai-header"><span class="ask-ai-brand"></span><div><h2>Ask AI</h2></div></header>
    <nav class="ask-ai-sessions" aria-label="编辑会话"></nav>
    <div class="ask-ai-content"></div>
    <div class="ask-ai-review-docks"></div>
    <div class="ask-ai-composers"></div>
  `
  panel.querySelector('.ask-ai-brand')!.append(createElement(Sparkles, { width: 22, height: 22, 'aria-hidden': 'true' }))
  const closeButton = document.createElement('button')
  closeButton.type = 'button'
  closeButton.className = `${buttonClasses('quiet', true)} ask-ai-close`
  closeButton.setAttribute('aria-label', '收起 Ask AI')
  closeButton.title = '收起侧栏，任务继续运行'
  closeButton.append(createElement(ChevronRight, { width: 20, height: 20, 'aria-hidden': 'true' }))
  panel.querySelector('header')!.append(closeButton)
  const launcher = document.createElement('button')
  launcher.type = 'button'
  launcher.className = 'ask-ai-launcher'
  launcher.hidden = true
  launcher.setAttribute('aria-label', '打开 Ask AI，恢复编辑会话')
  launcher.setAttribute('aria-expanded', 'false')
  const notifications = document.createElement('div')
  notifications.className = 'ask-ai-notifications'
  notifications.hidden = true
  notifications.setAttribute('role', 'status')
  notifications.setAttribute('aria-live', 'polite')
  notifications.setAttribute('aria-label', 'Ask AI 任务提示')
  root.append(panel, launcher, notifications)
  const navigation = panel.querySelector<HTMLElement>('nav')!
  const content = panel.querySelector<HTMLElement>('.ask-ai-content')!
  const composers = panel.querySelector<HTMLElement>('.ask-ai-composers')!
  const reviewDocks = panel.querySelector<HTMLElement>('.ask-ai-review-docks')!
  let sourceState: SourceState = 'checking'
  let sourceDetail = ''
  const setSourceStatus = (state: SourceState, detail = '') => {
    sourceState = state; sourceDetail = detail
    for (const status of content.querySelectorAll<HTMLElement>('.ask-ai-source-state')) {
      status.dataset.state = state
      status.setAttribute('aria-busy', String(state === 'checking'))
      status.querySelector('span')!.textContent = state === 'checking' ? '正在更新引用…'
        : state === 'updated' ? '引用已刷新' : state === 'unavailable' ? '未启用引用核验' : '引用更新失败，正文改动仍保留'
      status.title = detail
      status.querySelector<HTMLButtonElement>('button')!.hidden = state !== 'error'
    }
  }
  const sessions = new Set<ReturnType<typeof createSession>>()
  const sessionCounts = { chart: 0, table: 0 }
  let active: ReturnType<typeof createSession> | null = null
  let opener: HTMLElement | null = null
  let imagePreview: ReturnType<typeof createModal> | null = null
  const zoomImage = (target: HTMLImageElement) => {
    imagePreview ??= createModal({ root, overlayClass: 'ask-ai-image-preview', label: '图表放大预览', variant: 'media', closeLabel: '关闭图表预览', content: '<figure><img alt=""><figcaption></figcaption></figure>' })
    if (!imagePreview.card.querySelector('.ask-ai-image-preview-hint')) {
      const hint = document.createElement('p'); hint.className = 'ask-ai-image-preview-hint'; hint.textContent = '点击图片外区域或按 Esc 关闭'
      imagePreview.card.append(hint)
    }
    imagePreview.card.querySelector('img')!.src = target.getAttribute('src') ?? ''
    imagePreview.card.querySelector('figcaption')!.textContent = target.alt
    imagePreview.open()
  }
  panel.addEventListener('click', event => {
    if (event.target instanceof HTMLImageElement && !event.target.closest('.ask-ai-session-tab')) zoomImage(event.target)
  })
  panel.addEventListener('keydown', event => {
    if (event.target instanceof HTMLImageElement && !event.target.closest('.ask-ai-session-tab') && (event.key === 'Enter' || event.key === ' ')) {
      event.preventDefault(); zoomImage(event.target)
    }
  })
  const prepareImages = () => content.querySelectorAll('img').forEach(img => {
    img.tabIndex = 0
    img.setAttribute('role', 'button')
    img.setAttribute('aria-label', `${img.alt || '图表'}，点击放大`)
  })
  const imageObserver = new MutationObserver(prepareImages)
  imageObserver.observe(content, { childList: true, subtree: true })
  const refresh = () => {
    const running = [...sessions].filter(session => session.state === 'running').length
    const ready = [...sessions].filter(session => session.state === 'ready').length
    launcher.textContent = running ? `Ask AI · ${running} 项处理中` : ready ? `Ask AI · ${ready} 项待确认` : 'Ask AI · 继续编辑'
    launcher.dataset.ready = String(ready > 0)
    launcher.hidden = sessions.size === 0 || !panel.hidden
    notifications.hidden = !notifications.childElementCount
    if (sessions.size) {
      if (panel.hidden && notifications.parentElement !== root) root.append(notifications)
      else if (!panel.hidden && notifications.parentElement !== panel) panel.insertBefore(notifications, content)
    }
  }
  const hide = (restoreFocus = true) => {
    panel.hidden = true
    document.body.classList.remove('ask-ai-open')
    launcher.setAttribute('aria-expanded', 'false')
    refresh()
    if (restoreFocus && opener?.isConnected) opener.focus()
  }
  const otherPanelOpened = (event: Event) => {
    if ((event as CustomEvent<string>).detail !== 'ask-ai') hide(false)
  }
  document.addEventListener('report-panel-open', otherPanelOpened)
  closeButton.addEventListener('click', () => hide())
  launcher.addEventListener('click', () => active?.open())
  panel.addEventListener('keydown', event => {
    if (event.key === 'Escape' && !event.defaultPrevented) { event.preventDefault(); hide() }
  })

  function createSession(options: { kind: 'chart' | 'table'; label: string; content: string }) {
    const overlay = document.createElement('div')
    overlay.className = options.kind === 'chart' ? 'chart-ai-edit' : 'table-ai-edit'
    overlay.hidden = true
    const card = document.createElement('section')
    card.className = `ask-ai-session ${options.kind}-ai-edit-card`
    card.innerHTML = options.content
    const messages = document.createElement('div')
    messages.className = 'ask-ai-messages'
    messages.setAttribute('role', 'log')
    messages.setAttribute('aria-label', '本次编辑对话')
    // 消息区紧跟会话头（若有）插入；没有会话头时放在内容首位，避免依赖可选锚点导致消息区丢失。
    const headerAnchor = card.querySelector('.panel-header')
    if (headerAnchor) headerAnchor.after(messages)
    else card.prepend(messages)
    const workflow = document.createElement('ol')
    workflow.className = 'ask-ai-steps'
    workflow.setAttribute('aria-label', '修改步骤')
    for (const [index, label] of ['描述需求', 'AI 修改', '预览确认', '采用完成'].entries()) {
      const step = document.createElement('li')
      const marker = document.createElement('span'); marker.className = 'ask-ai-step-marker'; marker.setAttribute('aria-hidden', 'true'); marker.textContent = String(index + 1)
      step.append(marker, label); workflow.append(step)
    }
    card.prepend(workflow)
    overlay.append(card)
    content.append(overlay)
    const reviewDock = document.createElement('div'); reviewDock.className = 'ask-ai-review-dock'; reviewDock.hidden = true; reviewDocks.append(reviewDock)
    const composer = document.createElement('fieldset')
    composer.className = 'ask-ai-composer'
    composer.setAttribute('aria-label', options.kind === 'chart' ? '改图输入区' : '改表输入区')
    composer.hidden = true
    composers.append(composer)
    // 输入区（修改要求）固定在面板底部、滚动区之外：任何状态下都保持展开，审阅态与操作条上下并列。
    const syncComposer = () => { composer.hidden = !session.visible || !composer.childElementCount }
    const tab = document.createElement('button')
    tab.type = 'button'
    tab.className = 'ask-ai-session-tab'
    const tabLabel = document.createElement('span'); tabLabel.className = 'ask-ai-session-label'
    const tabStatus = document.createElement('span'); tabStatus.className = 'ask-ai-session-status'
    const tabIcon = document.createElement('span'); tabIcon.className = 'ask-ai-session-icon'
    tabIcon.append(createElement(options.kind === 'chart' ? ChartNoAxesCombined : Table2, { width: 20, height: 20, 'aria-hidden': 'true' }))
    const tabThumbnail = document.createElement('img'); tabThumbnail.className = 'ask-ai-session-thumbnail'
    tabThumbnail.alt = ''; tabThumbnail.setAttribute('aria-hidden', 'true'); tabThumbnail.hidden = true
    tab.append(tabIcon, tabThumbnail, tabLabel, tabStatus)
    navigation.append(tab)
    const number = ++sessionCounts[options.kind]
    let notification: HTMLElement | null = null
    const clearNotice = () => { notification?.remove(); notification = null; refresh() }
    const session = {
      overlay, card, composer, closeButton, reviewDock,
      idSuffix: number === 1 ? '' : `-${number}`,
      state: 'idle' as SessionState,
      label: options.label,
      get visible() { return active === session && !panel.hidden },
      open(initialFocus?: HTMLElement | null) {
        document.dispatchEvent(new CustomEvent('report-panel-open', { detail: 'ask-ai' }))
        clearNotice()
        if (panel.hidden) opener = document.activeElement instanceof HTMLElement ? document.activeElement : null
        for (const item of sessions) {
          item.overlay.hidden = item !== session
          item.reviewDock.hidden = item !== session || !item.reviewDock.childElementCount
          item.tab.setAttribute('aria-pressed', String(item === session))
        }
        active = session
        panel.hidden = false
        for (const item of sessions) item.syncComposer()
        document.body.classList.add('ask-ai-open')
        launcher.setAttribute('aria-expanded', 'true')
        closeButton.classList.remove('chart-ai-edit-close', 'table-ai-edit-close')
        closeButton.classList.add(`${options.kind}-ai-edit-close`)
        refresh()
        tab.scrollIntoView?.({ block: 'nearest', inline: 'nearest' })
        const availableButton = [...card.querySelectorAll<HTMLButtonElement>('button:not([disabled])')].find(button => !button.closest('details:not([open])'))
        ;(initialFocus ?? (!composer.disabled && !composer.hidden ? composer.querySelector<HTMLElement>('textarea:not([disabled])') : null) ?? card.querySelector<HTMLElement>('textarea:not([disabled])') ?? availableButton ?? closeButton).focus()
      },
      close() { if (active === session) hide() },
      remove() {
        clearNotice()
        sessions.delete(session)
        overlay.remove(); composer.remove(); reviewDock.remove(); tab.remove()
        if (active === session) { active = [...sessions].at(-1) ?? null; if (active && !panel.hidden) active.open(); else hide() }
        if (!sessions.size) { document.removeEventListener('report-panel-open', otherPanelOpened); imageObserver.disconnect(); imagePreview?.remove(); panel.remove(); launcher.remove(); notifications.remove(); document.body.classList.remove('ask-ai-open') }
        refresh()
      },
      setState(state: SessionState) {
        const backgroundFinished = session.state === 'running' && (state === 'ready' || state === 'error') && !session.visible
        if (state === 'running') clearNotice()
        if (state !== 'ready') session.mountReviewActions(null)
        session.state = state; composer.disabled = state === 'running'; updateTab(); updateSteps(); refresh()
        syncComposer()
        if (backgroundFinished) showNotice(state as 'ready' | 'error')
      },
      notifyReplaced(actions?: { locate: () => boolean; continueEditing: () => void }) {
        if (!actions) { showNotice('replaced'); return }
        session.setState('applied')
        session.mountComposer(null)
        const receipt = document.createElement('section'); receipt.className = 'ask-ai-receipt'; receipt.setAttribute('aria-label', '替换完成')
        const icon = document.createElement('span'); icon.className = 'ask-ai-receipt-icon'
        icon.append(createElement(CircleCheck, { width: 26, height: 26, 'aria-hidden': 'true' }))
        const title = document.createElement('h3'); title.textContent = '正文已更新'
        const note = document.createElement('p'); note.textContent = '已替换到正文，可用 Ctrl / ⌘ + Z 撤销。'
        const status = document.createElement('div'); status.className = 'ask-ai-source-state'; status.setAttribute('role', 'status')
        const statusText = document.createElement('span')
        const retry = document.createElement('button'); retry.type = 'button'; retry.className = buttonClasses('quiet'); retry.textContent = '重试'; retry.dataset.action = 'retry-sources'
        retry.addEventListener('click', () => { setSourceStatus('checking'); document.dispatchEvent(new Event('report-source-retry')) })
        status.append(statusText, retry)
        const controls = document.createElement('div'); controls.className = 'ask-ai-receipt-actions'
        const feedback = document.createElement('p'); feedback.className = 'ask-ai-receipt-feedback'; feedback.setAttribute('role', 'status')
        for (const [action, label] of [['locate-body', '定位正文'], ['continue-editing', '继续修改']] as const) {
          const control = document.createElement('button'); control.type = 'button'; control.dataset.action = action; control.className = buttonClasses(action === 'locate-body' ? 'primary' : 'secondary'); control.textContent = label
          control.addEventListener('click', () => {
            if (!actions.locate()) { feedback.dataset.tone = 'warn'; feedback.textContent = '正文内容已变化或无法唯一定位，请在正文重新选择后修改。'; return }
            feedback.dataset.tone = 'ok'
            feedback.textContent = action === 'locate-body' ? '已定位到正文对应位置。' : ''
            if (action === 'continue-editing') actions.continueEditing()
            else if (window.innerWidth < 1200) hide(false)
          })
          controls.append(control)
        }
        receipt.append(icon, title, note, status, controls, feedback)
        card.querySelector('[data-role="body"]')?.replaceChildren(receipt)
        setSourceStatus(sourceState, sourceDetail)
        if (!session.visible) showNotice('replaced')
      },
      setLabel(label: string) { session.label = label; updateTab() },
      setThumbnail(src: string) { tabThumbnail.src = src; tabThumbnail.hidden = false; tabIcon.hidden = true },
      mountReviewActions(actions: HTMLElement | null) {
        reviewDock.replaceChildren(...(actions ? [actions] : []))
        reviewDock.hidden = !session.visible || !actions
      },
      mountComposer(form: HTMLElement | null) {
        composer.replaceChildren(...(form ? [form] : []))
        syncComposer()
      },
      syncComposer,
      focusComposer() {
        syncComposer()
        composer.querySelector<HTMLTextAreaElement>('textarea:not([disabled])')?.focus()
      },
      addMessage(role: 'user' | 'assistant', value: string) {
        const message = document.createElement('p')
        message.className = `ask-ai-message ask-ai-message--${role}`
        message.textContent = value
        messages.append(message)
      },
      tab,
    }
    function updateTab() {
      tabLabel.textContent = `${options.kind === 'chart' ? '图' : '表'} ${number} · ${session.label}`
      tabStatus.textContent = stateLabels[session.state]
      tab.title = `${tabLabel.textContent} · ${tabStatus.textContent}`
      tab.dataset.state = session.state
    }
    function updateSteps() {
      const current = session.state === 'applied' ? 3 : session.state === 'ready' ? 2 : session.state === 'idle' ? 0 : 1
      workflow.setAttribute('aria-busy', String(session.state === 'running'))
      workflow.dataset.state = session.state
      Array.from(workflow.children).forEach((step, index) => {
        const item = step as HTMLElement
        item.dataset.stepState = index < current ? 'done' : index === current ? session.state === 'error' ? 'error' : 'current' : 'pending'
        if (index === current) item.setAttribute('aria-current', 'step')
        else item.removeAttribute('aria-current')
        item.querySelector('span')!.textContent = index < current || session.state === 'applied' ? '✓' : String(index + 1)
      })
    }
    function showNotice(kind: 'ready' | 'error' | 'replaced') {
      clearNotice()
      notification = document.createElement('article')
      notification.className = 'ask-ai-notification'
      notification.dataset.kind = kind
      const icon = document.createElement('span'); icon.className = 'ask-ai-notification-icon'
      icon.append(createElement(kind === 'error' ? CircleAlert : CircleCheck, { width: 20, height: 20, 'aria-hidden': 'true' }))
      const message = document.createElement('div'); message.className = 'ask-ai-notification-content'
      const title = document.createElement('strong')
      title.textContent = kind === 'replaced' ? '已替换到正文' : kind === 'ready' ? '新结果已生成' : '本轮修改未完成'
      const label = document.createElement('p'); label.className = 'ask-ai-notification-target'
      label.textContent = `${options.kind === 'chart' ? '图' : '表'} ${number} · ${session.label}`
      label.title = label.textContent
      const detail = document.createElement('p')
      detail.textContent = kind === 'replaced' ? '可撤销。'
        : kind === 'ready' ? '尚未替换正文。' : '原内容未变。'
      const view = document.createElement('button'); view.type = 'button'
      view.className = buttonClasses('quiet'); view.dataset.action = 'view-session'
      view.textContent = kind === 'replaced' ? '查看回执' : kind === 'ready' ? '查看预览' : '查看原因'
      view.addEventListener('click', () => session.open())
      const dismiss = document.createElement('button'); dismiss.type = 'button'
      dismiss.className = `${buttonClasses('quiet', true)} ask-ai-notification-dismiss`
      dismiss.dataset.action = 'dismiss'; dismiss.setAttribute('aria-label', '关闭此提示')
      dismiss.append(createElement(X, { width: 16, height: 16, 'aria-hidden': 'true' }))
      dismiss.addEventListener('click', clearNotice)
      message.append(title, label, detail, view)
      notification.append(icon, message, dismiss)
      // 最新通知置顶：容器超高滚动时，新结果始终在可视区顶部，不被旧通知挤出。
      notifications.prepend(notification)
      refresh()
    }
    tab.addEventListener('click', () => session.open())
    sessions.add(session)
    updateTab(); updateSteps(); refresh()
    return session
  }
  return { panel, createSession, setSourceStatus }
}

export type AskAISession = ReturnType<ReturnType<typeof createAskAIPanel>['createSession']>
let shared: ReturnType<typeof createAskAIPanel> | null = null
let latestSourceState: SourceState = 'checking'
let latestSourceDetail = ''
export function askAIPanel() {
  if (!shared?.panel.isConnected) {
    shared = createAskAIPanel()
    shared.setSourceStatus(latestSourceState, latestSourceDetail)
  }
  return shared
}

/** 来源刷新不应为了显示提示而创建尚未使用的 AI 侧栏。 */
export function updateAskAISourceStatus(state: SourceState, detail = '') {
  latestSourceState = state; latestSourceDetail = detail
  if (shared?.panel.isConnected) shared.setSourceStatus(state, detail)
}
