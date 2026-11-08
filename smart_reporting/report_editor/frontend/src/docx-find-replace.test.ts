import { afterEach, expect, it } from 'vitest'
import { Editor, Extension, Mark, Node } from '@tiptap/core'
import { UndoRedo } from '@tiptap/extensions'
import { Plugin } from '@tiptap/pm/state'
import { flushSync } from 'react-dom'
import { createDocxFindReplace, validateDocxReplacement } from './docx-find-replace'
import { createDocxRibbon } from './docx-ribbon'
import { docxOperations, replayDocxOperations, type DocxAnchor, type DocxPmNode } from './docx-operations'
import { NativeDraft } from './native-draft'
import { SearchHighlightExtension, searchPluginKey } from './vendor/genoffice-docs/apps/docs/src/renderer/editor/decoration-extensions'

const Doc = Node.create({ name: 'doc', topNode: true, content: 'block+' })
const attrs = () => ({ docxIndex: { default: null }, nativeTableStructure: { default: null } })
const Paragraph = Node.create({ name: 'docParagraph', group: 'block', content: 'inline*', addAttributes: attrs, renderHTML: () => ['p', 0] })
const Heading = Paragraph.extend({ name: 'docHeading', renderHTML: () => ['h1', 0] })
const Text = Node.create({ name: 'text', group: 'inline' })
const Break = Node.create({ name: 'docHardBreak', inline: true, group: 'inline', renderHTML: () => ['br'] })
const Protected = Node.create({ name: 'docProtected', group: 'block', content: 'inline*', addAttributes: attrs, renderHTML: () => ['aside', 0] })
const Table = Node.create({ name: 'docTable', group: 'block', content: 'docTableRow+', addAttributes: attrs, renderHTML: () => ['table', ['tbody', 0]] })
const Row = Node.create({ name: 'docTableRow', content: 'docTableCell+', renderHTML: () => ['tr', 0] })
const Cell = Node.create({ name: 'docTableCell', content: 'docParagraph+', renderHTML: () => ['td', 0] })
const Bold = Mark.create({ name: 'bold', renderHTML: () => ['b', 0] })
const Link = Mark.create({ name: 'link', addAttributes: () => ({ href: { default: 'https://example.test' }, tooltip: { default: null }, plain: { default: false }, rId: { default: 'rId2' } }), renderHTML: () => ['a', 0] })
const p = (text: string, index: number | null = 0, type = 'docParagraph'): DocxPmNode => ({ type, attrs: { docxIndex: index }, content: [{ type: 'text', text }] })
const table = (paras = ['cat']): DocxPmNode => ({ type: 'docTable', attrs: { docxIndex: 1 }, content: [{ type: 'docTableRow', content: [{ type: 'docTableCell', content: paras.map(text => p(text, null)) }] }] })
const anchor = (index: number, editable = true): DocxAnchor => ({ docxIndex: index, blockId: `block-${index}`, expectedObjectSha256: `sha-${index}`, editable })
const defaultAnchors: DocxAnchor[] = [anchor(0), { ...anchor(1, false), cells: [[{ cellId: 'cell-1-0-0', expectedObjectSha256: 'cell-sha', editable: true }]] }, anchor(2)]
const disposals: (() => void)[] = []
afterEach(() => { disposals.splice(0).forEach(dispose => dispose()); document.body.replaceChildren(); localStorage.clear() })
function setup(content: DocxPmNode[] = [p('cat cat'), table(), p('cat', 2, 'docHeading')], sourceAnchors = structuredClone(defaultAnchors)) {
  const root = document.createElement('div'); root.className = 'docx-native'; document.body.append(root)
  let baseline: DocxPmNode, ready = false, locked = false
  const draft = new NativeDraft({ documentId: 'find', revision: 1, sourceSha256: 'source-sha', scope: { database: 'db', companyId: 'co', userId: 'u', threadId: 't' } }, localStorage)
  const Guard = Extension.create({ name: 'testNativeGuard', addProseMirrorPlugins: () => [new Plugin({ filterTransaction(tr) {
    if (!ready || !tr.docChanged) return true
    if (locked || draft.saving || draft.closed) return false
    try { docxOperations(baseline, tr.doc.toJSON(), sourceAnchors); return true } catch { return false }
  } })] })
  const editor = new Editor({ element: root.appendChild(document.createElement('div')), extensions: [Doc, Paragraph, Heading, Text, Break, Protected, Table, Row, Cell, Bold, Link, UndoRedo, SearchHighlightExtension, Guard], content: { type: 'doc', content },
    editorProps: { handleScrollToSelection: () => true },
    onUpdate: () => { if (ready) draft.setOperations(docxOperations(baseline, editor.getJSON(), sourceAnchors)) },
  })
  baseline = editor.getJSON(); ready = true
  const find = createDocxFindReplace({ editor, root, anchors: sourceAnchors, getBaseline: () => baseline, isLocked: () => locked || draft.saving || draft.closed,
    getSection: () => undefined, getSectionOperation: () => undefined, styles: new Map() })
  disposals.push(() => { find.dispose(); editor.destroy() })
  const input = (selector: string, value: string) => { const field = find.panel.querySelector<HTMLInputElement>(selector)!; field.value = value; field.dispatchEvent(new Event('input', { bubbles: true })); return field }
  const search = (value: string) => input('[data-find-query]', value)
  const replaceWith = (value: string) => input('[data-find-replacement]', value)
  const action = (value: string) => find.panel.querySelector<HTMLButtonElement>(`[data-find-action="${value}"]`)!
  const message = () => find.panel.querySelector('[data-find-status]')!.textContent
  const count = () => find.panel.querySelector('[data-find-count]')!.textContent
  const mode = (value: string) => { const field = find.panel.querySelector<HTMLSelectElement>('[data-find-mode]')!; field.value = value; field.dispatchEvent(new Event('change', { bubbles: true })) }
  find.open('replace')
  return { root, editor, baseline, draft, find, search, replaceWith, action, message, count, mode, setLocked(value: boolean) { locked = value; find.refreshLock() } }
}

