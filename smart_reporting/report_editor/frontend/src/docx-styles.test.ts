import { afterEach, expect, it } from 'vitest'
import { Editor, Node } from '@tiptap/core'
import { UndoRedo } from '@tiptap/extensions'
import { createParagraphStyleControl, safeParagraphStyle } from './docx-styles'
import { docxOperations, replayDocxOperations, type DocxPmNode } from './docx-operations'
import { NativeDraft } from './native-draft'
const Doc = Node.create({ name: 'doc', topNode: true, content: 'block+' })
const Para = Node.create({ name: 'docParagraph', group: 'block', content: 'text*', addAttributes: () => ({ docxIndex: { default: null }, styleId: { default: null }, align: { default: 'center' } }), renderHTML: () => ['p', 0] })
const Text = Node.create({ name: 'text', group: 'inline' })
const catalog = () => new Map([['Normal', { styleId: 'Normal', name: '正文', type: 'paragraph', isDefault: true }], ['Custom', { styleId: 'Custom', name: '强调段', type: 'paragraph', basedOn: 'Normal' }]])
const editors: Editor[] = []
afterEach(() => { editors.splice(0).forEach(editor => editor.destroy()); document.body.replaceChildren() })
function fixture(editable = true) {
  const host = document.createElement('div'); document.body.append(host)
  const editor = new Editor({ element: host, editable, extensions: [Doc, Para, Text, UndoRedo], editorProps: { handleScrollToSelection: () => true }, content: { type: 'doc', content: [0, 1].map(docxIndex => ({ type: 'docParagraph', attrs: { docxIndex, styleId: docxIndex ? 'Normal' : null }, content: [{ type: 'text', text: 'text' }] })) } })
  editors.push(editor)
  const styles = catalog(); (editor.storage as any).listNumbering = { styles }
  const anchors = [0, 1].map(docxIndex => ({ docxIndex, blockId: `block${docxIndex}`, expectedObjectSha256: `hash${docxIndex}`, editable: true }))
  const original = editor.getJSON() as DocxPmNode
  const control = createParagraphStyleControl(editor, editable, anchors); document.body.append(control)
  const choose = (value: string) => { control.focus(); control.value = value; control.dispatchEvent(new Event('change')) }
  return { editor, styles, anchors, original, control, choose }
}
it('applies a source paragraph style and preserves direct attrs through undo/redo and NativeDraft recovery', () => {
  const f = fixture(); expect(f.control.dataset.styleState).toBe('inherited')
  f.choose('Custom')
  const ops = [{ kind: 'setParagraphStyle', blockId: 'block0', expectedObjectSha256: 'hash0', styleId: 'Custom' }]
  expect(docxOperations(f.original, f.editor.getJSON(), f.anchors, undefined, undefined, f.styles)).toEqual(ops)
  expect(f.editor.getJSON().content![0].attrs!.align).toBe('center')
  expect(f.editor.commands.undo()).toBe(true); expect(docxOperations(f.original, f.editor.getJSON(), f.anchors, undefined, undefined, f.styles)).toEqual([])
  expect(f.editor.commands.redo()).toBe(true)
  const values = new Map<string, string>(); const storage = { getItem: (k: string) => values.get(k) ?? null, setItem: (k: string, v: string) => { values.set(k, v) }, removeItem: (k: string) => { values.delete(k) } }
  const identity = { documentId: 'style', revision: 1, sourceSha256: 'source', scope: { database: 'd', companyId: 'c', userId: 'u', threadId: 't' } }
  new NativeDraft(identity, storage).setOperations(ops)
  const restored = replayDocxOperations(f.original, new NativeDraft(identity, storage).operations, f.anchors, undefined, undefined, f.styles)
  expect(docxOperations(f.original, restored, f.anchors, undefined, undefined, f.styles)).toEqual(ops)
  f.editor.commands.setContent(restored, { emitUpdate: false }); f.editor.commands.setTextSelection(1); expect(f.control.value).toBe('Custom')
})
it('shows mixed styles, applies a range atomically and preserves focus-time target', () => {
  const f = fixture(); f.editor.commands.setTextSelection({ from: 1, to: f.editor.state.doc.content.size - 1 })
  expect(f.control.dataset.styleState).toBe('mixed'); f.choose('Custom')
  expect(f.editor.getJSON().content!.every(node => node.attrs!.styleId === 'Custom')).toBe(true)
  f.editor.commands.undo(); f.control.blur(); f.editor.commands.setTextSelection(1); f.control.focus()
  f.editor.commands.setTextSelection(f.editor.state.doc.child(0).nodeSize + 1)
  f.control.value = 'Custom'; f.control.dispatchEvent(new Event('change'))
  expect(f.editor.getJSON().content!.map(node => node.attrs!.styleId)).toEqual(['Custom', 'Normal'])
})
it('refuses readonly, stale focus document, missing anchors and foreign replay identity', () => {
  const f = fixture(); f.control.focus(); f.editor.commands.insertContent('changed'); const before = f.editor.getJSON()
  f.control.value = 'Custom'; f.control.dispatchEvent(new Event('change')); expect(f.editor.getJSON()).toEqual(before)
  f.control.blur(); f.anchors[0].editable = false; f.editor.commands.setTextSelection(1); expect(f.control.disabled).toBe(true)
  expect(fixture(false).control.disabled).toBe(true)
  expect(() => replayDocxOperations(f.original, [{ kind: 'setParagraphStyle', blockId: 'block1', expectedObjectSha256: 'foreign', styleId: 'Custom' }], f.anchors, undefined, undefined, f.styles)).toThrow(/身份/)
  expect(() => replayDocxOperations(f.original, [{ kind: 'setParagraphStyle', blockId: 'block1', expectedObjectSha256: 'hash1', styleId: 'Custom', rawPPr: '<evil/>' }], f.anchors, undefined, undefined, f.styles)).toThrow(/字段/)
})
it.each(['missing', 'character', 'numbered', 'outline-off', 'cycle', 'orphan'])('rejects unsafe target or inherited style %s', mode => {
  const styles = catalog(); const bad: any = { styleId: 'Bad', name: 'Bad', type: 'paragraph' }
  if (mode === 'character') bad.type = 'character'
  if (mode === 'numbered') { bad.basedOn = 'Parent'; styles.set('Parent', { styleId: 'Parent', name: 'Parent', type: 'paragraph', numPr: {} } as any) }
  if (mode === 'outline-off') bad.headingOutlineOff = true
  if (mode === 'cycle') bad.basedOn = 'Bad'
  if (mode === 'orphan') bad.basedOn = 'absent'
  if (mode !== 'missing') styles.set('Bad', bad)
  expect(() => safeParagraphStyle(styles, 'Bad')).toThrow()
})

it('keeps the select DOM focused while ordinary basedOn style runs update and exposes unsupported reasons', () => {
  const f = fixture()
  f.styles.set('Heading', { styleId: 'Heading', name: '标题', type: 'paragraph', headingLevel: 1 } as any)
  f.styles.set('Numbered', { styleId: 'Numbered', name: '编号', type: 'paragraph', numPr: {} } as any)
  f.editor.commands.setMeta('refresh', true)
  expect(f.control.querySelector<HTMLOptionElement>('option[value="Heading"]')!.disabled).toBe(false)
  expect(f.control.querySelector<HTMLOptionElement>('option[value="Numbered"]')!.text).toContain('编号')
  expect(f.control.querySelector<HTMLOptionElement>('option[value="Numbered"]')!.disabled).toBe(true)
  f.styles.set('Custom', { ...f.styles.get('Custom')!, display: { sizeHalfPoints: 40, color: '336699' } } as any)
  f.choose('Custom')
  expect(document.activeElement).toBe(f.control)
  expect(f.control.isConnected).toBe(true)
  expect(f.control.value).toBe('Custom')
  expect(f.control.querySelector<HTMLOptionElement>('option[value="Normal"]')!.disabled).toBe(false)
})
