import { afterEach, beforeEach, expect, it, vi, type Mock } from 'vitest'
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import type { Editor } from '@tiptap/core'
import type { HeaderFooter } from '@genoffice/docx-engine'
import { DocxHeaderFooterSource, type DocxHeaderFooterController, type DocxHfPendingEditor } from './docx-hf-source'
import type { DocxHfPartKey } from './docx-hf'
import type { HfEditorHandle } from './vendor/genoffice-docs/apps/docs/src/renderer/editor/hf-editor'

type MountOptions = Parameters<typeof import('./vendor/genoffice-docs/apps/docs/src/renderer/editor/hf-editor').mountHfEditor>[1]
interface ObservableMount {
  input: HTMLTextAreaElement
  opts: MountOptions
  editor: { isEditable: boolean; setEditable: Mock<(editable: boolean) => void> }
  handle: HfEditorHandle
  changed: Mock<() => HeaderFooter | null>
  discard: Mock<() => void>
  exit: Mock<() => void>
}

const hfMock = vi.hoisted(() => {
  const mounts: ObservableMount[] = []
  return { mounts, mountHfEditor: vi.fn<(host: HTMLElement, opts: MountOptions) => HfEditorHandle>(), insertHfField: vi.fn() }
})
vi.mock('./vendor/genoffice-docs/apps/docs/src/renderer/editor/hf-editor', () => ({
  mountHfEditor: hfMock.mountHfEditor,
  insertHfField: hfMock.insertHfField,
}))

const roots = new Set<Root>()

beforeEach(() => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true)
  hfMock.mountHfEditor.mockImplementation((host, opts) => {
    // Observable stand-in for the vendor handle, not a mock of the React panel.
    // Input remains local until changed() is queried or the editor exits.
    const input = document.createElement('textarea')
    input.setAttribute('aria-label', 'mock hf content')
    input.value = opts.value.text
    host.append(input)
    const editor: ObservableMount['editor'] = {
      isEditable: true,
      setEditable: vi.fn(editable => {
        editor.isEditable = editable
        input.disabled = !editable
      }),
    }
    const changed = vi.fn((): HeaderFooter | null => input.value === opts.value.text ? null : {
      ...opts.value,
      text: input.value,
      paras: [{ runs: [{ text: input.value }] }],
    })
    let closed = false
    const close = (commit: boolean) => {
      if (closed) return
      closed = true
      input.removeEventListener('blur', onBlur)
      const next = commit ? changed() : null
      input.disabled = true
      if (next) opts.onCommit(next)
      // Real vendor discard(), like exit(), invokes onExit after destroying.
      opts.onExit()
    }
    const onBlur = () => close(true)
    input.addEventListener('blur', onBlur)
    const discard = vi.fn(() => close(false))
    const exit = vi.fn(() => close(true))
    const handle: HfEditorHandle = { editor: editor as unknown as Editor, changed, discard, exit }
    hfMock.mounts.push({ input, opts, editor, handle, changed, discard, exit })
    return handle
  })
})

afterEach(() => {
  act(() => { for (const root of roots) root.unmount() })
  roots.clear()
  document.body.replaceChildren()
  hfMock.mounts.splice(0)
  vi.clearAllMocks()
  vi.unstubAllGlobals()
})

function makeController() {
  const values = new Map<DocxHfPartKey, HeaderFooter>()
  const model: DocxHeaderFooterController['model'] = {
    titlePg: true, evenAndOddHeaders: true, pageNumberFmt: null, pageNumberStart: null, parts: {},
  }
  for (const part of ['header', 'footer'] as const) {
    for (const variant of ['default', 'first', 'even'] as const) {
      const key = `${part}.${variant}` as const
      values.set(key, { text: key, paras: [{ runs: [{ text: key }] }] })
      model.parts[key] = { rId: key, expectedPartSha256: `${key}-sha`, text: key, hasPageNumber: false, editable: true }
    }
  }
  const registerEditor = vi.fn<(editor: DocxHfPendingEditor | null) => void>()
  const onCommit = vi.fn<DocxHeaderFooterController['onCommit']>((part, variant, value) => {
    values.set(`${part}.${variant}`, value)
  })
  const controller: DocxHeaderFooterController = {
    editable: true,
    registerEditor,
    anchor: { sectionId: 'section-1', expectedSectionSha256: 'section-sha' },
    model,
    valueOf: (part, variant) => ({ value: values.get(`${part}.${variant}`)!, anchor: model.parts[`${part}.${variant}`]! }),
    onCommit,
  }
  const pending = () => {
    const latest = registerEditor.mock.calls.at(-1)?.[0]
    expect(latest).toBeTruthy()
    return latest!
  }
  return { controller, registerEditor, onCommit, pending }
}

