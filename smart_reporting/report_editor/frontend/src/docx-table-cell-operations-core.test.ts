import {expect,it} from 'vitest'
import {Schema} from '@tiptap/pm/model'
import {EditorState,type Transaction} from '@tiptap/pm/state'
import {CellSelection,TableMap,fixTables} from '@tiptap/pm/tables'
import {insertRowsOrColumns,deleteCells} from './vendor/genoffice-docs/apps/docs/src/renderer/editor/table-ops'
import {applyDocxTableCellChange,type DocxTableCellChange} from './docx-table-cell-operations-core'
const attrs=(a:Record<string,unknown>)=>Object.fromEntries(Object.entries(a).map(([k,v])=>[k,{default:v}]))
const schema=new Schema({nodes:{doc:{content:'(docTable|docParagraph)+'},text:{group:'inline'},docParagraph:{content:'text*',attrs:attrs({docxIndex:null,keepNext:false})},docTable:{content:'docTableRow+',tableRole:'table',attrs:attrs({colWidthsPct:null,widthPx:null,widthPct:null})},docTableRow:{content:'docTableCell*',tableRole:'row',attrs:attrs({heightTwips:null,heightRule:null,cantSplit:false,cantSplitEdited:false,rawTrPr:null})},docTableCell:{content:'docParagraph+',tableRole:'cell',attrs:attrs({colspan:1,rowspan:1,colwidth:null,gridGap:false,fill:null,borders:null,vAlign:null,cellMar:null,textDirection:null,noWrap:null,align:null,bold:null,color:null,tcPrEdited:false})}}})
function fixture(){return schema.node('docTable',{widthPx:480,colWidthsPct:[20,30,50]},[0,1,2].map(y=>schema.node('docTableRow',{heightTwips:500+y,cantSplit:true},[0,1,2].map(x=>schema.node('docTableCell',{colwidth:[[80,160,240][x]],fill:x===0?'FFFF00':null},schema.node('docParagraph',{docxIndex:y*3+x,keepNext:true},schema.text(`${y}:${x}`)))))))}
const rect={top:0,left:0,bottom:2,right:1}
const changes:DocxTableCellChange[]=[...(['above','below','left','right'] as const).map(where=>({type:'insert' as const,rect,where,count:2})),...(['shiftLeft','shiftUp','row','column'] as const).map(mode=>({type:'delete' as const,rect,mode}))]
it.each(changes)('matches pinned source command including tableEditing normalization %j',change=>{const table=fixture(),map=TableMap.get(table),doc=schema.node('doc',null,[table]),r=change.rect,state=EditorState.create({doc,selection:CellSelection.create(doc,1+map.map[r.top*map.width+r.left],1+map.map[(r.bottom-1)*map.width+r.right-1])});let tr:Transaction|undefined
 const command=change.type==='insert'?insertRowsOrColumns(change.count,change.where,600):deleteCells(change.mode)
 expect(command(state,t=>{tr=t})).toBe(true)
 const edited=state.apply(tr!),fixed=fixTables(edited),expected=(fixed?edited.apply(fixed):edited).doc.firstChild!
 expect(applyDocxTableCellChange(table,change,9000)!.toJSON()).toEqual(expected.toJSON())
})
it('rejects malformed inputs, merges and output budgets',()=>{for(const change of [{type:'insert',rect,where:'left',count:100},{type:'delete',rect:{...rect,right:4},mode:'row'},{type:'insert',rect,where:'above',count:1.2},{type:'delete',rect,mode:'row',extra:true}])expect(()=>applyDocxTableCellChange(fixture(),change as any,9360)).toThrow()})
it('returns explicit empty results for full deletion and inherited blank paragraph on shift',()=>{for(const mode of ['row','column'] as const)expect(applyDocxTableCellChange(fixture(),{type:'delete',rect:{top:0,left:0,bottom:3,right:3},mode},9360)).toBeNull();const result=applyDocxTableCellChange(fixture(),{type:'delete',rect:{top:0,left:0,bottom:3,right:3},mode:'shiftLeft'},9360)!;expect(result.type.name).toBe('docParagraph')})
