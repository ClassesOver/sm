import { afterEach, expect, it } from 'vitest'
import { Editor } from '@tiptap/core'
import { flushSync } from 'react-dom'
import { editorExtensions } from './vendor/genoffice-docs/apps/docs/src/renderer/editor/extensions'
import { createDocxRibbon } from './docx-ribbon'
import { NativeDocxParagraphProperties } from './docx-paragraph-properties'
import { docxOperations } from './docx-operations'
import { NativeTableStructure } from './docx-tables'

const editors: Editor[] = []
afterEach(() => { editors.splice(0).forEach(editor => editor.destroy()); document.body.replaceChildren() })
function setup(second = false, extra: Record<string, unknown> = {}) {
  const attrs = { docxIndex: 0, align: 'right', indentLeft: 720, indentRight: 365, lineSpacing: 1.04, lineRule: 'auto', lineRawTwips: 250, spaceBefore: 125, spaceAfter: 240, keepNext: true, ...extra }
  const editor = new Editor({ extensions: [...editorExtensions, NativeDocxParagraphProperties], editorProps: { handleScrollToSelection: () => true }, content: { type: 'doc', content: [
    { type: 'docParagraph', attrs, content: [{ type: 'text', text: '第一段正文' }] },
    ...(second ? [{ type: 'docParagraph', attrs: { ...attrs, docxIndex: 1, align: 'left', spaceAfter: 360 }, content: [{ type: 'text', text: '第二段正文' }] }] : []),
  ] } })
  editors.push(editor)
  const anchors = [0, 1].map(docxIndex => ({ docxIndex, blockId: `p${docxIndex}`, expectedObjectSha256: `hash${docxIndex}`, editable: true }))
  editor.commands.setTextSelection(second ? { from: 2, to: editor.state.doc.content.size - 1 } : 2)
  const root = document.body.appendChild(document.createElement('div')); root.append(createDocxRibbon(editor, true, undefined, undefined, undefined, anchors))
  const open = () => flushSync(() => { const entry = root.querySelector<HTMLButtonElement>('[data-action="paragraph-options"]'); expect(entry).not.toBeNull(); entry!.click() })
  const field = (name: string) => root.querySelector<HTMLInputElement | HTMLSelectElement>(`[aria-label="${name}"]`)!
  const submit = () => flushSync(() => root.querySelector<HTMLFormElement>('[aria-label="段落设置"] form')!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })))
  return { editor, anchors, root, open, field, submit }
}

it('opens the native full paragraph entry with exact current fields and keeps unchanged source state', () => {
  const { editor, root, open, field, submit } = setup(), before = editor.getJSON(), doc = editor.state.doc
  open()
  expect(field('段落对齐').value).toBe('right'); expect(field('左缩进（pt）').value).toBe('36'); expect(field('右缩进（pt）').value).toBe('18.25')
  expect(field('段前间距（pt）').value).toBe('6.25'); expect(field('段后间距（pt）').value).toBe('12'); expect(field('段落行距倍数').value).toBe('1.04')
  submit(); expect(root.querySelector('[aria-label="段落设置"]')).toBeNull(); expect(editor.state.doc).toBe(doc); expect(editor.getJSON()).toEqual(before)
})

it('applies alignment, right indent and spacing as one undoable native change', () => {
  const { editor, anchors, root, open, field, submit } = setup(), before = editor.getJSON(); open()
  field('段落对齐').value = 'center'; field('右缩进（pt）').value = '-12.35'; field('段后间距（pt）').value = '8.5'; submit()
  expect(root.querySelector('[aria-label="段落设置"]')).toBeNull()
  expect(docxOperations(before, editor.getJSON(), anchors, undefined, editor.schema)).toEqual([{ kind: 'setParagraphProperties', blockId: 'p0', expectedObjectSha256: 'hash0', values: { align: 'center', indentRight: -247, spaceAfter: 170 } }])
  editor.commands.undo(); expect(editor.getJSON()).toEqual(before); editor.commands.redo(); expect(editor.state.doc.firstChild!.attrs.indentRight).toBe(-247)
})

