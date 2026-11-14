import type {Schema} from '@tiptap/pm/model'
import {TableMap} from '@tiptap/pm/tables'
import type {DocxPmNode} from './docx-operations'
import {normalizeTablePropertiesPatch,type TablePropertiesPatch} from './docx-table-properties-core'
export interface DocxTablePropertiesAnchor {tablePropertiesEditable?:boolean;tablePropertiesReadOnlyReason?:string|null;columnWidthMaxTwips?:number;rowHeightMaxTwips?:number}
const equal=(a:unknown,b:unknown)=>JSON.stringify(a)===JSON.stringify(b)
const margins=(value:any)=>({top:value?.top??0,right:value?.right??108,bottom:value?.bottom??0,left:value?.left??108})
export function projectDocxTableProperties(source:DocxPmNode,anchor:DocxTablePropertiesAnchor,input:unknown,schema?:Schema):DocxPmNode{
 if(!schema||source.type!=='docTable'||!anchor.tablePropertiesEditable)throw Error(anchor.tablePropertiesReadOnlyReason??'当前来源不支持完整表格属性')
 if(Object.entries(source.attrs??{}).some(([k,v])=>k.startsWith('nativeTable')&&k!=='nativeTableProperties'&&v))throw Error('完整表格属性不能与同表其他修改混用，请先保存')
 const patch=normalizeTablePropertiesPatch(input),json=structuredClone(source),a=json.attrs??={};delete a.nativeTableProperties
 const table=schema.nodeFromJSON(source),map=TableMap.get(table),t=patch.table
 if(t){if(t.autoFit!==undefined){a.tblAutoFit=t.autoFit;a.tblAutoFitEdited=true};if(t.align!==undefined)a.tblAlign=t.align;if(t.margins){a.cellMar=t.margins;a.cellMarEdited=true};if(t.wrap!==undefined){const side=t.wrap==='none'?null:t.wrap;a.tblFloat=a.tblFloatSuppressed?null:side;a.tblFloatSource=side;a.tblFloatEdited=true;a.tblFloatXTwips=side?(t.xTwips??a.tblFloatXTwips??0):null;a.tblFloatYTwips=side?(t.yTwips??a.tblFloatYTwips??0):null;a.tblFloatHorzAnchor=side?(a.tblFloatHorzAnchor??'margin'):null;a.tblFloatVertAnchor=side?(a.tblFloatVertAnchor??'margin'):null;a.tblFloatWidthPx=side==='right'?(a.widthPx??null):null;a.tblFloatDistance=side?{top:t.distanceTwips??180,right:t.distanceTwips??180,bottom:t.distanceTwips??180,left:t.distanceTwips??180}:null}}
 if(patch.widthsTwips){if(patch.widthsTwips.length!==map.width||patch.widthsTwips.reduce((a,b)=>a+b,0)>(anchor.columnWidthMaxTwips??31680))throw Error('表格宽度超出当前节正文范围');const px=patch.widthsTwips.map(n=>n/15),total=px.reduce((a,b)=>a+b,0);a.widthPx=total;a.widthPct=null;a.colWidthsPct=px.map(n=>n/total*100);let ri=0;for(const row of json.content??[]){let ci=0;for(const cell of row.content??[]){const attrs=cell.attrs??={},span=Number(attrs.colspan??1);while(ri<map.height&&map.map[ri*map.width+ci]===undefined)ci++;attrs.colwidth=px.slice(ci,ci+span);ci+=span}ri++}}
 for(const r of patch.rows??[]){const row=json.content?.[r.index];if(!row)throw Error('行坐标无效');const attrs=row.attrs??={};if(r.heightTwips!==undefined){if(r.heightTwips!==null&&r.heightTwips>(anchor.rowHeightMaxTwips??28350))throw Error('行高超出当前节正文范围');attrs.heightTwips=r.heightTwips;attrs.heightRule=r.heightRule};if(r.cantSplit!==undefined){attrs.cantSplit=r.cantSplit;attrs.cantSplitEdited=true};if(r.repeatHeader!==undefined){attrs.repeatHeader=r.repeatHeader;attrs.repeatHeaderEdited=true}}
 for(const c of patch.cells??[]){if(c.row>=map.height||c.column>=map.width)throw Error('单元格坐标无效');const pos=map.map[c.row*map.width+c.column],rect=map.findCell(pos);if(rect.top!==c.row||rect.left!==c.column)throw Error('单元格坐标须指向合并格起点');let offset=0;for(let ri=0;ri<json.content!.length;ri++){const row=json.content![ri];let cellOffset=offset+1;for(const cell of row.content!){if(cellOffset===pos){const attrs=cell.attrs??={};if(c.vAlign!==undefined)attrs.vAlign=c.vAlign==='top'?null:c.vAlign;if(c.noWrap!==undefined)attrs.noWrap=c.noWrap?true:null;if(c.margins!==undefined)attrs.cellMar=c.margins;attrs.tcPrEdited=true}cellOffset+=schema.nodeFromJSON(cell).nodeSize}offset+=schema.nodeFromJSON(row).nodeSize}}
 if(patch.alt){a.tblCaption=patch.alt.title||null;a.tblDescription=patch.alt.description||null;a.tblAltEdited=true}
 a.nativeTableProperties=patch
 return schema.nodeFromJSON(json).toJSON() as DocxPmNode
}
/** 只从固定源命令触及的受控属性构建补丁，其余差异由 collector 完整投影校验拒绝。 */
export function tablePropertiesPatchOf(source:DocxPmNode,edited:DocxPmNode,schema:Schema):TablePropertiesPatch|null{
 const patch:TablePropertiesPatch={},a=source.attrs??{},b=edited.attrs??{},t:NonNullable<TablePropertiesPatch['table']>={}
 if(!equal(a.tblAutoFit,b.tblAutoFit))t.autoFit=b.tblAutoFit as any
 if(!equal(a.tblAlign,b.tblAlign))t.align=(b.tblAlign??'left') as any
 if(!equal(a.cellMar,b.cellMar))t.margins=margins(b.cellMar)
 if(['tblFloatSource','tblFloat','tblFloatXTwips','tblFloatYTwips','tblFloatDistance'].some(k=>!equal(a[k],b[k]))){t.wrap=(b.tblFloatSource??b.tblFloat??'none') as any;t.xTwips=Number(b.tblFloatXTwips??0);t.yTwips=Number(b.tblFloatYTwips??0);const d=b.tblFloatDistance as any;t.distanceTwips=Number(d?.right??d?.left??180)}
 if(Object.keys(t).length)patch.table=t
 const map=TableMap.get(schema.nodeFromJSON(edited)),baseMap=TableMap.get(schema.nodeFromJSON(source));if(map.width!==baseMap.width||map.height!==baseMap.height)throw Error('表格属性不能更改网格结构')
 const widths=Array.from({length:map.width},(_,col)=>{const cell=schema.nodeFromJSON(edited).nodeAt(map.map[col])!,rect=map.findCell(map.map[col]);return Math.round(Number(cell.attrs.colwidth?.[col-rect.left]??Number(b.widthPx??0)*Number((b.colWidthsPct as number[])?.[col]??0)/100)*15)})
 const oldWidths=Array.from({length:map.width},(_,col)=>{const cell=schema.nodeFromJSON(source).nodeAt(baseMap.map[col])!,rect=baseMap.findCell(baseMap.map[col]);return Math.round(Number(cell.attrs.colwidth?.[col-rect.left]??Number(a.widthPx??0)*Number((a.colWidthsPct as number[])?.[col]??0)/100)*15)})
 // contents 命令清空显示宽度；原生模式切换保留来源网格，不能将其登记成零列宽。
 const clearedForContents=b.tblAutoFit==='contents'&&b.widthPx==null&&b.colWidthsPct==null&&widths.every(width=>width===0)
 if(!clearedForContents&&!equal(widths,oldWidths))patch.widthsTwips=widths
 const rows:NonNullable<TablePropertiesPatch['rows']>=[],cells:NonNullable<TablePropertiesPatch['cells']>=[]
 for(let ri=0;ri<(edited.content?.length??0);ri++){const old=source.content![ri],next=edited.content![ri],oa=old.attrs??{},na=next.attrs??{},row:any={index:ri};if(['heightTwips','heightRule'].some(k=>!equal(oa[k],na[k]))){row.heightTwips=na.heightTwips??null;row.heightRule=row.heightTwips===null?null:(na.heightRule??'atLeast')};for(const k of ['cantSplit','repeatHeader'])if(Boolean(oa[k])!==Boolean(na[k]))row[k]=Boolean(na[k]);if(Object.keys(row).length>1)rows.push(row)}
 const seen=new Set<number>();for(let ri=0;ri<map.height;ri++)for(let col=0;col<map.width;col++){const pos=map.map[ri*map.width+col];if(seen.has(pos))continue;seen.add(pos);const old=schema.nodeFromJSON(source).nodeAt(baseMap.map[ri*map.width+col])!,next=schema.nodeFromJSON(edited).nodeAt(pos)!,cell:any={row:ri,column:col};if((old.attrs.vAlign??'top')!==(next.attrs.vAlign??'top'))cell.vAlign=next.attrs.vAlign??'top';if(Boolean(old.attrs.noWrap)!==Boolean(next.attrs.noWrap))cell.noWrap=Boolean(next.attrs.noWrap);if(!equal(old.attrs.cellMar,next.attrs.cellMar))cell.margins=next.attrs.cellMar===null?null:margins(next.attrs.cellMar);if(Object.keys(cell).length>2)cells.push(cell)}
 if(rows.length)patch.rows=rows;if(cells.length)patch.cells=cells
 if((a.tblCaption??'')!==(b.tblCaption??'')||(a.tblDescription??'')!==(b.tblDescription??''))patch.alt={title:String(b.tblCaption??''),description:String(b.tblDescription??'')}
 return Object.keys(patch).length?normalizeTablePropertiesPatch(patch):null
}
