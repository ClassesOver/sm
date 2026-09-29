import { describe, expect, it, vi } from 'vitest'

import { createSharePanel } from './share'

describe('edit share panel', () => {
  it('does not overwrite the clipboard when generation finishes after closing', async () => {
    let resolve!: (value: { openUrl: string; expiresAt: string }) => void
    const issue = vi.fn(() => new Promise<{ openUrl: string; expiresAt: string }>((done) => { resolve = done }))
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText } })
    const panel = createSharePanel(document.body, issue)
    panel.open()
    panel.dialog.querySelector<HTMLButtonElement>('[data-share="create"]')!.click()
    panel.close()
    resolve({ openUrl: 'https://reports.test/new', expiresAt: '2026-10-28T00:00:00Z' })
    await vi.waitFor(() => expect(panel.dialog.querySelector<HTMLInputElement>('[data-share="url"]')?.value).toContain('/new'))
    expect(writeText).not.toHaveBeenCalled()
    panel.dialog.remove()
  })

  it('disables copying the old link while generating a new one', async () => {
    const issue = vi.fn()
      .mockResolvedValueOnce({ openUrl: 'https://reports.test/old', expiresAt: '2026-10-28T00:00:00Z' })
      .mockImplementationOnce(() => new Promise(() => {}))
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText: vi.fn().mockResolvedValue(undefined) } })
    const panel = createSharePanel(document.body, issue)
    panel.open()
    const create = panel.dialog.querySelector<HTMLButtonElement>('[data-share="create"]')!
    create.click()
    await vi.waitFor(() => expect(create.disabled).toBe(false))
    create.click()
    expect(panel.dialog.querySelector<HTMLButtonElement>('[data-share="copy"]')!.disabled).toBe(true)
    panel.close()
    panel.dialog.remove()
  })

  it('issues a link only after confirmation and leaves it selectable if clipboard fails', async () => {
    const issue = vi.fn().mockResolvedValue({
      openUrl: 'https://reports.test/reports/v1/editor/open/shared-token',
      expiresAt: '2026-10-28T00:00:00Z',
    })
    const writeText = vi.fn().mockRejectedValueOnce(new Error('denied')).mockResolvedValue(undefined)
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true, value: { writeText },
    })
    const panel = createSharePanel(document.body, issue)

    panel.open()
    expect(issue).not.toHaveBeenCalled()
    expect(panel.dialog.textContent).toContain('获得链接的人可以编辑此修订版')
    expect(panel.dialog.textContent).toContain('30 天')
    panel.dialog.querySelector<HTMLButtonElement>('[data-share="create"]')!.click()
    await vi.waitFor(() => expect(issue).toHaveBeenCalledOnce())
    await vi.waitFor(() => expect(panel.dialog.querySelector<HTMLInputElement>('[data-share="url"]')?.value).toContain('shared-token'))
    await vi.waitFor(() => expect(panel.dialog.querySelector<HTMLElement>('[data-share="status"]')?.textContent).toContain('手动复制'))
    expect(panel.dialog.querySelector<HTMLElement>('[data-share="renew-note"]')?.textContent).toContain('旧链接仍有效')
    panel.dialog.querySelector<HTMLButtonElement>('[data-share="copy"]')!.click()
    await vi.waitFor(() => expect(writeText).toHaveBeenCalledTimes(2))
    expect(issue).toHaveBeenCalledOnce()
    panel.close()
    panel.open()
    expect(panel.dialog.querySelector<HTMLInputElement>('[data-share="url"]')?.value).toContain('shared-token')
    expect(issue).toHaveBeenCalledOnce()
    panel.dialog.remove()
  })
})
