import { afterEach, describe, expect, it } from 'vitest'
const path = './workbook-header-footer-editor'
const product = (): Promise<any> => import(/* @vite-ignore */ path)
const disposables: { dispose(): void }[] = []
afterEach(() => { disposables.splice(0).forEach(item => item.dispose()); document.body.replaceChildren() })

describe('lossless default header/footer editing', () => {
  it('rejects incomplete field tokens that would swallow the following region marker', async () => {
    const p = await product(), state = p.headerFooterEditorState(undefined)
    for (const value of ['abc&', '&"Unclosed font', '&&&']) {
      const edited = structuredClone(state.values); edited.header.left = value; edited.header.center = 'Middle'
      expect(() => p.headerFooterEditorPatch(state, edited)).toThrow(/完整|配对|闭合/)
    }
    const edited = structuredClone(state.values); edited.header.left = 'abc&&'; edited.header.center = 'Middle'
    expect(p.headerFooterEditorPatch(state, edited)).toEqual({ header: { left: 'abc&&', center: 'Middle', right: '' } })
  })

  it('keeps font, picture, unknown fields and escaped section markers when editing another region', async () => {
    const p = await product()
    const file = { oddHeader: '&L&"A &R Font,Bold"&12&BLeft&&R&CPage &P&R&G &Q', oddFooter: 'Centered', differentFirst: true, firstHeader: 'First', differentOddEven: true, evenFooter: 'Even' }
    const state = p.headerFooterEditorState(file)
    expect(state.values).toEqual({ header: { left: '&"A &R Font,Bold"&12&BLeft&&R', center: 'Page &P', right: '&G &Q' }, footer: { left: '', center: 'Centered', right: '' } })
    expect(state.hasFirstPage).toBe(true); expect(state.hasEvenPages).toBe(true)
    expect(p.headerFooterEditorPatch(state, structuredClone(state.values))).toBeUndefined()
    const edited = structuredClone(state.values); edited.header.center = 'Updated &P/&N'
    expect(p.headerFooterEditorPatch(state, edited)).toEqual({ header: { left: '&"A &R Font,Bold"&12&BLeft&&R', center: 'Updated &P/&N', right: '&G &Q' } })
    expect(file.firstHeader).toBe('First'); expect(file.evenFooter).toBe('Even')
  })

  it('overlays pending edits and clears only the changed half', async () => {
    const p = await product(), state = p.headerFooterEditorState({ oddHeader: '&LOriginal', oddFooter: '&RKeep &G' }, { header: { center: 'Draft' } })
    expect(state.values.header).toEqual({ left: '', center: 'Draft', right: '' })
    const edited = structuredClone(state.values); edited.header.center = ''
    expect(p.headerFooterEditorPatch(state, edited)).toEqual({ header: null })
    expect(p.headerFooterEditorState(undefined, { header: null }).values.header).toEqual({ left: '', center: '', right: '' })
  })

  it('rejects region-routing markers but accepts escaped markers and quoted font names', async () => {
    const p = await product(), state = p.headerFooterEditorState(undefined)
    for (const value of ['bad &L elsewhere', '&Ccenter', '&rright']) {
      const edited = structuredClone(state.values); edited.header.left = value
      expect(() => p.headerFooterEditorPatch(state, edited)).toThrow(/&&|区域/)
    }
    const edited = structuredClone(state.values); edited.header.left = '&&L &"A &R Font" &[Page]'
    expect(p.headerFooterEditorPatch(state, edited)).toEqual({ header: { left: '&&L &"A &R Font" &[Page]', center: '', right: '' } })
  })
})

describe('header/footer dialog', () => {
  it('notifies the print preview once after each close path without changing content', async () => {
    const p = await product(), patches: unknown[] = [], closed: string[] = [], target = { book: {}, sheet: {}, sheetId: 's' }
    const dialog = p.createHeaderFooterDialog(document.body, (patch: unknown) => patches.push(patch)); disposables.push(dialog)
    for (const action of ['cancel', 'escape', 'confirm']) {
      dialog.open(p.headerFooterEditorState(undefined), target, () => closed.push(action))
      if (action === 'cancel') document.querySelector<HTMLButtonElement>('[data-header-footer-cancel]')!.click()
      else if (action === 'escape') window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
      else document.querySelector('form')!.dispatchEvent(new Event('submit', { cancelable: true }))
    }
    expect(closed).toEqual(['cancel', 'escape', 'confirm']); expect(patches).toEqual([])
  })
  it('provides six textareas and applies only the edited half once', async () => {
    const p = await product(), patches: unknown[] = [], target = { book: {}, sheet: {}, sheetId: 's' }
    const dialog = p.createHeaderFooterDialog(document.body, (patch: unknown, captured: unknown) => patches.push({ patch, captured })); disposables.push(dialog)
    dialog.open(p.headerFooterEditorState({ oddHeader: '&L<strong>text</strong>', oddFooter: '&R&G' }), target)
    expect(document.querySelectorAll('textarea')).toHaveLength(6); expect(document.querySelector('strong')).toBeNull()
    const input = document.querySelector<HTMLTextAreaElement>('[data-header-footer-field=header-center]')!
    expect(input.getAttribute('aria-label')).toBeTruthy(); input.value = 'Page &P of &N'
    const form = document.querySelector('form')!, submit = () => form.dispatchEvent(new Event('submit', { cancelable: true, bubbles: true }))
    submit(); submit()
    expect(patches).toEqual([{ patch: { header: { left: '<strong>text</strong>', center: 'Page &P of &N', right: '' } }, captured: target }])
  })

  it('cancel, Escape and unchanged confirmation never write a patch', async () => {
    const p = await product(), patches: unknown[] = [], target = { book: {}, sheet: {}, sheetId: 's' }
    const dialog = p.createHeaderFooterDialog(document.body, (patch: unknown) => patches.push(patch)); disposables.push(dialog)
    const state = p.headerFooterEditorState({ oddHeader: '&COriginal' })
    dialog.open(state, target); document.querySelector<HTMLTextAreaElement>('textarea')!.value = 'Discard'; document.querySelector<HTMLButtonElement>('[data-header-footer-cancel]')!.click()
    dialog.open(state, target); window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    dialog.open(state, target); document.querySelector('form')!.dispatchEvent(new Event('submit', { cancelable: true }))
    expect(patches).toEqual([])
  })

  it('keeps edits open if the host rejects a stale target and disposes cleanly', async () => {
    const p = await product(), dialog = p.createHeaderFooterDialog(document.body, () => { throw new Error('工作表已改变') }); disposables.push(dialog)
    dialog.open(p.headerFooterEditorState(undefined), { book: {}, sheet: {}, sheetId: 's' })
    document.querySelector<HTMLTextAreaElement>('textarea')!.value = 'Edited'
    document.querySelector('form')!.dispatchEvent(new Event('submit', { cancelable: true }))
    expect(document.querySelector('[role=alert]')!.textContent).toBe('工作表已改变')
    expect(document.querySelector<HTMLElement>('[role=dialog]')!.hidden).toBe(false)
    expect(document.querySelector<HTMLTextAreaElement>('textarea')!.value).toBe('Edited')
    dialog.dispose(); expect(document.querySelector('[role=dialog]')).toBeNull()
  })
})
