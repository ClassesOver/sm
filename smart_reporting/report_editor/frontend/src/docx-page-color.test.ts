import { afterEach, describe, expect, it, vi } from 'vitest'
import { Editor, Node } from '@tiptap/core'
import { flushSync } from 'react-dom'
import { createDocxRibbon } from './docx-ribbon'
import { docxPageColorModel, docxPageColorOperations, effectiveDocxPageColor, withDocxPageColor } from './docx-page-color'
import { docxNativeOperations } from './docx-native-history'
import { replayDocxOperations } from './docx-operations'

const sha = 'a'.repeat(64)
const model = docxPageColorModel({ color: null, editable: true, readOnlyReason: null, expectedBackgroundSha256: sha })!

const editors: Editor[] = []
afterEach(() => { editors.splice(0).forEach(editor=>editor.destroy()); document.body.replaceChildren() })

describe('Word page colour draft (pinned Design ▸ Page Color)', () => {
  it('normalises source models and rejects malformed ones', () => {
    expect(model).toEqual({ color: null, editable: true, readOnlyReason: null, expectedBackgroundSha256: sha })
    for (const bad of [null, {}, { color: 'ffe699', editable: true, expectedBackgroundSha256: sha }, { color: null, editable: true, expectedBackgroundSha256: 'x' }, { color: null, editable: 'yes', expectedBackgroundSha256: sha }]) expect(docxPageColorModel(bad)).toBeNull()
  })

  it('sets, replaces and withdraws a single identity-bound operation and survives the native-history filter', () => {
    const others = [{ kind: 'setSectionLayout', sectionId: 's', expectedSectionSha256: sha, values: { columns: 2 } }]
    const set = withDocxPageColor(others, model, 'ffe699')
    expect(set).toEqual([...others, { kind: 'setPageColor', expectedBackgroundSha256: sha, color: 'FFE699' }])
    expect(docxNativeOperations(set)).toEqual(set)
    expect(effectiveDocxPageColor(set, model)).toBe('FFE699')
    const changed = withDocxPageColor(set, model, '0E2841')
    expect(changed.filter(op => op.kind === 'setPageColor')).toEqual([{ kind: 'setPageColor', expectedBackgroundSha256: sha, color: '0E2841' }])
    expect(withDocxPageColor(changed, model, null)).toEqual(others)
    const coloured = { ...model, color: 'FF0000' }
    expect(withDocxPageColor([], coloured, null)).toEqual([{ kind: 'setPageColor', expectedBackgroundSha256: sha, color: null }])
    expect(effectiveDocxPageColor([], coloured)).toBe('FF0000')
    expect(effectiveDocxPageColor(withDocxPageColor([], coloured, null), coloured)).toBeNull()
  })

  it('refuses read-only sources, bad colours and drafts that no longer match the source', () => {
    expect(() => withDocxPageColor([], { ...model, editable: false, readOnlyReason: '页面背景含主题色' }, 'FF0000')).toThrow('页面背景含主题色')
    expect(() => withDocxPageColor([], null, 'FF0000')).toThrow('页面颜色能力')
    expect(() => withDocxPageColor([], model, '#FF0000')).toThrow('6 位十六进制')
    const op = { kind: 'setPageColor', expectedBackgroundSha256: sha, color: 'FF0000' }
    expect(docxPageColorOperations([op], model)).toEqual([op])
    for (const bad of [[op, op], [{ ...op, expectedBackgroundSha256: 'b'.repeat(64) }], [{ ...op, color: 'ff0000' }], [{ ...op, color: null }], [{ ...op, extra: 1 }]]) expect(() => docxPageColorOperations(bad, model)).toThrow('原草稿已保留')
    expect(() => docxPageColorOperations([op], null)).toThrow()
    expect(() => docxPageColorOperations([op], { ...model, editable: false, readOnlyReason: '只读' })).toThrow('只读')
  })
})

