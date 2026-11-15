import {afterEach,expect,it} from 'vitest'
import {Editor} from '@tiptap/core'
import {editorExtensions} from './vendor/genoffice-docs/apps/docs/src/renderer/editor/extensions'
import * as rich from './docx-new-rich-paragraph'
const api=rich as any
const editors:Editor[]=[]
afterEach(()=>editors.splice(0).forEach(e=>e.destroy()))
function fixture(){const e=new Editor({extensions:[...editorExtensions,...(api.NativeNewRichParagraph?[api.NativeNewRichParagraph]:[])],editorProps:{handleScrollToSelection:()=>true},content:{type:'doc',content:[{type:'docParagraph',attrs:{docxIndex:0},content:[{type:'text',text:'原文'}]}]}});editors.push(e);return e}
const anchors=[{docxIndex:0,blockId:'p0',expectedObjectSha256:'hash0',editable:true}]
it('compiles, replays and undoes an unsaved rich paragraph in one history step',()=>{
 expect(typeof api.docxNewRichParagraphOperation).toBe('function')
 const e=fixture(),before=e.getJSON(),fresh={type:'docParagraph',attrs:{align:'center',spaceAfter:240},content:[{type:'text',text:'新段',marks:[{type:'bold'},{type:'docTextStyle',attrs:{fontAscii:'Calibri',eastAsiaFont:'宋体',sizeHalfPoints:28}}]},{type:'hardBreak'},{type:'text',text:'下一行',marks:[{type:'italic'}]}]}
 e.commands.insertContentAt(e.state.doc.content.size,fresh)
 const draft=e.getJSON(),operation=api.docxNewRichParagraphOperation(before,draft,1,anchors,e.schema)
 expect(operation).toMatchObject({kind:'insertRichParagraph',blockId:'p0',position:'after',paragraph:{format:{align:'center',spaceAfter:240}}})
 const restored=structuredClone(before);api.replayDocxNewRichParagraph(restored,operation,anchors,e.schema,new Map())
 expect(restored).toEqual(draft)
 e.commands.undo();expect(e.getJSON()).toEqual(before)
 e.commands.redo();expect(e.getJSON()).toEqual(draft)
})
it('Enter preserves simple supported inherited marks and paragraph alignment without a save barrier',()=>{
 expect(typeof api.docxNewRichParagraphOperation).toBe('function')
 const e=fixture();e.commands.setContent({type:'doc',content:[{type:'docParagraph',attrs:{docxIndex:0,align:'right'},content:[{type:'text',text:'甲乙',marks:[{type:'bold'},{type:'docTextStyle',attrs:{color:'123456',sizeHalfPoints:30}}]}]}]})
 const before=e.getJSON();e.commands.setTextSelection(3);e.commands.splitBlock();e.commands.insertContent('继承')
 const draft=e.getJSON(),operation=api.docxNewRichParagraphOperation(before,draft,1,anchors,e.schema)
 expect(operation.paragraph).toMatchObject({format:{align:'right'},runs:[{text:'继承',bold:true,color:'123456',sizeHalfPoints:30}]})
 const replay=structuredClone(before);api.replayDocxNewRichParagraph(replay,operation,anchors,e.schema,new Map());expect(replay).toEqual(draft)
})
it('rejects raw XML, forged source identity, inline atoms and unknown rich attributes',()=>{
 expect(typeof api.docxNewRichParagraphOperation).toBe('function')
 const e=fixture(),before=e.getJSON(),fresh=e.schema.nodeFromJSON({type:'docParagraph',content:[{type:'text',text:'x'}]}).toJSON()
 for(const change of [{attrs:{...fresh.attrs,rawPPr:'<w:pPr/>'}},{content:[{type:'text',text:'x',marks:[{type:'docTextStyle',attrs:{rawRPr:'<w:rPr/>'}}]}]},{content:[{type:'docNoteRef',attrs:{id:'1',kind:'footnote'}}]}]){
  const draft={...before,content:[before.content![0]!,{...fresh,...change}]};expect(()=>api.docxNewRichParagraphOperation(before,draft,1,anchors,e.schema)).toThrow()
 }
 const draft={...before,content:[before.content![0]!,fresh]},operation=api.docxNewRichParagraphOperation(before,draft,1,anchors,e.schema)
 expect(()=>api.replayDocxNewRichParagraph(structuredClone(before),{...operation,expectedObjectSha256:'fake'},anchors,e.schema,new Map())).toThrow()
})
it('preserves insertion order with a shared replay counter and binds only trusted existing style/list definitions',()=>{
 expect(typeof api.docxNewRichParagraphOperation).toBe('function')
 const e=fixture(),before=e.getJSON(),bindings={styles:new Map([['Body',{type:'paragraph'}]]),numbering:new Map([['4',{levels:{0:{numFmt:'decimal'}}}]])}
 const fresh=e.schema.nodeFromJSON({type:'docListItem',attrs:{numId:'4',kind:'ordered',ilvl:0,styleId:'Body'},content:[{type:'text',text:'条目'}]}).toJSON()
 const draft={...before,content:[before.content![0]!,fresh,fresh]},a=api.docxNewRichParagraphOperation(before,draft,1,anchors,e.schema,bindings),b=api.docxNewRichParagraphOperation(before,draft,2,anchors,e.schema,bindings),restored=structuredClone(before),counter=new Map()
 api.replayDocxNewRichParagraph(restored,a,anchors,e.schema,counter,bindings);api.replayDocxNewRichParagraph(restored,b,anchors,e.schema,counter,bindings);expect(restored).toEqual(draft)
 expect(()=>api.docxNewRichParagraphOperation(before,draft,1,anchors,e.schema)).toThrow()
})

