// @vitest-environment jsdom
import {describe,it,expect} from 'vitest'
import {Editor} from '@tiptap/core'
import {editorExtensions} from './vendor/genoffice-docs/apps/docs/src/renderer/editor/extensions'
import {NativeDocxRichPaste,createDocxRichPaste} from './docx-rich-paste'
const sha='a'.repeat(64)
const original={type:'doc',content:[{type:'docParagraph',attrs:{docxIndex:0},content:[{type:'text',text:'A😀B'}]},{type:'docParagraph',attrs:{docxIndex:1},content:[{type:'text',text:'Tail'}]}]}
describe('structured foreign paste',()=>{
 it('replaces a cross-paragraph UTF16 range, switches modes from original context, replays and undoes',()=>{
  const source=createDocxRichPaste(sha),editor=new Editor({extensions:[...editorExtensions,NativeDocxRichPaste],content:original})
  try{const base=editor.getJSON();editor.commands.setTextSelection({from:4,to:8});const controls=source.controls(editor,()=>[])
   controls.paste({text:'Hello\nWorld',html:'<p style="color:#ff0000"><b>Hello</b></p><h2>World</h2>'},'source')
   expect(editor.state.doc.child(0).textContent).toBe('A😀Hello');expect(editor.state.doc.child(1).textContent).toBe('Worldail');expect(editor.state.doc.child(1).type.name).toBe('docHeading')
   const ops=source.normalize(base,editor.getJSON(),editor.schema).operations;expect(source.replay(base,ops,editor.schema)).toEqual(editor.getJSON());expect(ops[0]).toMatchObject({kind:'pasteRichContent',start:{docxIndex:0,offset:3},end:{docxIndex:1,offset:1}})
   controls.switchMode('text');expect(editor.state.doc.child(1).type.name).toBe('docParagraph');controls.switchMode('source');expect(editor.state.doc.child(1).type.name).toBe('docHeading')
   expect(editor.commands.undo()).toBe(true);expect(editor.commands.redo()).toBe(true)
  }finally{editor.destroy()}
 })
 it('keeps lists and merged rich tables and rejects external native identity injection',()=>{
  const source=createDocxRichPaste(sha),editor=new Editor({extensions:[...editorExtensions,NativeDocxRichPaste],content:original})
  try{const base=editor.getJSON();editor.commands.setTextSelection(1);source.controls(editor,()=>[]).paste({text:'one two cell',html:'<ul><li>one</li><li><i>two</i></li></ul><table><tr><td colspan="2"><b>cell</b></td></tr></table>'},'source');const ops=source.normalize(base,editor.getJSON(),editor.schema).operations;expect(JSON.stringify(ops[0].blocks)).toContain('docListItem');expect(JSON.stringify(ops[0].blocks)).toContain('docTable');const forged=structuredClone(ops);(forged[0].blocks as any[])[0].attrs.docxIndex=7;expect(()=>source.replay(base,forged,editor.schema)).toThrow()}
  finally{editor.destroy()}
 })
})
it('merges from the original caret, keeps inline images and rejects remote images atomically',()=>{
 const source=createDocxRichPaste(sha),editor=new Editor({extensions:[...editorExtensions,NativeDocxRichPaste],content:{type:'doc',content:[{type:'docParagraph',attrs:{docxIndex:0,align:'right'},content:[{type:'text',text:'Target',marks:[{type:'docTextStyle',attrs:{font:'Arial',color:'0000FF'}}]}]}]}})
 try{const base=editor.getJSON();editor.commands.setTextSelection(3);const controls=source.controls(editor,()=>[])
  expect(()=>controls.paste({html:'<p><img src="https://invalid.example/a.png"></p>'},'source')).toThrow('未访问外网');expect(editor.getJSON()).toEqual(base);expect(controls.mode()).toBe(null)
  controls.paste({text:'red',html:'<p style="color:#ff0000"><b>red</b></p>'},'source');controls.switchMode('merge');const op=source.normalize(base,editor.getJSON(),editor.schema).operations[0] as any;expect(op.blocks[0].attrs.align).toBe('right');expect(op.blocks[0].content[0].marks).toContainEqual({type:'docTextStyle',attrs:{font:'Arial',color:'0000FF'}});controls.switchMode('source');expect(JSON.stringify(source.normalize(base,editor.getJSON(),editor.schema).operations)).toContain('FF0000')
 }finally{editor.destroy()}
})
it('represents data images and nested list levels without carrying native identities',()=>{
 const source=createDocxRichPaste(sha),editor=new Editor({extensions:[...editorExtensions,NativeDocxRichPaste],content:original})
 try{const base=editor.getJSON();editor.commands.setTextSelection(1);source.controls(editor,()=>[]).paste({html:'<ol><li>outer<ol><li>inner</li></ol></li></ol><p><img width="1" height="1" src="data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aD1sAAAAASUVORK5CYII="></p>'},'source');const op=source.normalize(base,editor.getJSON(),editor.schema).operations[0] as any;expect(op.blocks.filter((n:any)=>n.type==='docListItem').map((n:any)=>n.attrs.ilvl)).toEqual([0,1]);expect(JSON.stringify(op.blocks)).toContain('data:image/png;base64,');expect(JSON.stringify(op.blocks)).not.toContain('docxIndex')
 }finally{editor.destroy()}
})