function renderSource(controller: DocxHeaderFooterController) {
  const host = document.createElement('div')
  document.body.append(host)
  const root = createRoot(host)
  roots.add(root)
  act(() => root.render(<DocxHeaderFooterSource controller={controller} />))
  return {
    host,
    unmount: () => { act(() => root.unmount()); roots.delete(root) },
  }
}

function button(host: HTMLElement, label: string) {
  const found = [...host.querySelectorAll<HTMLButtonElement>('button')].find(item => (item.getAttribute('aria-label') ?? item.textContent) === label)
  expect(found, label).toBeTruthy()
  return found!
}

function currentMount() {
  const mounted = hfMock.mounts.at(-1)
  expect(mounted).toBeTruthy()
  return mounted!
}

function typeWithoutBlur(mounted: ObservableMount, text: string) {
  mounted.input.focus()
  mounted.input.value = text
  mounted.input.dispatchEvent(new InputEvent('input', { bubbles: true, inputType: 'insertText', data: text }))
  expect(document.activeElement).toBe(mounted.input)
}

it('opens and commits the explicitly requested footer variant without editing the header', () => {
  const { controller, onCommit } = makeController()
  const host = document.createElement('div'); document.body.append(host)
  const root = createRoot(host); roots.add(root)
  act(() => root.render(<DocxHeaderFooterSource controller={controller} target={{ part: 'footer', variant: 'even' }} />))
  expect(currentMount().opts.value.text).toBe('footer.even')
  typeWithoutBlur(currentMount(), 'Changed footer')
  act(() => currentMount().exit())
  expect(onCommit).toHaveBeenCalledWith('footer', 'even', expect.objectContaining({ text: 'Changed footer' }), undefined)
})

it.each([
  { label: '页脚', part: 'footer', variant: 'default' },
  { label: '首页', part: 'header', variant: 'first' },
])('registerEditor flush uses the current part/variant after selecting $label', ({ label, part, variant }) => {
  const { controller, pending, onCommit } = makeController()
  const { host } = renderSource(controller)
  const original = currentMount()
  typeWithoutBlur(original, 'pending header before switch')

  act(() => button(host, label).click())

  // Leaving the old part commits under its own identity, not the next one.
  expect(onCommit.mock.calls[0]?.slice(0, 3)).toEqual([
    'header', 'default', expect.objectContaining({ text: 'pending header before switch' }),
  ])
  expect(original.discard).toHaveBeenCalledTimes(1)
  const active = currentMount()
  expect(active).not.toBe(original)
  expect(active.opts.value.text).toBe(`${part}.${variant}`)
  typeWithoutBlur(active, 'pending current part')
  onCommit.mockClear()

  act(() => pending().flush())

  expect(onCommit).toHaveBeenCalledTimes(1)
  expect(onCommit.mock.calls[0]?.slice(0, 3)).toEqual([
    part, variant, expect.objectContaining({ text: 'pending current part' }),
  ])
  expect(active.exit).not.toHaveBeenCalled()
})

it('flush reads focused input without blur or exit and preserves the committed value', () => {
  const { controller, pending, onCommit } = makeController()
  renderSource(controller)
  const active = currentMount()
  const blur = vi.fn()
  active.input.addEventListener('blur', blur)
  typeWithoutBlur(active, 'latest text not yet blurred')
  expect(onCommit).not.toHaveBeenCalled()

  act(() => pending().flush())

  expect(active.changed).toHaveBeenCalled()
  expect(active.exit).not.toHaveBeenCalled()
  expect(blur).not.toHaveBeenCalled()
  expect(onCommit).toHaveBeenCalledTimes(1)
  expect(onCommit.mock.calls[0]?.slice(0, 3)).toEqual([
    'header', 'default', expect.objectContaining({ text: 'latest text not yet blurred' }),
  ])
  expect(currentMount().input.value).toBe('latest text not yet blurred')
})

