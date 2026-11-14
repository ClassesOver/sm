import JSZip from 'jszip'
import { expect, it } from 'vitest'
import { createBlankWorkbook } from '../packages/xlsx-engine/src/index'
import { applyWorkbookOperations } from './operations'

async function linkedFixture() {
 const zip = await JSZip.loadAsync(await createBlankWorkbook())
 zip.file('xl/workbook.xml',(await zip.file('xl/workbook.xml')!.async('string')).replace('</workbook>','<externalReferences><externalReference r:id="ext1"/><externalReference r:id="ext2"/></externalReferences></workbook>'))
 zip.file('xl/_rels/workbook.xml.rels',(await zip.file('xl/_rels/workbook.xml.rels')!.async('string')).replace('</Relationships>','<Relationship Id="ext1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/externalLink" Target="externalLinks/externalLink1.xml"/><Relationship Id="ext2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/externalLink" Target="externalLinks/externalLink2.xml"/></Relationships>'))
 for (let n=1;n<=2;n++) {
  zip.file('xl/externalLinks/externalLink'+n+'.xml','<externalLink xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><externalBook r:id="rId1"><sheetNames><sheetName val="Data"/></sheetNames></externalBook></externalLink>')
  zip.file('xl/externalLinks/_rels/externalLink'+n+'.xml.rels','<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/externalLinkPath" Target="file:///source'+n+'.xlsx" TargetMode="External"/></Relationships>')
 }
 zip.file('xl/worksheets/sheet1.xml','<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData><row r="1"><c r="A1" s="0"><f>[1]Data!A1*2</f><v>6</v></c><c r="B1" t="b"><f>[1]Data!B1</f><v>1</v></c><c r="C1" t="str"><f>[1]Data!C1</f><v>text</v></c><c r="D1"><f>[2]Data!A1</f><v>3</v></c><c r="E1" t="inlineStr"><is><t>[2]Data!A1</t></is></c></row></sheetData></worksheet>')
 zip.file('customXml/keep.bin',new Uint8Array([1,2,3,255]))
 return zip.generateAsync({type:'uint8array'})
}
it('changes only the indexed source relationship and preserves formulas caches and other entries',async()=>{
 const before=await linkedFixture(),after=await applyWorkbookOperations(before,[{kind:'retargetExternalLink',index:1,expectedTarget:'file:///source1.xlsx',target:'replacement.xlsx'}])
 const a=await JSZip.loadAsync(before),b=await JSZip.loadAsync(after)
 expect(await b.file('xl/externalLinks/_rels/externalLink1.xml.rels')!.async('string')).toContain('Target="replacement.xlsx"')
 for(const path of Object.keys(a.files).filter(p=>!a.files[p]!.dir&&p!=='xl/externalLinks/_rels/externalLink1.xml.rels'))expect(await b.file(path)!.async('uint8array')).toEqual(await a.file(path)!.async('uint8array'))
})
it('breaks typed cached cells renumbers survivors and removes only owned link parts',async()=>{
 const bytes=await applyWorkbookOperations(await linkedFixture(),[{kind:'breakExternalLink',index:1,expectedTarget:'file:///source1.xlsx'}]),zip=await JSZip.loadAsync(bytes),sheet=await zip.file('xl/worksheets/sheet1.xml')!.async('string')
 expect(sheet).toContain('<c r="A1" s="0"><v>6</v></c>');expect(sheet).toContain('t="b"><v>1</v>');expect(sheet).toContain('<t xml:space="preserve">text</t>');expect(sheet).toContain('<f>[1]Data!A1</f>');expect(sheet).toContain('<t>[2]Data!A1</t>')
 expect(zip.file('xl/externalLinks/externalLink1.xml')).toBeNull();expect(zip.file('xl/externalLinks/_rels/externalLink1.xml.rels')).toBeNull();expect(zip.file('xl/externalLinks/externalLink2.xml')).not.toBeNull();expect(await zip.file('customXml/keep.bin')!.async('uint8array')).toEqual(new Uint8Array([1,2,3,255]))
})
it('rejects stale identities and unsupported break carriers before creating output',async()=>{
 const bytes=await linkedFixture()
 await expect(applyWorkbookOperations(bytes,[{kind:'retargetExternalLink',index:1,expectedTarget:'other.xlsx',target:'x.xlsx'}])).rejects.toThrow(/来源|变化/)
 const zip=await JSZip.loadAsync(bytes);zip.file('xl/workbook.xml',(await zip.file('xl/workbook.xml')!.async('string')).replace('</workbook>','<definedNames><definedName name="External">[1]Data!A1</definedName></definedNames></workbook>'))
 await expect(applyWorkbookOperations(await zip.generateAsync({type:'uint8array'}),[{kind:'breakExternalLink',index:1,expectedTarget:'file:///source1.xlsx'}])).rejects.toThrow(/defined name|名称/)
})

