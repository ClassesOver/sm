import { beforeEach, describe, expect, it } from 'vitest'
import { createExportSettingsPanel } from './export-settings'

describe('createExportSettingsPanel', () => {
  beforeEach(() => { document.body.innerHTML = '<main id="app"></main>' })
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
})
