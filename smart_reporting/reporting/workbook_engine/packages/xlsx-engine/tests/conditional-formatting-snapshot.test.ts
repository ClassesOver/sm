import {expect,it} from 'vitest'
import { createBlankWorkbook } from '../src/index'
import { createBufferEntrySource } from '../src/zip'
import { replaceConditionalFormattingSnapshots } from '../src/conditional-formatting-snapshot'
import { readConditionalFormattingSnapshot } from '../src/conditional-formatting-read'
import { applyCfRules, type CfWireRule } from '../src/conditional-formatting-source'
import { StylesheetEditor } from '../src/styles-write'
const area=[{startRow:0,endRow:2,startColumn:0,endColumn:0}]
const bar=(color:string):CfWireRule=>({ranges:area,stopIfTrue:false,rule:{type:'dataBar',isShowValue:true,config:{min:{type:'min'},max:{type:'max'},positiveColor:color}}})
it('creates, replaces and deletes a full sheet snapshot through real ZIP bytes',async()=>{
 const first=await replaceConditionalFormattingSnapshots(await createBlankWorkbook(),[{sheetName:'Sheet1',rules:[bar('#112233')]}])
 const edited=await replaceConditionalFormattingSnapshots(first,[{sheetName:'Sheet1',rules:[bar('#445566')]}])
 let source=await createBufferEntrySource(edited)
 let model=readConditionalFormattingSnapshot(await source.readText('xl/worksheets/sheet1.xml'),await source.readText('xl/styles.xml'))
 expect(model.issues).toEqual([]);expect(model.rules).toHaveLength(1);expect((model.rules[0]!.rule.config as any).positiveColor).toBe('#445566')
 const cleared=await replaceConditionalFormattingSnapshots(edited,[{sheetName:'Sheet1',rules:[]}]);source=await createBufferEntrySource(cleared)
 model=readConditionalFormattingSnapshot(await source.readText('xl/worksheets/sheet1.xml'),await source.readText('xl/styles.xml'));expect(model.issues).toEqual([]);expect(model.rules).toEqual([])
})
const highlights:Record<string,unknown>[]=[
 {subType:'number',operator:'between',value:[1,4]},
 ...['containsText','notContainsText','beginsWith','endsWith','equal','notEqual','containsBlanks','notContainsBlanks','containsErrors','notContainsErrors'].map(operator=>({subType:'text',operator,value:'A & "B"'})),
 {subType:'duplicateValues'},{subType:'uniqueValues'},
 {subType:'rank',value:3,isPercent:true,isBottom:true},
 ...['greaterThan','greaterThanOrEqual','lessThan','lessThanOrEqual'].map(operator=>({subType:'average',operator})),
 {subType:'formula',value:'A1>0'},
]
it.each(highlights)('roundtrips the fixed-source highlight rule %j',async shape=>{
 const b=await createBufferEntrySource(await createBlankWorkbook()),style=new StylesheetEditor(await b.readText('xl/styles.xml'))
 const rule:CfWireRule={ranges:area,stopIfTrue:true,rule:{type:'highlightCell',...shape,style:{bl:1,it:1,st:{s:1},ul:{s:1},cl:{rgb:'#112233'},bg:{rgb:'#FFEEDD'}}}}
 const xml=applyCfRules('<worksheet><sheetData/></worksheet>',[rule],style),parsed=readConditionalFormattingSnapshot(xml,style.serialize())
 expect(parsed.issues).toEqual([]);expect(parsed.rules).toHaveLength(1)
 // Source renderer intentionally projects some cellIs conditions to formulas;
 // unchanged persistence must preserve the original cellIs, not rewrite it.
 const {assemblePackage}=await import('../src/zip')
 const base=await createBlankWorkbook(),path='xl/worksheets/sheet1.xml'
 const input=(await assemblePackage(base,{replaced:new Map([[path,xml],['xl/styles.xml',style.serialize()]]),added:new Map(),addedBinary:new Map(),removedEntries:[],addedEntries:[],touchedEntries:[path,'xl/styles.xml']})).buffer
 const saved=await createBufferEntrySource(await replaceConditionalFormattingSnapshots(input,[{sheetName:'Sheet1',rules:parsed.rules}]))
 expect(await saved.readText(path)).toBe(xml);expect(await saved.readText('xl/styles.xml')).toBe(style.serialize())
})
it('retains the original XML and reports unknown rule and extension identities instead of silently accepting an incomplete snapshot',()=>{
 const xml='<worksheet><sheetData/><conditionalFormatting sqref="A1"><cfRule type="future" priority="1"><alien/></cfRule></conditionalFormatting><extLst><ext uri="unknown"><x:cfRule/></ext></extLst></worksheet>'
 const model=readConditionalFormattingSnapshot(xml,'<styleSheet/>');expect(model.sourceXml).toBe(xml);expect(model.issues.length).toBeGreaterThan(0)
})

