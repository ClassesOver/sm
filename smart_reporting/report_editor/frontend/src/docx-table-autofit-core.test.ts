import { expect, it } from 'vitest'
import { Schema } from '@tiptap/pm/model'
import { applyTableAutoFitSteps } from './docx-table-autofit-core'
const attrs=(v:Record<string,unknown>)=>Object.fromEntries(Object.entries(v).map(([k,defaultValue])=>[k,{default:defaultValue}]))
const schema=new Schema({nodes:{doc:{content:'docTable+'},text:{group:'inline'},p:{content:'inline*'},docTable:{content:'row+',tableRole:'table',attrs:attrs({widthPx:null,widthPct:null,colWidthsPct:null,tblAutoFit:'fixed',tblAutoFitEdited:false,opaque:'keep'})},row:{content:'cell*',tableRole:'row',attrs:attrs({cantSplit:true})},cell:{content:'p',tableRole:'cell',attrs:attrs({colspan:1,rowspan:1,colwidth:null,rawTcPr:'keep'})}},marks:{bold:{}}})
const fixture=()=>schema.node('docTable',null,[schema.node('row',null,[0,1].map(i=>schema.node('cell',null,schema.node('p',null,schema.text(String(i),[schema.mark('bold')])))))])
it('preserves integer source widths and only changes AutoFit geometry',()=>{
 const table=fixture()
 for(const mode of ['window','fixed'] as const){const out=applyTableAutoFitSteps(table,[2000,2001],9000,[{mode}]);expect(out.widthsTwips).toEqual([2000,2001]);expect(out.mode).toBe(mode);expect(out.table.attrs.opaque).toBe('keep');expect(out.table.firstChild!.attrs.cantSplit).toBe(true);expect(out.table.firstChild!.firstChild!.content.eq(table.firstChild!.firstChild!.content)).toBe(true)}
})
it('replays contents then window then fixed without collapsing modes',()=>{
 const table=fixture()
 expect(applyTableAutoFitSteps(table,[2000,2001],9000,[{mode:'contents'}]).widthsTwips).toEqual([4680,4680])
 expect(applyTableAutoFitSteps(table,[2000,2001],9000,[{mode:'contents'},{mode:'window'}]).widthsTwips).toEqual([4680,4680])
 const out=applyTableAutoFitSteps(table,[2000,2001],9000,[{mode:'contents'},{mode:'window'},{mode:'fixed'}]);expect(out.widthsTwips).toEqual([4500,4500]);expect(out.table.attrs.widthPx).toBe(600)
})
it('rejects untrusted step fields, invalid grid and budgets atomically',()=>{
 const table=fixture(),before=table.toJSON()
 for(const steps of [[],[{mode:'bogus'}],[{mode:'fixed',widths:[1,2]}],Array(51).fill({mode:'window'})])expect(()=>applyTableAutoFitSteps(table,[2000,2001],9000,steps as any)).toThrow()
 for(const widths of [[0,100],[2000],[1.5,2000]])expect(()=>applyTableAutoFitSteps(table,widths,9000,[{mode:'fixed'}])).toThrow()
 expect(table.toJSON()).toEqual(before)
})
