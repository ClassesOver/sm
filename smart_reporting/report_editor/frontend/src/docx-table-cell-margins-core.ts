import type {Node as PmNode} from '@tiptap/pm/model'
import {TableMap} from '@tiptap/pm/tables'
export type TableCellMargins={top:number;right:number;bottom:number;left:number}
export type PartialTableCellMargins=Partial<TableCellMargins>
export interface TableCellMarginsSource {defaults:PartialTableCellMargins|null;raw:string|null;cells:(PartialTableCellMargins|null)[]}
const sides=['top','right','bottom','left'] as const
const fail=():never=>{throw new Error('docx_table_cell_margins_invalid')}
export function normalizeTableCellMargins(value:unknown,complete=false):PartialTableCellMargins|null{
 if(value==null){if(complete)fail();return null}
 if(typeof value!=='object'||Array.isArray(value)||Object.keys(value).some(key=>!sides.includes(key as typeof sides[number]))||complete&&Object.keys(value).length!==4)fail()
 const result:PartialTableCellMargins={}
 for(const side of sides){if(!Object.hasOwn(value,side))continue;const n=(value as TableCellMargins)[side];if(!Number.isSafeInteger(n)||n<0||n>28350)fail();result[side]=n}
 return Object.keys(result).length?result:null
}
export function tableCellMarginsState(table:PmNode){
 const cells:(PartialTableCellMargins|null)[]=[]
 table.forEach(row=>row.forEach(cell=>cells.push(normalizeTableCellMargins(cell.attrs.cellMar))))
 return{defaults:normalizeTableCellMargins(table.attrs.cellMar),cells}
}
/** Ribbon源applyTableValue的margins组；只改变整表默认，不重写任何tcPr。 */
export function applyTableCellMargins(table:PmNode,margins:TableCellMargins):PmNode{
 const value=normalizeTableCellMargins(margins,true)
 if(table.type.spec.tableRole!=='table'||!table.childCount||table.childCount>100)fail()
 table.check();let count=0
 table.forEach(row=>{if(row.type.spec.tableRole!=='row'||row.childCount>30)fail();row.forEach(cell=>{if(!Number.isSafeInteger(cell.attrs.colspan)||cell.attrs.colspan<1||!Number.isSafeInteger(cell.attrs.rowspan)||cell.attrs.rowspan<1||cell.attrs.gridGap||++count>1000)fail()})})
 const map=TableMap.get(table);if(map.problems?.length||map.width>30||map.width*map.height>1000)fail()
 return table.type.create({...table.attrs,cellMar:value,cellMarEdited:true},table.content,table.marks)
}
