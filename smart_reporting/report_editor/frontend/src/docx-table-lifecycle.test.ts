import {afterEach,expect,it} from 'vitest'
import {Editor,Extension,Node} from '@tiptap/core'
import {UndoRedo} from '@tiptap/extensions'
import {CellSelection,TableMap} from '@tiptap/pm/tables'
import {NodeSelection} from '@tiptap/pm/state'
import type {DocxPmNode} from './docx-operations'
import {NativeDocxHistory} from './docx-native-history'
import {createDocxTableLifecycleControls,normalizeDocxTableLifecycle,replayDocxTableLifecycle,assertDocxTableLifecycleBatch} from './docx-table-lifecycle'
const attrs=(v:Record<string,unknown>)=>Object.fromEntries(Object.entries(v).map(([key,value])=>[key,{default:value}]))
const Doc=Node.create({name:'doc',topNode:true,content:'block+'}),Text=Node.create({name:'text',group:'inline'})
const Paragraph=Node.create({name:'docParagraph',group:'block',content:'text*',addAttributes:()=>attrs({docxIndex:null,align:null}),renderHTML:()=>['p',0]})
const Table=Node.create({name:'docTable',group:'block',content:'docTableRow+',addAttributes:()=>attrs({docxIndex:null,sdtShell:null,blockRevision:null,originalStructure:null,originalFormatting:null,tblCaption:null,tblDescription:null,tblAltEdited:false,styleId:'Grid',colWidthsPct:[40,60]}),renderHTML:()=>['table',['tbody',0]]})
const Row=Node.create({name:'docTableRow',content:'docTableCell+',addAttributes:()=>attrs({rawTrPr:'row'}),renderHTML:()=>['tr',0]})
const Cell=Node.create({name:'docTableCell',content:'docParagraph+',addAttributes:()=>attrs({colspan:1,rowspan:1,colwidth:null,rawTcPr:'cell'}),renderHTML:()=>['td',0]})
const Roles=Extension.create({name:'roles',extendNodeSchema:e=>({tableRole:({docTable:'table',docTableRow:'row',docTableCell:'cell'} as Record<string,string>)[e.name]})})
const editors:Editor[]=[];afterEach(()=>editors.splice(0).forEach(e=>e.destroy()))
function setup(only=false){
 const table={type:'docTable',attrs:{docxIndex:1,originalStructure:'identity',originalFormatting:'format',tblCaption:'caption',tblDescription:'description'},content:[0,1,2].map(r=>({type:'docTableRow',content:[0,1].map(c=>({type:'docTableCell',content:[{type:'docParagraph',attrs:{align:'right'},content:[{type:'text',text:`${r}:${c}`}]}]}))}))}
 const editor=new Editor({extensions:[Doc,Text,Paragraph,Table,Row,Cell,Roles,NativeDocxHistory,UndoRedo],content:{type:'doc',content:only?[table]:[{type:'docParagraph',attrs:{docxIndex:0},content:[{type:'text',text:'body'}]},table]},editorProps:{handleScrollToSelection:()=>true}});editors.push(editor)
 const baseline=editor.getJSON() as DocxPmNode,anchors=[{docxIndex:1,blockId:'table-1',expectedObjectSha256:'a'.repeat(64),tableLifecycleEditable:true}],errors:string[]=[]
 const controls=createDocxTableLifecycleControls({editor,baseline,anchors,reason:()=>null,onError:e=>errors.push(String(e))})
 const pos=()=>only?0:editor.state.doc.firstChild!.nodeSize
 const select=(row=1)=>{const t=editor.state.doc.nodeAt(pos())!,map=TableMap.get(t);editor.view.dispatch(editor.state.tr.setSelection(CellSelection.create(editor.state.doc,pos()+1+map.map[row*map.width])))}
 return{editor,baseline,anchors,controls,errors,pos,select}
}
it('split uses pinned source projection, preserves rows and formatting, resets lower identity and alt, and undo redo atomically',()=>{
 const f=setup();f.select();expect(f.controls.run('table-split-table'),f.errors.join(';')).toBe(true)
 const current=f.editor.getJSON() as DocxPmNode,parts=current.content!;expect(parts.map(n=>n.type)).toEqual(['docParagraph','docTable','docParagraph','docTable'])
 expect(parts[1].content).toEqual(f.baseline.content![1].content!.slice(0,1));expect(parts[3].content).toEqual(f.baseline.content![1].content!.slice(1))
 expect(parts[3].attrs).toMatchObject({docxIndex:null,originalStructure:null,originalFormatting:null,tblCaption:null,tblDescription:null,tblAltEdited:false,styleId:'Grid',colWidthsPct:[40,60]})
 expect(parts[2]).toEqual(f.editor.schema.nodes.docParagraph.create().toJSON())
 const normalized=normalizeDocxTableLifecycle(f.baseline,current,f.anchors,f.editor.schema);expect(normalized.current).toEqual(f.baseline);expect(normalized.operations).toEqual([{kind:'splitTable',blockId:'table-1',expectedObjectSha256:'a'.repeat(64),row:1}]);expect(replayDocxTableLifecycle(f.baseline,normalized.operations,f.anchors,f.editor.schema)).toEqual(current)
 f.editor.commands.undo();expect(f.editor.getJSON()).toEqual(f.baseline);f.editor.commands.redo();expect(f.editor.getJSON()).toEqual(current)
})
it.each([false,true])('delete final/only table uses source deletion and schema blank paragraph (only=%s)',only=>{
 const f=setup(only);f.editor.view.dispatch(f.editor.state.tr.setSelection(NodeSelection.create(f.editor.state.doc,f.pos())));expect(f.controls.run('table-delete'),f.errors.join(';')).toBe(true)
 expect(f.editor.getJSON().content).toEqual(only?[f.editor.schema.nodes.docParagraph.create().toJSON()]:[f.baseline.content![0]])
 expect(normalizeDocxTableLifecycle(f.baseline,f.editor.getJSON(),f.anchors,f.editor.schema).current).toEqual(f.baseline)
 f.editor.commands.undo();expect(f.editor.getJSON()).toEqual(f.baseline);f.editor.commands.redo();expect(f.editor.state.doc.childCount).toBe(1)
})
it('rejects first-row split, readonly, composing, locked source and unsaved drift',()=>{
 const f=setup();f.select(0);expect(f.controls.reason('table-split-table')).toMatch(/首行|第一行/)
 f.select();f.editor.setEditable(false);expect(f.controls.run('table-delete')).toBe(false);f.editor.setEditable(true)
 Object.defineProperty(f.editor.view,'composing',{value:true,configurable:true});expect(f.controls.run('table-delete')).toBe(false);Object.defineProperty(f.editor.view,'composing',{value:false,configurable:true})
 f.anchors[0].tableLifecycleEditable=false;expect(f.controls.run('table-delete')).toBe(false);f.anchors[0].tableLifecycleEditable=true
 f.editor.view.dispatch(f.editor.state.tr.insertText('extra',1));expect(f.controls.run('table-delete')).toBe(false)
})
it('validates entire projection and rejects forged SHA, IDs, extra edits, mixed intents and operation order',()=>{
 const f=setup();f.select();f.controls.run('table-split-table');const current=f.editor.getJSON() as DocxPmNode,op=(current.attrs!.nativeDocxOperations as any[])[0]
 for(const forged of [{...op,expectedObjectSha256:'b'.repeat(64)},{...op,blockId:'foreign'},{...op,row:0},{...op,row:3},{...op,extra:true}])expect(()=>replayDocxTableLifecycle(f.baseline,[forged],f.anchors,f.editor.schema)).toThrow()
 for(const operations of [[op,op],[op,{kind:'setPageColor'}],[{kind:'setPageColor'},op]])expect(()=>assertDocxTableLifecycleBatch(operations)).toThrow()
 const extra=structuredClone(current);extra.content![0].content![0].text='forged';expect(()=>normalizeDocxTableLifecycle(f.baseline,extra,f.anchors,f.editor.schema)).toThrow()
 const ids=structuredClone(current);ids.content![3].attrs!.docxIndex=1;expect(()=>normalizeDocxTableLifecycle(f.baseline,ids,f.anchors,f.editor.schema)).toThrow()
 expect(f.controls.run('table-delete')).toBe(false)
})
it('ordinary documents normalize without taking over other operation journals',()=>{
 const f=setup(),current=structuredClone(f.baseline);current.attrs!.nativeDocxOperations=[{kind:'setPageColor',color:'red'}];expect(normalizeDocxTableLifecycle(f.baseline,current,f.anchors,f.editor.schema)).toEqual({current,operations:[]})
})