it('save lock synchronously locks the nested editor and keeps every panel control disabled after effects', () => {
  const { controller, pending } = makeController()
  const { host } = renderSource(controller)
  const active = currentMount()
  act(() => {
    pending().setEditable(false)
    // Must lock before React processes state/effect cleanup, not just on rerender.
    expect(active.editor.setEditable).toHaveBeenLastCalledWith(false)
    expect(active.editor.isEditable).toBe(false)
    expect(active.input.disabled).toBe(true)
  })

  const controls = [...host.querySelectorAll<HTMLButtonElement | HTMLInputElement | HTMLSelectElement>('button, input, select')]
  expect(controls.length).toBeGreaterThan(0)
  for (const control of controls) expect(control.disabled, control.getAttribute('aria-label') ?? control.textContent ?? '').toBe(true)
  expect(host.querySelector('[role="status"]')?.textContent).toContain('正在保存')
  hfMock.insertHfField.mockClear()
  act(() => button(host, '页码').click())
  expect(hfMock.insertHfField).not.toHaveBeenCalled()
})

it('unlock restores controls and the content flushed before saving', () => {
  const { controller, pending, onCommit } = makeController()
  const { host } = renderSource(controller)
  typeWithoutBlur(currentMount(), 'saved pending content')
  act(() => pending().flush())
  const beforeLock = currentMount()
  const commitsBeforeLock = onCommit.mock.calls.length

  act(() => pending().setEditable(false))
  expect(beforeLock.editor.setEditable).toHaveBeenLastCalledWith(false)
  act(() => pending().setEditable(true))

  // Lock may discard and remount; requiring the destroyed instance to receive
  // setEditable(true) would test an implementation detail, not recovery.
  expect(currentMount().editor.isEditable).toBe(true)
  expect(currentMount().input.disabled).toBe(false)
  expect(currentMount().input.value).toBe('saved pending content')
  expect(onCommit).toHaveBeenCalledTimes(commitsBeforeLock)
  for (const control of host.querySelectorAll<HTMLButtonElement | HTMLInputElement | HTMLSelectElement>('button, input, select')) {
    expect(control.disabled).toBe(false)
  }
  expect(host.querySelector('[role="status"]')).toBeNull()
  hfMock.insertHfField.mockClear()
  act(() => button(host, '页码').click())
  expect(hfMock.insertHfField).toHaveBeenCalledWith(currentMount().handle.editor, 'PAGE')
})

it.each([
  { label: '首页不同', action: 'hf-title-page', flag: 'titlePg' },
  { label: '奇偶页不同', action: 'hf-even-odd', flag: 'evenAndOddHeaders' },
])('toggling $label while typing commits the pending text instead of the stale part value', ({ action, flag }) => {
  const { controller, onCommit } = makeController()
  const { host } = renderSource(controller)
  const active = currentMount()
  typeWithoutBlur(active, 'text typed before option toggle')
  const checkbox = host.querySelector<HTMLInputElement>(`[data-source-action="${action}"]`)!
  expect(checkbox.checked).toBe(true)
  // Native click triggers React's checkbox onChange without a synthetic blur.
  act(() => checkbox.click())

  expect(onCommit).toHaveBeenCalledTimes(1)
  expect(onCommit.mock.calls[0]?.slice(0, 3)).toEqual([
    'header', 'default', expect.objectContaining({ text: 'text typed before option toggle' }),
  ])
  expect(onCommit.mock.calls[0]?.[3]).toEqual({ [flag]: false })
  expect(currentMount().input.value).toBe('text typed before option toggle')
})

it.each([
  ['hf-title-page', 'titlePgReadOnlyReason'], ['hf-even-odd', 'evenAndOddHeadersReadOnlyReason'],
] as const)('shows unknown markup in %s without allowing its normalization', (action, reason) => {
  const { controller, onCommit } = makeController()
  controller.model[reason] = '页眉选项标记无法解释'
  const { host } = renderSource(controller)
  const checkbox = host.querySelector<HTMLInputElement>(`[data-source-action="${action}"]`)!
  expect(checkbox.disabled).toBe(true)
  expect(checkbox.indeterminate).toBe(true)
  expect(checkbox.title).toBe('页眉选项标记无法解释')
  act(() => checkbox.click())
  expect(onCommit).not.toHaveBeenCalled()
})

