import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { createEditorShell } from './shell'
import { createSlidesEditorView } from './slides-main'
import { NativeDraft } from './native-draft'

// jsdom没有尺寸观察API；让新标尺正常挂载，布局仍由真实浏览器烟测验收。
beforeEach(() => vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} }))

describe('shared PPTX editor', () => {
  beforeEach(() => {
    document.body.innerHTML = '<main id="app"></main>'
    Object.defineProperty(HTMLDialogElement.prototype, 'showModal', { configurable: true, value: function (this: HTMLDialogElement) { this.open = true } })
    Object.defineProperty(HTMLDialogElement.prototype, 'close', { configurable: true, value: function (this: HTMLDialogElement) { this.open = false; this.dispatchEvent(new Event('close')) } })
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    document.body.replaceChildren()
  })

  async function openEditor(headerFooter?: { footer: string | null; slideNum: boolean; date: string | null; dateAuto?: boolean }) {
    const deck = {
      revision: 1, sha256: 'a'.repeat(64), size: { cx: 9144000, cy: 5143500 },
      slides: [0, 1].map(slideIndex => ({
        slideIndex,
        ...(headerFooter ? { headerFooter } : {}),
        animations: [],
        elements: ['title', 'body'].map(id => ({
          id, type: 'text', name: id, text: `${id} ${slideIndex}`, editable: true, deletable: true,
          geometry: { x: 10, y: 20, width: 300, height: 80 },
        })),
      })),
    }
    const fetcher = vi.fn<typeof fetch>().mockImplementation(async () =>
      new Response(JSON.stringify(deck)),
    )
    vi.stubGlobal('fetch', fetcher)
    const root = document.querySelector<HTMLElement>('#app')!
    const shell = createEditorShell(root, 'full', 'pptx')
    const view = createSlidesEditorView(shell.editor, { save: shell.save, download: shell.exportPptx, native: !!headerFooter })
    await vi.waitFor(() => expect(root.querySelectorAll('.slide-open')).toHaveLength(2))
    return { root, shell, fetcher, view }
  }

  it('removes reference overlays when the editor is disposed', async () => {
    const { root, view } = await openEditor({ footer: null, slideNum: false, date: null })
    root.querySelector<HTMLButtonElement>('[data-command="ruler"]')!.click()
    root.querySelector<HTMLButtonElement>('[data-command="guides"]')!.click()
    expect(document.querySelector('.ruler')).not.toBeNull()
    expect(document.querySelector('.ruler-bubble')).not.toBeNull()
    view.dispose()
    expect(document.querySelector('.ruler,.ruler-corner,.guide-line,.ruler-bubble')).toBeNull()
  })

  it('preserves a fixed date when changing the footer', async () => {
    const { root, shell, fetcher } = await openEditor({ footer: 'old', slideNum: false, date: '2026-10-01', dateAuto: false })
    root.querySelector<HTMLButtonElement>('[data-command="headerFooter"]')!.click()
    const dialog = document.querySelector<HTMLDialogElement>('.slides-hf-dialog')!
    expect(dialog.querySelector<HTMLInputElement>('[name="dateAuto"]')!.checked).toBe(false)
    dialog.querySelector<HTMLInputElement>('[name="footer"]')!.value = 'new footer'
    dialog.querySelector<HTMLButtonElement>('[value="ok"]')!.click()
    fetcher.mockResolvedValueOnce(new Response(JSON.stringify({ revision: 2, revisionRegistered: true, validation: { issues: [] } })))
    shell.save.click()
    await vi.waitFor(() => expect(shell.statusLabel.textContent).toBe('已保存'))
    const payload = JSON.parse(fetcher.mock.calls.at(-1)![1]!.body as string)
    expect(payload.headerFooter).toMatchObject({ date: '2026-10-01', dateAuto: false, footer: 'new footer' })
  })

  describe.each([
    { command: 'insertTable', title: '插入表格', field: 'cols', initial: '5', edited: '7' },
    { command: 'addSection', title: '新增节', field: 'name', initial: '无标题节', edited: '未提交的节' },
    { command: 'headerFooter', title: '页眉和页脚', field: 'footer', initial: '', edited: '未提交的页脚' },
  ])('$title settings dialog', spec => {
    it.each(['cancel', 'nativeCancel', 'title'])('restores focus and discards local changes on %s', async action => {
      const { root, shell, fetcher } = await openEditor({ footer: null, slideNum: false, date: null })
      const opener = root.querySelector<HTMLButtonElement>(`[data-command="${spec.command}"]`)!
      const status = shell.statusLabel.textContent
      opener.focus(); opener.click()
      const dialog = root.querySelector<HTMLDialogElement>(`dialog[aria-label="${spec.title}"]`)!
      const input = dialog.querySelector<HTMLInputElement>(`[name="${spec.field}"]`)!
      input.focus(); input.value = spec.edited
      const requestCount = fetcher.mock.calls.length
      if (action === 'nativeCancel') dialog.dispatchEvent(new Event('cancel', { cancelable: true }))
      else if (action === 'title') {
        const close = dialog.querySelector<HTMLButtonElement>(`[aria-label="关闭${spec.title}"]`)
        expect(close).not.toBeNull(); close!.click()
      } else dialog.querySelector<HTMLButtonElement>('[value="cancel"]')!.click()
      expect(dialog.isConnected).toBe(false)
      expect(document.activeElement).toBe(opener)
      expect(shell.statusLabel.textContent).toBe(status)
      expect(fetcher.mock.calls).toHaveLength(requestCount)
      opener.click()
      const reopened = root.querySelector<HTMLDialogElement>(`dialog[aria-label="${spec.title}"]`)!
      expect(reopened.querySelector<HTMLInputElement>(`[name="${spec.field}"]`)!.value).toBe(spec.initial)
      reopened.querySelector<HTMLButtonElement>('[value="cancel"]')!.click()
    })
  })

  it('keeps table dimensions and section names in the native save payload', async () => {
    const { root, shell, fetcher } = await openEditor({ footer: null, slideNum: false, date: null })
    root.querySelector<HTMLButtonElement>('[data-command="insertTable"]')!.click()
    let dialog = root.querySelector<HTMLDialogElement>('dialog[aria-label="插入表格"]')!
    dialog.querySelector<HTMLInputElement>('[name="cols"]')!.value = '3'
    dialog.querySelector<HTMLInputElement>('[name="rows"]')!.value = '4'
    dialog.querySelector<HTMLButtonElement>('[value="ok"]')!.click()
    root.querySelector<HTMLButtonElement>('[data-command="addSection"]')!.click()
    dialog = root.querySelector<HTMLDialogElement>('dialog[aria-label="新增节"]')!
    dialog.querySelector<HTMLInputElement>('[name="name"]')!.value = ' 第二部分 '
    dialog.querySelector<HTMLButtonElement>('[value="ok"]')!.click()
    fetcher.mockResolvedValueOnce(new Response(JSON.stringify({ revision: 2, revisionRegistered: true, validation: { issues: [] } })))
    shell.save.click()
    await vi.waitFor(() => expect(shell.statusLabel.textContent).toBe('已保存'))
    const payload = JSON.parse(fetcher.mock.calls.at(-1)![1]!.body as string)
    expect(payload.tables).toEqual([{ slideIndex: 0, rows: 4, cols: 3 }])
    expect(payload.sections).toEqual([{ slideIndex: 0, name: '第二部分' }])
  })

  it.each([
    { command: 'insertTable', title: '插入表格', field: 'cols', value: '0', message: '行数和列数须为 1–75 的整数' },
    { command: 'addSection', title: '新增节', field: 'name', value: '', message: '请输入节名称' },
  ])('keeps invalid $title input and exposes a keyboard-readable error', async spec => {
    const { root, shell, fetcher } = await openEditor({ footer: null, slideNum: false, date: null })
    root.querySelector<HTMLButtonElement>(`[data-command="${spec.command}"]`)!.click()
    const dialog = root.querySelector<HTMLDialogElement>(`dialog[aria-label="${spec.title}"]`)!
    const input = dialog.querySelector<HTMLInputElement>(`[name="${spec.field}"]`)!
    input.value = spec.value
    const status = shell.statusLabel.textContent, requests = fetcher.mock.calls.length
    dialog.querySelector<HTMLButtonElement>('[value="ok"]')!.click()
    const error = dialog.querySelector<HTMLElement>('[role="alert"]')!
    expect(error.textContent).toBe(spec.message)
    expect(error.getAttribute('aria-label')).toBe(`${spec.title}错误`)
    expect(error.tabIndex).toBe(0)
    error.focus()
    expect(document.activeElement).toBe(error)
    expect(input.value).toBe(spec.value)
    expect(dialog.open).toBe(true)
    expect(shell.statusLabel.textContent).toBe(status)
    expect(fetcher.mock.calls).toHaveLength(requests)
  })

  it('defaults a legacy fixed date to non-automatic mode', async () => {
    const { root } = await openEditor({ footer: null, slideNum: false, date: '2026-10-01' })
    root.querySelector<HTMLButtonElement>('[data-command="headerFooter"]')!.click()
    const dialog = document.querySelector<HTMLDialogElement>('.slides-hf-dialog')!
    expect(dialog.querySelector<HTMLInputElement>('[name="dateAuto"]')!.checked).toBe(false)
    dialog.querySelector<HTMLButtonElement>('[value="cancel"]')!.click()
  })

  it('keeps an explicitly automatic date automatic', async () => {
    const { root } = await openEditor({ footer: null, slideNum: false, date: '2026-10-01', dateAuto: true })
    root.querySelector<HTMLButtonElement>('[data-command="headerFooter"]')!.click()
    const dialog = document.querySelector<HTMLDialogElement>('.slides-hf-dialog')!
    expect(dialog.querySelector<HTMLInputElement>('[name="dateAuto"]')!.checked).toBe(true)
    dialog.querySelector<HTMLButtonElement>('[value="cancel"]')!.click()
  })

  it('remaps restored section references after removing a pending slide', async () => {
    const root = document.querySelector<HTMLElement>('#app')!
    const shell = createEditorShell(root, 'full', 'pptx')
    const deck = { revision: 1, sha256: 'a'.repeat(64), size: { cx: 9144000, cy: 5143500 },
      slides: [0, 1].map(slideIndex => ({ slideIndex, animations: [], elements: [] })) }
    vi.stubGlobal('fetch', vi.fn<typeof fetch>().mockImplementation(async () =>
      new Response(JSON.stringify(deck)),
    ))
    const storage = new Map<string, string>()
    const draft = new NativeDraft({ documentId: 'slides-test', revision: 1, sourceSha256: 'a'.repeat(64),
      scope: { database: 'test', companyId: '1', userId: '1', threadId: '1' } }, {
      getItem: key => storage.get(key) ?? null,
      setItem: (key, value) => { storage.set(key, value) },
      removeItem: key => { storage.delete(key) },
    }, () => 'test-request')
    draft.setOperations([{ kind: 'editSlides', order: [0, 2, 3, 1],
      newSlides: [{ layoutFrom: 0 }, { layoutFrom: 0 }],
      sections: [{ slideIndex: 3, name: 'Retained section' }] }])
    createSlidesEditorView(shell.editor, { save: shell.save, download: shell.exportPptx,
      native: true, draft, request: async <T>() => deck as T })
    await vi.waitFor(() => expect(root.querySelectorAll('[data-new-slide="true"]')).toHaveLength(2))
    root.querySelector<HTMLElement>('[data-new-slide="true"]')!.querySelector<HTMLButtonElement>('[aria-label="移除新建的幻灯片"]')!.click()
    expect(draft.operations[0]).toMatchObject({ order: [0, 2, 1], newSlides: [{ layoutFrom: 0 }],
      sections: [{ slideIndex: 2, name: 'Retained section' }] })
  })

  it('retains pending geometry when switching objects before saving', async () => {
    const { root, shell, fetcher } = await openEditor()
    const x = root.querySelector<HTMLInputElement>('[name="x"]')!
    const select = root.querySelector<HTMLSelectElement>('#object-select')!
    x.value = '125'
    x.dispatchEvent(new Event('change'))
    select.value = 'body'
    select.dispatchEvent(new Event('change'))
    select.value = 'title'
    select.dispatchEvent(new Event('change'))

    expect(x.value).toBe('125')
    const y = root.querySelector<HTMLInputElement>('[name="y"]')!
    y.value = '75'
    y.dispatchEvent(new Event('change'))
    fetcher.mockResolvedValueOnce(new Response(JSON.stringify({
      revision: 2, revisionRegistered: true, validation: { issues: [] }, pptx: { downloadUrl: '/download/r2' },
    })))
    shell.save.click()
    await vi.waitFor(() => expect(shell.statusLabel.textContent).toBe('已保存'))
    const payload = JSON.parse(fetcher.mock.calls.at(-1)![1]!.body as string)
    expect(payload.edits).toEqual([{
      slideIndex: 0, elementId: 'title',
      geometry: { x: 125, y: 75, width: 300, height: 80 },
    }])
  })

  it('saves background, watermark and deletions and drops edits of deleted objects', async () => {
    const { root, shell, fetcher } = await openEditor()
    const select = root.querySelector<HTMLSelectElement>('#object-select')!
    select.value = 'body'
    select.dispatchEvent(new Event('change'))
    const text = root.querySelector<HTMLTextAreaElement>('#object-text')!
    text.value = '将被删除'; text.dispatchEvent(new Event('input'))
    root.querySelector<HTMLButtonElement>('.object-delete')!.click()
    expect([...select.options].map(option => option.value)).toEqual(['title'])

    root.querySelector<HTMLButtonElement>('.watermark-add')!.click()
    const watermarkText = root.querySelector<HTMLInputElement>('.structure-pending input')!
    watermarkText.value = '仅供内部'; watermarkText.dispatchEvent(new Event('input'))
    const background = root.querySelector<HTMLInputElement>('#background-color')!
    background.value = '#123456'; background.dispatchEvent(new Event('change'))
    expect(root.querySelectorAll('.structure-pending li')).toHaveLength(3)

    fetcher.mockResolvedValueOnce(new Response(JSON.stringify({ revision: 2, revisionRegistered: true, validation: { issues: [] } })))
    shell.save.click()
    await vi.waitFor(() => expect(shell.statusLabel.textContent).toBe('已保存'))
    const payload = JSON.parse(fetcher.mock.calls.at(-1)![1]!.body as string)
    expect(payload.edits).toEqual([])
    expect(payload.deletions).toEqual([{ slideIndex: 0, elementId: 'body' }])
    expect(payload.backgrounds).toEqual([{ slideIndex: 0, color: '#123456' }])
    expect(payload.textBoxes).toHaveLength(1)
    expect(payload.textBoxes[0]).toMatchObject({ slideIndex: 0, text: '仅供内部', fontSize: 64, color: '#DCE3EB', rotation: -25 })
    expect(payload.textBoxes[0]).not.toHaveProperty('watermark')
    expect(root.querySelectorAll('.structure-pending li')).toHaveLength(0)
  })

  it('locks editing while save is pending and restores it after failure', async () => {
    const { root, shell, fetcher } = await openEditor()
    const text = root.querySelector<HTMLTextAreaElement>('#object-text')!
    text.value = '保存快照'; text.dispatchEvent(new Event('input'))
    let resolve!: (response: Response) => void
    fetcher.mockImplementationOnce(() => new Promise(done => { resolve = done }))
    shell.save.click()
    expect(shell.editor.inert).toBe(true)
    expect(text.disabled).toBe(true)
    text.value = '请求中不应写入'; text.dispatchEvent(new Event('input', { bubbles: true }))
    resolve(new Response(JSON.stringify({ detail: { message: '保存故障' } }), { status: 500 }))
    await vi.waitFor(() => expect(shell.statusLabel.textContent).toBe('保存失败'))
    expect(shell.editor.inert).toBe(false)
    expect(text.disabled).toBe(false)
    root.querySelector<HTMLSelectElement>('#object-select')!.dispatchEvent(new Event('change'))
    expect(text.value).toBe('保存快照')
    fetcher.mockResolvedValueOnce(new Response(JSON.stringify({ revision: 2, revisionRegistered: true, validation: { issues: [] } })))
    shell.save.click()
    await vi.waitFor(() => expect(shell.statusLabel.textContent).toBe('已保存'))
    const payload = JSON.parse(fetcher.mock.calls.at(-1)![1]!.body as string)
    expect(payload.edits[0].text).toBe('保存快照')
  })

  it('waits for in-flight AI acceptance before saving the pending edits', async () => {
    const { root, shell, fetcher } = await openEditor()
    const text = root.querySelector<HTMLTextAreaElement>('#object-text')!
    text.value = '人工文字'; text.dispatchEvent(new Event('input'))
    fetcher.mockResolvedValueOnce(new Response(JSON.stringify({ editId: 'pending-accept' })))
      .mockResolvedValueOnce(new Response(JSON.stringify({ editId: 'pending-accept', status: 'succeeded', proposal: { summary: '改标题', edits: [{ slideIndex: 0, elementId: 'title', text: 'AI文字' }], order: [0, 1] } })))
    root.querySelector<HTMLTextAreaElement>('#ai-instruction')!.value = '改标题'
    root.querySelector<HTMLFormElement>('.ai-form')!.dispatchEvent(new Event('submit', { cancelable: true }))
    await vi.waitFor(() => expect(root.querySelector<HTMLElement>('.ai-preview')!.hidden).toBe(false))
    let resolve!: (response: Response) => void
    fetcher.mockImplementationOnce(() => new Promise(done => { resolve = done }))
    root.querySelector<HTMLButtonElement>('.ai-accept')!.click()
    shell.save.click()
    expect(fetcher.mock.calls.filter(([url]) => String(url).endsWith('/save'))).toHaveLength(0)
    resolve(new Response(JSON.stringify({ accepted: true })))
    await vi.waitFor(() => expect(text.value).toBe('AI文字'))
    fetcher.mockResolvedValueOnce(new Response(JSON.stringify({ revision: 2, revisionRegistered: true, validation: { issues: [] } })))
    shell.save.click()
    await vi.waitFor(() => expect(shell.statusLabel.textContent).toBe('已保存'))
    expect(JSON.parse(fetcher.mock.calls.at(-1)![1]!.body as string).edits[0].text).toBe('AI文字')
  })

  it('shows the latest pending animation timing for the selected slide only', async () => {
    const { root } = await openEditor()
    const duration = root.querySelector<HTMLInputElement>('#animation-duration')!
    const delay = root.querySelector<HTMLInputElement>('#animation-delay')!
    const add = root.querySelector<HTMLButtonElement>('.animation-add')!
    duration.value = '900'
    add.click()
    duration.value = '1500'
    delay.value = '250'
    add.click()

    expect(duration.value).toBe('1500')
    expect(delay.value).toBe('250')
    root.querySelectorAll<HTMLButtonElement>('.slide-open')[1]!.click()
    expect(duration.value).toBe('500')
    expect(delay.value).toBe('0')
    root.querySelectorAll<HTMLButtonElement>('.slide-open')[0]!.click()
    expect(duration.value).toBe('1500')
    expect(delay.value).toBe('250')
  })

  it('undoes an accepted AI proposal without losing earlier manual edits', async () => {
    const { root, fetcher } = await openEditor()
    const text = root.querySelector<HTMLTextAreaElement>('#object-text')!
    text.value = '人工修订标题'
    text.dispatchEvent(new Event('input'))
    fetcher
      .mockResolvedValueOnce(new Response(JSON.stringify({ editId: 'edit-1' })))
      .mockResolvedValueOnce(new Response(JSON.stringify({
        editId: 'edit-1', status: 'succeeded', proposal: {
          summary: '缩短标题并调整页面顺序',
          edits: [{ slideIndex: 0, elementId: 'title', text: 'AI 精简标题' }],
          order: [1, 0], theme: 'modern',
        },
      })))
      .mockResolvedValueOnce(new Response(JSON.stringify({ accepted: true })))
    root.querySelector<HTMLTextAreaElement>('#ai-instruction')!.value = '精简标题'
    root.querySelector<HTMLFormElement>('.ai-form')!.dispatchEvent(new Event('submit', { cancelable: true }))
    await vi.waitFor(() => expect(root.querySelector<HTMLElement>('.ai-preview')!.hidden).toBe(false))
    expect(text.value).toBe('人工修订标题')
    root.querySelector<HTMLButtonElement>('.ai-accept')!.click()
    await vi.waitFor(() => expect(text.value).toBe('AI 精简标题'))
    expect(root.querySelector<HTMLSelectElement>('#theme-select')!.value).toBe('modern')
    expect(root.querySelector('.slide-title')!.textContent).toBe('title 1')

    root.querySelector<HTMLButtonElement>('.undo-button')!.click()

    expect(text.value).toBe('人工修订标题')
    expect(root.querySelector<HTMLSelectElement>('#theme-select')!.value).toBe('')
    expect(root.querySelector('.slide-title')!.textContent).toBe('title 0')
    expect(root.querySelector<HTMLButtonElement>('.undo-button')!.disabled).toBe(true)
  })
})

