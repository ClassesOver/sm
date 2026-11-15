import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { Editor } from '@tiptap/core'
import { editorExtensions } from './vendor/genoffice-docs/apps/docs/src/renderer/editor/extensions'
import { NativeNewRichParagraph } from './docx-new-rich-paragraph'
import { NativeDocxEquations, createDocxEquations } from './docx-equations'
import { NativeDocxSplit } from './docx-native-split'
import { docxOperations, replayDocxOperations } from './docx-operations'
const editors:Editor[]=[]
beforeEach(()=>{vi.spyOn(HTMLCanvasElement.prototype,'getContext').mockReturnValue(null)})
afterEach(()=>{editors.splice(0).forEach(editor=>editor.destroy());vi.restoreAllMocks()})
const anchors=[{docxIndex:0,blockId:'p0',expectedObjectSha256:'hash0',editable:true}]
function fixture(type='docParagraph',safe=true){
 const equations=createDocxEquations({sourceId:'a'.repeat(64),targets:[{targetId:'body-0',blockIndex:0,paragraphOrdinal:0,container:'body',text:'abcd',expectedParagraphSha256:'b'.repeat(64),formulas:[]}]})
 const attrs={docxIndex:0,align:'center',spaceAfter:120,...(type==='docHeading'?{level:1,styleId:'Heading1'}:{}),...(type==='docListItem'?{kind:'ordered',numId:'1',ilvl:0}:{})}
 const editor=new Editor({extensions:[...editorExtensions,NativeNewRichParagraph,NativeDocxEquations,...(safe?[NativeDocxSplit]:[])],editorProps:{handleScrollToSelection:()=>true},content:equations.annotate({type:'doc',content:[{type,attrs,content:[{type:'text',text:'abcd',marks:[{type:'bold'},{type:'docTextStyle',attrs:{color:'123456'}}]}]}]})})
 editors.push(editor);return editor
}
function enter(editor:Editor){let handled=false;editor.view.someProp('handleKeyDown',handler=>{handled=!!handler(editor.view,new KeyboardEvent('keydown',{key:'Enter'}));return handled});return handled}
it.each([1,3,5])('paragraph split at %i retains one source identity, clears new provenance and compiles/replays atomically',position=>{
 const editor=fixture(),baseline=editor.getJSON();editor.commands.setTextSelection(position)
 expect(editor.commands.splitBlock()).toBe(true);expect(editor.state.doc.childCount).toBe(2)
 const retained=position===1?1:0,fresh=1-retained
 expect(editor.state.doc.child(retained).attrs).toMatchObject({docxIndex:0,nativeEquationTarget:'body-0',nativeEquationOffset:0})
 expect(editor.state.doc.child(fresh).attrs).toMatchObject({docxIndex:null,nativeEquationTarget:null,nativeEquationId:null,nativeEquationOffset:null,align:'center',spaceAfter:120})
 const operations=docxOperations(baseline,editor.getJSON(),anchors,undefined,editor.schema)
 const replay=replayDocxOperations(baseline,operations,anchors,undefined,editor.schema)
 expect(replay).toEqual(editor.getJSON())
 editor.commands.undo();expect(editor.getJSON()).toEqual(baseline);editor.commands.redo();expect(editor.state.doc.childCount).toBe(2)
})
it('middle split retains stored marks for immediately typed text',()=>{
 const editor=fixture();editor.commands.setTextSelection(3);expect(editor.commands.splitBlock()).toBe(true);editor.commands.insertContent('X')
 expect(editor.state.doc.child(1).firstChild!.marks.map(mark=>mark.type.name)).toEqual(['bold','docTextStyle'])
 expect(editor.state.doc.child(1).firstChild!.marks.find(mark=>mark.type.name==='docTextStyle')!.attrs.color).toBe('123456')
})
it.each([1,3,5])('actual source Enter at list position %i keeps source-left policy and list kind/level',position=>{
 const editor=fixture('docListItem'),baseline=editor.getJSON();editor.commands.setTextSelection(position);expect(enter(editor)).toBe(true)
 expect(editor.state.doc.content.content.map(node=>node.type.name)).toEqual(position===1?['docParagraph','docListItem']:['docListItem','docListItem'])
 expect(editor.state.doc.child(0).attrs).toMatchObject({docxIndex:0,nativeEquationTarget:'body-0'})
 if(position!==1)expect(editor.state.doc.child(0).attrs).toMatchObject({kind:'ordered',numId:'1',ilvl:0})
 expect(editor.state.doc.child(1).attrs).toMatchObject({docxIndex:null,nativeEquationTarget:null,nativeEquationOffset:null,kind:'ordered',numId:'1',ilvl:0,align:'center'})
 editor.commands.undo();expect(editor.getJSON()).toEqual(baseline)
})
it.each([1,3,5])('actual source Enter at heading position %i retains native heading behavior',position=>{
 const editor=fixture('docHeading');editor.commands.setTextSelection(position);expect(enter(editor)).toBe(true)
 expect(editor.state.doc.content.content.map(node=>node.type.name)).toEqual(position===1?['docParagraph','docHeading']:position===5?['docHeading','docParagraph']:['docHeading','docHeading'])
 const retained=position===1?1:0,fresh=1-retained
 expect(editor.state.doc.child(retained).attrs).toMatchObject({docxIndex:0,nativeEquationTarget:'body-0',styleId:'Heading1'})
 expect(editor.state.doc.child(fresh).attrs.docxIndex).toBeNull();expect(editor.state.doc.child(fresh).attrs.nativeEquationTarget).toBeNull()
 if(position===5)expect(editor.state.doc.child(fresh).attrs.styleId).toBeNull()
})
it('end split preserves explicit stored marks and core keepMarks false semantics',()=>{
 const editor=fixture();editor.commands.setTextSelection(5);editor.commands.setMark('italic')
 expect(editor.commands.splitBlock()).toBe(true)
 expect(editor.state.storedMarks?.map(mark=>mark.type.name)??[]).toContain('italic')
 editor.commands.insertContent('typed');expect(editor.state.doc.child(1).firstChild!.marks.map(mark=>mark.type.name)).toContain('italic')
 editor.commands.setMark('strike');expect(editor.commands.splitBlock({keepMarks:false})).toBe(true)
 const core=fixture('docParagraph',false);core.commands.setTextSelection(5);core.commands.setMark('italic');core.commands.splitBlock();core.commands.insertContent('typed');core.commands.setMark('strike');core.commands.splitBlock({keepMarks:false})
 expect(editor.state.storedMarks?.map(mark=>mark.toJSON())??null).toEqual(core.state.storedMarks?.map(mark=>mark.toJSON())??null)
})
it('dry-run split leaves source state unchanged',()=>{
 const editor=fixture(),baseline=editor.getJSON();editor.commands.setTextSelection(3)
 expect(editor.can().splitBlock()).toBe(true);expect(editor.getJSON()).toEqual(baseline)
})