it('shows mixed fields and only writes the explicitly replaced value across trusted paragraphs', () => {
  const { editor, anchors, open, field, submit } = setup(true), before = editor.getJSON(); open()
  expect(field('段落对齐').value).toBe(''); expect(field('段后间距（pt）').value).toBe('')
  field('段后间距（pt）').value = '9'; submit()
  expect(docxOperations(before, editor.getJSON(), anchors, undefined, editor.schema)).toEqual([0, 1].map(index => ({ kind: 'setParagraphProperties', blockId: `p${index}`, expectedObjectSha256: `hash${index}`, values: { spaceAfter: 180 } })))
  expect(editor.state.doc.firstChild!.attrs.align).toBe('right'); expect(editor.state.doc.lastChild!.attrs.align).toBe('left')
})

it('cancels all edits and shows editable source-supported flags', () => {
  const { editor, root, open, field } = setup(), before = editor.getJSON(); open(); field('右缩进（pt）').value = '9'
  const flags = root.querySelectorAll<HTMLInputElement>('[data-paragraph-flag]'); expect(flags.length).toBe(6)
  expect([...flags].every(flag => !flag.disabled)).toBe(true)
  root.querySelector<HTMLButtonElement>('[data-paragraph-cancel]')!.click(); expect(editor.getJSON()).toEqual(before)
})

it.each(['document', 'selection', 'readonly'])('refuses a stale %s before applying any field', change => {
  const { editor, root, open, field, submit } = setup(); open(); field('右缩进（pt）').value = '9'
  if (change === 'document') editor.commands.insertContent('变')
  else if (change === 'selection') editor.commands.setTextSelection(3)
  else editor.setEditable(false)
  const before = editor.getJSON(); submit(); expect(editor.getJSON()).toEqual(before); expect(root.querySelector('[role="alert"]')!.textContent).toContain('重新打开')
})

it('rejects out-of-range left indent atomically without applying the other valid field', () => {
  const { editor, root, open, field, submit } = setup(), before = editor.getJSON(); open(); field('左缩进（pt）').value = '721'; field('右缩进（pt）').value = '9'; submit()
  expect(editor.getJSON()).toEqual(before); expect(root.querySelector('[role="alert"]')!.textContent).toContain('段落属性')
})

it('combines pagination flags and outline with layout, preserving untouched source state through draft replay', async () => {
  const { editor, anchors, root, open, field, submit } = setup(), before = editor.getJSON(); open()
  field('段落对齐').value = 'center'; field('大纲级别').value = '3'
  for (const [key, value] of Object.entries({ keepNext: false, keepLines: true, widowControl: false, suppressLineNumbers: true, pageBreakBefore: true, contextualSpacing: true })) {
    root.querySelector<HTMLInputElement>(`[data-paragraph-flag="${key}"]`)!.checked = value
  }
  submit()
  expect(root.querySelector('[role="alert"]')).toBeNull()
  const operations = docxOperations(before, editor.getJSON(), anchors, undefined, editor.schema)
  expect(operations).toHaveLength(1); expect(operations[0]!.kind).toBe('setParagraphProperties')
  expect(operations[0]!.values).toEqual({ align: 'center', outlineLevel: 3, keepNext: false, keepLines: true, widowControl: false, suppressLineNumbers: true, pageBreakBefore: true, contextualSpacing: true })
  const { replayDocxOperations } = await import('./docx-operations')
  expect(replayDocxOperations(before, operations, anchors, undefined, editor.schema)).toEqual(editor.getJSON())
  expect(editor.state.doc.firstChild!.attrs.lineRawTwips).toBe(250)
  editor.commands.undo(); expect(editor.getJSON()).toEqual(before)
})

it('rejects a forged intent combined with changed body or unknown values', async () => {
  const { editor, anchors } = setup(), before = editor.getJSON()
  const { projectDocxParagraphProperties } = await import('./docx-paragraph-properties')
  const projected = projectDocxParagraphProperties(before.content![0]!, anchors[0]!, { keepLines: true }, editor.schema)
  const current = { ...before, content: [projected] }
  projected.content![0]!.text = '伪造正文'
  expect(() => docxOperations(before, current, anchors, undefined, editor.schema)).toThrow('同段正文')
  expect(() => projectDocxParagraphProperties(before.content![0]!, anchors[0]!, { unknown: true }, editor.schema)).toThrow()
})

