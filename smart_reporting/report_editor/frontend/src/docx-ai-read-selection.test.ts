import {expect,it} from 'vitest'
import {Schema, type Node} from '@tiptap/pm/model'
import {TextSelection,NodeSelection} from '@tiptap/pm/state'
import {CellSelection,TableMap} from '@tiptap/pm/tables'
import {docxAIReadSelection} from './docx-ai-read-selection'
const schema=new Schema({nodes:{doc:{content:'block+'},text:{group:'inline'},docParagraph:{group:'block',content:'text*',attrs:{docxIndex:{default:null}}},docTable:{group:'block',content:'docTableRow+',tableRole:'table',attrs:{docxIndex:{default:null},nativeTableColumnWidths:{default:null},nativeTableRowHeights:{default:null},nativeTableAlignment:{default:null},nativeTableStructure:{default:null},nativeTableCellShape:{default:null}}},docTableRow:{content:'docTableCell+',tableRole:'row'},docTableCell:{content:'docParagraph+',tableRole:'cell',attrs:{colspan:{default:1},rowspan:{default:1}}}}})
const p=(index:number|null,text='正文')=>schema.nodes.docParagraph.create({docxIndex:index},schema.text(text))
const cell=(text:string)=>schema.nodes.docTableCell.create(null,p(null,text))
const table=(attrs:object={})=>schema.nodes.docTable.create({docxIndex:2,...attrs},[schema.nodes.docTableRow.create(null,[cell('所选'),cell('邻格秘密')]),schema.nodes.docTableRow.create(null,[cell('下格'),cell('末格')])])
const source=schema.nodes.doc.create(null,[p(0),p(1),table()])
const anchors=[{docxIndex:0,blockId:'p0'},{docxIndex:1,blockId:'p1'},{docxIndex:2,blockId:'t',cells:[[{cellId:'a'},{cellId:'b'}],[{cellId:'c'},{cellId:'d'}]]}]
const tablePos=source.child(0).nodeSize+source.child(1).nodeSize
function read(doc:Node,selection:TextSelection|CellSelection|NodeSelection,nested=false){return docxAIReadSelection(doc,selection,source,anchors,nested)}
it('单格光标带列宽行高对齐草稿仍只授权该单元格',()=>{
 const doc=schema.nodes.doc.create(null,[p(0),p(1),table({nativeTableColumnWidths:[1,2],nativeTableRowHeights:[3],nativeTableAlignment:'center'})])
 const pos=tablePos+1+TableMap.get(doc.child(2)).map[0]
 expect(read(doc,TextSelection.create(doc,pos+2))).toEqual([{blockId:'t',cellId:'a'}])
})
it('跨段选择包含全部所选段落，部分段落按整段',()=>{
 expect(read(source,TextSelection.create(source,2,source.child(0).nodeSize+2))).toEqual([{blockId:'p0'},{blockId:'p1'}])
})
it('CellSelection完整授权多格，绝不扩大为整表',()=>{
 const map=TableMap.get(source.child(2)),start=tablePos+1
 expect(read(source,CellSelection.create(source,start+map.map[0],start+map.map[3]))).toEqual(['a','b','c','d'].map(cellId=>({blockId:'t',cellId})))
})
it('结构或合并拆分意图无法可靠定位时拒绝，不能退回整表',()=>{
 for(const attrs of [{nativeTableStructure:[{kind:'insertRow'}]},{nativeTableCellShape:[{kind:'merge'}]}]){
  const doc=schema.nodes.doc.create(null,[p(0),p(1),table(attrs)]),pos=tablePos+1+TableMap.get(doc.child(2)).map[0]
  expect(read(doc,TextSelection.create(doc,pos+2))).toEqual([])
 }
})
it('只有显式整表NodeSelection可授权整表，嵌套输入拒绝',()=>{
 expect(read(source,NodeSelection.create(source,tablePos))).toEqual([{blockId:'t'}])
 expect(read(source,TextSelection.create(source,1),true)).toEqual([])
})
it('新增未绑定段落或重复来源身份拒绝整个选区',()=>{
 const doc=schema.nodes.doc.create(null,[p(0),p(null),p(1),table()])
 expect(read(doc,TextSelection.create(doc,1,doc.child(0).nodeSize+2))).toEqual([])
 const duplicate=schema.nodes.doc.create(null,[p(0),p(0),p(1),table()])
 expect(read(duplicate,TextSelection.create(duplicate,1))).toEqual([])
})
it('普通文本跨格与跨表选择逐格授权，末端未选中的格不加入',()=>{
 const map=TableMap.get(source.child(2)),start=tablePos+1
 expect(read(source,TextSelection.create(source,start+map.map[0]+2,start+map.map[1]+3))).toEqual([{blockId:'t',cellId:'a'},{blockId:'t',cellId:'b'}])
 expect(read(source,TextSelection.create(source,source.child(0).nodeSize+2,start+map.map[0]+3))).toEqual([{blockId:'p1'},{blockId:'t',cellId:'a'}])
})
it('无结构意图标记但实际行数或跨列拓扑不符也拒绝来源映射',()=>{
 const original=source.child(2)
 const changedRow=schema.nodes.docTableRow.create(null,[schema.nodes.docTableCell.create({colspan:2},p(null,'合并文字'))])
 const changed=[schema.nodes.docTable.create({docxIndex:2},[original.child(0)]),schema.nodes.docTable.create({docxIndex:2},[changedRow,original.child(1)])]
 for(const block of changed){const doc=schema.nodes.doc.create(null,[p(0),p(1),block]);expect(read(doc,TextSelection.create(doc,tablePos+4))).toEqual([]);expect(read(doc,NodeSelection.create(doc,tablePos))).toEqual([])}
})
