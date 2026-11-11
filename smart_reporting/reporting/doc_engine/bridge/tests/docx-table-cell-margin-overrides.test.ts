import assert from 'node:assert/strict'
import {test} from 'node:test'
import JSZip from 'jszip'
import {parseDocx,saveDocx} from '../../packages/docx-engine/src/index.ts'
import {buildDocx} from '../../packages/docx-engine/tests/helpers/build-docx.ts'
import {tableCellMarginOverridesAvailability,editTableCellMarginOverrides,verifyTableCellMarginOverridesResult} from '../docx-table-cell-margin-overrides.ts'
const mar=(v:Record<string,number>)=>'<w:tcMar>'+Object.entries(v).map(([s,n])=>`<w:${s} w:w="${n}" w:type="dxa"/>`).join('')+'</w:tcMar>'
const cell=(text:string,pr='')=>`<w:tc><w:tcPr><w:tcW w:w="2001" w:type="dxa"/>${pr}<w:noWrap/><w:textDirection w:val="tbRl"/></w:tcPr><w:p w:rsidR="AABBCCDD"><w:pPr><w:jc w:val="end"/></w:pPr><w:r><w:t>${text}</w:t></w:r></w:p></w:tc>`
const style='<w:style w:type="table" w:styleId="Margins"><w:tblStylePr w:type="firstRow"><w:tcPr>'+mar({top:23,left:41})+'</w:tcPr></w:tblStylePr></w:style>'
const xml='<w:tbl><w:tblPr><w:tblStyle w:val="Margins"/><w:tblLook w:firstRow="1"/><w:bidiVisual/><w:tblCellMar><w:left w:w="108"/></w:tblCellMar></w:tblPr><w:tblGrid><w:gridCol w:w="2001"/><w:gridCol w:w="1999"/></w:tblGrid><w:tr><w:tblPrEx><w:tblCellMar><w:bottom w:w="17"/></w:tblCellMar></w:tblPrEx>'+cell('owner',mar({right:0})+'<w:vMerge w:val="restart"/>')+cell('styled only')+'</w:tr><w:tr>'+cell('hidden',mar({left:71})+'<w:vMerge/>')+cell('other')+'</w:tr></w:tbl>'
const open=async(value=xml)=>{const bytes=await buildDocx({bodyXml:value,extraStylesXml:style});const parsed=await parseDocx(bytes);return{bytes,parsed,block:parsed.blocks.find(b=>b.type==='table')!}}
const margins={top:0,right:130,bottom:96,left:175},set={top:1,left:0,bottom:2,right:1,margins},reset={...set,margins:null},mask=(s:string)=>s.replace(/<w:tcMar(?:\s[^>]*)?\/>|<w:tcMar(?:\s[^>]*)?>[\s\S]*?<\/w:tcMar>/g,'')
test('trusted raw/effective/reset source uses original parser style and row context',async()=>{const{block,parsed}=await open(),a=await tableCellMarginOverridesAvailability(block,parsed);assert.equal(a.tableCellMarginOverridesEditable,true);const c=a.tableCellMarginOverridesSource!.cells;assert.deepEqual(c[0].raw,{right:0});assert.deepEqual(c[0].effective,{top:23,right:0,bottom:17,left:41});assert.deepEqual(c[0].resetEffective,{top:23,bottom:17,left:41});assert.equal(c[1].rawPresent,false);assert.equal(c[1].raw,null);assert.deepEqual(c[1].effective,c[1].resetEffective);assert.ok(c[1].effective)})
test('ordered reset removes both physical margins while preserving hidden content and package parts',async()=>{const{block,parsed,bytes}=await open(),result=await editTableCellMarginOverrides(block,[set,reset],parsed);assert.equal(mask(result.xml),mask(block.originalXml!));assert.ok(result.xml.includes('hidden'));assert.equal((result.xml.match(/<w:tcMar>/g)||[]).length,0);const output=await saveDocx(parsed,[{kind:'xml',docxIndex:block.docxIndex,xml:result.xml}]),reopened=(await parseDocx(output)).blocks.find(b=>b.type==='table')!;verifyTableCellMarginOverridesResult(reopened,result);assert.deepEqual(reopened.table!.rows[0][0].cellMarTwips,{top:23,left:41,bottom:17});const a=await JSZip.loadAsync(bytes),b=await JSZip.loadAsync(output);for(const n of Object.keys(a.files))if(!a.files[n].dir&&n!=='word/document.xml')assert.deepEqual(await a.file(n)!.async('uint8array'),await b.file(n)!.async('uint8array'))})
test('set patches merged physical overrides; absent tcPr gets an ordered container',async()=>{const{block,parsed}=await open(),r=await editTableCellMarginOverrides(block,[set],parsed);assert.equal(mask(r.xml),mask(block.originalXml!));assert.equal((r.xml.match(/<w:tcMar>/g)||[]).length,2);verifyTableCellMarginOverridesResult((await open(r.xml)).block,r);const absent=await open(xml.replace(/<w:tcPr>[\s\S]*?<\/w:tcPr>/g,''));const inserted=await editTableCellMarginOverrides(absent.block,[{...set,top:0,left:1,bottom:1,right:2}],absent.parsed);assert.ok(inserted.xml.includes('<w:tcPr><w:tcMar>'))})
test('ambiguous declarations, revisions, stale context and invalid steps fail atomically',async()=>{for(const raw of ['<w:left w:w="1"/><w:start w:w="2"/>','<w:left w:w="1" w:type="pct"/>','<w:left w:w="1" w:extra="x"/>']){const{block,parsed}=await open(xml.replace(mar({right:0}),'<w:tcMar>'+raw+'</w:tcMar>'));assert.equal((await tableCellMarginOverridesAvailability(block,parsed)).tableCellMarginOverridesEditable,false)}const{block,parsed}=await open();await assert.rejects(editTableCellMarginOverrides(block,[{...set,margins:{...margins,left:-1}}],parsed));await assert.rejects(editTableCellMarginOverrides({...block,originalXml:block.originalXml!.replace('hidden','changed')},[set],parsed));assert.throws(()=>verifyTableCellMarginOverridesResult(block,{xml:block.originalXml,cells:[],margins:[],physicalMargins:[]} as any));const r=await open(xml.replace('</w:tcPr>','<w:tcPrChange w:id="1"><w:tcPr/></w:tcPrChange></w:tcPr>'));assert.equal((await tableCellMarginOverridesAvailability(r.block,r.parsed)).tableCellMarginOverridesEditable,false)})
test('batch cached baseline equals single-owner parser references across tables with distinct raw overrides',async()=>{
 const bytes=await buildDocx({bodyXml:xml+xml.replace('owner','second').replace('w:w="0" w:type="dxa"','w:w="99" w:type="dxa"'),extraStylesXml:style}),parsed=await parseDocx(bytes),tables=parsed.blocks.filter(b=>b.type==='table')
 const caps=await Promise.all(tables.map(b=>tableCellMarginOverridesAvailability(b,parsed)))
 for(let i=0;i<tables.length;i++){
  assert.equal(caps[i].tableCellMarginOverridesEditable,true)
  const reference=await parseDocx(await saveDocx(parsed,parsed.blocks.map(b=>b===tables[i]?{kind:'xml' as const,docxIndex:b.docxIndex!,xml:mask(b.originalXml!)}:{kind:'original' as const,docxIndex:b.docxIndex!})))
  const effective=reference.blocks.find(b=>b.docxIndex===tables[i].docxIndex)!.table!.rows.flatMap(r=>r.filter(c=>c.vMerge!=='continue').map(c=>c.cellMarTwips??null))
  assert.deepEqual(caps[i].tableCellMarginOverridesSource!.cells.map(c=>c.resetEffective),effective)
  const other=reference.blocks.find(b=>b.docxIndex===tables[1-i].docxIndex)!
  assert.equal(other.originalXml,tables[1-i].originalXml)
 }
 assert.deepEqual(caps[0].tableCellMarginOverridesSource!.cells[0].raw,{right:0});assert.deepEqual(caps[1].tableCellMarginOverridesSource!.cells[0].raw,{right:99})
 const again=await tableCellMarginOverridesAvailability(tables[0],parsed);assert.deepEqual(again,caps[0])
})
test('empty raw tcMar remains distinguishable from absent; reset removes owner and hidden continuation containers',async()=>{
 const{block,parsed}=await open(xml.replace(mar({right:0}),'<w:tcMar/>'))
 const cap=await tableCellMarginOverridesAvailability(block,parsed),c=cap.tableCellMarginOverridesSource!.cells[0]
 assert.equal(c.rawPresent,true);assert.equal(c.raw,null);assert.deepEqual(c.effective,c.resetEffective)
 const result=await editTableCellMarginOverrides(block,[reset],parsed)
 assert.equal(result.xml.includes('<w:tcMar'),false);assert.ok(result.xml.includes('hidden'));verifyTableCellMarginOverridesResult((await open(result.xml)).block,result)
})
test('owner without raw override still exposes and clears hidden continuation override',async()=>{
 const{block,parsed}=await open(xml.replace(mar({right:0}),'')),cap=await tableCellMarginOverridesAvailability(block,parsed),owner=cap.tableCellMarginOverridesSource!.cells[0]
 assert.equal(owner.rawPresent,false);assert.equal(owner.raw,null);assert.equal(owner.hasPhysicalOverrides,true)
 const result=await editTableCellMarginOverrides(block,[reset],parsed)
 assert.equal(result.xml.includes('<w:tcMar'),false);assert.equal(mask(result.xml),mask(block.originalXml!));verifyTableCellMarginOverridesResult((await open(result.xml)).block,result)
})