describe('draft restore replay', () => {
  it('replayDocxOperations treats setPageColor as a document-level operation (no body anchor)', () => {
    const original = { type: 'doc', content: [{ type: 'docParagraph', attrs: { docxIndex: 0 }, content: [{ type: 'text', text: '正文' }] }] }
    const op = { kind: 'setPageColor', expectedBackgroundSha256: sha, color: 'FFC000' }
    expect(replayDocxOperations(original, [op], [{ docxIndex: 0, blockId: 'p0', expectedObjectSha256: 'x', editable: true }])).toEqual(original)
  })
})

describe('Design ▸ Page Color ribbon control', () => {
  const editorFor = (editable = true) => {
    const host = document.createElement('div'); document.body.append(host)
    const Doc = Node.create({ name: 'doc', topNode: true, content: 'block+' })
    const P = Node.create({ name: 'docParagraph', group: 'block', content: 'text*', renderHTML: () => ['p', 0] })
    const T = Node.create({ name: 'text', group: 'inline' })
    return new Editor({ element: host, editable, extensions: [Doc, P, T], content: { type: 'doc', content: [{ type: 'docParagraph', content: [{ type: 'text', text: 'x' }] }] } })
  }
  const mount = (controls: Parameters<typeof createDocxRibbon>[19], editable = true) => {
    const editor = editorFor(editable)
    editors.push(editor)
    const ribbon = createDocxRibbon(editor, editable, undefined, undefined, undefined, [], undefined, undefined, undefined, undefined, undefined, undefined, [], undefined, undefined, undefined, undefined, undefined, undefined, controls)
    document.body.append(ribbon)
    ribbon.querySelector<HTMLButtonElement>('[data-tab-label="设计"]')!.click()
    return ribbon
  }

  it('offers the pinned theme + standard palette and “no colour”, reflecting the current value', () => {
    let current: string | null = null
    const apply = vi.fn((color: string | null) => { current = color })
    const ribbon = mount({ current: () => current, reason: () => null, apply })
    const trigger = ribbon.querySelector<HTMLButtonElement>('[data-action="page-color"]')!
    expect(trigger.disabled).toBe(false); expect(trigger.title).toBe('页面颜色：无颜色')
    const click = (selector:string) => flushSync(()=>ribbon.querySelector<HTMLButtonElement>(selector)!.click())
    const orange = '.gcp-standard-row [aria-label="橙色"]'
    flushSync(()=>trigger.click()); expect(trigger.getAttribute('aria-expanded')).toBe('true')
    expect(ribbon.querySelectorAll('.gcp-theme-base [role="gridcell"]')).toHaveLength(10)
    expect(ribbon.querySelectorAll('.gcp-standard-row [role="gridcell"]')).toHaveLength(10)
    expect(ribbon.querySelectorAll('.gcp-theme-shades [role="gridcell"]').length).toBeGreaterThan(10)
    click(orange)
    expect(apply).toHaveBeenLastCalledWith('FFC000')
    expect(trigger.getAttribute('aria-expanded')).toBe('false')
    expect(trigger.title).toBe('页面颜色：#FFC000')
    flushSync(()=>trigger.click())
    expect(ribbon.querySelector(orange)!.getAttribute('aria-selected')).toBe('true')
    click('.gcp-auto')
    expect(apply).toHaveBeenLastCalledWith(null)
  })

  it('is disabled with the reason for read-only sources or a read-only document and reports apply errors', () => {
    const report = vi.fn()
    const readonly = mount({ current: () => 'FF0000', reason: () => '页面背景含主题色、图片或渐变填充，保持原样', apply: () => {} })
    const trigger = readonly.querySelector<HTMLButtonElement>('[data-action="page-color"]')!
    expect(trigger.disabled).toBe(true); expect(trigger.title).toContain('主题色')
    document.body.replaceChildren()
    expect(mount({ current: () => null, reason: () => null, apply: () => {} }, false).querySelector<HTMLButtonElement>('[data-action="page-color"]')!.disabled).toBe(true)
    expect(report).not.toHaveBeenCalled()
  })
})
