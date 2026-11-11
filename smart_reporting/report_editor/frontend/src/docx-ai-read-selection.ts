import type {Node} from '@tiptap/pm/model'
import {NodeSelection, type Selection} from '@tiptap/pm/state'
import {CellSelection} from '@tiptap/pm/tables'

type ReadAnchor = {docxIndex: number; blockId: string; cells?: readonly (readonly {cellId: string}[])[]}
export type DocxAIReadSelection = {blockId: string; cellId?: string}[]
/** 阅读独立定位：布局属性不扩大授权；来源或表结构不明时拒绝整个选区。 */
export function docxAIReadSelection(doc: Node, selection: Selection, source: Node, anchors: readonly ReadAnchor[], nestedInputActive=false): DocxAIReadSelection {
  if(nestedInputActive)return []
  const result: DocxAIReadSelection=[]
  let invalid=false
  const intersects=(position:number,size:number)=>selection.ranges.some(range=>range.$from.pos===range.$to.pos
    ? range.$from.pos>position && range.$from.pos<position+size
    : range.$from.pos<position+size && range.$to.pos>position)
  const uniqueBlock=(value:Node,index:number)=>{let count=0;value.forEach(node=>{if(node.attrs.docxIndex===index)count++});return count===1}
  doc.forEach((block,position)=>{
    if(!intersects(position,block.nodeSize))return
    const index:unknown=block.attrs.docxIndex
    const anchor=typeof index==='number' ? anchors.find(item=>item.docxIndex===index) : undefined
    const original=typeof index==='number' ? source.content.content.find(node=>node.attrs.docxIndex===index) : undefined
    if(!anchor || !original || original.type!==block.type || !uniqueBlock(doc,anchor.docxIndex) || !uniqueBlock(source,anchor.docxIndex)){invalid=true;return}
    if(block.type.name!=='docTable'){
      if(!['docParagraph','docHeading','docListItem'].includes(block.type.name)){invalid=true;return}
      result.push({blockId:anchor.blockId});return
    }
    if(block.attrs.nativeTableStructure || block.attrs.nativeTableCellShape || block.childCount!==original.childCount || !anchor.cells){invalid=true;return}
    // 仅比较身份相关拓扑；列宽、行高、对齐及文字样式不改变单元格对应关系。
    for(let row=0;row<block.childCount;row++){
      const currentRow=block.child(row),sourceRow=original.child(row)
      if(currentRow.childCount!==sourceRow.childCount || anchor.cells[row]?.length!==currentRow.childCount){invalid=true;return}
      for(let column=0;column<currentRow.childCount;column++){
        const current=currentRow.child(column),before=sourceRow.child(column)
        if(current.type!==before.type || current.attrs.colspan!==before.attrs.colspan || current.attrs.rowspan!==before.attrs.rowspan){invalid=true;return}
      }
    }
    if(selection instanceof NodeSelection && selection.from===position && selection.node===block){result.push({blockId:anchor.blockId});return}
    const selectedCells=new Set<number>()
    if(selection instanceof CellSelection)selection.forEachCell((_cell,pos)=>selectedCells.add(pos))
    let count=0
    block.forEach((row,rowOffset,rowIndex)=>row.forEach((cell,cellOffset,columnIndex)=>{
      const cellPosition=position+1+rowOffset+1+cellOffset
      if(selection instanceof CellSelection ? !selectedCells.has(cellPosition) : !intersects(cellPosition,cell.nodeSize))return
      const cellId=anchor.cells?.[rowIndex]?.[columnIndex]?.cellId
      if(!cellId){invalid=true;return}
      count++;result.push({blockId:anchor.blockId,cellId})
    }))
    if(!count)invalid=true
  })
  return invalid ? [] : result
}
