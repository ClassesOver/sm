import { expect, it, afterEach } from 'vitest'
import { Editor } from '@tiptap/core'
import { editorExtensions } from './vendor/genoffice-docs/apps/docs/src/renderer/editor/extensions'
import { docxNativeOperations, NativeDocxHistory } from './docx-native-history'
import { NativeStylesPane, applyStylesPaneAction, normalizeStylesPane, stylesPaneSelectionEditable } from './docx-styles-pane-operations'
import { replayDocxOperations } from './docx-operations'
import { normalizePlainDocxRuns, replayPlainDocxRuns } from './docx-plain-paragraph-runs'
import { flushSync } from 'react-dom'
import { createRoot } from 'react-dom/client'
import { StylesPane } from './docx-styles-pane-source'
import { registerStylesPaneContext, stylesPaneFormatState } from './docx-styles-pane-adapter'
import type { StyleInfo } from '@genoffice/docx-engine'

const editors: Editor[] = []
afterEach(() => { editors.splice(0).forEach(editor => editor.destroy()); document.body.replaceChildren() })

it('retains source-bound StyleUpsert definitions in native document history', () => {
  const operation = { kind: 'upsertStyle', expectedStylesSha256: 'a'.repeat(64), upsert: { styleId: 'ReportBody', type: 'paragraph', name: 'Report Body' } }
  expect(docxNativeOperations([operation])).toEqual([operation])
})

