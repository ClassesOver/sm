import {expect,it} from 'vitest'
import {Schema} from '@tiptap/pm/model'
import {applyTableCellTextDirectionSteps} from './docx-table-cell-text-direction-core'
const schema=new Schema({nodes:{doc:{content:'table+'},text:{group:'inline'},p:{content:'inline*'},table:{content:'row+',tableRole:'table',attrs:{widthPx:{default:123}}},row:{content:'cell*',tableRole:'row',attrs:{heightTwips:{default:300}}},cell:{content:'p',tableRole:'cell',attrs:{colspan:{default:1},rowspan:{default:1},textDirection:{default:null},tcPrEdited:{default:false},opaque:{default:'keep'}}}},marks:{bold:{}}})
const c=(text:string,attrs={})=>schema.node('cell',attrs,schema.node('p',null,schema.text(text,[schema.mark('bold')])))
const fixture=()=>schema.node('table',null,[schema.node('row',null,[c('A',{colspan:2}),c('B')]),schema.node('row',null,[c('C'),c('D'),c('E')])])
it('uses rectangle grid slots to touch unique merged owners and preserves all content/geometry',()=>{
 const table=fixture(),out=applyTableCellTextDirectionSteps(table,[{top:0,left:1,bottom:2,right:2,direction:'tbRl'}])
 expect(out.directions).toEqual(['tbRl',null,null,'tbRl',null]);expect(out.table.attrs).toEqual(table.attrs)
 expect(out.table.firstChild!.attrs).toEqual(table.firstChild!.attrs);expect(out.table.firstChild!.firstChild!.content.eq(table.firstChild!.firstChild!.content)).toBe(true);expect(out.table.firstChild!.firstChild!.attrs.opaque).toBe('keep')
})
it('replays vertical and horizontal clear on logical owners without reviving old direction',()=>{
 const table=fixture(),out=applyTableCellTextDirectionSteps(table,[{top:0,left:0,bottom:2,right:3,direction:'btLr'},{top:0,left:0,bottom:1,right:2,direction:'lrTb'}])
 expect(out.directions).toEqual([null,'btLr','btLr','btLr','btLr']);expect(out.table.firstChild!.firstChild!.attrs.tcPrEdited).toBe(true)
})
it('rejects malformed direction fields, rectangles and excessive steps atomically',()=>{
 const table=fixture(),before=table.toJSON(),step={top:0,left:0,bottom:1,right:1,direction:'tbRl'}
 for(const steps of [[],[{...step,direction:'tbRlV'}],[{...step,right:4}],[{...step,top:1.5}],[{...step,xml:'fake'}],Array(51).fill(step)])expect(()=>applyTableCellTextDirectionSteps(table,steps as any)).toThrow()
 expect(table.toJSON()).toEqual(before)
})