it('finds across text marks, body/headings/tables, decorates and wraps navigation without dirtying drafts', () => {
  const f = setup()
  f.search('cat')
  expect(f.count()).toBe('1/4')
  expect(searchPluginKey.getState(f.editor.state)?.find()).toHaveLength(4)
  f.action('previous').click(); expect(f.count()).toBe('4/4')
  expect(f.editor.state.selection.$from.parent.type.name).toBe('docHeading')
  f.action('next').click(); expect(f.count()).toBe('1/4')
  f.find.panel.querySelectorAll<HTMLButtonElement>('.find-result')[2].click()
  expect(f.editor.state.selection.$from.parent.textContent).toBe('cat')
  expect(f.editor.state.selection.$from.depth).toBe(4)
  expect(f.draft.operations).toEqual([])
  f.action('close').click()
  expect(searchPluginKey.getState(f.editor.state)?.find()).toEqual([])
})

it('replaces all atomically into strict source operations, replays persisted drafts and supports one-step undo/redo', () => {
  const f = setup(); f.search('cat'); f.replaceWith('dog')
  expect(f.find.replace(true)).toBe(true)
  expect(f.draft.operations).toEqual([
    { kind: 'replaceParagraph', blockId: 'block-0', expectedObjectSha256: 'sha-0', text: 'dog dog' },
    { kind: 'replaceCellText', blockId: 'block-1', cellId: 'cell-1-0-0', expectedObjectSha256: 'cell-sha', text: 'dog' },
    { kind: 'replaceParagraph', blockId: 'block-2', expectedObjectSha256: 'sha-2', text: 'dog' },
  ])
  expect(f.message()).toContain('已替换 4 处')
  const restored = new NativeDraft(f.draft.identity, localStorage)
  expect(restored.operations).toEqual(f.draft.operations)
  expect(f.editor.schema.nodeFromJSON(replayDocxOperations(f.baseline, restored.operations, defaultAnchors)).eq(f.editor.state.doc)).toBe(true)
  expect(f.editor.commands.undo()).toBe(true); expect(f.editor.getJSON()).toEqual(f.baseline); expect(f.draft.operations).toEqual([])
  expect(f.editor.commands.redo()).toBe(true); expect(f.editor.getText()).toContain('dog dog')
})