const styles = new Map<string, StyleInfo>([
  ['Normal',{styleId:'Normal',name:'Normal',type:'paragraph',isDefault:true,qFormat:true}],
  ['Body',{styleId:'Body',name:'Report Body',type:'paragraph',qFormat:true}],
  ['Heading1',{styleId:'Heading1',name:'heading 1',type:'paragraph',headingLevel:1,qFormat:true}],
  ['Emphasis',{styleId:'Emphasis',name:'Emphasis',type:'character',qFormat:true,display:{italic:true}}],
])
function setup() {
  const editor = new Editor({ extensions:[...editorExtensions,NativeDocxHistory,NativeStylesPane], editorProps:{handleScrollToSelection:()=>true}, content:{type:'doc',content:[
    {type:'docParagraph',attrs:{docxIndex:0,styleId:'Normal'},content:[{type:'text',text:'alpha',marks:[{type:'bold'},{type:'docTextStyle',attrs:{color:'123456',rawRPr:'<w:rPr><w:lang w:val="en-US"/></w:rPr>'}}]},{type:'text',text:' beta'}]},
    {type:'docParagraph',attrs:{docxIndex:1,styleId:'Body'},content:[{type:'text',text:'adjacent'}]},
  ]}}); editors.push(editor)
  const anchors=[0,1].map(docxIndex=>({docxIndex,blockId:`p${docxIndex}`,expectedObjectSha256:`hash${docxIndex}`,editable:true,fontDialogEditable:true}))
  editor.storage.listNumbering.styles=styles;editor.commands.setTextSelection({from:1,to:11})
  return {editor,anchors,before:editor.getJSON()}
}
it('applies paragraph and heading styles with source majority semantics and keeps the selected range', () => {
  const f=setup(), selection=f.editor.state.selection.toJSON()
  applyStylesPaneAction(f.editor,'Heading1','paragraph',f.anchors,styles)
  const changed=f.editor.getJSON().content![0]!
  expect(changed.type).toBe('docHeading');expect(changed.attrs!.level).toBe(1)
  expect(changed.content![0]!.marks!.some(mark=>mark.type==='bold')).toBe(true)
  expect(f.editor.state.selection.toJSON()).toEqual(selection)
  const normalized=normalizeStylesPane(f.before,f.editor.getJSON(),f.anchors,styles,f.editor.schema)
  expect(normalized.current).toEqual(f.before);expect(normalized.operations).toHaveLength(1)
  const restored=replayDocxOperations(f.before,normalized.operations,f.anchors,undefined,f.editor.schema,styles)
  expect(f.editor.schema.nodeFromJSON(restored).toJSON()).toEqual(f.editor.getJSON())
  f.editor.commands.undo();expect(f.editor.getJSON()).toEqual(f.before)
  f.editor.commands.redo();expect(f.editor.state.doc.firstChild!.type.name).toBe('docHeading')
})
it('merges character styles into original rPr and source toggle removes the whole text-style mark',()=>{
  const f=setup();f.editor.commands.setTextSelection({from:2,to:5})
  applyStylesPaneAction(f.editor,'Emphasis','character',f.anchors,styles)
  const first=f.editor.state.doc.firstChild!;expect(first.child(1).marks.find(mark=>mark.type.name==='docTextStyle')!.attrs).toMatchObject({styleId:'Emphasis',color:'123456',rawRPr:'<w:rPr><w:lang w:val="en-US"/></w:rPr>'})
  applyStylesPaneAction(f.editor,'Emphasis','character',f.anchors,styles,true)
  expect(f.editor.state.doc.firstChild!.child(1).marks.some(mark=>mark.type.name==='docTextStyle')).toBe(false)
  expect(f.editor.state.doc.firstChild!.child(1).marks.some(mark=>mark.type.name==='bold')).toBe(true)
  expect(normalizeStylesPane(f.before,f.editor.getJSON(),f.anchors,styles,f.editor.schema).operations).toHaveLength(1)
})
it('keeps caret character style pending and persists later typed text with the native run plan',()=>{
  const f=setup();f.editor.commands.setTextSelection(3)
  applyStylesPaneAction(f.editor,'Emphasis','character',f.anchors,styles)
  expect(f.editor.getJSON()).toEqual(f.before)
  f.editor.commands.insertContent('Z')
  const result=normalizePlainDocxRuns(f.before,f.editor.getJSON(),f.anchors)
  expect(JSON.stringify(result.operations)).toContain('Emphasis')
  const replayed=replayPlainDocxRuns(f.before,result.operations,f.anchors)
  expect(f.editor.schema.nodeFromJSON(replayed).toJSON()).toEqual(f.editor.getJSON())
})
it('rejects forged styles and unsupported anchors before modifying the document',()=>{
  const f=setup()
  expect(()=>applyStylesPaneAction(f.editor,'Missing','paragraph',f.anchors,styles)).toThrow()
  expect(f.editor.getJSON()).toEqual(f.before)
  expect(()=>applyStylesPaneAction(f.editor,'Body','paragraph',[{...f.anchors[0]!,fontDialogEditable:false}],styles)).toThrow()
  expect(f.editor.getJSON()).toEqual(f.before)
})
it('disables source mutation controls for unsupported or duplicate source anchors',()=>{
  const f=setup()
  expect(typeof stylesPaneSelectionEditable).toBe('function')
  expect(stylesPaneSelectionEditable(f.editor,f.anchors)).toBe(true)
  expect(stylesPaneSelectionEditable(f.editor,[...f.anchors,f.anchors[0]!])).toBe(false)
  expect(stylesPaneSelectionEditable(f.editor,[{...f.anchors[0]!,fontDialogEditable:false}])).toBe(false)
  const doc=f.editor.getJSON();doc.content![0]={type:'docProtected',attrs:{docxIndex:0,blockType:'image'}}
  f.editor.commands.setContent(doc);f.editor.commands.setNodeSelection(0)
  expect(stylesPaneSelectionEditable(f.editor,f.anchors)).toBe(false)
})
it('provides the source pane search, filters, instance selection and a cancelable complete style dialog',()=>{
  const f=setup(), host=document.body.appendChild(document.createElement('div')), root=createRoot(host), notices:string[]=[]
  const release=registerStylesPaneContext(f.editor,{anchors:f.anchors,source:styles,onError:error=>{throw error}})
  const render=()=>flushSync(()=>root.render(<StylesPane editor={f.editor} styles={styles} fs={stylesPaneFormatState(f.editor,styles)} canEdit pending={{}} onUpsert={()=>null} onNotice={message=>notices.push(message)} onClose={()=>{}} />))
  try {
    render();expect(host.querySelectorAll('[data-style-id]')).toHaveLength(4)
    const button=(text:string)=>[...host.querySelectorAll<HTMLButtonElement>('button')].find(item=>item.textContent===text)!
    flushSync(()=>button('新建样式…').click())
    const dialog=host.querySelector('[role=dialog]')!;expect(dialog).not.toBeNull()
    expect(dialog.querySelectorAll('input,select').length).toBeGreaterThanOrEqual(12)
    expect(dialog.querySelector('select[aria-label="西文字体"]')).not.toBeNull()
    flushSync(()=>button('取消').click());expect(host.querySelector('[role=dialog]')).toBeNull();expect(f.editor.getJSON()).toEqual(f.before)
    flushSync(()=>host.querySelector<HTMLElement>('[data-style-id="Body"]')!.dispatchEvent(new MouseEvent('contextmenu',{bubbles:true,cancelable:true})))
    expect(host.textContent).toContain('修改');expect(host.textContent).toContain('更新以匹配所选内容');expect(host.textContent).not.toContain('删除样式')
  } finally { flushSync(()=>root.unmount());release() }
})