it('shows mixed flags without changing untouched values', () => {
  const { editor, root, open } = setup(true)
  const json = editor.getJSON(); json.content![1]!.attrs!.keepNext = false
  editor.commands.setContent(json); editor.commands.setTextSelection({ from: 2, to: editor.state.doc.content.size - 1 }); open()
  expect(root.querySelector<HTMLInputElement>('[data-paragraph-flag="keepNext"]')!.indeterminate).toBe(true)
  expect(root.querySelector<HTMLInputElement>('[data-paragraph-flag="widowControl"]')!.checked).toBe(true)
})

it.each(['docListItem', 'docHeading'])('protects %s source-bound outline levels', type => {
  const { editor, field, open } = setup()
  const json = editor.getJSON(); json.content![0]!.type = type
  json.content![0]!.attrs = { ...json.content![0]!.attrs, level: 2, outlineOnly: false, numId: '1', ilvl: 0, kind: 'ordered' }
  editor.commands.setContent(json); editor.commands.setTextSelection(2); open()
  expect(field('大纲级别').disabled).toBe(true)
  expect(field('大纲级别').title).toContain('来源定义')
})

it('rejects mismatched draft identity and same-paragraph operation mixing', async () => {
  const { editor, anchors, open, field, submit } = setup(), before = editor.getJSON()
  open(); field('右缩进（pt）').value = '10'; submit()
  const operations = docxOperations(before, editor.getJSON(), anchors, undefined, editor.schema)
  const { replayDocxOperations } = await import('./docx-operations')
  expect(() => replayDocxOperations(before, [{ ...operations[0]!, expectedObjectSha256: 'forged' }], anchors, undefined, editor.schema)).toThrow('来源身份')
  expect(() => replayDocxOperations(before, [...operations, { kind: 'setParagraphAlignment', blockId: 'p0', expectedObjectSha256: 'hash0', alignment: 'center' }], anchors, undefined, editor.schema)).toThrow('同段其它操作')
})

it('disables the full dialog for a source-restricted paragraph', () => {
  const { editor, anchors, root } = setup()
  Object.assign(anchors[0]!, { paragraphPropertiesEditable: false })
  editor.commands.setTextSelection(3)
  expect(root.querySelector<HTMLButtonElement>('[data-action="paragraph-options"]')!.disabled).toBe(true)
})

it('applies paragraph settings to a signed simple table-cell paragraph through draft replay', async () => {
  const editor = new Editor({ extensions: [...editorExtensions, NativeTableStructure, NativeDocxParagraphProperties], editorProps: { handleScrollToSelection: () => true }, content: { type: 'doc', content: [
    { type: 'docTable', attrs: { docxIndex: 0 }, content: [{ type: 'docTableRow', content: [{ type: 'docTableCell', content: [{ type: 'docParagraph', attrs: { align: 'left', spaceAfter: 120 }, content: [{ type: 'text', text: '表格段落' }] }] }] }] },
  ] } })
  editors.push(editor)
  expect(editor.schema.nodes.docTable.spec.attrs).toHaveProperty('nativeTableCellParagraphProperties')
  const anchors = [{ docxIndex: 0, blockId: 'table', expectedObjectSha256: 'table-hash', editable: true, cells: [[{ cellId: 'cell', expectedObjectSha256: 'cell-hash', editable: true, paragraphs: [{ index: 0, expectedObjectSha256: 'paragraph-hash', editable: true }] }]] }]
  let textPosition = 0
  editor.state.doc.descendants((node, pos) => { if (node.isText) textPosition = pos })
  editor.commands.setTextSelection(textPosition + 1)
  const root = document.body.appendChild(document.createElement('div'))
  root.append(createDocxRibbon(editor, true, undefined, undefined, undefined, anchors))
  flushSync(() => root.querySelector<HTMLButtonElement>('[data-action="paragraph-options"]')!.click())
  root.querySelector<HTMLSelectElement>('[aria-label="段落对齐"]')!.value = 'center'
  flushSync(() => root.querySelector<HTMLFormElement>('[aria-label="段落设置"] form')!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })))
  expect(editor.getJSON().content![0]!.attrs!.nativeTableCellParagraphProperties, root.querySelector('[role="alert"]')?.textContent).toBeTruthy()
  const operations = docxOperations({ type: 'doc', content: [{ type: 'docTable', attrs: { docxIndex: 0 }, content: [{ type: 'docTableRow', content: [{ type: 'docTableCell', content: [{ type: 'docParagraph', attrs: { align: 'left', spaceAfter: 120 }, content: [{ type: 'text', text: '表格段落' }] }] }] }] }] }, editor.getJSON(), anchors, undefined, editor.schema)
  expect(operations).toEqual([{ kind: 'setTableCellParagraphProperties', blockId: 'table', expectedObjectSha256: 'table-hash', cellId: 'cell', expectedCellSha256: 'cell-hash', paragraphIndex: 0, expectedParagraphSha256: 'paragraph-hash', values: { align: 'center' } }])
  const { replayDocxOperations } = await import('./docx-operations')
  expect(replayDocxOperations({ type: 'doc', content: [{ type: 'docTable', attrs: { docxIndex: 0 }, content: [{ type: 'docTableRow', content: [{ type: 'docTableCell', content: [{ type: 'docParagraph', attrs: { align: 'left', spaceAfter: 120 }, content: [{ type: 'text', text: '表格段落' }] }] }] }] }] }, operations, anchors, undefined, editor.schema)).toEqual(editor.getJSON())
  editor.commands.undo(); expect(editor.state.doc.firstChild!.firstChild!.firstChild!.firstChild!.attrs.align).toBe('left')
})