it('requires reopening the saved revision before another edit can be saved', async () => {
  document.body.innerHTML = '<main id="app"></main>'
  const deck = { revision: 1, sha256: 'a'.repeat(64), size: { cx: 9144000, cy: 5143500 }, slides: [{ slideIndex: 0, elements: [{ id: 'title', type: 'text', name: 'title', text: '标题', editable: true, geometry: { x: 10, y: 20, width: 300, height: 80 } }] }] }
  const fetcher = vi.fn<typeof fetch>().mockImplementation(async () => new Response(JSON.stringify(deck)))
  vi.stubGlobal('fetch', fetcher)
  const root = document.querySelector<HTMLElement>('#app')!
  const shell = createEditorShell(root, 'full', 'pptx')
  createSlidesEditorView(shell.editor, { save: shell.save, download: shell.exportPptx })
  await vi.waitFor(() => expect(root.querySelectorAll('.slide-open')).toHaveLength(1))
  const text = root.querySelector<HTMLTextAreaElement>('#object-text')!
  text.value = '第一轮修改'; text.dispatchEvent(new Event('input'))
  fetcher.mockResolvedValueOnce(new Response(JSON.stringify({ revision: 2, revisionRegistered: true, validation: { issues: [] }, pptx: { downloadUrl: '/download/r2' }, editor: { openUrl: '/reports/v1/slides/open/r2' } })))
  shell.save.click()
  await vi.waitFor(() => expect(root.querySelector('.revision-link')).not.toBeNull())
  expect(shell.save.disabled).toBe(true)
  let preventedByEditor = true
  const reopen = root.querySelector('.revision-link')!
  reopen.addEventListener('click', event => { preventedByEditor = event.defaultPrevented; event.preventDefault() }, { once: true })
  reopen.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }))
  expect(preventedByEditor).toBe(false)
  expect(root.querySelector('.status-message')!.textContent).toContain('打开新修订后继续编辑')
  text.value = '第二轮修改'; text.dispatchEvent(new Event('input'))
  shell.save.click()
  expect(fetcher.mock.calls.filter(([, init]) => init?.method === 'POST')).toHaveLength(1)
  vi.unstubAllGlobals()
})
