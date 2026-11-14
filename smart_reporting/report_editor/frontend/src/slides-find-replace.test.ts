import { afterEach, expect, it, vi } from 'vitest'
import { buildSlidesFindMatches, openSlidesFindReplace, planSlidesReplace, type SlidesFindSource } from './slides-find-replace'

const slides: SlidesFindSource[] = [
  { slideIndex: 0, elements: [
    { id: 'title', type: 'text', text: 'Cat cat CAT [cat] $&', editable: true, findReplaceEditable: true },
    { id: 'mixed', type: 'text', text: 'cat rich', editable: true, findReplaceEditable: false },
    { id: 'table', type: 'table', text: 'cat cell', editable: true, findReplaceEditable: true },
    { id: 'missing-proof', type: 'shape', text: 'cat unknown', editable: true },
  ] },
  { slideIndex: 1, elements: [{ id: 'shape', type: 'shape', text: 'cat\ncat', editable: true, findReplaceEditable: true }] },
]
const conditions = { query: 'cat', replacement: '$&', matchCase: false }
afterEach(() => document.body.replaceChildren())

it.each(['Escape', 'Enter'])('输入法或已消费按键不关闭查找或跳转匹配：%s', key => {
  for (const protection of ['composition', 'legacy', 'handled']) {
    const navigate = vi.fn(), replace = vi.fn()
    const handle = openSlidesFindReplace(document.body, { getSlides: () => slides, getEdits: () => [], isLocked: () => false, onNavigate: navigate, onReplace: replace })
    const dialog = document.querySelector('dialog')!, query = dialog.querySelector<HTMLInputElement>('[aria-label="查找文字"]')!
    query.value = 'cat'; query.focus()
    const event = new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true, isComposing: protection === 'composition', keyCode: protection === 'legacy' ? 229 : 0 })
    if (protection === 'handled') event.preventDefault()
    query.dispatchEvent(event)
    expect(dialog.isConnected).toBe(true); expect(query.value).toBe('cat'); expect(document.activeElement).toBe(query)
    expect(navigate).not.toHaveBeenCalled(); expect(replace).not.toHaveBeenCalled()
    query.dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true }))
    if (key === 'Escape') expect(dialog.isConnected).toBe(false)
    else expect(navigate).toHaveBeenCalledWith(0, 'title')
    handle.dispose()
  }
})

it.each(['closeFindReplace', 'headerClose', 'Escape', 'cancel', 'dispose'])('restores the opener when closed with %s without replacing text', action => {
  const opener = document.body.appendChild(document.createElement('button')); opener.textContent = '查找'; opener.focus()
  const onReplace = vi.fn(), handle = openSlidesFindReplace(document.body, { getSlides: () => slides, getEdits: () => [], isLocked: () => false, onNavigate: vi.fn(), onReplace })
  const dialog = document.querySelector('dialog')!
  expect(document.activeElement).toBe(dialog.querySelector('[aria-label="查找文字"]'))
  if (action === 'dispose') handle.dispose()
  else if (action === 'Escape') dialog.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }))
  else if (action === 'cancel') dialog.dispatchEvent(new Event('cancel', { cancelable: true }))
  else if (action === 'headerClose') dialog.querySelector<HTMLButtonElement>('[aria-label="关闭查找和替换"]')!.click()
  else dialog.querySelector<HTMLButtonElement>('[data-command="closeFindReplace"]')!.click()
  expect(document.querySelector('dialog')).toBeNull()
  expect(document.activeElement).toBe(opener)
  expect(onReplace).not.toHaveBeenCalled()
  handle.dispose()
})

it('finds only proven editable source text, uses pending text and visible page order, and never mutates edits', () => {
  const edits = [{ slideIndex: 0, elementId: 'title', text: 'edited CAT cat', geometry: { x: 1, y: 2, width: 3, height: 4 } }]
  const original = structuredClone(edits)
  expect(buildSlidesFindMatches(slides, edits, 'cat', false, { order: [1, 0] })).toEqual([
    { slideIndex: 1, elementId: 'shape', count: 2 }, { slideIndex: 0, elementId: 'title', count: 2 },
  ])
  expect(edits).toEqual(original)
  expect(buildSlidesFindMatches(slides, edits, 'cat', true)[0]!.count).toBe(1)
  expect(buildSlidesFindMatches(slides, edits, '', false)).toEqual([])
  expect(buildSlidesFindMatches(slides, edits, 'cat', false, { deletedSlides: [1], deletions: [{ slideIndex: 0, elementId: 'title' }] })).toEqual([])
})