it('does not rewrite the draft when the registered editor is flushed repeatedly without new edits', () => {
  const { controller, pending, onCommit } = makeController()
  renderSource(controller)
  const active = currentMount()
  typeWithoutBlur(active, 'flush once')

  act(() => pending().flush())
  expect(onCommit).toHaveBeenCalledTimes(1)
  expect(currentMount()).not.toBe(active)
  act(() => pending().flush())

  expect(onCommit).toHaveBeenCalledTimes(1)
})

it('unmount unregisters the pending editor and discards the child without committing', () => {
  const { controller, registerEditor, onCommit } = makeController()
  const { unmount } = renderSource(controller)
  const active = currentMount()
  typeWithoutBlur(active, 'uncommitted on unmount')
  expect(registerEditor).toHaveBeenLastCalledWith(expect.objectContaining({ flush: expect.any(Function), setEditable: expect.any(Function) }))

  unmount()

  expect(registerEditor).toHaveBeenLastCalledWith(null)
  expect(active.discard).toHaveBeenCalledTimes(1)
  expect(active.exit).not.toHaveBeenCalled()
  expect(onCommit).not.toHaveBeenCalled()
})

it('confirms replacing the current section variant before discarding local content, and preserves it on cancel', () => {
  const f = makeController(), onLink = vi.fn()
  f.controller.linked = () => ({ value: false, ownerLabel: '第 2 节' })
  f.controller.onLink = onLink
  const { host } = renderSource(f.controller)
  const mounted = currentMount()
  mounted.input.value = 'uncommitted local header'
  const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false)
  const checkbox = host.querySelector<HTMLInputElement>('[data-source-action="hf-link-previous"]')!
  act(() => checkbox.click())
  expect(confirm).toHaveBeenCalledWith(expect.stringContaining('替换'))
  expect(onLink).not.toHaveBeenCalled()
  expect(mounted.discard).not.toHaveBeenCalled()
  expect(mounted.input.value).toBe('uncommitted local header')
  confirm.mockReturnValue(true)
  act(() => checkbox.click())
  expect(onLink).toHaveBeenCalledExactlyOnceWith('header', 'default', true)
  expect(mounted.discard).toHaveBeenCalledOnce()
  expect(f.onCommit).not.toHaveBeenCalled()
  confirm.mockRestore()
})


it('passes pending inherited text to the unlink transaction without discarding it or confirming', () => {
  const f = makeController(), onLink = vi.fn()
  f.controller.linked = () => ({ value: true, ownerLabel: '第 1 节' })
  f.controller.onLink = onLink
  const { host } = renderSource(f.controller)
  const mounted = currentMount(); mounted.input.value = 'pending inherited text'
  const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true)
  act(() => host.querySelector<HTMLInputElement>('[data-source-action="hf-link-previous"]')!.click())
  expect(confirm).not.toHaveBeenCalled()
  expect(onLink).toHaveBeenCalledExactlyOnceWith('header', 'default', false, expect.objectContaining({ text: 'pending inherited text' }))
  expect(mounted.discard).not.toHaveBeenCalled()
  confirm.mockRestore()
})

it('ignores a late commit from an editor opened on another section', () => {
  const f = makeController()
  renderSource(f.controller)
  const mounted = currentMount()
  f.controller.anchor = { sectionId: 'other-section', expectedSectionSha256: 'other-sha' }
  act(() => mounted.opts.onCommit({ text: 'late content' }))
  expect(f.onCommit).not.toHaveBeenCalled()
})


it('remounts a discarded editor when linking changes owner but both contents are equal', () => {
  const f = makeController()
  let linked = false
  f.controller.linked = () => ({ value: linked, ownerLabel: linked ? '第 1 节' : '第 2 节' })
  f.controller.onLink = (_part, _variant, value) => { linked = value }
  const { host } = renderSource(f.controller), mounted = currentMount()
  const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true)
  act(() => host.querySelector<HTMLInputElement>('[data-source-action="hf-link-previous"]')!.click())
  expect(mounted.discard).toHaveBeenCalled()
  expect(currentMount()).not.toBe(mounted)
  expect(currentMount().input.disabled).toBe(false)
  confirm.mockRestore()
})
