import { pdfRibbonLabel } from './pdf-ribbon-locales'

const TABS = [
  { id: 'home', labels: { en: 'Home', zh: '开始' } },
  { id: 'annotate', labels: { en: 'Annotate', zh: '注释' } },
  { id: 'edit', labels: { en: 'Edit', zh: '编辑' } },
  { id: 'page', labels: { en: 'Page', zh: '页面' } },
  { id: 'view', labels: { en: 'View', zh: '视图' } },
  { id: 'fillForm', labels: { en: 'Fill Form', zh: '填写表单' }, contextual: true },
  { id: 'formDesign', labels: { en: 'Form Design', zh: '表单设计' }, contextual: true },
] as const

export interface PdfRibbon {
  group(tab: string, label: string): HTMLElement
  setHasForms(hasForms: boolean): void
  setLanguage(language: string): void
  dispose(): void
}

export function createPdfRibbon(host: HTMLElement, options: { hasForms?: boolean } = {}): PdfRibbon {
  const root = document.createElement('div')
  root.className = 'pdf-ribbon'
  root.setAttribute('role', 'region')
  root.setAttribute('aria-label', 'PDF ribbon')
  const tabs = document.createElement('div')
  tabs.className = 'pdf-ribbon-tabs'
  tabs.setAttribute('role', 'tablist')
  const panels = new Map<string, HTMLElement>()
  const buttons = new Map<string, HTMLButtonElement>()
  const contextual = new Set<string>()
  let active = 'home'
  let hasForms = options.hasForms === true
  let language = document.documentElement.lang || 'en'
  const tabLabel = (tab: typeof TABS[number]) => pdfRibbonLabel(tab.labels.zh, language)
  const groups: { element: HTMLElement; name: string; title: HTMLElement }[] = []

  const select = (id: string) => {
    active = id
    for (const [tabId, panel] of panels) {
      panel.hidden = tabId !== id
      buttons.get(tabId)?.setAttribute('aria-selected', String(tabId === id))
      buttons.get(tabId)?.setAttribute('tabindex', String(tabId === id ? 0 : -1))
    }
  }

  for (const tab of TABS) {
    const button = document.createElement('button')
    button.type = 'button'
    button.textContent = tabLabel(tab)
    button.id = `pdf-ribbon-tab-${tab.id}`
    button.dataset.pdfRibbonTab = tab.id
    button.setAttribute('role', 'tab')
    button.setAttribute('aria-controls', `pdf-ribbon-panel-${tab.id}`)
    if ('contextual' in tab && tab.contextual) {
      contextual.add(tab.id)
      button.hidden = !hasForms
    }
    button.addEventListener('click', () => select(tab.id))
    button.addEventListener('keydown', event => {
      const visibleTabs = [...buttons].filter(([id]) => !contextual.has(id) || hasForms).map(([id]) => id)
      const index = visibleTabs.indexOf(tab.id)
      const next = event.key === 'ArrowRight' ? visibleTabs[(index + 1) % visibleTabs.length]
        : event.key === 'ArrowLeft' ? visibleTabs[(index + visibleTabs.length - 1) % visibleTabs.length]
        : event.key === 'Home' ? visibleTabs[0]
        : event.key === 'End' ? visibleTabs[visibleTabs.length - 1] : undefined
      if (!next) return
      event.preventDefault()
      select(next)
      buttons.get(next)?.focus()
    })
    tabs.append(button)
    buttons.set(tab.id, button)

    const panel = document.createElement('div')
    panel.id = `pdf-ribbon-panel-${tab.id}`
    panel.dataset.pdfRibbonPanel = tab.id
    panel.setAttribute('role', 'tabpanel')
    panel.setAttribute('aria-labelledby', button.id)
    if (contextual.has(tab.id)) panel.hidden = true
    panel.hidden = tab.id !== active
    panels.set(tab.id, panel)
    root.append(panel)
  }
  root.prepend(tabs)
  host.append(root)
  select(active)

  return {
    group(tab, label) {
      const panel = panels.get(tab)
      if (!panel) throw new Error(`Unknown PDF ribbon tab: ${tab}`)
      const group = document.createElement('section')
      group.className = 'pdf-ribbon-group'
      group.setAttribute('aria-label', label)
      const title = document.createElement('h3')
      title.textContent = pdfRibbonLabel(label, language)
      group.append(title)
      panel.append(group)
      group.setAttribute('aria-label', title.textContent)
      groups.push({ element: group, name: label, title })
      return group
    },
    setHasForms(value) {
      hasForms = value
      for (const id of contextual) {
        buttons.get(id)!.hidden = !value
        if (!value && active === id) select('home')
      }
    },
    setLanguage(value) {
      language = value
      for (const tab of TABS) buttons.get(tab.id)!.textContent = tabLabel(tab)
      for (const group of groups) { group.title.textContent = pdfRibbonLabel(group.name, language); group.element.setAttribute('aria-label', group.title.textContent) }
    },
    dispose() { root.remove() },
  }
}