it('uses separate undo boundaries for current replacement and consumes refreshed positions after edits/undo', () => {
  const f = setup([p('cat cat')], [anchor(0)])
  f.search('cat'); f.replaceWith('kitten'); f.action('replace').click()
  expect(f.editor.getText()).toBe('kitten cat'); expect(f.count()).toBe('1/1')
  f.action('replace').click(); expect(f.editor.getText()).toBe('kitten kitten')
  f.editor.commands.undo(); expect(f.editor.getText()).toBe('kitten cat')
  f.editor.commands.undo(); expect(f.editor.getText()).toBe('cat cat'); expect(f.count()).toBe('1/2')
  f.editor.commands.insertContentAt(1, 'pre ')
  f.action('replace').click(); expect(f.editor.getText()).toBe('pre kitten cat')
})

it.each(['readonly', 'saving', 'closed'])('keeps find/navigation available but rejects forced replacement while %s', state => {
  const f = setup(); f.search('cat'); f.replaceWith('dog')
  if (state === 'readonly') { f.editor.setEditable(false); f.setLocked(true) }
  if (state === 'saving') f.draft.beginSave()
  if (state === 'closed') { f.draft.beginSave(); f.draft.saveCompleted({ revision: 2, revisionRegistered: true }) }
  f.find.refreshLock()
  expect(f.action('replace').disabled).toBe(true)
  expect(f.action('next').disabled).toBe(false); f.action('next').click(); expect(f.count()).toBe('2/4')
  expect(f.find.replace(true)).toBe(false); expect(f.editor.getJSON()).toEqual(f.baseline)
  expect(f.message()).toContain('不能替换')
})

it('rejects a replace-all containing a readonly cell without editing the earlier safe body', () => {
  const anchors = structuredClone(defaultAnchors); anchors[1].cells![0][0].editable = false
  const f = setup(undefined, anchors); f.search('cat'); f.replaceWith('dog')
  expect(f.find.replace(true)).toBe(false); expect(f.message()).toContain('只读')
  expect(f.editor.getJSON()).toEqual(f.baseline); expect(f.draft.dirty).toBe(false)
  expect(f.find.replace(false)).toBe(true); expect(f.editor.getText()).toContain('dog cat')
})

it.each(['new', 'duplicate', 'missing-hash', 'duplicate-anchor', 'readonly', 'link', 'complex'])('accurately rejects unsupported %s targets without draft changes', kind => {
  let node = p('cat'), anchors = [anchor(0)]
  if (kind === 'new') node = p('cat', null)
  if (kind === 'duplicate-anchor') anchors.push(anchor(0))
  if (kind === 'missing-hash') anchors[0].expectedObjectSha256 = ''
  if (kind === 'readonly') anchors[0].editable = false
  if (kind === 'link') node.content![0].marks = [{ type: 'link' }]
  if (kind === 'complex') node.content!.push({ type: 'docHardBreak' })
  const f = setup(kind === 'duplicate' ? [node, node] : [node], anchors); f.search('cat'); f.replaceWith('dog')
  expect(f.find.replace(true)).toBe(false); expect(f.message()).toMatch(/锚点|只读|链接|复杂内联/)
  expect(f.editor.getJSON()).toEqual(f.baseline); expect(f.draft.dirty).toBe(false)
})

it('refuses text replacement in a structural table draft and preserves all existing operations', () => {
  const f = setup([table()], [defaultAnchors[1]])
  const candidate = structuredClone(f.baseline)
  candidate.content![0].attrs!.nativeTableStructure = { kind: 'insertTableRow', index: 0 }
  // Refresh projections use setContent with the native guard suspended in main.
  const g = setup([candidate.content![0]], [defaultAnchors[1]])
  g.search('cat'); g.replaceWith('dog')
  expect(g.find.replace(true)).toBe(false); expect(g.message()).toContain('结构修改后请先保存')
  expect(g.editor.getJSON()).toEqual(g.baseline)
})

