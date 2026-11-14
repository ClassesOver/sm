import { afterEach, expect, it } from 'vitest'
import { NativeDraft } from './native-draft'
import { createPdfFormSettingsPanel } from './pdf-form-settings-panel'
import { bindPdfFormDesignPanel } from './pdf-form-design'

afterEach(() => document.body.replaceChildren())

function fixture(kind: 'settings' | 'design') {
  const foreign = document.body.appendChild(document.createElement('button'))
  foreign.dataset.pdfRibbonTab = 'home'; foreign.setAttribute('aria-selected', 'true')
  const root = document.body.appendChild(document.createElement('main'))
  const selected = root.appendChild(document.createElement('button'))
  selected.dataset.pdfRibbonTab = 'home'; selected.setAttribute('aria-selected', 'true')
  const source = root.appendChild(document.createElement('section'))
  const opener = source.appendChild(document.createElement('button'))
  opener.focus()
  const draft = new NativeDraft({ documentId: 'panel-close', revision: 1, sourceSha256: 'a'.repeat(64), scope: { database: 'db', companyId: 'co', userId: 'u', threadId: 't' } }, { getItem: () => null, setItem() {}, removeItem() {} })
  const ui = kind === 'settings'
    ? createPdfFormSettingsPanel(root, 'pdf-form-create-panel', '字段设置', '帮助', '关闭字段设置')
    : bindPdfFormDesignPanel({ root, draft, model: () => ({ sourceSha256: 'a'.repeat(64), formDesignWidgets: [] }), unavailable: () => null, refresh: async () => {} })
  ui.open()
  const panel = 'panel' in ui ? ui.panel : ui.element
  const close = panel.querySelector<HTMLButtonElement>('header button')!
  return { foreign, selected, source, opener, panel, close, draft }
}

for (const kind of ['settings', 'design'] as const) {
  for (const action of ['click', 'Escape']) {
    it.each(['hidden', 'disabled', 'disconnected'])(`${kind} ${action}: unavailable %s opener returns focus to its own selected tab`, state => {
      const f = fixture(kind)
      if (state === 'hidden') f.source.hidden = true
      else if (state === 'disabled') f.opener.disabled = true
      else f.opener.remove()
      f.close.focus()
      if (action === 'click') f.close.click()
      else f.close.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }))
      expect(f.panel.hidden).toBe(true)
      expect(document.activeElement).toBe(f.selected)
      expect(document.activeElement).not.toBe(f.foreign)
      expect(f.draft.operations).toEqual([])
    })
    it(`${kind} ${action}: visible opener remains the preferred focus destination`, () => {
      const f = fixture(kind)
      if (action === 'click') f.close.click()
      else f.close.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }))
      expect(document.activeElement).toBe(f.opener)
      expect(f.draft.operations).toEqual([])
    })
  }
}
