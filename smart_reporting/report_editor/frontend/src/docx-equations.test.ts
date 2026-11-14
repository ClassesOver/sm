// @vitest-environment jsdom
import {describe,it,expect} from 'vitest'
import {Editor} from '@tiptap/core'
import {editorExtensions} from './vendor/genoffice-docs/apps/docs/src/renderer/editor/extensions'
import {NativeDocxEquations,createDocxEquations} from './docx-equations'
const model={sourceId:'a'.repeat(64),targets:[{targetId:'body',blockIndex:0,paragraphOrdinal:0,container:'body' as const,text:'A😀B',expectedParagraphSha256:'b'.repeat(64),formulas:[]},{targetId:'cell',blockIndex:1,paragraphOrdinal:0,container:'table' as const,text:'Cell',expectedParagraphSha256:'c'.repeat(64),formulas:[]}]}
describe('native equation projection',()=>{
 it('projects body display at exact UTF16 offset, re-edits, deletes, restores draft and history',()=>{
  const source=createDocxEquations(model),doc={type:'doc',content:[{type:'docParagraph',attrs:{docxIndex:0},content:[{type:'text',text:'A😀B'}]}]},editor=new Editor({extensions:[...editorExtensions,NativeDocxEquations],content:source.annotate(doc)})
  try{const baseline=editor.getJSON();editor.commands.setTextSelection(4);const controls=source.controls(editor,()=>[]);controls.insert('x^2',false)
   expect(editor.state.doc.childCount).toBe(3);expect(editor.state.doc.child(0).textContent).toBe('A😀');expect(editor.state.doc.child(2).textContent).toBe('B')
   const collected=source.normalize(baseline,editor.getJSON(),editor.schema);expect(collected.operations).toHaveLength(1);expect(JSON.stringify(collected.operations)).not.toMatch(/omml|genXml/)
   expect(source.replay(baseline,collected.operations,editor.schema)).toEqual(editor.getJSON())
   const pos=editor.state.doc.child(0).nodeSize;controls.update(pos,'\\frac{y}{2}');expect(editor.state.doc.nodeAt(pos)?.attrs.formulaDisplay.latex).toBe('\\frac{y}{2}')
   controls.delete(pos);expect(editor.state.doc.textContent).toBe('A😀B');expect(editor.commands.undo()).toBe(true);expect(editor.state.doc.childCount).toBe(3);expect(editor.commands.redo()).toBe(true)
  }finally{editor.destroy()}
 })
 it('rejects forged current projection and unsupported container insertions',()=>{
  const source=createDocxEquations(model),editor=new Editor({extensions:[...editorExtensions,NativeDocxEquations],content:source.annotate({type:'doc',content:[{type:'docParagraph',attrs:{docxIndex:0},content:[{type:'text',text:'A😀B'}]}]})})
  try{const base=editor.getJSON();editor.commands.setTextSelection(2);source.controls(editor,()=>[]).insert('x',true);const current=editor.getJSON() as import('./docx-operations').DocxPmNode;current.content![0].content![0].text='forged';expect(()=>source.normalize(base,current,editor.schema)).toThrow(/公式/)}finally{editor.destroy()}
 })
 it('rejects a nested editor context instead of using the stale body selection',()=>{
  const source=createDocxEquations(model),editor=new Editor({extensions:[...editorExtensions,NativeDocxEquations],content:source.annotate({type:'doc',content:[{type:'docParagraph',attrs:{docxIndex:0},content:[{type:'text',text:'A😀B'}]}]})})
  try{const base=editor.getJSON();editor.commands.setTextSelection(2);const controls=source.controls(editor,()=>[],()=>'嵌套表格不接受公式');expect(controls.reason()).toContain('嵌套表格');expect(()=>controls.insert('x',true)).toThrow(/嵌套表格/);expect(editor.getJSON()).toEqual(base)}finally{editor.destroy()}
 })
 it('keeps table display math inside the original cell and replays it exactly',()=>{
  const source=createDocxEquations({sourceId:model.sourceId,targets:[model.targets[1]]}),editor=new Editor({extensions:[...editorExtensions,NativeDocxEquations],content:source.annotate({type:'doc',content:[{type:'docTable',attrs:{docxIndex:1},content:[{type:'docTableRow',content:[{type:'docTableCell',content:[{type:'docParagraph',content:[{type:'text',text:'Cell'}]}]}]}]}]})})
  try{const base=editor.getJSON();let pos=0;editor.state.doc.descendants((node,at)=>{if(node.type.name==='docParagraph')pos=at+3});editor.commands.setTextSelection(pos);source.controls(editor,()=>[]).insert('\\sqrt{x}',false);expect(editor.state.doc.childCount).toBe(1);const paragraph=editor.state.doc.child(0).child(0).child(0).child(0);expect(paragraph.textContent).toBe('Cell');expect(paragraph.child(1).type.name).toBe('docInlineMath');expect(paragraph.child(1).attrs.display).toBe(true);const ops=source.normalize(base,editor.getJSON(),editor.schema).operations;expect(ops[0].steps).toEqual([{targetId:'cell',action:'insert',offset:2,display:true,latex:'\\sqrt{x}'}])}finally{editor.destroy()}
 })
})
