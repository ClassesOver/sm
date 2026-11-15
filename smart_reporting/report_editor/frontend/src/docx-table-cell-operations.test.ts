import {afterEach,expect,it} from 'vitest'
import {Editor,Extension,Node} from '@tiptap/core'
import {UndoRedo} from '@tiptap/extensions'
import {CellSelection,TableMap} from '@tiptap/pm/tables'
import {NodeSelection} from '@tiptap/pm/state'
import {Plugin} from '@tiptap/pm/state'
import type {DocxPmNode} from './docx-operations'
import {NativeDocxHistory} from './docx-native-history'
import {createDocxTableCellControls,normalizeDocxTableCellOperation,replayDocxTableCellOperation,assertDocxTableCellOperationBatch,normalizeDocxTableCellSources} from './docx-table-cell-operations'
const attrs=(v:Record<string,unknown>)=>Object.fromEntries(Object.entries(v).map(([key,value])=>[key,{default:value}]))
const Doc=Node.create({name:'doc',topNode:true,content:'block+'}),Text=Node.create({name:'text',group:'inline'})
const Paragraph=Node.create({name:'docParagraph',group:'block',content:'text*',addAttributes:()=>attrs({docxIndex:null,align:null}),renderHTML:()=>['p',0]})
const Table=Node.create({name:'docTable',group:'block',content:'docTableRow+',addAttributes:()=>attrs({docxIndex:null,originalStructure:'identity',originalFormatting:'format',styleId:'Grid',widthPx:300,widthPct:null,colWidthsPct:[40,60]}),renderHTML:()=>['table',['tbody',0]]})
const Row=Node.create({name:'docTableRow',content:'docTableCell+',addAttributes:()=>attrs({rawTrPr:'row'}),renderHTML:()=>['tr',0]})
const Cell=Node.create({name:'docTableCell',content:'docParagraph+',addAttributes:()=>attrs({colspan:1,rowspan:1,colwidth:null,gridGap:false,rawTcPr:'cell'}),renderHTML:()=>['td',0]})
const Roles=Extension.create({name:'roles',extendNodeSchema:e=>({tableRole:({docTable:'table',docTableRow:'row',docTableCell:'cell'} as Record<string,string>)[e.name]})})
const editors:Editor[]=[];const controlsList:{dispose:()=>void}[]=[]
afterEach(()=>{controlsList.splice(0).forEach(c=>c.dispose());editors.splice(0).forEach(e=>e.destroy());document.body.innerHTML=''})
function setup(only=false){
 const table={type:'docTable',attrs:{docxIndex:1},content:[0,1,2].map(r=>({type:'docTableRow',content:[0,1].map(c=>({type:'docTableCell',attrs:{colwidth:[c?180:120]},content:[{type:'docParagraph',attrs:{align:'right'},content:[{type:'text',text:`${r}:${c}`}]}]}))}))}
 const editor=new Editor({extensions:[Doc,Text,Paragraph,Table,Row,Cell,Roles,NativeDocxHistory,UndoRedo],content:{type:'doc',content:only?[table]:[{type:'docParagraph',attrs:{docxIndex:0},content:[{type:'text',text:'body'}]},table]},editorProps:{handleScrollToSelection:()=>true}});editors.push(editor)
 const anchors=[{docxIndex:1,blockId:'table-1',expectedObjectSha256:'a'.repeat(64),tableCellsEditable:true,tableCellsWidthsTwips:[1800,2700],tableCellsMaxWidthTwips:9000}]
 const baseline=normalizeDocxTableCellSources(editor.getJSON() as DocxPmNode,anchors,editor.schema)
 const errors:string[]=[],lock={value:null as string|null},controls=createDocxTableCellControls({editor,baseline,anchors,root:document.body,reason:()=>lock.value,onError:e=>errors.push(String(e))});controlsList.push(controls)
 const pos=()=>only?0:editor.state.doc.firstChild!.nodeSize
 const select=(top=1,left=0,bottom=top+1,right=left+1)=>{const map=TableMap.get(editor.state.doc.nodeAt(pos())!);editor.view.dispatch(editor.state.tr.setSelection(CellSelection.create(editor.state.doc,pos()+1+map.map[top*map.width+left],pos()+1+map.map[(bottom-1)*map.width+right-1])))}
 return{editor,baseline,anchors,controls,errors,lock,pos,select}
}
const dialog=()=>document.querySelector<HTMLElement>('[role=dialog]')!
function submit(mode?:string,count?:string){if(mode){const radio=dialog().querySelector<HTMLInputElement>(`input[value="${mode}"]`)!;radio.checked=true;radio.dispatchEvent(new Event('change',{bubbles:true}))}if(count!==undefined)dialog().querySelector<HTMLInputElement>('input[type=number]')!.value=count;dialog().querySelector('form')!.dispatchEvent(new Event('submit',{bubbles:true,cancelable:true}))}
it('insert dialog freezes a rectangle and records source-bound isolated projection with atomic undo',()=>{
 const f=setup();f.select(1,0,3,2);expect(f.controls.run('table-insert-cells'),f.errors.join(';')).toBe(true);expect(dialog().getAttribute('aria-label')).toBe('插入单元格');submit('above','2')
 expect(dialog()).toBeNull();expect(f.editor.state.doc.nodeAt(f.pos())!.childCount).toBe(5)
 const current=f.editor.getJSON() as DocxPmNode,op=(current.attrs!.nativeDocxOperations as any[])[0];expect(op).toEqual({kind:'editTableCells',blockId:'table-1',expectedObjectSha256:'a'.repeat(64),change:{type:'insert',rect:{top:1,left:0,bottom:3,right:2},where:'above',count:2}})
 expect(normalizeDocxTableCellOperation(f.baseline,current,f.anchors,f.editor.schema)).toEqual({current:f.baseline,operations:[op]});expect(replayDocxTableCellOperation(f.baseline,[op],f.anchors,f.editor.schema)).toEqual(current)
 f.editor.commands.undo();expect(f.editor.getJSON()).toEqual(f.baseline);f.editor.commands.redo();expect(f.editor.getJSON()).toEqual(current)
})
it.each(['shiftLeft','shiftUp','row','column'])('delete dialog applies actual %s mode',mode=>{
 const f=setup();f.select();expect(f.controls.run('table-delete-cells')).toBe(true);submit(mode)
 expect(dialog(),f.errors.join(';')).toBeNull();const current=f.editor.getJSON() as DocxPmNode;expect((current.attrs!.nativeDocxOperations as any[])[0].change).toEqual({type:'delete',rect:{top:1,left:0,bottom:2,right:1},mode});expect(normalizeDocxTableCellOperation(f.baseline,current,f.anchors,f.editor.schema).current).toEqual(f.baseline)
})
it('strict count validation keeps modal and input until valid; cancel and IME do not mutate',()=>{
 const f=setup();f.select();f.controls.run('table-insert-cells')
 for(const value of ['','0','101','1.5','1e1']){submit('below',value);expect(dialog()).not.toBeNull();expect(dialog().querySelector('[role=alert]')!.textContent).not.toBe('');expect(f.editor.getJSON()).toEqual(f.baseline)}
 const composing=new KeyboardEvent('keydown',{key:'Escape',isComposing:true,bubbles:true});dialog().dispatchEvent(composing);expect(dialog()).not.toBeNull()
 dialog().dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}));expect(dialog()).toBeNull();expect(f.editor.getJSON()).toEqual(f.baseline)
})
it('dialog checks stale selection, permission, composing and source snapshot before apply',()=>{
 const f=setup();f.select();f.controls.run('table-delete-cells');f.select(0);submit('row');expect(dialog().querySelector('[role=alert]')!.textContent).toMatch(/选区|选择|改变/);expect(f.editor.getJSON()).toEqual(f.baseline);f.controls.dispose()
 for(const change of [(g:ReturnType<typeof setup>)=>{g.lock.value='只读'},(g:ReturnType<typeof setup>)=>{g.anchors[0].expectedObjectSha256='b'.repeat(64)},(g:ReturnType<typeof setup>)=>{Object.defineProperty(g.editor.view,'composing',{value:true,configurable:true})}]){const g=setup();g.select();g.controls.run('table-delete-cells');change(g);submit('row');expect(dialog()).not.toBeNull();expect(g.editor.getJSON()).toEqual(g.baseline);g.controls.dispose()}
})
it('rejects forged SHA, source identities, changes, mixed journals and extra body edits',()=>{
 const f=setup();f.select();f.controls.run('table-delete-cells');submit('row');const current=f.editor.getJSON() as DocxPmNode,op=(current.attrs!.nativeDocxOperations as any[])[0]
 for(const forged of [{...op,expectedObjectSha256:'b'.repeat(64)},{...op,blockId:'foreign'},{...op,extra:1},{...op,change:{...op.change,mode:'unknown'}},{...op,change:{...op.change,rect:{top:0,left:0,bottom:100,right:1}}}])expect(()=>replayDocxTableCellOperation(f.baseline,[forged],f.anchors,f.editor.schema)).toThrow()
 for(const ops of [[op,op],[op,{kind:'unknown'}],[{kind:'setPageColor'},op]])expect(()=>assertDocxTableCellOperationBatch(ops)).toThrow()
 const extra=structuredClone(current);extra.content![0].content![0].text='forged';expect(()=>normalizeDocxTableCellOperation(f.baseline,extra,f.anchors,f.editor.schema)).toThrow()
 const ids=structuredClone(current);ids.content![1].attrs!.docxIndex=99;expect(()=>normalizeDocxTableCellOperation(f.baseline,ids,f.anchors,f.editor.schema)).toThrow()
})
it('whole-table selection delete leaves schema filler and preserves neighbouring document coordinates',()=>{
 const f=setup(true);f.editor.view.dispatch(f.editor.state.tr.setSelection(NodeSelection.create(f.editor.state.doc,0)));f.controls.run('table-delete-cells');submit('row');expect(f.editor.getJSON().content).toEqual([f.editor.schema.nodes.docParagraph.create().toJSON()]);f.editor.commands.undo();expect(f.editor.getJSON()).toEqual(f.baseline)
 const g=setup();g.select();g.controls.run('table-insert-cells');submit('right','1');expect(g.editor.getJSON().content![0]).toEqual(g.baseline.content![0]);expect(g.editor.getJSON().content![1].attrs!.docxIndex).toBe(1)
})
it('checks dispatch acceptance and preserves failed dialog with no history',()=>{
 const f=setup();const guard=new Plugin({filterTransaction:tr=>!tr.docChanged});f.editor.registerPlugin(guard);f.select();f.controls.run('table-delete-cells');submit('row');expect(dialog()).not.toBeNull();expect(dialog().querySelector('[role=alert]')!.textContent).toMatch(/拒绝|接受|应用/);expect(f.editor.getJSON()).toEqual(f.baseline);expect(f.editor.can().undo()).toBe(false)
})
it('normalizes exact signed twip colwidths without changing source attrs and skips locked sources',()=>{
 const f=setup();expect(f.baseline.content![1].content![0].content![0].attrs!.colwidth).toEqual([120]);const widths={...f.anchors[0],tableCellsWidthsTwips:[1801,2699]},original=structuredClone(f.baseline),normalized=normalizeDocxTableCellSources(original,[widths],f.editor.schema)
 expect(normalized.content![1].attrs).toEqual(original.content![1].attrs);expect(normalized.content![1].content![0].content![0].attrs!.colwidth).toEqual([1801/15]);expect(normalizeDocxTableCellSources(original,[{...widths,tableCellsEditable:false}],f.editor.schema)).toEqual(original)
})
it('read-only, tracking, unsaved edits, source mismatch and unsupported source grids refuse before opening',()=>{
 const f=setup();f.select();f.editor.setEditable(false);expect(f.controls.reason('table-insert-cells')).toMatch(/不可编辑/);expect(f.controls.run('table-insert-cells')).toBe(false);f.editor.setEditable(true)
 f.editor.storage.trackChanges={enabled:true,author:'tester',trackMoves:false,trackFormatting:false};expect(f.controls.reason('table-delete-cells')).toMatch(/修订/);f.editor.storage.trackChanges.enabled=false
 f.editor.view.dispatch(f.editor.state.tr.insertText('pending',1));expect(f.controls.run('table-insert-cells')).toBe(false);expect(dialog()).toBeNull()
 const g=setup();g.select();g.anchors[0].tableCellsEditable=false;expect(g.controls.run('table-delete-cells')).toBe(false)
 const h=setup(),bad=structuredClone(h.baseline);bad.content![1].content![0].content![0].attrs!.colwidth=[999];const op={kind:'editTableCells',blockId:'table-1',expectedObjectSha256:'a'.repeat(64),change:{type:'delete',rect:{top:0,left:0,bottom:1,right:1},mode:'row'}}
 expect(()=>replayDocxTableCellOperation(bad,[op],h.anchors,h.editor.schema)).toThrow()
 const nested=structuredClone(h.baseline);nested.content![1].content![0].content![0].attrs!.gridGap=true;expect(()=>replayDocxTableCellOperation(nested,[op],h.anchors,h.editor.schema)).toThrow()
 for(const forged of [{...op,expectedObjectSha256:'a'.repeat(63)},{...op,change:{...op.change,rect:{top:-1,left:0,bottom:1,right:1}}},{...op,change:{...op.change,rect:{top:0,left:0,bottom:1,right:1,extra:0}}}])expect(()=>replayDocxTableCellOperation(h.baseline,[forged],h.anchors,h.editor.schema)).toThrow()
})
it('local IME composition retains dialog and blocks submit and Escape until composition ends',()=>{
 const f=setup();f.select();f.controls.run('table-insert-cells');dialog().dispatchEvent(new Event('compositionstart',{bubbles:true}));submit('below','1');expect(f.editor.getJSON()).toEqual(f.baseline)
 dialog().dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true,cancelable:true}));expect(dialog()).not.toBeNull();dialog().dispatchEvent(new Event('compositionend',{bubbles:true}));submit('below','1');expect(dialog()).toBeNull();expect(f.editor.state.doc.nodeAt(f.pos())!.childCount).toBe(4)
})
it('ordinary and unknown-only journals stay with their existing normalizer',()=>{
 const f=setup(),current=structuredClone(f.baseline);current.attrs!.nativeDocxOperations=[{kind:'unknown'}];expect(normalizeDocxTableCellOperation(f.baseline,current,f.anchors,f.editor.schema)).toEqual({current,operations:[]});expect(replayDocxTableCellOperation(f.baseline,[],f.anchors,f.editor.schema)).toEqual(f.baseline)
})