it('plans literal nonoverlapping replacements, preserves geometry and all unrelated edits, and replaces one selected hit', () => {
  const edits = [{ slideIndex: 0, elementId: 'title', geometry: { x: 1, y: 2, width: 3, height: 4 } }, { slideIndex: 1, elementId: 'other', text: 'untouched' }]
  const plan = planSlidesReplace(slides, edits, conditions)
  expect(plan.count).toBe(6)
  expect(plan.edits[0]).toEqual({ ...edits[0], text: '$& $& $& [$&] $&' })
  expect(plan.edits[1]).toEqual(edits[1])
  expect(plan.edits[2]).toEqual({ slideIndex: 1, elementId: 'shape', text: '$&\n$&' })
  expect(edits[0]).not.toHaveProperty('text')
  expect(planSlidesReplace(slides, [], { ...conditions, target: { slideIndex: 0, elementId: 'title' } }).edits).toEqual([
    { slideIndex: 0, elementId: 'title', text: '$& cat CAT [cat] $&' },
  ])
  expect(planSlidesReplace(slides, [], { ...conditions, query: '[cat]' }).count).toBe(1)
  expect(planSlidesReplace([{ slideIndex: 0, elements: [{ ...slides[0]!.elements[0]!, text: 'aaaa' }] }], [], { ...conditions, query: 'aa', replacement: '' }).edits[0]!.text).toBe('')
  expect(planSlidesReplace(slides, [], { ...conditions, query: 'cat\ncat' }).count).toBe(0)
})

it('returns no edits for no effective change and rejects unsupported replacement controls before any update', () => {
  expect(planSlidesReplace(slides, [], { ...conditions, query: 'CAT', replacement: 'CAT', matchCase: true })).toEqual({ edits: [], count: 0 })
  expect(() => planSlidesReplace(slides, [], { ...conditions, replacement: '\u0000' })).toThrow()
})

function panel(onReplace = vi.fn(), isLocked = () => false) {
  const onNavigate = vi.fn()
  openSlidesFindReplace(document.body, { getSlides: () => slides, getEdits: () => [], isLocked, onNavigate, onReplace })
  const query = document.querySelector<HTMLInputElement>('[aria-label="查找文字"]')!
  query.value = 'cat'; query.dispatchEvent(new Event('input'))
  const replacement = document.querySelector<HTMLInputElement>('[aria-label="替换为"]')!
  replacement.value = 'dog'; replacement.dispatchEvent(new Event('input'))
  const click = (name: string) => document.querySelector<HTMLButtonElement>(`[data-command="${name}"]`)!.click()
  return { click, query, onNavigate, onReplace }
}

it('find wraps by element without writing; first replace navigates, then commits once; case toggle resets selection', () => {
  const { click, onNavigate, onReplace } = panel()
  click('replace')
  expect(onNavigate).toHaveBeenLastCalledWith(0, 'title')
  expect(onReplace).not.toHaveBeenCalled()
  click('replace')
  expect(onReplace).toHaveBeenCalledTimes(1)
  expect(onReplace.mock.calls[0]![0].count).toBe(1)
  const matchCase = document.querySelector<HTMLInputElement>('[aria-label="区分大小写"]')!
  matchCase.checked = true; matchCase.dispatchEvent(new Event('change'))
  click('replace')
  expect(onReplace).toHaveBeenCalledTimes(1)
  click('findNext'); click('findNext')
  expect(onNavigate).toHaveBeenLastCalledWith(0, 'title')
})

it('replace all is one atomic callback, reads live data, and keeps panel with useful errors on failure', () => {
  const apply = vi.fn(() => { throw new Error('草稿已锁定') })
  const { click } = panel(apply)
  click('replaceAll')
  expect(apply).toHaveBeenCalledTimes(1)
  expect((apply.mock.calls[0] as unknown[])[0]).toMatchObject({ count: 6 })
  expect(document.querySelector('[role="status"]')!.textContent).toContain('草稿已锁定')
  expect(document.querySelector('dialog')).not.toBeNull()
})

it('rechecks lock before replacing and Escape closes without edits', () => {
  let locked = false
  const { click, query, onReplace } = panel(vi.fn(), () => locked)
  locked = true; click('replaceAll')
  expect(onReplace).not.toHaveBeenCalled()
  expect(document.querySelector('[role="status"]')!.textContent).toContain('只读')
  query.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
  expect(document.querySelector('dialog')).toBeNull()
})

