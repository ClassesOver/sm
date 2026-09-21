import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createExportSettingsPanel } from './export-settings'

describe('createExportSettingsPanel', () => {
  beforeEach(() => {
    document.body.innerHTML = '<main id="app"></main>'
    localStorage.clear()
  })
  it('returns user-selected export options', () => {
    const panel = createExportSettingsPanel(document.body)
    panel.open()
    panel.dialog.querySelector<HTMLInputElement>('[name="cover"]')!.checked = true
    panel.dialog.querySelector<HTMLInputElement>('[name="toc"]')!.checked = false
    panel.dialog.querySelector<HTMLTextAreaElement>('[name="note"]')!.value = '运营数据复核后发布'
    expect(panel.read()).toEqual({
      cover: true,
      toc: false,
      headerFooter: true,
      pageNumbers: true,
      note: '运营数据复核后发布',
    })
  })

  it('still returns settings when persistence is unavailable', () => {
    const setItem = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new DOMException('quota exceeded', 'QuotaExceededError')
    })
    try {
      const panel = createExportSettingsPanel(document.body)

      let settings: ReturnType<typeof panel.read> | undefined
      expect(() => { settings = panel.read() }).not.toThrow()
      expect(settings).toMatchObject({ toc: true, headerFooter: true, pageNumbers: true })
    } finally {
      setItem.mockRestore()
    }
  })

  it('restores focus when the panel is closed after confirmation', () => {
    const opener = document.createElement('button')
    document.body.append(opener)
    opener.focus()
    const panel = createExportSettingsPanel(document.body)
    panel.open()

    panel.close()

    expect(panel.dialog.hidden).toBe(true)
    expect(document.activeElement).toBe(opener)
  })

  it('closes from the shared modal backdrop and restores the opener', () => {
    const opener = document.createElement('button')
    document.body.append(opener)
    opener.focus()
    const panel = createExportSettingsPanel(document.body)
    panel.open()

    panel.dialog.click()

    expect(panel.dialog.hidden).toBe(true)
    expect(document.activeElement).toBe(opener)
  })
})