it('source SHA changes, external lock and tracking mode refuse without history changes',()=>{
 const f=setup();f.select();f.anchors[0].expectedObjectSha256='b'.repeat(64);expect(f.controls.run('table-delete')).toBe(false);expect(f.editor.getJSON()).toEqual(f.baseline)
 const g=setup();g.select();g.editor.storage.trackChanges={enabled:true,author:"tester",trackMoves:false,trackFormatting:false};expect(g.controls.run('table-delete')).toBe(false);expect(g.controls.reason('table-delete')).toMatch(/修订/)
 const h=setup();h.select();const locked=createDocxTableLifecycleControls({editor:h.editor,baseline:h.baseline,anchors:h.anchors,reason:()=> '文档保护',onError:()=>{}});expect(locked.run('table-delete')).toBe(false);expect(locked.reason('table-delete')).toBe('文档保护');expect(h.editor.can().undo()).toBe(false)
})
it('delete from a cell selection and unknown journal records reject atomically',()=>{
 const f=setup();f.select(2);expect(f.controls.run('table-delete')).toBe(true);f.editor.commands.undo();expect(f.editor.getJSON()).toEqual(f.baseline)
 const g=setup();g.select();g.controls.run('table-split-table');const current=g.editor.getJSON() as DocxPmNode;(current.attrs!.nativeDocxOperations as unknown[]).push({kind:'unknown'})
 expect(()=>normalizeDocxTableLifecycle(g.baseline,current,g.anchors,g.editor.schema)).toThrow()
 const invalid=structuredClone(g.baseline);invalid.content!.push(structuredClone(invalid.content![1]));const op={kind:'deleteTable',blockId:'table-1',expectedObjectSha256:'a'.repeat(64)}
 expect(()=>replayDocxTableLifecycle(invalid,[op],g.anchors,g.editor.schema)).toThrow()
})
function shortcut(f:ReturnType<typeof setup>,target:HTMLElement=f.editor.view.dom,init:KeyboardEventInit={},prepare?:(e:KeyboardEvent)=>void){
 const event=new KeyboardEvent('keydown',{key:'Enter',ctrlKey:true,shiftKey:true,bubbles:true,cancelable:true,...init});prepare?.(event)
 let handled:boolean|undefined;target.addEventListener('keydown',e=>{handled=f.controls.handleKey(e)},{once:true,capture:true});target.dispatchEvent(event)
 return{event,handled}
}
it.each(['ctrl','meta'])('owned %s Shift Enter splits a selected table through the isolated source journal',modifier=>{
 const f=setup();f.select();const {event,handled}=shortcut(f,f.editor.view.dom.querySelector<HTMLElement>('td p')!,{ctrlKey:modifier==='ctrl',metaKey:modifier==='meta'})
 expect(handled).toBe(true);expect(event.defaultPrevented).toBe(true);expect(f.editor.state.doc.childCount).toBe(4)
 expect((f.editor.getJSON().attrs!.nativeDocxOperations as any[])[0]).toMatchObject({kind:'splitTable',row:1});f.editor.commands.undo();expect(f.editor.getJSON()).toEqual(f.baseline)
})
it('shortcut ignores a paragraph selection and targets outside this editor or inside a nested editor',()=>{
 const f=setup();f.editor.commands.setTextSelection(1);const paragraph=shortcut(f);expect(paragraph.handled).toBe(false);expect(paragraph.event.defaultPrevented).toBe(false)
 f.select();const outside=document.createElement('div'),input=document.createElement('input'),dialog=document.createElement('div'),nested=document.createElement('div'),nestedText=document.createElement('p')
 dialog.setAttribute('role','dialog');dialog.append(input);nested.className='ProseMirror';nested.append(nestedText);f.editor.view.dom.append(dialog,nested)
 const g=setup();for(const target of [outside,input,nestedText,g.editor.view.dom]){const {event,handled}=shortcut(f,target);expect(handled).toBe(false);expect(event.defaultPrevented).toBe(false)}
 expect(f.editor.getJSON()).toEqual(f.baseline)
})
it('shortcut ignores consumed or composing events and unsupported modifiers without stealing input',()=>{
 const f=setup();f.select()
 for(const [init,prepare] of [[{isComposing:true},undefined],[{},(e:KeyboardEvent)=>Object.defineProperty(e,'keyCode',{value:229})],[{},(e:KeyboardEvent)=>e.preventDefault()],[{altKey:true},undefined],[{shiftKey:false},undefined],[{ctrlKey:false},undefined]] as [KeyboardEventInit,((e:KeyboardEvent)=>void)?][]){
  const {event,handled}=shortcut(f,f.editor.view.dom,init,prepare);expect(handled).toBe(false);expect(event.defaultPrevented).toBe(!!prepare&&event.keyCode!==229)
 }
 Object.defineProperty(f.editor.view,'composing',{value:true,configurable:true});const composing=shortcut(f);expect(composing.handled).toBe(false);expect(composing.event.defaultPrevented).toBe(false)
 expect(f.editor.getJSON()).toEqual(f.baseline)
})
it('owned shortcut is consumed on the first row and in readonly mode without source fallback',()=>{
 const f=setup();f.select(0);const first=shortcut(f);expect(first.handled).toBe(true);expect(first.event.defaultPrevented).toBe(true);expect(f.errors.at(-1)).toMatch(/第一行/);expect(f.editor.getJSON()).toEqual(f.baseline)
 f.select();f.editor.setEditable(false);const readonly=shortcut(f);expect(readonly.handled).toBe(true);expect(readonly.event.defaultPrevented).toBe(true);expect(f.editor.getJSON()).toEqual(f.baseline)
})
