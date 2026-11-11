import { expect, it } from 'vitest'
import { Editor } from '@tiptap/core'
import { editorExtensions } from './vendor/genoffice-docs/apps/docs/src/renderer/editor/extensions'
import { createParagraphStyleControl } from './docx-styles'
import { docxOperations } from './docx-operations'
import { NativeRibbonStyle } from './docx-style-majority'
import { replayDocxOperations } from './docx-operations'

it('applies source Ribbon majority shedding with paragraph style in one transaction', () => {
 const make = () => new Editor({extensions:[...editorExtensions, NativeRibbonStyle],editorProps:{handleScrollToSelection:()=>true},content:{type:'doc',content:[{type:'docParagraph',attrs:{docxIndex:0},content:[{type:'text',text:'Body',marks:[{type:'bold'}]}]}]}})
 const editor=make(), source=make(), styles=new Map([['Normal',{styleId:'Normal',name:'Normal',type:'paragraph',isDefault:true}],['Custom',{styleId:'Custom',name:'Custom',type:'paragraph'}]])
 ;(editor.storage as any).listNumbering.styles=styles
 const anchors=[{docxIndex:0,blockId:'p0',expectedObjectSha256:'sha0',editable:true,paragraphStyleEditable:true}]
 const control=createParagraphStyleControl(editor,true,anchors);document.body.append(control);editor.commands.setTextSelection(2);control.focus();control.value='Custom';control.dispatchEvent(new Event('change'))
 const node=source.state.doc.child(0), tr=source.state.tr.setNodeMarkup(0,undefined,{...node.attrs,styleId:'Custom',nativeRibbonStyle:true})
 tr.removeMark(1,5,source.schema.marks.bold);source.view.dispatch(tr)
 const actual=editor.getJSON(),expected=source.getJSON();console.log(JSON.stringify({local:actual.content![0].content,fixedSource:expected.content![0].content}))
 editor.destroy();source.destroy();control.remove();expect(actual).toEqual(expected)
})


it.each([['ABC', 'D', true], ['AB', 'CD', false], ['A', 'BCD', false]])('uses strict majority on text %s / %s', (marked, rest, removed) => {
  const styles = new Map([['Normal', { styleId: 'Normal', name: 'Normal', type: 'paragraph', isDefault: true }], ['Custom', { styleId: 'Custom', name: 'Custom', type: 'paragraph' }]])
  const editor = new Editor({ extensions: [...editorExtensions, NativeRibbonStyle], editorProps: { handleScrollToSelection: () => true }, content: { type: 'doc', content: [{ type: 'docParagraph', attrs: { docxIndex: 0, styleId: 'Custom', keepNext: true }, content: [{ type: 'text', text: marked, marks: [{ type: 'bold' }, { type: 'docTextStyle', attrs: { color: '123456', font: 'CJK', fontAscii: 'Arial', sizeHalfPoints: 32, rawRPr: '<w:rPr><w:noProof/></w:rPr>' } }] }, { type: 'text', text: rest, marks: [{ type: 'italic' }] }] }] } })
  ;(editor.storage as any).listNumbering.styles = styles
  const anchors = [{ docxIndex: 0, blockId: 'p0', expectedObjectSha256: 'sha0', editable: true, paragraphStyleEditable: true }], baseline = editor.getJSON()
  const control = createParagraphStyleControl(editor, true, anchors); document.body.append(control)
  editor.commands.setTextSelection(2); control.focus(); control.value = 'Custom'; control.dispatchEvent(new Event('change'))
  const current = editor.getJSON(), marks = current.content![0].content![0].marks ?? []
  expect(marks.some(mark => mark.type === 'bold')).toBe(!removed)
  const attrs = marks.find(mark => mark.type === 'docTextStyle')?.attrs
  for (const key of ['color', 'font', 'fontAscii', 'sizeHalfPoints']) expect(attrs?.[key] == null).toBe(removed)
  expect(attrs?.rawRPr).toBe('<w:rPr><w:noProof/></w:rPr>')
  const ops = docxOperations(baseline, current, anchors, undefined, editor.schema, styles)
  expect(ops).toEqual([{ kind: 'setParagraphStyle', blockId: 'p0', expectedObjectSha256: 'sha0', styleId: 'Custom', ribbon: true }])
  expect(() => replayDocxOperations(baseline, [ops[0]!, { ...ops[0]! }], anchors, undefined, editor.schema, styles)).toThrow()
  const restored = replayDocxOperations(baseline, ops, anchors, undefined, editor.schema, styles)
  expect(editor.schema.nodeFromJSON(restored).eq(editor.state.doc)).toBe(true)
  editor.commands.undo(); expect(editor.getJSON()).toEqual(baseline); editor.commands.redo(); expect(editor.getJSON()).toEqual(current)
  const forged = structuredClone(current) as import('./docx-operations').DocxPmNode; forged.content![0].content![0].text += 'forged'
  expect(() => docxOperations(baseline, forged, anchors, undefined, editor.schema, styles)).toThrow()
  for (const ribbon of [false, null, 1, 'true']) expect(() => replayDocxOperations(baseline, [{ ...ops[0]!, ribbon }], anchors, undefined, editor.schema, styles)).toThrow()
  editor.destroy(); control.remove()
})