it.each(['3Arrows','4Rating','5Rating'])('roundtrips %s icon threshold order and reverse',async iconType=>{
 const source=await createBufferEntrySource(await createBlankWorkbook()),styles=await source.readText('xl/styles.xml')
 for(const reverse of [false,true]){
  const count=Number(iconType[0]),config=Array.from({length:count},(_,i)=>({iconType,iconId:String(reverse?count-1-i:i),operator:'greaterThanOrEqual',value:i===count-1?{type:'min'}:{type:'percent',value:100-i*20}}))
  const xml=applyCfRules('<worksheet><sheetData/></worksheet>',[{ranges:area,stopIfTrue:false,rule:{type:'iconSet',isShowValue:false,config}}],{internDxf:()=>0})
  const parsed=readConditionalFormattingSnapshot(xml,styles);expect(parsed.issues).toEqual([]);expect(applyCfRules('<worksheet><sheetData/></worksheet>',parsed.rules,{internDxf:()=>0})).toBe(xml)
 }
})
it('roundtrips a three-color scale with formula and percentile thresholds',async()=>{
 const rule:CfWireRule={ranges:area,stopIfTrue:true,rule:{type:'colorScale',config:[{index:2,color:'#00FF00',value:{type:'max'}},{index:0,color:'#FF0000',value:{type:'formula',value:'SUM(A1:A3)'}},{index:1,color:'#FFFFFF',value:{type:'percentile',value:50}}]}}
 const xml=applyCfRules('<worksheet><sheetData/></worksheet>',[rule],{internDxf:()=>0}),parsed=readConditionalFormattingSnapshot(xml,'<styleSheet/>')
 expect(parsed.issues).toEqual([]);expect(applyCfRules('<worksheet><sheetData/></worksheet>',parsed.rules,{internDxf:()=>0})).toBe(xml)
})
it.each([
 ['unknown type',(xml:string)=>xml.replace('type="dataBar"','type="future"')],
 ['unknown rule attribute',(xml:string)=>xml.replace('priority="1"','priority="1" future="yes"')],
 ['out of bounds range',(xml:string)=>xml.replace('A1:A3','XFE1:XFE3')],
 ['duplicate priority',(xml:string)=>xml.replace('</conditionalFormatting>',xml.match(/<cfRule[\s\S]*<\/cfRule>/)![0]+'</conditionalFormatting>')],
 ['linked extension',(xml:string)=>xml.replace('</cfRule>','<extLst><ext uri="linked"><x14:id>id</x14:id></ext></extLst></cfRule>')],
])('rejects incomplete %s source identities',async(_name,mutate)=>{
 const b=await createBufferEntrySource(await createBlankWorkbook()),styles=await b.readText('xl/styles.xml'),xml=applyCfRules('<worksheet><sheetData/></worksheet>',[bar('#112233')],{internDxf:()=>0})
 const original=mutate(xml),parsed=readConditionalFormattingSnapshot(original,styles);expect(parsed.sourceXml).toBe(original);expect(parsed.issues.length).toBeGreaterThan(0)
})
it('detects referenced dxf corruption and unsupported font properties',async()=>{
 const b=await createBufferEntrySource(await createBlankWorkbook()),styles=new StylesheetEditor(await b.readText('xl/styles.xml'))
 const xml=applyCfRules('<worksheet><sheetData/></worksheet>',[{ranges:area,stopIfTrue:false,rule:{type:'highlightCell',subType:'formula',value:'A1>0',style:{bl:1}}}],styles)
 expect(readConditionalFormattingSnapshot(xml.replace('dxfId="0"','dxfId="999"'),styles.serialize()).issues.length).toBeGreaterThan(0)
 expect(readConditionalFormattingSnapshot(xml,styles.serialize().replace('<b/>','<b/><sz val="18"/>')).issues.length).toBeGreaterThan(0)
 expect(readConditionalFormattingSnapshot(xml,styles.serialize().replace('<b/>','<b future="1"/>')).issues.length).toBeGreaterThan(0)
})
it('deduplicates highlight dxfs and preserves all other sheet bytes on replace and clear',async()=>{
 const { applySheetEdits }=await import('../src/index'),{assemblePackage}=await import('../src/zip')
 let bytes=await applySheetEdits(await createBlankWorkbook(),{renames:[],additions:[{name:'Other'}],removals:[],order:['Sheet1','Other']})
 const original=await createBufferEntrySource(bytes),otherPath='xl/worksheets/sheet2.xml',other=await original.readText(otherPath)
 const wire:CfWireRule={ranges:area,stopIfTrue:true,rule:{type:'highlightCell',subType:'formula',value:'A1>0',style:{bl:1,bg:{rgb:'#112233'}}}}
 bytes=await replaceConditionalFormattingSnapshots(bytes,[{sheetName:'Sheet1',rules:[wire,wire]}])
 const first=await createBufferEntrySource(bytes),styles=await first.readText('xl/styles.xml');expect(styles.match(/<dxf>/g)).toHaveLength(1);expect(await first.readText(otherPath)).toBe(other)
 const changed=await replaceConditionalFormattingSnapshots(bytes,[{sheetName:'Sheet1',rules:[wire]}]),after=await createBufferEntrySource(changed);expect(await after.readText('xl/styles.xml')).toBe(styles);expect(await after.readText(otherPath)).toBe(other)
 const sheet=await after.readText('xl/worksheets/sheet1.xml'),corrupt=sheet.replace('priority="1"','priority="1" future="1"')
 const mutation=await assemblePackage(changed,{replaced:new Map([['xl/worksheets/sheet1.xml',corrupt]]),added:new Map(),addedBinary:new Map(),removedEntries:[],addedEntries:[],touchedEntries:['xl/worksheets/sheet1.xml']})
 await expect(replaceConditionalFormattingSnapshots(mutation.buffer,[{sheetName:'Sheet1',rules:[]}])).rejects.toThrow(/incomplete/)
})
it('accepts schema-default flags but rejects hidden block metadata and retains sparse priorities in evaluation order',()=>{
 const first=applyCfRules('<worksheet><sheetData/></worksheet>',[bar('#112233'),bar('#445566')],{internDxf:()=>0})
 const defaults=first.replace(/<dataBar>/g,'<dataBar showValue="true">').replace('priority="1"','priority="20" stopIfTrue="false"').replace('priority="2"','priority="3"')
 const parsed=readConditionalFormattingSnapshot(defaults,'<styleSheet/>');expect(parsed.issues).toEqual([]);expect((parsed.rules[0]!.rule.config as any).positiveColor).toBe('#445566')
 expect(readConditionalFormattingSnapshot(first.replace('sqref="A1:A3"','sqref="A1:A3" pivot="1"'),'<styleSheet/>').issues.length).toBeGreaterThan(0)
})
it('accepts conventional dxf solid foreground color but rejects unknown dxf attributes',async()=>{
 const source=await createBufferEntrySource(await createBlankWorkbook()),styles=new StylesheetEditor(await source.readText('xl/styles.xml'))
 const xml=applyCfRules('<worksheet><sheetData/></worksheet>',[{ranges:area,stopIfTrue:false,rule:{type:'highlightCell',subType:'formula',value:'A1>0',style:{bg:{rgb:'#112233'}}}}],styles)
 const external=styles.serialize().replace('<patternFill><bgColor rgb="FF112233"/></patternFill>','<patternFill patternType="solid"><fgColor rgb="FF112233"/><bgColor indexed="64"/></patternFill>')
 expect(readConditionalFormattingSnapshot(xml,external).issues).toEqual([])
 expect(readConditionalFormattingSnapshot(xml,external.replace('<dxf>','<dxf future="1">')).issues.length).toBeGreaterThan(0)
})
it('projects the source default negative data-bar fill instead of guessing same-as-positive',()=>{
 const xml=applyCfRules('<worksheet><sheetData/></worksheet>',[bar('#112233')],{internDxf:()=>0})
 const parsed=readConditionalFormattingSnapshot(xml,'<styleSheet/>');expect(parsed.issues).toEqual([]);expect((parsed.rules[0]!.rule.config as any).nativeColor).toBe('#FF0000')
})
const x14ns='http://schemas.microsoft.com/office/spreadsheetml/2009/9/main',linkedId='{00000000-0000-0000-0000-000000000001}'
const linked='<conditionalFormatting sqref="B1:B3"><cfRule type="dataBar" priority="3"><dataBar><cfvo type="min"/><cfvo type="max"/><color rgb="FF638EC6"/></dataBar><extLst><ext uri="{B025F937-C7B1-47D3-B67F-A62EFF666E3E}" xmlns:x14="'+x14ns+'"><x14:id>'+linkedId+'</x14:id></ext></extLst></cfRule></conditionalFormatting>'
const twin='<extLst><ext uri="{78C0D931-6437-407D-A8EE-F0AAD7539E65}" xmlns:x14="'+x14ns+'"><x14:conditionalFormattings><x14:conditionalFormatting xmlns:xm="http://schemas.microsoft.com/office/excel/2006/main"><x14:cfRule type="dataBar" priority="3" id="'+linkedId+'"><x14:dataBar minLength="0" maxLength="100"><x14:cfvo type="autoMin"/><x14:cfvo type="autoMax"/><x14:negativeFillColor rgb="FFFF0000"/></x14:dataBar></x14:cfRule><xm:sqref>B1:B3</xm:sqref></x14:conditionalFormatting></x14:conditionalFormattings></ext></extLst>'
async function replacePart(bytes:Uint8Array,path:string,xml:string){const {assemblePackage}=await import('../src/zip');return(await assemblePackage(bytes,{replaced:new Map([[path,xml]]),added:new Map(),addedBinary:new Map(),removedEntries:[],addedEntries:[],touchedEntries:[path]})).buffer}
it('preserves a paired linked x14 rule byte-for-byte while replacing another rule',async()=>{
 const base=await createBlankWorkbook(),source=await createBufferEntrySource(base),sheet=await source.readText('xl/worksheets/sheet1.xml'),xml=sheet.replace('</worksheet>',linked+twin+'</worksheet>')
 const bytes=await replacePart(base,'xl/worksheets/sheet1.xml',xml),model=readConditionalFormattingSnapshot(xml,await source.readText('xl/styles.xml'))
 expect(model.issues).toEqual([]);expect(model.rules).toHaveLength(1)
 const saved=await replaceConditionalFormattingSnapshots(bytes,[{sheetName:'Sheet1',rules:[...model.rules,bar('#112233')]}]),out=await(await createBufferEntrySource(saved)).readText('xl/worksheets/sheet1.xml')
 expect(out).toContain(linked);expect(out).toContain(twin);expect(out.match(/<cfRule\b/g)).toHaveLength(2)
 await expect(replaceConditionalFormattingSnapshots(bytes,[{sheetName:'Sheet1',rules:[]}])).rejects.toThrow()
 const changed=structuredClone(model.rules);(changed[0]!.rule.config as any).positiveColor='#112233'
 await expect(replaceConditionalFormattingSnapshots(bytes,[{sheetName:'Sheet1',rules:changed}])).rejects.toThrow()
})
it('creates only necessary stylesheet parts when highlight rules first need dxfs',async()=>{
 const {assemblePackage}=await import('../src/zip'),base=await createBlankWorkbook(),source=await createBufferEntrySource(base)
 const ct=(await source.readText('[Content_Types].xml')).replace(/<Override\b[^>]*PartName="\/xl\/styles.xml"[^>]*\/>/g,''),rels=(await source.readText('xl/_rels/workbook.xml.rels')).replace(/<Relationship\b[^>]*Type="[^"]*\/styles"[^>]*\/>/g,'')
 const stripped=(await assemblePackage(base,{replaced:new Map([['[Content_Types].xml',ct],['xl/_rels/workbook.xml.rels',rels]]),added:new Map(),addedBinary:new Map(),removedEntries:['xl/styles.xml'],addedEntries:[],touchedEntries:['[Content_Types].xml','xl/_rels/workbook.xml.rels','xl/styles.xml']})).buffer
 const barOnly=await replaceConditionalFormattingSnapshots(stripped,[{sheetName:'Sheet1',rules:[bar('#112233')]}]);expect(await(await createBufferEntrySource(barOnly)).has('xl/styles.xml')).toBe(false)
 const wire:CfWireRule={ranges:area,stopIfTrue:false,rule:{type:'highlightCell',subType:'formula',value:'A1>0',style:{bl:1}}}
 const saved=await replaceConditionalFormattingSnapshots(stripped,[{sheetName:'Sheet1',rules:[wire]}]),out=await createBufferEntrySource(saved)
 expect(await out.has('xl/styles.xml')).toBe(true);expect(await out.readText('[Content_Types].xml')).toContain('PartName="/xl/styles.xml"');expect(await out.readText('xl/_rels/workbook.xml.rels')).toContain('Target="styles.xml"')
 expect(readConditionalFormattingSnapshot(await out.readText('xl/worksheets/sheet1.xml'),await out.readText('xl/styles.xml')).issues).toEqual([])
})
it.each([
 ['missing twin',()=>linked],
 ['wrong twin range',()=>linked+twin.replace('<xm:sqref>B1:B3','<xm:sqref>C1:C3')],
 ['duplicate id',()=>linked+twin+twin],
 ['foreign x14 namespace',()=>linked+twin.replace('xmlns:x14="'+x14ns+'"','xmlns:x14="https://foreign.invalid"')],
 ['foreign xm namespace',()=>linked+twin.replace('http://schemas.microsoft.com/office/excel/2006/main','https://foreign.invalid')],
 ['different twin priority',()=>linked+twin.replace('priority="3"','priority="4"')],
])('does not authorize linked %s as a complete editable snapshot',async(_name,make)=>{
 const base=await createBlankWorkbook(),source=await createBufferEntrySource(base),sheet=await source.readText('xl/worksheets/sheet1.xml'),xml=sheet.replace('</worksheet>',make()+'</worksheet>')
 const bytes=await replacePart(base,'xl/worksheets/sheet1.xml',xml)
 expect(readConditionalFormattingSnapshot(xml,await source.readText('xl/styles.xml')).issues.length).toBeGreaterThan(0)
 await expect(replaceConditionalFormattingSnapshots(bytes,[{sheetName:'Sheet1',rules:[]}])).rejects.toThrow(/incomplete/)
})
it('refuses to retarget a foreign stylesheet relationship when first adding a dxf',async()=>{
 const {assemblePackage}=await import('../src/zip'),base=await createBlankWorkbook(),source=await createBufferEntrySource(base),path='xl/_rels/workbook.xml.rels'
 const rels=(await source.readText(path)).replace('Target="styles.xml"','Target="../foreign.xml"')
 const bytes=(await assemblePackage(base,{replaced:new Map([[path,rels]]),added:new Map(),addedBinary:new Map(),removedEntries:['xl/styles.xml'],addedEntries:[],touchedEntries:[path,'xl/styles.xml']})).buffer
 const wire:CfWireRule={ranges:area,stopIfTrue:false,rule:{type:'highlightCell',subType:'formula',value:'A1>0',style:{bl:1}}}
 await expect(replaceConditionalFormattingSnapshots(bytes,[{sheetName:'Sheet1',rules:[wire]}])).rejects.toThrow(/nonstandard styles relationship/)
})
it('renders retained x14 negative fill and gradient while leaving their source XML untouched',()=>{
 const xml='<worksheet><sheetData/>'+linked+twin.replace('minLength="0"','gradient="0" minLength="0"').replace('FFFF0000','FF00FF00')+'</worksheet>'
 const parsed=readConditionalFormattingSnapshot(xml,'<styleSheet/>');expect(parsed.issues).toEqual([]);expect((parsed.rules[0]!.rule.config as any).nativeColor).toBe('#00FF00');expect((parsed.rules[0]!.rule.config as any).isGradient).toBe(false)
 expect(applyCfRules(xml,parsed.rules,{internDxf:()=>0})).toBe(xml)
})
it('does not silently discard an edit to a preserved x14-only visual property',async()=>{
 const bytes=await createBlankWorkbook(),source=await createBufferEntrySource(bytes),sheet=(await source.readText('xl/worksheets/sheet1.xml')).replace('</worksheet>',linked+twin+'</worksheet>'),input=await replacePart(bytes,'xl/worksheets/sheet1.xml',sheet)
 const parsed=readConditionalFormattingSnapshot(sheet,await source.readText('xl/styles.xml'));(parsed.rules[0]!.rule.config as any).nativeColor='#112233'
 await expect(replaceConditionalFormattingSnapshots(input,[{sheetName:'Sheet1',rules:parsed.rules}])).rejects.toThrow(/linked source rule must remain unchanged/)
})
it.each(['00','80','FF'])('normalizes source-display ARGB %s consistently in bars, scales and dxfs',async alpha=>{
 const base=await createBlankWorkbook(),source=await createBufferEntrySource(base),stylesXml=await source.readText('xl/styles.xml')
 const wires:CfWireRule[]=[bar('#112233'),{ranges:area,stopIfTrue:false,rule:{type:'colorScale',config:[{index:0,color:'#112233',value:{type:'min'}},{index:1,color:'#445566',value:{type:'max'}}]}},{ranges:area,stopIfTrue:false,rule:{type:'highlightCell',subType:'formula',value:'A1>0',style:{cl:{rgb:'#112233'},bg:{rgb:'#445566'}}}}]
 const styles=new StylesheetEditor(stylesXml),xml=applyCfRules('<worksheet><sheetData/></worksheet>',wires,styles).replace(/rgb="FF/g,`rgb="${alpha}`),style=styles.serialize().replace(/rgb="FF/g,`rgb="${alpha}`)
 const parsed=readConditionalFormattingSnapshot(xml,style);expect(parsed.issues).toEqual([]);expect(parsed.rules).toHaveLength(3)
 expect((parsed.rules[0]!.rule.config as any).positiveColor).toBe('#112233');expect((parsed.rules[2]!.rule.style as any).bg.rgb).toBe('#445566')
})
it('imports a no-styles workbook through the public reader without adding parts or losing formulas and plain CF',async()=>{
 const {readWorkbook,applyCellEdits}=await import('../src/index'),{assemblePackage}=await import('../src/zip')
 const base=await applyCellEdits(await createBlankWorkbook(),[{sheetName:'Sheet1',row:0,column:0,writeValue:true,cell:{value:3}},{sheetName:'Sheet1',row:0,column:1,writeValue:true,cell:{value:6,formula:'=A1*2'}}]),source=await createBufferEntrySource(base)
 const ct=(await source.readText('[Content_Types].xml')).replace(/<Override\b[^>]*PartName="\/xl\/styles.xml"[^>]*\/>/g,''),rels=(await source.readText('xl/_rels/workbook.xml.rels')).replace(/<Relationship\b[^>]*Type="[^"]*\/styles"[^>]*\/>/g,'')
 const sheet=applyCfRules(await source.readText('xl/worksheets/sheet1.xml'),[bar('#112233')],{internDxf:()=>0})
 const input=(await assemblePackage(base,{replaced:new Map([['[Content_Types].xml',ct],['xl/_rels/workbook.xml.rels',rels],['xl/worksheets/sheet1.xml',sheet]]),added:new Map(),addedBinary:new Map(),removedEntries:['xl/styles.xml'],addedEntries:[],touchedEntries:['[Content_Types].xml','xl/_rels/workbook.xml.rels','xl/styles.xml','xl/worksheets/sheet1.xml']})).buffer
 const before=Uint8Array.from(input),model=await readWorkbook(input)
 expect(model.styles.cellXfs).toHaveLength(1);expect(model.sheets[0]!.cells.A1!.value).toBe(3);expect(model.sheets[0]!.cells.B1!.formula).toBe('=A1*2')
 expect(model.styles.fonts[0]!.family).toBe('');expect(model.styles.fonts[0]!.size).toBeUndefined();expect(model.styles.fonts[0]!.color).toBeUndefined()
 expect(model.sheets[0]!.conditionalFormatting!.issues).toEqual([]);expect(model.sheets[0]!.conditionalFormatting!.rules).toHaveLength(1)
 expect(await(await createBufferEntrySource(input)).has('xl/styles.xml')).toBe(false);expect(input).toEqual(before)
 const missingDxf=sheet.replace('type="dataBar"','type="cellIs" operator="greaterThan" dxfId="0"').replace(/<dataBar>[\s\S]*?<\/dataBar>/,'<formula>5</formula>')
 const corrupt=await replacePart(input,'xl/worksheets/sheet1.xml',missingDxf),incomplete=await readWorkbook(corrupt)
 expect(incomplete.sheets[0]!.conditionalFormatting!.issues.length).toBeGreaterThan(0)
 await expect(replaceConditionalFormattingSnapshots(corrupt,[{sheetName:'Sheet1',rules:[]}])).rejects.toThrow(/incomplete/)
})
it('does not normalize malformed RGB or unrelated color-node attributes out of identity checks',()=>{
 const xml=applyCfRules('<worksheet><sheetData/></worksheet>',[bar('#112233')],{internDxf:()=>0})
 for(const bad of [xml.replace('FF112233','ZZ112233'),xml.replace('FF112233','11223'),xml.replace('rgb="FF112233"','rgb="00112233" future="1"')])expect(readConditionalFormattingSnapshot(bad,'<styleSheet/>').issues.length).toBeGreaterThan(0)
})
it('reads an external theme+tint differential font/fill with source theme-over-rgb precedence',async()=>{
 const base=await createBlankWorkbook(),source=await createBufferEntrySource(base),styles=new StylesheetEditor(await source.readText('xl/styles.xml'))
 const wire:CfWireRule={ranges:area,stopIfTrue:false,rule:{type:'highlightCell',subType:'formula',value:'A1>0',style:{cl:{rgb:'#112233'},bg:{rgb:'#445566'}}}}
 const xml=applyCfRules('<worksheet><sheetData/></worksheet>',[wire],styles),external=styles.serialize().replace('<color rgb="FF112233"/>','<color rgb="FFFFFF00" theme="4" tint="0.4"/>').replace('<bgColor rgb="FF445566"/>','<bgColor theme="5" tint="-0.25"/>')
 const model=readConditionalFormattingSnapshot(xml,external)
 expect(model.issues).toEqual([]);expect(model.rules).toHaveLength(1)
})
it('reads external differential indexed colors including the workbook palette override',async()=>{
 const base=await createBlankWorkbook(),source=await createBufferEntrySource(base),styles=new StylesheetEditor(await source.readText('xl/styles.xml'))
 const xml=applyCfRules('<worksheet><sheetData/></worksheet>',[{ranges:area,stopIfTrue:false,rule:{type:'highlightCell',subType:'formula',value:'A1>0',style:{cl:{rgb:'#112233'}}}}],styles)
 const external=styles.serialize().replace('<color rgb="FF112233"/>','<color indexed="2"/>').replace('</styleSheet>','<colors><indexedColors><rgbColor rgb="00000000"/><rgbColor rgb="00FFFFFF"/><rgbColor rgb="00123456"/></indexedColors></colors></styleSheet>')
 const model=readConditionalFormattingSnapshot(xml,external);expect(model.issues).toEqual([]);expect((model.rules[0]!.rule.style as any).cl.rgb).toBe('#123456')
})
it('projects external cellIs reference operands without dropping the rule',()=>{
 const xml='<worksheet><sheetData/><conditionalFormatting sqref="A1:A3"><cfRule type="cellIs" priority="1" operator="greaterThan"><formula>$B$1+2</formula></cfRule></conditionalFormatting></worksheet>'
 const model=readConditionalFormattingSnapshot(xml,'<styleSheet/>');expect(model.issues).toEqual([]);expect(model.rules).toHaveLength(1);expect(model.rules[0]!.rule).toMatchObject({type:'highlightCell',subType:'formula',value:'A1>($B$1+2)'})
})
it('preserves two same-RGB different-theme dxf identities and interns only a real style edit',async()=>{
 const base=await createBlankWorkbook(),source=await createBufferEntrySource(base),styles=new StylesheetEditor(await source.readText('xl/styles.xml')),path='xl/worksheets/sheet1.xml'
 const wire=(value:string,rangesValue=area):CfWireRule=>({ranges:rangesValue,stopIfTrue:false,rule:{type:'highlightCell',subType:'formula',value,style:{cl:{rgb:'#112233'}}}})
 const first=wire('A1>0'),second=wire('A1<0')
 const xml=applyCfRules(await source.readText(path),[first,second],styles)
 const originalStyles=styles.serialize().replace('<dxf><font><color rgb="FF112233"/></font></dxf>','<dxf><font><color theme="4"/></font></dxf><dxf><font><color theme="5"/></font></dxf>').replace('<dxfs count="1">','<dxfs count="2">')
 const sheet=xml.replace('priority="2"','priority="2"').replace(/dxfId="0"(?= priority="2")/,'dxfId="1"')
 const theme='<a:theme xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><a:themeElements><a:clrScheme name="custom"><a:accent1><a:srgbClr val="112233"/></a:accent1><a:accent2><a:srgbClr val="112233"/></a:accent2><a:accent3><a:srgbClr val="A5A5A5"/></a:accent3><a:accent4><a:srgbClr val="FFC000"/></a:accent4><a:accent5><a:srgbClr val="5B9BD5"/></a:accent5><a:accent6><a:srgbClr val="70AD47"/></a:accent6></a:clrScheme></a:themeElements></a:theme>'
 const {assemblePackage}=await import('../src/zip')
 const input=(await assemblePackage(base,{replaced:new Map([[path,sheet],['xl/styles.xml',originalStyles]]),added:new Map([['xl/theme/theme1.xml',theme]]),addedBinary:new Map(),removedEntries:[],addedEntries:['xl/theme/theme1.xml'],touchedEntries:[path,'xl/styles.xml','xl/theme/theme1.xml']})).buffer
 const model=(await(await import('../src/index')).readWorkbook(input)).sheets[0]!.conditionalFormatting!;expect(model.issues).toEqual([])
 expect((model.rules[0]!.rule.style as any).cl.rgb).toBe('#112233');expect((model.rules[1]!.rule.style as any).cl.rgb).toBe('#112233')
 const saved=await replaceConditionalFormattingSnapshots(input,[{sheetName:'Sheet1',rules:model.rules}]),out=await createBufferEntrySource(saved)
 expect(await out.readText('xl/styles.xml')).toBe(originalStyles);expect(await out.readText(path)).toBe(sheet)
 const changed=structuredClone(model.rules);(changed[0]!.rule.style as any).cl.rgb='#445566'
 const edited=await createBufferEntrySource(await replaceConditionalFormattingSnapshots(input,[{sheetName:'Sheet1',rules:changed}]))
 expect(await edited.readText('xl/styles.xml')).toContain('<color rgb="FF445566"/>');expect(await edited.readText('xl/styles.xml')).toContain('<color theme="4"/>');expect(await edited.readText(path)).toContain('dxfId="1" priority="2"')
})
it.each(['theme="99"','theme="4" tint="NaN"','indexed="66"','theme="4" future="1"'])('rejects unresolved or unprojected source dxf color %s',async attributes=>{
 const base=await createBlankWorkbook(),source=await createBufferEntrySource(base),styles=new StylesheetEditor(await source.readText('xl/styles.xml'))
 const xml=applyCfRules('<worksheet><sheetData/></worksheet>',[{ranges:area,stopIfTrue:false,rule:{type:'highlightCell',subType:'formula',value:'A1>0',style:{cl:{rgb:'#112233'}}}}],styles)
 const modified=styles.serialize().replace('rgb="FF112233"',attributes);expect(readConditionalFormattingSnapshot(xml,modified).issues.length).toBeGreaterThan(0)
})
it.each([[64,'#000000'],[65,'#FFFFFF']])('keeps indexed system slot %s independent of workbook overrides',async(index,expected)=>{
 const base=await createBlankWorkbook(),source=await createBufferEntrySource(base),styles=new StylesheetEditor(await source.readText('xl/styles.xml'))
 const xml=applyCfRules('<worksheet><sheetData/></worksheet>',[{ranges:area,stopIfTrue:false,rule:{type:'highlightCell',subType:'formula',value:'A1>0',style:{cl:{rgb:'#112233'},bg:{rgb:'#445566'}}}}],styles)
 const external=styles.serialize().replace('rgb="FF112233"',`indexed="${index}"`).replace('rgb="FF445566"',`indexed="${index}"`).replace('</styleSheet>',`<colors><indexedColors>${'<rgbColor rgb="00123456"/>'.repeat(66)}</indexedColors></colors></styleSheet>`)
 const model=readConditionalFormattingSnapshot(xml,external);expect(model.issues).toEqual([]);expect((model.rules[0]!.rule.style as any).cl.rgb).toBe(expected);expect((model.rules[0]!.rule.style as any).bg.rgb).toBe(expected)
})
it('retains original cellIs XML until its actual condition changes',async()=>{
 const base=await createBlankWorkbook(),source=await createBufferEntrySource(base),path='xl/worksheets/sheet1.xml'
 const sheet=(await source.readText(path)).replace('</worksheet>','<conditionalFormatting sqref="A1:A3"><cfRule type="cellIs" priority="1" operator="greaterThan"><formula>$B$1+2</formula></cfRule></conditionalFormatting></worksheet>')
 const {assemblePackage}=await import('../src/zip')
 const input=(await assemblePackage(base,{replaced:new Map([[path,sheet]]),added:new Map(),addedBinary:new Map(),removedEntries:[],addedEntries:[],touchedEntries:[path]})).buffer
 const model=readConditionalFormattingSnapshot(sheet,await source.readText('xl/styles.xml'));expect(model.issues).toEqual([])
 const unchanged=await createBufferEntrySource(await replaceConditionalFormattingSnapshots(input,[{sheetName:'Sheet1',rules:model.rules}]))
 expect(await unchanged.readText(path)).toBe(sheet);expect(await unchanged.readText('xl/styles.xml')).toBe(await source.readText('xl/styles.xml'))
 const styled=structuredClone(model.rules);styled[0]!.rule.style={bl:1}
 const editedStyle=await createBufferEntrySource(await replaceConditionalFormattingSnapshots(input,[{sheetName:'Sheet1',rules:styled}]))
 expect(await editedStyle.readText(path)).toContain('type="cellIs"');expect(await editedStyle.readText(path)).toContain('<formula>$B$1+2</formula>')
 styled[0]!.rule.value='A1>($C$1+3)'
 const editedCondition=await createBufferEntrySource(await replaceConditionalFormattingSnapshots(input,[{sheetName:'Sheet1',rules:styled}]))
 expect(await editedCondition.readText(path)).toContain('type="expression"');expect(await editedCondition.readText(path)).toContain('<formula>A1&gt;($C$1+3)</formula>')
})

// Fixed GenOffice univer-sync.ts:7481-7554,7689-7752 source contracts.
const externalCellIs=(operator:string,formulas:string[],sqref='A1:A3')=>'<worksheet><sheetData/><conditionalFormatting sqref="'+sqref+'"><cfRule type="cellIs" priority="1" operator="'+operator+'">'+formulas.map(value=>'<formula>'+value.replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;')+'</formula>').join('')+'</cfRule></conditionalFormatting></worksheet>'
it.each([
 ['equal',['$B$1+2'],'A1=($B$1+2)'],['notEqual',['$B$1+2'],'A1<>($B$1+2)'],
 ['greaterThan',['$B$1+2'],'A1>($B$1+2)'],['greaterThanOrEqual',['$B$1+2'],'A1>=($B$1+2)'],
 ['lessThan',['$B$1+2'],'A1<($B$1+2)'],['lessThanOrEqual',['$B$1+2'],'A1<=($B$1+2)'],
 ['between',['$B$1+2','3*4'],'AND(A1>=($B$1+2),A1<=(3*4))'],
 ['notBetween',['$B$1+2','3*4'],'NOT(AND(A1>=($B$1+2),A1<=(3*4)))'],
 ['equal',['"a*?"'],'A1="a~*~?"'],['notEqual',['"a*?"'],'A1<>"a*?"'],
 ['equal',['"MiXeD"'],'A1="MiXeD"'],['equal',['"a""B"'],'A1="a""B"'],
 ['greaterThan',['"alpha"'],'A1>"alpha"'],['between',['"a"','B1+2'],'AND(A1>="a",A1<=(B1+2))'],
] as [string,string[],string][])('uses exact source comparison/wildcard/case formula for %s %j',(operator,formulas,expected)=>{
 const model=readConditionalFormattingSnapshot(externalCellIs(operator,formulas),'<styleSheet/>')
 expect(model.issues).toEqual([]);expect(model.rules[0]!.rule).toMatchObject({subType:'formula',value:expected})
})
it.each([
 ['equal',[0],'A1=0'],['notEqual',[0],'A1<>0'],['greaterThan',[-1],'A1>-1'],
 ['greaterThanOrEqual',[0],'A1>=0'],['lessThan',[1],'A1<1'],['lessThanOrEqual',[0],'A1<=0'],
 ['between',[2,-2],'AND(A1>=-2,A1<=2)'],['notBetween',[2,-2],'NOT(AND(A1>=-2,A1<=2))'],
] as [string,number[],string][])('projects source blank-diverging numeric %s %j only within formula budget',(operator,values,expected)=>{
 const formulas=values.map(String),small=readConditionalFormattingSnapshot(externalCellIs(operator,formulas,'A1:A20000'),'<styleSheet/>')
 expect(small.issues).toEqual([]);expect(small.rules[0]!.rule).toMatchObject({subType:'formula',value:expected})
 const large=readConditionalFormattingSnapshot(externalCellIs(operator,formulas,'A1:A20001'),'<styleSheet/>')
 expect(large.issues).toEqual([]);expect(large.rules[0]!.rule).toMatchObject({subType:'number',operator,value:values})
})
it.each([
 ['equal',[1]],['notEqual',[1]],['greaterThan',[1]],['greaterThanOrEqual',[1]],
 ['lessThan',[-1]],['lessThanOrEqual',[-1]],['between',[1,2]],['notBetween',[1,2]],
] as [string,number[]][])('keeps source native numeric %s %j when blanks agree',(operator,values)=>{
 const model=readConditionalFormattingSnapshot(externalCellIs(operator,values.map(String)),'<styleSheet/>')
 expect(model.issues).toEqual([]);expect(model.rules[0]!.rule).toMatchObject({subType:'number',operator,value:values})
})
it('uses source huge-range quoted equality fallback but keeps references as formulas',()=>{
 const quoted=readConditionalFormattingSnapshot(externalCellIs('equal',['"a*?"'],'A1:A20001'),'<styleSheet/>')
 expect(quoted.issues).toEqual([]);expect(quoted.rules[0]!.rule).toMatchObject({subType:'text',operator:'equal',value:'a*?'})
 const reference=readConditionalFormattingSnapshot(externalCellIs('equal',['$B$1+2'],'A1:A20001'),'<styleSheet/>')
 expect(reference.issues).toEqual([]);expect(reference.rules[0]!.rule).toMatchObject({subType:'formula',value:'A1=($B$1+2)'})
})
it('uses the source top-left sorted anchor and total covered count across disjoint ranges',()=>{
 const reference=readConditionalFormattingSnapshot(externalCellIs('greaterThan',['$Z$1+2'],'D9:D10 B2:B3'),'<styleSheet/>')
 expect(reference.issues).toEqual([]);expect(reference.rules[0]!.rule).toMatchObject({subType:'formula',value:'B2>($Z$1+2)'})
 const budget=readConditionalFormattingSnapshot(externalCellIs('equal',['"a*?"'],'D1:D10001 B1:B10000'),'<styleSheet/>')
 expect(budget.issues).toEqual([]);expect(budget.rules[0]!.rule).toMatchObject({subType:'text',operator:'equal',value:'a*?'})
})
it.each([
 ['between',['2','B1']],['between',['B1']],['greaterThan',['B1','C1']],['future',['B1']],['equal',[]],
] as [string,string[]][])('retains incomplete cellIs source for unsupported operands %s %j',(operator,formulas)=>{
 const xml=externalCellIs(operator,formulas),model=readConditionalFormattingSnapshot(xml,'<styleSheet/>')
 expect(model.issues.length).toBeGreaterThan(0);expect(model.sourceXml).toBe(xml);expect(model.rules).toEqual([])
})
it('retains independent same-condition styles and original no-dxf cellIs while editing another rule',async()=>{
 const bytes=await createBlankWorkbook(),source=await createBufferEntrySource(bytes),path='xl/worksheets/sheet1.xml',styles=new StylesheetEditor(await source.readText('xl/styles.xml'))
 const first=styles.internDxf('<dxf><font><b/></font></dxf>'),second=styles.internDxf('<dxf><font><i/></font></dxf>')
 const rules=[undefined,first,second].map((id,index)=>'<conditionalFormatting sqref="A1:A3"><cfRule type="cellIs" priority="'+(index+1)+'"'+(id===undefined?'':' dxfId="'+id+'"')+' operator="greaterThan"><formula>$B$1+2</formula></cfRule></conditionalFormatting>').join('')
 const sheet=(await source.readText(path)).replace('</worksheet>',rules+'</worksheet>'),{assemblePackage}=await import('../src/zip')
 const input=(await assemblePackage(bytes,{replaced:new Map([[path,sheet],['xl/styles.xml',styles.serialize()]]),added:new Map(),addedBinary:new Map(),removedEntries:[],addedEntries:[],touchedEntries:[path,'xl/styles.xml']})).buffer
 const model=readConditionalFormattingSnapshot(sheet,styles.serialize());expect(model.issues).toEqual([])
 const reordered=[model.rules[2]!,model.rules[0]!,model.rules[1]!,bar('#112233')]
 const saved=await createBufferEntrySource(await replaceConditionalFormattingSnapshots(input,[{sheetName:'Sheet1',rules:reordered}]))
 const next=await saved.readText(path),read=readConditionalFormattingSnapshot(next,await saved.readText('xl/styles.xml'))
 expect(read.issues).toEqual([]);expect(read.rules.slice(0,3).map(rule=>rule.rule.style)).toEqual(reordered.slice(0,3).map(rule=>rule.rule.style))
 expect(next).toMatch(/type="cellIs" priority="2" operator="greaterThan"/);expect(await saved.readText('xl/styles.xml')).toBe(styles.serialize())
})
it('keeps unchanged source cellIs attribute/formula bytes when only an adjacent rule changes',async()=>{
 const bytes=await createBlankWorkbook(),source=await createBufferEntrySource(bytes),path='xl/worksheets/sheet1.xml',styles=new StylesheetEditor(await source.readText('xl/styles.xml'))
 const id=styles.internDxf('<dxf><font><b/></font></dxf>')
 const raw='<cfRule type="cellIs" priority="1" stopIfTrue="true" dxfId="'+id+'" operator="greaterThan"><formula>$B$1 + 2</formula></cfRule>'
 const sheet=(await source.readText(path)).replace('</worksheet>','<conditionalFormatting sqref="A1:A3">'+raw+'</conditionalFormatting></worksheet>'),{assemblePackage}=await import('../src/zip')
 const input=(await assemblePackage(bytes,{replaced:new Map([[path,sheet],['xl/styles.xml',styles.serialize()]]),added:new Map(),addedBinary:new Map(),removedEntries:[],addedEntries:[],touchedEntries:[path,'xl/styles.xml']})).buffer
 const model=readConditionalFormattingSnapshot(sheet,styles.serialize());expect(model.issues).toEqual([])
 const saved=await createBufferEntrySource(await replaceConditionalFormattingSnapshots(input,[{sheetName:'Sheet1',rules:[...model.rules,bar('#112233')]}]))
 expect(await saved.readText(path)).toContain(raw);expect(await saved.readText('xl/styles.xml')).toBe(styles.serialize())
})
