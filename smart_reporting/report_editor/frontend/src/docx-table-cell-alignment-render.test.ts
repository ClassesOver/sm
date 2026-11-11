import { afterEach, expect, it } from 'vitest'
import { Editor } from '@tiptap/core'
import { tableModelToPmNode } from './vendor/genoffice-docs/apps/docs/src/renderer/editor/convert'
import { editorExtensions } from './vendor/genoffice-docs/apps/docs/src/renderer/editor/extensions'

const editors: Editor[] = []
afterEach(() => editors.splice(0).forEach(editor => editor.destroy()))

it.each(['docTableCell', 'docTableHeader'].flatMap(type => ['center', 'right'].map(align => ({ type, align }))))('renders paragraph start independently of stale $type/$align first-paragraph alignment after reopen', ({ type, align }) => {
  const editor = new Editor({ extensions: editorExtensions, editorProps: { handleScrollToSelection: () => true }, content: {
    type: 'doc', content: [{ type: 'docTable', content: [{ type: 'docTableRow', content: [{ type, attrs: { align }, content: [
      { type: 'docParagraph', attrs: { align: 'right' }, content: [{ type: 'text', text: 'LTR right' }] },
      { type: 'docParagraph', attrs: { bidi: true }, content: [{ type: 'text', text: 'שלום explicit' }] },
      { type: 'docParagraph', attrs: { bidiInferred: true }, content: [{ type: 'text', text: 'שלום inferred' }] },
      { type: 'docListItem', attrs: { bidi: true, kind: 'bullet', numId: '1', ilvl: 0 }, content: [{ type: 'text', text: 'שלום list' }] },
      { type: 'docParagraph', content: [{ type: 'text', text: 'LTR start' }] },
      { type: 'docParagraph', attrs: { align: 'center' }, content: [{ type: 'text', text: 'explicit center' }] },
      { type: 'docParagraph', attrs: { tblPara: JSON.stringify({ align: 'center' }) }, content: [{ type: 'text', text: 'table style center' }] },
    ] }] }] }] },
  })
  editors.push(editor)
  const cell = editor.view.dom.querySelector('td,th') as HTMLElement
  // Browser inheritance must carry logical start, which each paragraph resolves
  // using its own direction; the first paragraph's old alignment is not a tc property.
  expect(cell.style.textAlign).toBe('start')
  const paras = cell.querySelectorAll<HTMLElement>(':scope > p, :scope > .doc-li')
  expect(paras[0].style.textAlign).toBe('right')
  for (const index of [1, 2, 3]) {
    expect(paras[index].style.direction).toBe('rtl')
    expect(paras[index].style.textAlign).toBe('')
  }
  expect(paras[4].style.textAlign).toBe('')
  expect(paras[5].style.textAlign).toBe('center')
  expect(paras[6].style.textAlign).toBe('center')
  expect(editor.state.doc.firstChild!.firstChild!.firstChild!.attrs.align).toBe(align)
})


it('source converter reopened baseline retains cell attrs and styles while each paragraph owns its alignment', () => {
  const model: any = { rows: [[{ paras: ['LTR right', 'שלום', 'LTR start'], align: 'right', richParas: [
    { runs: [{ text: 'LTR right' }], align: 'right' },
    { runs: [{ text: 'שלום' }], bidi: true },
    { runs: [{ text: 'LTR start' }] },
  ] }]], colWidthsTwips: [2001] }
  const table = tableModelToPmNode(model, 4)
  const editor = new Editor({ extensions: editorExtensions, content: { type: 'doc', content: [
    { type: 'docParagraph', attrs: { align: 'center' }, content: [{ type: 'text', text: 'body unchanged' }] }, table,
  ] } })
  editors.push(editor)
  const cell = editor.view.dom.querySelector('td') as HTMLElement
  expect(cell.style.textAlign).toBe('start')
  expect(cell.querySelectorAll('p')[0].style.textAlign).toBe('right')
  expect(cell.querySelectorAll('p')[1].style.direction).toBe('rtl')
  expect(cell.querySelectorAll('p')[1].style.textAlign).toBe('')
  expect(cell.querySelectorAll('p')[2].style.textAlign).toBe('')
  expect((editor.view.dom.firstElementChild as HTMLElement).style.textAlign).toBe('center')
  expect(editor.state.doc.child(1).child(0).child(0).attrs.align).toBe('right')
})