it('prepares source-backed formulas for the existing calculation engine and keeps unsupported formulas explicit', async()=>{
 const {prepareExternalLinkUpdate}=await import('../packages/xlsx-engine/src/external-links-update')
 const source=await JSZip.loadAsync(await createBlankWorkbook('Data'))
 source.file('xl/worksheets/sheet1.xml','<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData><row r="1"><c r="A1"><v>12</v></c><c r="B1" t="b"><v>0</v></c><c r="C1" t="inlineStr"><is><t>new text</t></is></c></row></sheetData></worksheet>')
 const report=await prepareExternalLinkUpdate(await linkedFixture(),[{index:1,expectedTarget:'file:///source1.xlsx',bytes:await source.generateAsync({type:'uint8array'})}])
 expect(report.candidates.map(item=>[item.address,item.expression])).toEqual([['A1','=12*2'],['B1','=FALSE'],['C1','="new text"']])
 expect(report.skipped).toEqual([expect.objectContaining({address:'D1',reason:expect.stringMatching(/授权|选择/)})])
})
it('writes typed update caches while retaining exact formulas and refuses stale formula replay', async()=>{
 const op={kind:'updateExternalLinkCaches',updates:[{sheetName:'Sheet1',address:'A1',formula:'[1]Data!A1*2',value:24},{sheetName:'Sheet1',address:'B1',formula:'[1]Data!B1',value:false},{sheetName:'Sheet1',address:'C1',formula:'[1]Data!C1',value:'new text'}]}
 const bytes=await applyWorkbookOperations(await linkedFixture(),[op]),zip=await JSZip.loadAsync(bytes),sheet=await zip.file('xl/worksheets/sheet1.xml')!.async('string')
 expect(sheet).toContain('<f>[1]Data!A1*2</f><v>24</v>');expect(sheet).toContain('t="b"><f>[1]Data!B1</f><v>0</v>');expect(sheet).toContain('t="str"><f>[1]Data!C1</f><v>new text</v>')
 await expect(applyWorkbookOperations(bytes,[{...op,updates:[{...op.updates[0],formula:'changed'}]}])).rejects.toThrow(/公式|变化/)
})
it('binds authorized file bytes by digest without modifying the workbook and rejects identity tampering',async()=>{
 const source=await createBlankWorkbook('Data'),{sha256Hex}=await import('../packages/xlsx-engine/src/sha256'),bytes=await linkedFixture()
 const operation={kind:'bindExternalLinkSource',index:1,expectedTarget:'file:///source1.xlsx',name:'source1.xlsx',mediaType:'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',size:source.length,sha256:await sha256Hex(source),bytesBase64:Buffer.from(source).toString('base64')}
 expect(await applyWorkbookOperations(bytes,[operation])).toEqual(bytes)
 await expect(applyWorkbookOperations(bytes,[{...operation,sha256:'0'.repeat(64)}])).rejects.toThrow(/身份|摘要/)
})
it('refuses formula mutation on a protected worksheet and refuses aliased link-part ownership',async()=>{
 const zip=await JSZip.loadAsync(await linkedFixture());zip.file('xl/worksheets/sheet1.xml',(await zip.file('xl/worksheets/sheet1.xml')!.async('string')).replace('</worksheet>','<sheetProtection sheet="1"/></worksheet>'))
 await expect(applyWorkbookOperations(await zip.generateAsync({type:'uint8array'}),[{kind:'breakExternalLink',index:1,expectedTarget:'file:///source1.xlsx'}])).rejects.toThrow(/保护/)
 const alias=await JSZip.loadAsync(await linkedFixture());alias.file('xl/_rels/workbook.xml.rels',(await alias.file('xl/_rels/workbook.xml.rels')!.async('string')).replace('Target="externalLinks/externalLink2.xml"','Target="externalLinks/externalLink1.xml"'))
 await expect(applyWorkbookOperations(await alias.generateAsync({type:'uint8array'}),[{kind:'breakExternalLink',index:1,expectedTarget:'file:///source1.xlsx'}])).rejects.toThrow(/共享|重复|身份/)
})
it('handles escaped targets and canonical internal link paths before breaking',async()=>{
 const zip=await JSZip.loadAsync(await linkedFixture())
 zip.file('xl/_rels/workbook.xml.rels',(await zip.file('xl/_rels/workbook.xml.rels')!.async('string')).replace('Target="externalLinks/externalLink1.xml"','Target="./externalLinks/externalLink1.xml"'))
 zip.file('xl/externalLinks/_rels/externalLink1.xml.rels',(await zip.file('xl/externalLinks/_rels/externalLink1.xml.rels')!.async('string')).replace('file:///source1.xlsx','file:///a&amp;b.xlsx'))
 const bytes=await applyWorkbookOperations(await zip.generateAsync({type:'uint8array'}),[{kind:'breakExternalLink',index:1,expectedTarget:'file:///a&b.xlsx'}]),out=await JSZip.loadAsync(bytes)
 expect(out.file('xl/externalLinks/externalLink1.xml')).toBeNull()
})
it('does not treat external-reference-looking quoted text as a formula dependency',async()=>{
 const zip=await JSZip.loadAsync(await linkedFixture());zip.file('xl/worksheets/sheet1.xml',(await zip.file('xl/worksheets/sheet1.xml')!.async('string')).replace('<f>[2]Data!A1</f>','<f>IF(1=1,&quot;[1]Data!A1&quot;,[2]Data!A1)</f>'))
 const bytes=await applyWorkbookOperations(await zip.generateAsync({type:'uint8array'}),[{kind:'breakExternalLink',index:1,expectedTarget:'file:///source1.xlsx'}]),out=await JSZip.loadAsync(bytes)
 expect(await out.file('xl/worksheets/sheet1.xml')!.async('string')).toContain('<f>IF(1=1,&quot;[1]Data!A1&quot;,[1]Data!A1)</f>')
})
it('leaves ordinary table formulas and quoted bracket text out of external updates',async()=>{
 const zip=await JSZip.loadAsync(await linkedFixture());zip.file('xl/worksheets/sheet1.xml',(await zip.file('xl/worksheets/sheet1.xml')!.async('string')).replace('</row>','<c r="F1"><f>SUM(Table1[Amount])</f><v>5</v></c><c r="G1" t="str"><f>&quot;[1]Data!A1&quot;</f><v>text</v></c></row>'))
 const {prepareExternalLinkUpdate}=await import('../packages/xlsx-engine/src/external-links-update'),report=await prepareExternalLinkUpdate(await zip.generateAsync({type:'uint8array'}),[])
 expect(report.skipped.map(item=>item.address)).toEqual(['A1','B1','C1','D1']);expect(report.candidates).toEqual([])
})
it('freezes shared-string formula cache as its actual text rather than string-table index',async()=>{
 const zip=await JSZip.loadAsync(await linkedFixture());zip.file('xl/sharedStrings.xml','<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><si><t>actual text</t></si></sst>');zip.file('xl/worksheets/sheet1.xml',(await zip.file('xl/worksheets/sheet1.xml')!.async('string')).replace('r="C1" t="str"','r="C1" t="s"').replace('<v>text</v>','<v>0</v>'))
 const out=await JSZip.loadAsync(await applyWorkbookOperations(await zip.generateAsync({type:'uint8array'}),[{kind:'breakExternalLink',index:1,expectedTarget:'file:///source1.xlsx'}]))
 expect(await out.file('xl/worksheets/sheet1.xml')!.async('string')).toContain('<t xml:space="preserve">actual text</t>')
})
it('rejects foreign-namespace external link parts rather than trusting lookalike elements',async()=>{
 const zip=await JSZip.loadAsync(await linkedFixture());zip.file('xl/externalLinks/externalLink1.xml',(await zip.file('xl/externalLinks/externalLink1.xml')!.async('string')).replace('http://schemas.openxmlformats.org/spreadsheetml/2006/main','urn:foreign'))
 await expect(applyWorkbookOperations(await zip.generateAsync({type:'uint8array'}),[{kind:'retargetExternalLink',index:1,expectedTarget:'file:///source1.xlsx',target:'replacement.xlsx'}])).rejects.toThrow(/命名空间|身份/)
})