it('validates the entire plan before commit and preserves all draft operations through one undo', async () => {
  const { NativeDraft } = await import('./native-draft')
  const stored = new Map<string, string>()
  const draft = new NativeDraft({ documentId: 'find-replace', revision: 1, sourceSha256: 'a'.repeat(64),
    scope: { database: 'test', companyId: 'test', userId: 'test', threadId: 'test' } },
  { getItem: key => stored.get(key) ?? null, setItem: (key, value) => { stored.set(key, value) }, removeItem: key => { stored.delete(key) } })
  draft.setOperations([{ kind: 'editSlides', edits: [{ slideIndex: 0, elementId: 'title', geometry: { x: 1, y: 2, width: 3, height: 4 } }], hiddenSlides: [{ slideIndex: 1, hidden: true }] }])
  const before = draft.operations
  const op = before[0]!
  const plan = planSlidesReplace(slides, op.edits as { slideIndex: number; elementId: string }[], { ...conditions, replacement: 'dog' })
  draft.setOperations([{ ...op, edits: plan.edits }])
  expect(draft.operations[0]!.hiddenSlides).toEqual(op.hiddenSlides)
  draft.undo()
  expect(draft.operations).toEqual(before)
  draft.redo()
  expect(draft.operations[0]!.edits).toEqual(plan.edits)
  const oversized = [{ slideIndex: 0, elements: [{ ...slides[0]!.elements[0]!, text: 'cat' }] },
    { slideIndex: 1, elements: [{ ...slides[1]!.elements[0]!, text: 'cat '.repeat(6000) }] }]
  const original = structuredClone(plan.edits)
  expect(() => planSlidesReplace(oversized, [], { ...conditions, replacement: 'longer' })).toThrow('20000')
  expect(plan.edits).toEqual(original)
  expect(() => planSlidesReplace(slides, [], { ...conditions, replacement: 'two\nlines' })).toThrow('换行')
})

it('invalidates a stale selection when pending text changes, and reads current edits for replace all', () => {
  let edits: { slideIndex: number; elementId: string; text: string }[] = []
  const apply = vi.fn()
  const navigate = vi.fn()
  openSlidesFindReplace(document.body, { getSlides: () => slides, getEdits: () => edits, isLocked: () => false,
    onNavigate: navigate, onReplace: apply })
  const query = document.querySelector<HTMLInputElement>('[aria-label="查找文字"]')!
  query.value = 'cat'; query.dispatchEvent(new Event('input'))
  const click = (command: string) => document.querySelector<HTMLButtonElement>(`[data-command="${command}"]`)!.click()
  click('findNext')
  edits = [{ slideIndex: 0, elementId: 'title', text: 'no current hit' }]
  click('replace')
  expect(apply).not.toHaveBeenCalled()
  expect(navigate).toHaveBeenLastCalledWith(1, 'shape')
  click('replaceAll')
  expect(apply).toHaveBeenCalledTimes(1)
  expect(apply.mock.calls[0]![0].count).toBe(2)
  expect(apply.mock.calls[0]![0].edits[0]).toEqual(edits[0])
})

it('continues finding from the consumed element after a single replacement', () => {
  let edits: import('./slides-find-replace').SlidesFindEdit[] = []
  const navigate = vi.fn()
  openSlidesFindReplace(document.body, { getSlides: () => slides, getEdits: () => edits, isLocked: () => false,
    onNavigate: navigate, onReplace: plan => { edits = plan.edits } })
  const query = document.querySelector<HTMLInputElement>('[aria-label="查找文字"]')!
  query.value = 'cat'; query.dispatchEvent(new Event('input'))
  const replacement = document.querySelector<HTMLInputElement>('[aria-label="替换为"]')!
  replacement.value = 'dog'
  const click = (command: string) => document.querySelector<HTMLButtonElement>(`[data-command="${command}"]`)!.click()
  click('findNext'); click('findNext'); click('replace'); click('findNext')
  expect(navigate).toHaveBeenLastCalledWith(1, 'shape')
})

it('separates the fixed title and actions from the scrollable search fields and named guidance', () => {
  openSlidesFindReplace(document.body, { getSlides: () => slides, getEdits: () => [], isLocked: () => false,
    onNavigate: vi.fn(), onReplace: vi.fn() })
  const dialog = document.querySelector('dialog')!
  expect(dialog.querySelector('header h2')?.textContent).toBe('查找和替换')
  expect(dialog.querySelector('header [aria-label="关闭查找和替换"]')).not.toBeNull()
  expect(dialog.querySelector('.slides-find-body [aria-label="查找文字"]')).not.toBeNull()
  expect(dialog.querySelector('footer [data-command="replaceAll"]')).not.toBeNull()
  const scope = dialog.querySelector<HTMLElement>('[role=region][aria-label="查找替换范围说明"]')
  expect(scope).not.toBeNull()
  expect(scope!.tabIndex).toBe(0)
  expect(scope!.textContent).toContain('混合样式')
})

it('keeps replacement refusal readable through a named keyboard-accessible result without committing', () => {
  const { click, onReplace } = panel(vi.fn(), () => true)
  click('replaceAll')
  const status = document.querySelector<HTMLElement>('[role=status]')!
  expect(status.getAttribute('aria-label')).toBe('查找替换结果')
  expect(status.tabIndex).toBe(0)
  expect(status.textContent).toContain('只读')
  expect(onReplace).not.toHaveBeenCalled()
})

it('reveals an action result without stealing the search field focus', () => {
  const { click, query } = panel(vi.fn(), () => true)
  const status = document.querySelector<HTMLElement>('[role=status]')!
  const reveal = vi.fn()
  status.scrollIntoView = reveal
  query.focus(); click('replaceAll')
  expect(reveal).toHaveBeenCalledWith({ block: 'nearest' })
  expect(document.activeElement).toBe(query)
})