it('uses explicit adjacent insertion capability for production tables whose body-editable flag is false',()=>{
 const e=fixture(),before={type:'doc',content:[{type:'docTable',attrs:{docxIndex:0},content:[{type:'docTableRow',content:[{type:'docTableCell',content:[{type:'docParagraph'}]}]}]}]}
 const source=e.schema.nodeFromJSON(before).toJSON(),fresh=e.schema.nodeFromJSON({type:'docParagraph',content:[{type:'text',text:'表后',marks:[{type:'bold'}]}]}).toJSON(),tableAnchors=[{docxIndex:0,blockId:'table',expectedObjectSha256:'hash',editable:false,insertParagraphAdjacentEditable:true}]
 const draft={...source,content:[source.content![0]!,fresh]},operation=api.docxNewRichParagraphOperation(source,draft,1,tableAnchors,e.schema)
 expect(operation).toMatchObject({kind:'insertRichParagraph',blockId:'table',position:'after'})
 const restored=structuredClone(source);api.replayDocxNewRichParagraph(restored,operation,tableAnchors,e.schema,new Map());expect(restored).toEqual(draft)
 expect(()=>api.docxNewRichParagraphOperation(source,draft,1,[{...tableAnchors[0],insertParagraphAdjacentEditable:false}],e.schema)).toThrow()
})
it('Enter inherits consistent automatic spacing raw twips and replays the real PM paragraph',()=>{
 const e=fixture();e.commands.setContent({type:'doc',content:[{type:'docParagraph',attrs:{docxIndex:0,lineSpacing:1.15,lineRule:'auto',lineRawTwips:276},content:[{type:'text',text:'原段'}]}]})
 const before=e.getJSON();e.commands.setTextSelection(3);e.commands.splitBlock();e.commands.insertContent('继承行距')
 const draft=e.getJSON(),operation=api.docxNewRichParagraphOperation(before,draft,1,anchors,e.schema)
 expect(operation.paragraph.format).toMatchObject({lineSpacing:1.15,lineRule:'auto',lineRawTwips:276})
 const replay=structuredClone(before);api.replayDocxNewRichParagraph(replay,operation,anchors,e.schema,new Map());expect(replay).toEqual(draft)
 const contradictory=structuredClone(draft);contradictory.content![1]!.attrs!.lineSpacing=2
 expect(()=>api.docxNewRichParagraphOperation(before,contradictory,1,anchors,e.schema)).toThrow()
})
it('source-bound imported italic survives middle insertion compilation and byte-exact metadata replay',()=>{
 const e=fixture();e.commands.setContent({type:'doc',content:[{type:'docParagraph',attrs:{docxIndex:0},content:[{type:'text',text:'LEFT MIDDLE RIGHT',marks:[{type:'italic'},{type:'docTextStyle',attrs:{rawRPr:'<w:rPr><w:i/></w:rPr>'}}]}]}]})
 const before=e.getJSON();e.commands.setTextSelection(6);e.chain().splitBlock().command(({tr})=>{const p=tr.selection.$from;tr.setNodeMarkup(p.before(1),undefined,{...p.parent.attrs,docxIndex:null});return true}).run();e.commands.insertContent('INSERT ')
 const draft=e.getJSON(),operation=api.docxNewRichParagraphOperation(before,draft,1,anchors,e.schema)
 expect(operation.paragraph.runs[0]).toMatchObject({italic:true,sourceFormat:{blockId:'p0',expectedObjectSha256:'hash0',from:0}})
 expect(JSON.stringify(operation)).not.toContain('rawRPr')
 const replay=structuredClone(before);replay.content![0]=draft.content![0]!;api.replayDocxNewRichParagraph(replay,operation,anchors,e.schema,new Map());expect(replay).toEqual(draft)
 const forged=structuredClone(draft);forged.content![1]!.content![0]!.marks!.find(m=>m.type==='docTextStyle')!.attrs!.rawRPr='<w:rPr><w:i/><w:unknown/></w:rPr>'
 expect(()=>api.docxNewRichParagraphOperation(before,forged,1,anchors,e.schema)).toThrow()
})
