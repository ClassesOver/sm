import {expect,it} from 'vitest'
import {applyRowColumnOps,createBlankWorkbook,readWorkbook} from '../src'
import {shiftRangedFeatures} from '../src/structural'
import {assemblePackage,createBufferEntrySource} from '../src/zip'
const id='{00000000-0000-0000-0000-000000000001}'
const base='<conditionalFormatting sqref="B1:B3"><cfRule type="dataBar" priority="1"><dataBar><cfvo type="min"/><cfvo type="max"/><color rgb="FF638EC6"/></dataBar><extLst><ext uri="{B025F937-C7B1-47D3-B67F-A62EFF666E3E}" xmlns:x14="http://schemas.microsoft.com/office/spreadsheetml/2009/9/main"><x14:id>'+id+'</x14:id></ext></extLst></cfRule></conditionalFormatting>'
const twin='<extLst><ext uri="{78C0D931-6437-407D-A8EE-F0AAD7539E65}" xmlns:x14="http://schemas.microsoft.com/office/spreadsheetml/2009/9/main"><x14:conditionalFormattings><x14:conditionalFormatting xmlns:xm="http://schemas.microsoft.com/office/excel/2006/main"><x14:cfRule type="dataBar" priority="1" id="'+id+'"><x14:dataBar><x14:cfvo type="autoMin"/><x14:cfvo type="autoMax"/></x14:dataBar></x14:cfRule><xm:sqref>B1:B3</xm:sqref></x14:conditionalFormatting></x14:conditionalFormattings></ext><ext uri="unrelated"><custom value="B1:B3"/></ext></extLst>'
const xml='<worksheet><sheetData/>'+base+twin+'</worksheet>'
it.each([
 [{axis:'row',start:0,delta:1},'B2:B4'],
 [{axis:'column',start:0,delta:1},'C1:C3'],
 [{axis:'row',start:1,delta:-1},'B1:B2'],
] as const)('shifts linked CF base and twin together for %j',(spec,expected)=>{
 const shifted=shiftRangedFeatures(xml,spec)
 expect(shifted).toContain('sqref="'+expected+'"');expect(shifted).toContain('<xm:sqref>'+expected+'</xm:sqref>')
 expect(shifted).toContain('<ext uri="unrelated"><custom value="B1:B3"/></ext>')
})
it('deletes the complete linked scope without leaving a dangling twin',()=>{
 const shifted=shiftRangedFeatures(xml,{axis:'row',start:0,delta:-3})
 expect(shifted).not.toContain('<conditionalFormatting');expect(shifted).not.toContain('<x14:conditionalFormatting');expect(shifted).not.toContain(id)
 expect(shifted).toContain('<ext uri="unrelated"><custom value="B1:B3"/></ext>')
})
it.each([
 ['scope',xml.replace('<xm:sqref>B1:B3</xm:sqref>','<xm:sqref>C1:C3</xm:sqref>')],
 ['duplicate twin',xml.replace('</x14:conditionalFormattings>',twin.match(/<x14:conditionalFormatting\b[\s\S]*?<\/x14:conditionalFormatting>/)![0]+'</x14:conditionalFormattings>')],
 ['foreign namespace',xml.replace('http://schemas.microsoft.com/office/excel/2006/main','https://foreign.invalid')],
])('refuses ambiguous linked %s before a partial shift',(_name,input)=>{
 expect(()=>shiftRangedFeatures(input,{axis:'row',start:0,delta:1})).toThrow(/linked/i)
})
it('keeps linked CF readable through real ZIP insert/remove and preserves an unrelated sheet',async()=>{
 const bytes=await createBlankWorkbook(),source=await createBufferEntrySource(bytes),path='xl/worksheets/sheet1.xml'
 const sheet=(await source.readText(path)).replace('</worksheet>',base+twin+'</worksheet>')
 const second='<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData/><extLst><ext uri="foreign"><data text="B1:B3"/></ext></extLst></worksheet>'
 const book=(await source.readText('xl/workbook.xml')).replace('</sheets>','<sheet name="Other" sheetId="2" r:id="rId999"/></sheets>')
 const rel=(await source.readText('xl/_rels/workbook.xml.rels')).replace('</Relationships>','<Relationship Id="rId999" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet2.xml"/></Relationships>')
 const input=(await assemblePackage(bytes,{replaced:new Map([[path,sheet],['xl/workbook.xml',book],['xl/_rels/workbook.xml.rels',rel]]),added:new Map([['xl/worksheets/sheet2.xml',second]]),addedBinary:new Map(),removedEntries:[],addedEntries:['xl/worksheets/sheet2.xml'],touchedEntries:[path,'xl/workbook.xml','xl/_rels/workbook.xml.rels','xl/worksheets/sheet2.xml']})).buffer
 for(const op of [{kind:'insert-rows',index:0,count:1},{kind:'remove-rows',index:1,count:1}] as const){
  const changed=await applyRowColumnOps(input,'Sheet1',[op]),model=(await readWorkbook(changed)).sheets[0]!.conditionalFormatting!
  expect(model.issues).toEqual([]);expect(model.linkedRuleIds).toEqual([id]);expect(await(await createBufferEntrySource(changed)).readText('xl/worksheets/sheet2.xml')).toBe(second)
 }
 const deleted=await applyRowColumnOps(input,'Sheet1',[{kind:'remove-rows',index:0,count:3}])
 expect((await readWorkbook(deleted)).sheets[0]!.conditionalFormatting!.issues).toEqual([])
 expect(await(await createBufferEntrySource(deleted)).readText(path)).not.toContain(id)
})
it('drops an empty extension wrapper only after its last known linked CF dies',()=>{
 const onlyLinked=xml.replace('<ext uri="unrelated"><custom value="B1:B3"/></ext>','')
 const shifted=shiftRangedFeatures(onlyLinked,{axis:'row',start:0,delta:-3})
 expect(shifted).not.toContain('<extLst');expect(shifted).not.toContain('<x14:conditionalFormattings')
})
it('moves linked and ordinary rules sharing a base scope without altering either condition',()=>{
 const ordinary='<cfRule type="expression" priority="2"><formula>B1&gt;0</formula></cfRule>'
 const mixed=xml.replace('</conditionalFormatting>',ordinary+'</conditionalFormatting>')
 const shifted=shiftRangedFeatures(mixed,{axis:'row',start:0,delta:1})
 expect(shifted).toContain('sqref="B2:B4"');expect(shifted).toContain('<xm:sqref>B2:B4</xm:sqref>');expect(shifted).toContain(ordinary)
 expect((shifted.match(/<cfRule\b/g)??[])).toHaveLength(2)
})
