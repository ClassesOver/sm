import {NativeDocxEquations}from './docx-equations'
import {it,expect}from 'vitest'
import {Editor}from '@tiptap/core'
import {editorExtensions}from './vendor/genoffice-docs/apps/docs/src/renderer/editor/extensions'
import {NativeNewRichParagraph}from './docx-new-rich-paragraph'
import {docxOperations,replayDocxOperations,type DocxPmNode}from './docx-operations'
it('compiles and restores a source Enter-created formatted paragraph before first save',()=>{
 const editor=new Editor({extensions:[...editorExtensions,NativeNewRichParagraph,NativeDocxEquations],content:{type:'doc',content:[{type:'docParagraph',attrs:{docxIndex:0,align:'center',nativeEquationTarget:'source-target',nativeEquationOffset:0},content:[{type:'text',text:'old'}]}]}})
 const baseline=editor.getJSON()as DocxPmNode,anchors=[{docxIndex:0,blockId:'original',expectedObjectSha256:'hash',editable:true}]
 editor.commands.setTextSelection(4);editor.commands.keyboardShortcut('Enter');editor.commands.toggleMark('bold');editor.commands.insertContent('new')
 const current=editor.getJSON()as DocxPmNode,ops=docxOperations(baseline,current,anchors,undefined,editor.schema,new Map())
 expect(ops.some(op=>op.kind==='insertRichParagraph')).toBe(true)
 expect(ops.find(op=>op.kind==='insertRichParagraph')?.paragraph).toMatchObject({format:{align:'center'},runs:[{text:'new',bold:true}]})
 expect(replayDocxOperations(baseline,ops,anchors,undefined,editor.schema,new Map())).toEqual(current)
 editor.destroy()
})

it('keeps select-all deletion and plain draft restore free of original native target identities',()=>{
 const editor=new Editor({extensions:[...editorExtensions,NativeNewRichParagraph,NativeDocxEquations],content:{type:'doc',content:[{type:'docParagraph',attrs:{docxIndex:0,nativeEquationTarget:'original-equation-scope',nativeEquationOffset:0},content:[{type:'text',text:'keep'}]}]}})
 const baseline=editor.getJSON()as DocxPmNode,anchors=[{docxIndex:0,blockId:'p',expectedObjectSha256:'hash',editable:true}]
 editor.commands.selectAll();editor.commands.deleteSelection()
 const current=editor.getJSON()as DocxPmNode,ops=docxOperations(baseline,current,anchors,undefined,editor.schema,new Map())
 const restored=replayDocxOperations(baseline,ops,anchors,undefined,editor.schema,new Map())
 expect(restored).toEqual(current)
 expect(restored.content?.[0].attrs?.nativeEquationTarget).toBeNull()
 editor.destroy()
})

it.each(['paragraph','table','deleted'].flatMap(boundary=>[false,true].map(reverse=>({boundary,reverse}))))('keeps mixed insertion order at $boundary boundary, reverse=$reverse',({boundary,reverse})=>{
 const editor=new Editor({extensions:[...editorExtensions,NativeNewRichParagraph]})
 const table=(idx:number)=>({type:'docTable',attrs:{docxIndex:idx},content:[{type:'docTableRow',content:[{type:'docTableCell',content:[{type:'docParagraph'}]}]}]})
 const para=(idx:number|null,text:string,italic=false)=>({type:'docParagraph',attrs:{docxIndex:idx},content:[{type:'text',text,...(italic?{marks:[{type:'italic'}]}:{})}]})
 const original=editor.schema.nodeFromJSON({type:'doc',content:boundary==='paragraph'?[table(0),para(1,'tail')]:boundary==='table'?[table(0),table(1)]:[table(0),para(1,'deleted'),{type:'docProtected',attrs:{docxIndex:2,blockType:'image'}}]}).toJSON()as DocxPmNode
 const rich=para(null,'rich',true),plain=para(null,'plain'),picture={type:'docProtected',attrs:{docxIndex:null,blockType:'image',label:'图片（粘贴）',imageDataUrl:'data:image/png;base64,QUJD',imageWidthPx:3,imageHeightPx:2,genImage:{mime:'image/png',base64:'QUJD',widthPx:3,heightPx:2}}}
 const fresh=boundary==='deleted'?[picture,rich]:[rich,plain];if(reverse)fresh.reverse()
 const current=editor.schema.nodeFromJSON({type:'doc',content:[original.content![0],...fresh,original.content!.at(-1)]}).toJSON()as DocxPmNode
 const bindings=original.content!.map(n=>({docxIndex:Number(n.attrs!.docxIndex),blockId:'block'+n.attrs!.docxIndex,expectedObjectSha256:'hash'+n.attrs!.docxIndex,editable:n.type==='docParagraph',insertParagraphAdjacentEditable:n.type==='docTable'}))
 const ops=docxOperations(original,current,bindings,undefined,editor.schema,new Map())
 expect(editor.schema.nodeFromJSON(replayDocxOperations(original,ops,bindings,undefined,editor.schema,new Map())).toJSON()).toEqual(current)
 editor.destroy()
})
