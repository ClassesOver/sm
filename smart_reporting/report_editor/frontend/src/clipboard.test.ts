import { afterEach, describe, expect, it, vi } from 'vitest'

import { copyText } from './clipboard'

describe('copyText', () => {
  afterEach(() => {
    vi.restoreAllMocks()
    delete (document as Partial<Document>).execCommand
  })

  it('uses the Clipboard API when it succeeds', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText } })
    document.execCommand = vi.fn()

    await copyText('https://reports.test/a')

    expect(writeText).toHaveBeenCalledWith('https://reports.test/a')
    expect(document.execCommand).not.toHaveBeenCalled()
  })

  it('falls back to selection copy when the Clipboard API rejects', async () => {
    const writeText = vi.fn().mockRejectedValue(new Error('denied'))
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText } })
    const execCommand = vi.fn().mockReturnValue(true)
    document.execCommand = execCommand

    await expect(copyText('https://reports.test/b')).resolves.toBeUndefined()

    expect(execCommand).toHaveBeenCalledWith('copy')
    expect(document.body.querySelector('textarea')).toBeNull()
  })

  it('falls back to selection copy when the Clipboard API is missing', async () => {
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: undefined })
    const execCommand = vi.fn().mockReturnValue(true)
    document.execCommand = execCommand

    await expect(copyText('https://reports.test/c')).resolves.toBeUndefined()

    expect(execCommand).toHaveBeenCalledWith('copy')
  })

  it('rejects when both paths fail', async () => {
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: undefined })

    await expect(copyText('https://reports.test/d')).rejects.toThrow('clipboard unavailable')
  })
})
