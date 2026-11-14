/** DOM-free source-equivalent Insert/Delete Cells adapter. */
import type {Node as PmNode} from '@tiptap/pm/model'
import {EditorState,type Transaction} from '@tiptap/pm/state'
import {CellSelection,TableMap,deleteRow,deleteColumn,fixTables} from '@tiptap/pm/tables'
import {columnWidthsPx,copyCellFormatting,insertColumnAt,insertRowAt,pctOf,reflowColumns} from './vendor/genoffice-docs/apps/docs/src/renderer/ai/table-ops'
export type DocxTableCellRect={top:number;left:number;bottom:number;right:number}
export type DocxTableCellChange={type:'insert';rect:DocxTableCellRect;where:'above'|'below'|'left'|'right';count:number}|{type:'delete';rect:DocxTableCellRect;mode:'shiftLeft'|'shiftUp'|'row'|'column'}
const fail=():never=>{throw new Error('docx_table_cells_invalid')}
const keys=(v:unknown,k:string[]):v is Record<string,unknown>=>!!v&&typeof v==='object'&&!Array.isArray(v)&&Object.keys(v).length===k.length&&Object.keys(v).every(x=>k.includes(x))
export function assertDocxTableCellChange(value:unknown):asserts value is DocxTableCellChange {
 if(!value||typeof value!=='object')fail()
 const v=value as Record<string,unknown>,insert=v.type==='insert'
 if(!keys(v,insert?['type','rect','where','count']:['type','rect','mode'])||!['insert','delete'].includes(v.type as string)||!keys(v.rect,['top','left','bottom','right'])||!Object.values(v.rect).every(Number.isSafeInteger))fail()
 if(insert?(!['above','below','left','right'].includes(v.where as string)||!Number.isSafeInteger(v.count)||Number(v.count)<1||Number(v.count)>100):!['shiftLeft','shiftUp','row','column'].includes(v.mode as string))fail()
}
export function applyDocxTableCellChange(table:PmNode,change:DocxTableCellChange,maxWidthTwips:number):PmNode|null {
 assertDocxTableCellChange(change)
 if(!Number.isSafeInteger(maxWidthTwips)||maxWidthTwips<1||maxWidthTwips>31680||table.type.spec.tableRole!=='table')fail()
 table.check()
 const map=TableMap.get(table),r=change.rect
 if(map.problems?.length||map.height<1||map.height>100||map.width<1||map.width>30||map.width*map.height>1000||r.top<0||r.left<0||r.bottom<=r.top||r.right<=r.left||r.bottom>map.height||r.right>map.width)fail()
 for(const pos of new Set(map.map)){const c=table.nodeAt(pos)!;if(c.attrs.colspan!==1||c.attrs.rowspan!==1||c.attrs.gridGap)fail();c.descendants(n=>{if(n.type.spec.tableRole==='table')fail()})}
 if(change.type==='insert'){const row=['above','below'].includes(change.where),h=map.height+(row?change.count:0),w=map.width+(row?0:change.count);if(h>100||w>30||h*w>1000)fail()}
 if(change.type==='delete'&&((change.mode==='row'&&r.bottom-r.top===map.height)||(change.mode==='column'&&r.right-r.left===map.width)))return null
 const schema=table.type.schema,doc=schema.topNodeType.create(null,[table]),state=EditorState.create({doc,selection:CellSelection.create(doc,1+map.map[r.top*map.width+r.left],1+map.map[(r.bottom-1)*map.width+r.right-1])})
 let tr=state.tr
 if(change.type==='insert'){
  const {where,count:n}=change
  if(where==='above'||where==='below'){
   const at=where==='above'?r.top:r.bottom,ref=table.child(where==='above'?r.top:r.bottom-1)
   for(let i=0;i<n;i++)insertRowAt(tr,0,at)
   copyCellFormatting(tr,0,x=>x.top>=at&&x.top<at+n&&x.bottom===x.top+1,x=>[where==='above'?at+n:at-1,x.left])
   tr.doc.firstChild!.forEach((row,off,i)=>{if(i>=at&&i<at+n)tr.setNodeMarkup(1+off,undefined,{...row.attrs,heightTwips:ref.attrs.heightTwips,heightRule:ref.attrs.heightRule,cantSplit:ref.attrs.cantSplit,cantSplitEdited:!!ref.attrs.cantSplit})})
  }else{
   const at=where==='left'?r.left:r.right,ref=where==='left'?r.left:r.right-1,widths=columnWidthsPx(table,map),pct=pctOf(table,map,widths),next=widths?[...widths]:null,p=[...pct]
   for(let i=0;i<n;i++){insertColumnAt(tr,0,at+i);next?.splice(at+i,0,widths![ref]);p.splice(at+i,0,pct[ref])}
   copyCellFormatting(tr,0,x=>x.left>=at&&x.left<at+n&&x.right===x.left+1,x=>[x.top,where==='left'?at+n:at-1])
   const total=next?.reduce((a,b)=>a+b,0)??0
   reflowColumns(tr,0,next&&total>maxWidthTwips/15?next.map(w=>w*maxWidthTwips/15/total):next,p)
  }
 }else if(change.mode==='row'||change.mode==='column'){
  let captured:Transaction|undefined
  if(!(change.mode==='row'?deleteRow:deleteColumn)(state,t=>{captured=t})||!captured)fail()
  tr=captured!
  if(change.mode==='column'){const widths=columnWidthsPx(table,map),pct=pctOf(table,map,widths),keep=(_:unknown,i:number)=>i<r.left||i>=r.right;reflowColumns(tr,0,widths?widths.filter(keep):null,pct.filter(keep))}
 }else{
  const rows:PmNode[]=[],height=r.bottom-r.top,width=r.right-r.left
  for(let y=0;y<map.height;y++){
   const cells:PmNode[]=[]
   for(let x=0;x<map.width;x++){
    let sy=y,sx=x,blank=false,gap=false
    if(change.mode==='shiftLeft'&&y>=r.top&&y<r.bottom&&x>=r.left){sx=x+width;if(sx>=map.width){sx=r.left+x-(map.width-width);blank=true;gap=true}}
    if(change.mode==='shiftUp'&&x>=r.left&&x<r.right&&y>=r.top){sy=y+height;if(sy>=map.height){sy=map.height-1;blank=true}}
    const src=table.child(sy).child(sx),first=src.firstChild
    cells.push(blank?src.type.create({...src.attrs,...(gap?{gridGap:true,fill:null,borders:null}:{})},schema.nodes.docParagraph.create(first?.type.name==='docParagraph'?{...first.attrs,docxIndex:null}:{docxIndex:null})):src)
   }
   if(cells.some(c=>!c.attrs.gridGap))rows.push(table.child(y).type.create(table.child(y).attrs,cells))
  }
  const next=rows.length?table.type.create(table.attrs,rows):schema.nodes.docParagraph.create()
  tr.replaceWith(0,table.nodeSize,next)
 }
 // tableEditing's appendTransaction repairs source's null/misaligned colwidths.
 const edited=state.apply(tr),fixed=fixTables(edited),result=(fixed?edited.apply(fixed):edited).doc.firstChild!
 result.check()
 if(result.type.spec.tableRole==='table'&&TableMap.get(result).problems?.length)fail()
 return result
}
export {Schema} from '@tiptap/pm/model'
