import {expect,it} from 'vitest'
import {docxOperations,formatRangeChanges,replayDocxOperations,type DocxPmNode} from './docx-operations'
const baseline:DocxPmNode={type:'doc',content:[{type:'docParagraph',attrs:{docxIndex:0},content:[{type:'text',text:'中文ABC',marks:[{type:'docTextStyle',attrs:{font:'宋体',eastAsiaFont:'宋体',fontAscii:'Calibri',fontCs:'Arial'}}]}]}]}
const anchors=[{docxIndex:0,blockId:'p0',expectedObjectSha256:'sha',editable:true}]
it.each(['formatParagraph','formatRange'])('replays CJK %s into eastAsia while preserving Latin',kind=>{
 const result=replayDocxOperations(baseline,[{kind,blockId:'p0',expectedObjectSha256:'sha',...(kind==='formatRange'?{from:0,to:5}:{}),style:{fontFamily:'微软雅黑'}}],anchors)
 expect(result.content![0]!.content![0]!.marks![0]!.attrs).toMatchObject({font:'微软雅黑',eastAsiaFont:'微软雅黑',fontAscii:'Calibri',fontCs:'Arial'})
})
it('replays Latin into ascii without overwriting existing eastAsia',()=>{
 const result=replayDocxOperations(baseline,[{kind:'formatParagraph',blockId:'p0',expectedObjectSha256:'sha',style:{fontFamily:'Times New Roman'}}],anchors)
 expect(result.content![0]!.content![0]!.marks![0]!.attrs).toMatchObject({font:'宋体',eastAsiaFont:'宋体',fontAscii:'Times New Roman'})
})
it('keeps null font clearing all direct font slots',()=>{
 const result=replayDocxOperations(baseline,[{kind:'formatParagraph',blockId:'p0',expectedObjectSha256:'sha',style:{fontFamily:null}}],anchors)
 const attrs=result.content![0]!.content![0]!.marks?.[0]?.attrs??{}
 for(const key of ['font','fontAscii','fontCs','eastAsiaFont','themeRFonts'])expect(attrs[key] == null).toBe(true)
})
it('collects explicit Latin slot edits as the fontFamily protocol',()=>{
 const after=structuredClone(baseline.content![0]!);after.content![0]!.marks![0]!.attrs!.fontAscii='Arial'
 expect(formatRangeChanges(baseline.content![0]!,after)).toEqual([{from:0,to:5,style:{fontFamily:'Arial'}}])
})
it('refuses simultaneous changes to both script slots without widening the protocol',()=>{
 const after=structuredClone(baseline.content![0]!);Object.assign(after.content![0]!.marks![0]!.attrs!,{fontAscii:'Arial',font:'微软雅黑',eastAsiaFont:'微软雅黑'})
 expect(()=>formatRangeChanges(baseline.content![0]!,after)).toThrow('分别保存')
})
it('refuses an independent complex-script slot change',()=>{
 const after=structuredClone(baseline.content![0]!);after.content![0]!.marks![0]!.attrs!.fontCs='Arabic'
 expect(()=>formatRangeChanges(baseline.content![0]!,after)).toThrow('暂不支持')
})
it('refuses text edits combined with script-slot font changes',()=>{
 const after=structuredClone(baseline);after.content![0]!.content![0]!.text='修改中文ABC';after.content![0]!.content![0]!.marks![0]!.attrs!.fontAscii='Arial'
 expect(()=>docxOperations(baseline,after,anchors)).toThrow('先保存再设置')
})
it('allows plain text edits with a newly materialized all-null default font mark',()=>{
 const before:DocxPmNode={type:'doc',content:[{type:'docParagraph',attrs:{docxIndex:0},content:[{type:'text',text:'中文'}]}]}
 const after=structuredClone(before);after.content![0]!.content![0]!.text='中文修改';after.content![0]!.content![0]!.marks=[{type:'docTextStyle',attrs:{font:null,fontAscii:null,eastAsiaFont:null}}]
 expect(docxOperations(before,after,anchors)).toEqual([{kind:'replaceParagraph',blockId:'p0',expectedObjectSha256:'sha',text:'中文修改'}])
})

it.each(['LXGW WenKai','Ma Shan Zheng','ZCOOL XiaoWei'])('keeps %s in the East Asian slot on replay',font=>{
 const result=replayDocxOperations(baseline,[{kind:'formatRange',blockId:'p0',expectedObjectSha256:'sha',from:0,to:5,style:{fontFamily:font}}],anchors)
 expect(result.content![0]!.content![0]!.marks![0]!.attrs).toMatchObject({font,eastAsiaFont:font,fontAscii:'Calibri'})
})
