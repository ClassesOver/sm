export type ToolbarBar = 'public' | 'format' | 'context'
export interface ToolbarContext { kind: string; id?: string; label?: string }
export interface ToolbarAction {
  id: string
  bar: ToolbarBar
  label: string
  icon?: string
  element?: HTMLButtonElement
  visible?: () => boolean
  disabled?: () => boolean
  run: () => void | Promise<void>
}

/** 动作注册拥有按钮生命周期；格式实现只提供动作及状态，不再复制按钮模板。 */
export function createToolbar(host: HTMLElement) {
  const bars = {} as Record<ToolbarBar, HTMLElement>
  for (const [bar, label] of [['public', '公共操作'], ['format', '格式操作'], ['context', '当前对象操作']] as const) {
    const node = document.createElement('div')
    node.className = `editor-toolbar-bar editor-toolbar-${bar}`
    node.dataset.toolbarBar = bar
    node.setAttribute('role', 'toolbar'); node.setAttribute('aria-label', label)
    host.append(node); bars[bar] = node
  }
  const actions = new Map<string, { action: ToolbarAction; button: HTMLButtonElement; busy: boolean }>()
  let context: ToolbarContext | null = null
  const refresh = () => {
    for (const entry of actions.values()) {
      if (entry.action.visible) entry.button.hidden = !entry.action.visible()
      entry.button.setAttribute('aria-busy', String(entry.busy))
      entry.button.disabled = entry.busy || Boolean(entry.action.disabled?.())
    }
  }
  const registerToolbarAction = (action: ToolbarAction) => {
    if (actions.has(action.id)) throw new Error(`重复的工具栏动作：${action.id}`)
    const existing = action.element ?? [...(host.closest('.report-app') ?? host).querySelectorAll<HTMLButtonElement>('button[data-action]')].find(node => node.dataset.action === action.id)
    const button = existing ?? document.createElement('button')
    button.type = 'button'; button.dataset.action = action.id
    if (!existing) { button.textContent = action.label; button.setAttribute('aria-label', action.label) }
    if (action.icon && !existing) { const icon = document.createElement('i'); icon.dataset.lucide = action.icon; icon.setAttribute('aria-hidden', 'true'); button.prepend(icon) }
    const entry = { action, button, busy: false }
    button.addEventListener('click', async () => {
      if (entry.busy || action.disabled?.() || action.visible?.() === false) return
      entry.busy = true; refresh()
      try { await action.run() }
      catch (error) { host.dispatchEvent(new CustomEvent('toolbar-error', { bubbles: true, detail: error })) }
      finally { entry.busy = false; refresh() }
    })
    if (!button.closest('[data-toolbar-overflow]')) bars[action.bar].append(button);  actions.set(action.id, entry); refresh()
    return () => { button.remove(); actions.delete(action.id) }
  }
  return {
    bars, registerToolbarAction, refreshToolbar: refresh,
    setContextTarget(target: ToolbarContext | null) {
      context = target
      bars.context.dataset.targetKind = target?.kind ?? ''
      bars.context.setAttribute('aria-label', target?.label ? `当前对象操作：${target.label}` : '当前对象操作')
      refresh()
    },
    getContextTarget: () => context,
  }
}