it('reuses source regex/wildcard captures, case/width options, validates patterns and rejects paragraph splitting', () => {
  const f = setup([p('CAT cat ＣＡＴ cot')], [anchor(0)])
  f.search('cat'); expect(f.count()).toBe('1/3')
  const matchCase = f.find.panel.querySelector<HTMLInputElement>('[data-find-option="matchCase"]')!
  matchCase.checked = true; matchCase.dispatchEvent(new Event('change', { bubbles: true })); expect(f.count()).toBe('1/1')
  matchCase.checked = false
  f.mode('regex'); f.search('c(a|o)t'); f.replaceWith('$1!')
  expect(f.find.replace(true)).toBe(true); expect(f.editor.getText()).toBe('A! a! Ａ! o!')
  f.editor.commands.undo(); f.mode('wildcard'); f.search('c(?)t'); f.replaceWith('x\\1x')
  expect(f.find.replace(false)).toBe(true); expect(f.editor.getText()).toBe('xAx cat ＣＡＴ cot')
  f.search('['); expect(f.message()).toContain('表达式无效'); expect(f.count()).toBe('0/0')
  f.mode('literal'); f.search('cat'); f.replaceWith('^p')
  expect(f.find.replace(true)).toBe(false); expect(f.message()).toContain('段落拆分')
})

it('detects save projection mismatches for mixed style boundaries and multi-paragraph cells, preserves source marks for equal lengths', () => {
  const node = p('cat'); node.content![0].marks = [{ type: 'bold' }]; node.content!.push({ type: 'text', text: ' tail' })
  const f = setup([node], [anchor(0)]); f.search('cat'); f.replaceWith('kitten')
  expect(f.find.replace(false)).toBe(false); expect(f.message()).toContain('格式边界')
  f.replaceWith('dog'); expect(f.find.replace(false)).toBe(true)
  const g = setup([table(['cat', 'tail'])], [defaultAnchors[1]])
  g.search('cat'); g.replaceWith('dog'); expect(g.find.replace(false)).toBe(false); expect(g.message()).toMatch(/结构|分段/)
})

it('rejects text over backend limits and surrogate-splitting replacement', () => {
  const f = setup([p('cat')], [anchor(0)]); f.search('cat'); f.replaceWith('x'.repeat(20001))
  expect(f.find.replace(false)).toBe(false); expect(f.message()).toContain('20000')
  const g = setup([p('😀')], [anchor(0)]); g.search('\uD83D'); g.replaceWith('x')
  expect(g.find.replace(false)).toBe(false); expect(g.message()).toContain('Unicode')
})

it('wires Home Find/Replace and scoped Ctrl+F/H, cleans handlers up and leaves readonly find enabled', () => {
  const f = setup()
  const ribbon = createDocxRibbon(f.editor, true, undefined, undefined, undefined, defaultAnchors, undefined, undefined, f.find.open)
  f.root.append(ribbon)
  flushSync(() => ribbon.querySelector<HTMLButtonElement>('[data-action="find"]')!.click())
  expect(f.find.panel.hidden).toBe(false)
  expect(f.find.panel.querySelector<HTMLElement>('[data-replace-row]')!.hidden).toBe(true)
  flushSync(() => ribbon.querySelector<HTMLButtonElement>('[data-action="replace"]')!.click())
  expect(f.find.panel.querySelector<HTMLElement>('[data-replace-row]')!.hidden).toBe(false)
  f.editor.setEditable(false)
  expect(ribbon.querySelector<HTMLButtonElement>('[data-action="find"]')!.disabled).toBe(false)
  f.action('close').click()
  const key = new KeyboardEvent('keydown', { key: 'h', ctrlKey: true, bubbles: true, cancelable: true })
  f.editor.view.dom.dispatchEvent(key); expect(key.defaultPrevented).toBe(true); expect(f.find.panel.hidden).toBe(false)
  f.find.dispose()
  const after = new KeyboardEvent('keydown', { key: 'f', ctrlKey: true, bubbles: true, cancelable: true })
  f.root.dispatchEvent(after); expect(after.defaultPrevented).toBe(false)
})

it('validates preexisting foreign replay identity rather than trusting superficially valid operations', () => {
  const f = setup([p('cat')], [anchor(0)]), candidate = structuredClone(f.baseline)
  candidate.content![0].content![0].text = 'dog'
  expect(() => validateDocxReplacement(f.baseline, candidate, [], f.editor.schema, new Map())).toThrow(/锚点/)
})
