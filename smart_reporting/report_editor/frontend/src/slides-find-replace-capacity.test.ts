import { afterEach, expect, it, vi } from 'vitest'
import { openSlidesFindReplace, planSlidesReplace, type SlidesFindSource, type SlidesFindEdit } from './slides-find-replace'
const conditions = { query: 'cat', replacement: 'dog', matchCase: false }
const source = (count: number): SlidesFindSource[] => [{ slideIndex: 0, elements: Array.from({ length: count }, (_, i) => ({ id: String(i), type: 'text', text: i === 0 ? 'cat unique' : 'cat', editable: true, findReplaceEditable: true })) }]
const pending = (count: number): SlidesFindEdit[] => Array.from({ length: count }, (_, i) => ({ slideIndex: 0, elementId: String(i), text: 'cat', geometry: { x: i, y: 2, width: 30, height: 40 } }))
afterEach(() => document.body.replaceChildren())
it('atomically rejects 501 new edits without changing source or incoming draft', () => {
  const slides = source(501), edits: SlidesFindEdit[] = [], before = structuredClone(slides)
  expect(() => planSlidesReplace(slides, edits, conditions)).toThrow('500')
  expect(slides).toEqual(before); expect(edits).toEqual([])
})
it('allows exactly 500 edit objects and 501 occurrences in one object', () => {
  expect(planSlidesReplace(source(500), [], conditions).edits).toHaveLength(500)
  const slides = source(1); slides[0]!.elements[0]!.text = 'cat '.repeat(501)
  const plan = planSlidesReplace(slides, [], conditions)
  expect(plan.count).toBe(501); expect(plan.edits).toHaveLength(1)
})
it('checks final draft capacity, preserving existing geometry and slide identity', () => {
  const edits = pending(500), before = structuredClone(edits)
  const plan = planSlidesReplace(source(1), edits, conditions)
  expect(plan.edits).toHaveLength(500); expect(plan.edits[0]).toEqual({ ...edits[0], text: 'dog' }); expect(edits).toEqual(before)
  expect(() => planSlidesReplace(source(501), pending(499), conditions)).toThrow('500')
  const secondSlide = [{ ...source(1)[0]!, slideIndex: 1 }]
  expect(() => planSlidesReplace(secondSlide, edits, conditions)).toThrow('500')
  expect(planSlidesReplace([...source(1), ...secondSlide], [], conditions).edits).toHaveLength(2)
})
it('preserves dialog inputs without committing overflow and accepts a narrower query once', () => {
  const slides = source(501), onReplace = vi.fn(), incoming = [{ ...pending(1)[0]!, text: 'cat unique' }], before = structuredClone(incoming)
  openSlidesFindReplace(document.body, { getSlides: () => slides, getEdits: () => incoming, isLocked: () => false, onNavigate: vi.fn(), onReplace })
  const query = document.querySelector<HTMLInputElement>('[aria-label="查找文字"]')!, replacement = document.querySelector<HTMLInputElement>('[aria-label="替换为"]')!, button = document.querySelector<HTMLButtonElement>('[data-command="replaceAll"]')!
  query.value = 'cat'; replacement.value = 'dog'
  for (let i = 0; i < 2; i++) {
    button.click(); expect(onReplace).not.toHaveBeenCalled()
    expect(document.querySelector('[role="status"]')!.textContent).toContain('500')
    expect(document.querySelector('[role="status"]')!.textContent).not.toContain('已替换')
    expect(query.value).toBe('cat'); expect(replacement.value).toBe('dog'); expect(incoming).toEqual(before)
  }
  query.value = 'unique'; query.dispatchEvent(new Event('input')); button.click()
  expect(onReplace).toHaveBeenCalledTimes(1); expect(onReplace.mock.calls[0]![0].edits).toHaveLength(1)
})
it('commits exactly 500 replacements through the dialog in one controller call', () => {
  const onReplace = vi.fn()
  openSlidesFindReplace(document.body, { getSlides: () => source(500), getEdits: () => [], isLocked: () => false, onNavigate: vi.fn(), onReplace })
  document.querySelector<HTMLInputElement>('[aria-label="查找文字"]')!.value = 'cat'
  document.querySelector<HTMLInputElement>('[aria-label="替换为"]')!.value = 'dog'
  document.querySelector<HTMLButtonElement>('[data-command="replaceAll"]')!.click()
  expect(onReplace).toHaveBeenCalledTimes(1); expect(onReplace.mock.calls[0]![0].edits).toHaveLength(500)
})