it('links paragraph tabs to panels and uses a single roving tab stop', () => {
  const { root, open } = setup(); open()
  const tabs = [...root.querySelectorAll<HTMLButtonElement>('[aria-label="段落设置"] [role="tab"]')]
  expect(tabs.map(tab => tab.tabIndex)).toEqual([0, -1])
  for (const tab of tabs) {
    expect(tab.id).not.toBe('')
    const panel = document.getElementById(tab.getAttribute('aria-controls')!)!
    expect(panel?.getAttribute('role')).toBe('tabpanel')
    expect(panel?.getAttribute('aria-labelledby')).toBe(tab.id)
  }
  tabs[1]!.click(); expect(tabs.map(tab => tab.tabIndex)).toEqual([-1, 0])
})

it('switches paragraph tabs with arrow wraparound, Home and End without changing the document', () => {
  const { editor, root, open } = setup(), before = editor.getJSON(); open()
  const tabs = [...root.querySelectorAll<HTMLButtonElement>('[aria-label="段落设置"] [role="tab"]')]
  tabs[0]!.focus()
  for (const [key, expected] of [['ArrowRight', 1], ['ArrowRight', 0], ['ArrowLeft', 1], ['Home', 0], ['End', 1]] as const) {
    const event = new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true })
    document.activeElement!.dispatchEvent(event)
    expect(event.defaultPrevented).toBe(true); expect(document.activeElement).toBe(tabs[expected])
    expect(tabs.map(tab => tab.getAttribute('aria-selected'))).toEqual(expected === 0 ? ['true', 'false'] : ['false', 'true'])
    expect(root.querySelector<HTMLElement>(`[data-panel="${expected === 0 ? 'indents' : 'pagination'}"]`)!.hidden).toBe(false)
  }
  expect(editor.getJSON()).toEqual(before)
})

it.each(['composition', 'legacy', 'consumed'])('preserves paragraph tabs during protected %s keyboard events', protection => {
  const { root, open } = setup(); open()
  const tabs = [...root.querySelectorAll<HTMLButtonElement>('[aria-label="段落设置"] [role="tab"]')]
  tabs[0]!.focus()
  const event = new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true, cancelable: true, isComposing: protection === 'composition', keyCode: protection === 'legacy' ? 229 : 0 })
  if (protection === 'consumed') event.preventDefault()
  tabs[0]!.dispatchEvent(event)
  expect(document.activeElement).toBe(tabs[0]); expect(tabs[0]!.getAttribute('aria-selected')).toBe('true')
})
