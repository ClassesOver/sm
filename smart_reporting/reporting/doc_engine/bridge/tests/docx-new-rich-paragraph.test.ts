import assert from 'node:assert/strict'
import {test} from 'node:test'
import JSZip from 'jszip'
import {buildDocx} from '../../packages/docx-engine/tests/helpers/build-docx.ts'
import {parseDocx} from '../../packages/docx-engine/src/parse.ts'
import {saveDocx} from '../../packages/docx-engine/src/patch.ts'
import * as rich from '../docx-new-rich-paragraph.ts'
const api=rich as any
const op:any={kind:'insertRichParagraph',blockId:'anchor',expectedObjectSha256:'hash',position:'after',paragraph:{type:'paragraph',format:{align:'center',spaceAfter:240,lineSpacing:1.5},runs:[{text:'继承 ',bold:true,fontAscii:'Calibri',eastAsiaFont:'宋体',sizeHalfPoints:28},{text:'换行\n下一行',italic:true,color:'FF0000'}]}}
test('new rich paragraph writes actual runs, paragraph formatting and breaks without touching original XML or unrelated parts',async()=>{
 assert.equal(typeof api.validateNewRichParagraphOperation,'function')
 const bytes=await buildDocx({bodyXml:'<w:p w:rsidR="ABC"><w:r><w:t>原文</w:t></w:r></w:p>',headerXml:'<w:p><w:r><w:t>页眉</w:t></w:r></w:p>'}),parsed=await parseDocx(bytes)
 const value=api.validateNewRichParagraphOperation(op,{blockId:'anchor',expectedObjectSha256:'hash',type:'paragraph',editable:true})
 const output=await saveDocx(parsed,[{kind:'original',docxIndex:parsed.blocks[0].docxIndex!},{kind:'generated',block:api.buildNewRichParagraph(value.paragraph)}])
 const before=await JSZip.loadAsync(bytes),after=await JSZip.loadAsync(output),xml=await after.file('word/document.xml')!.async('string')
 assert.ok(xml.includes(parsed.blocks[0].originalXml!));assert.match(xml,/<w:jc w:val="center"/);assert.match(xml,/<w:b\/>/);assert.match(xml,/<w:i\/>/);assert.match(xml,/<w:br\/>/);assert.match(xml,/w:eastAsia="宋体"/);assert.match(xml,/w:val="FF0000"/)
 for(const entry of Object.values(before.files))if(!entry.dir&&entry.name!=='word/document.xml')assert.deepEqual(await after.file(entry.name)!.async('uint8array'),await entry.async('uint8array'),entry.name)
})
test('typed whitelist rejects forged XML/relationships, nonfinite format and untrusted style/list IDs',()=>{
 assert.equal(typeof api.normalizeNewRichParagraph,'function')
 for(const paragraph of [{...op.paragraph,rawPPr:'<w:pPr/>'},{...op.paragraph,runs:[{text:'x',rawRPr:'<w:rPr/>'}]},{...op.paragraph,runs:[{text:'x',link:{rId:'rId1'}}]},{...op.paragraph,format:{lineSpacing:NaN}},{...op.paragraph,styleId:'Unknown'},{...op.paragraph,type:'listItem',list:{numId:'999',ilvl:0,kind:'ordered'}}])assert.throws(()=>api.normalizeNewRichParagraph(paragraph))
 assert.throws(()=>api.validateNewRichParagraphOperation({...op,expectedObjectSha256:'forged'},{blockId:'anchor',expectedObjectSha256:'hash',type:'paragraph',editable:true}))
 assert.throws(()=>api.validateNewRichParagraphOperation(op,{blockId:'anchor',expectedObjectSha256:'hash',type:'paragraph',editable:false}))
})
test('style and numbering bindings require explicit trusted source definitions and matching level kind',()=>{
 assert.equal(typeof api.normalizeNewRichParagraph,'function')
 const bindings={styles:new Map([['Heading1',{type:'paragraph',headingLevel:1}],['Emphasis',{type:'character'}]]),numbering:new Map([['4',{levels:{0:{numFmt:'decimal'},1:{numFmt:'bullet'}}}]])}
 assert.equal(api.normalizeNewRichParagraph({type:'heading',level:1,styleId:'Heading1',runs:[{text:'标题',styleId:'Emphasis'}]},bindings).styleId,'Heading1')
 assert.equal(api.normalizeNewRichParagraph({type:'listItem',list:{numId:'4',ilvl:1,kind:'bullet'},runs:[]},bindings).list.numId,'4')
 assert.throws(()=>api.normalizeNewRichParagraph({type:'listItem',list:{numId:'4',ilvl:1,kind:'ordered'},runs:[]},bindings))
})
test('pending empty paragraph formatting is typed data and persists as an empty formatted run',async()=>{
 const normalized=api.normalizeNewRichParagraph({type:'paragraph',runs:[],caretFormat:{text:'',bold:true,sizeHalfPoints:32}})
 const block=api.buildNewRichParagraph(normalized)
 assert.equal(block.runs[0].bold,true);assert.equal(block.runs[0].sizeHalfPoints,32);assert.equal(block.caretFormat,undefined)
 const bytes=await buildDocx({bodyXml:'<w:p><w:r><w:t>anchor</w:t></w:r></w:p>'}),parsed=await parseDocx(bytes),saved=await saveDocx(parsed,[{kind:'original',docxIndex:parsed.blocks[0].docxIndex!},{kind:'generated',block}]),zip=await JSZip.loadAsync(saved),xml=await zip.file('word/document.xml')!.async('string');assert.match(xml,/<w:b\/>/);assert.match(xml,/<w:sz w:val="32"/)
 assert.throws(()=>api.normalizeNewRichParagraph({type:'paragraph',runs:[],caretFormat:{text:'',rawRPr:'<w:rPr/>'}}))
})
test('supports before/after ordinary top-level table anchors while preserving the complete table XML',async()=>{
 const bytes=await buildDocx({bodyXml:'<w:tbl><w:tblPr/><w:tblGrid><w:gridCol w:w="5000"/></w:tblGrid><w:tr><w:tc><w:tcPr/><w:p><w:r><w:t>table text</w:t></w:r></w:p></w:tc></w:tr></w:tbl>'}),parsed=await parseDocx(bytes),table=parsed.blocks.find(b=>b.type==='table')!
 for(const position of ['before','after']){
  const checked=api.validateNewRichParagraphOperation({...op,position},{blockId:'anchor',expectedObjectSha256:'hash',type:table.type,editable:false,insertParagraphAdjacentEditable:true}),generated={kind:'generated' as const,block:api.buildNewRichParagraph(checked.paragraph)},original={kind:'original' as const,docxIndex:table.docxIndex!},saved=await saveDocx(parsed,position==='before'?[generated,original]:[original,generated]),zip=await JSZip.loadAsync(saved),xml=await zip.file('word/document.xml')!.async('string')
  assert.ok(xml.includes(table.originalXml!));assert.equal(xml.indexOf('继承')<xml.indexOf('table text'),position==='before')
 }
 assert.throws(()=>api.validateNewRichParagraphOperation(op,{blockId:'anchor',expectedObjectSha256:'hash',type:'table',editable:false}))
 for(const extra of [{hidden:true},{sdtShell:{}},{type:'passthrough'},{protectedDocument:true}])assert.throws(()=>api.validateNewRichParagraphOperation(op,{blockId:'anchor',expectedObjectSha256:'hash',type:'paragraph',editable:true,...extra}))
})
test('retains inherited auto line spacing raw twips and rejects contradictory multipliers',async()=>{
 for(const raw of [276,278,241]){
  const bytes=await buildDocx({bodyXml:`<w:p><w:pPr><w:spacing w:line="${raw}" w:lineRule="auto"/></w:pPr><w:r><w:t>source</w:t></w:r></w:p>`}),parsed=await parseDocx(bytes),source=parsed.blocks[0],format={lineRule:source.format!.lineRule,lineRawTwips:source.format!.lineRawTwips,lineSpacing:source.format!.lineSpacing},spec=api.normalizeNewRichParagraph({type:'paragraph',format,runs:[{text:'inherited'}]})
  const saved=await saveDocx(parsed,[{kind:'original',docxIndex:source.docxIndex!},{kind:'generated',block:api.buildNewRichParagraph(spec)}]),zip=await JSZip.loadAsync(saved),xml=await zip.file('word/document.xml')!.async('string'),reparsed=await parseDocx(saved)
  assert.match(xml,new RegExp(`w:line="${raw}" w:lineRule="auto"`));assert.equal(reparsed.blocks[1].format!.lineRawTwips,raw)
  assert.throws(()=>api.normalizeNewRichParagraph({type:'paragraph',format:{...format,lineSpacing:2},runs:[]}))
 }
 assert.equal(api.normalizeNewRichParagraph({type:'paragraph',format:{lineRule:'auto',lineRawTwips:276},runs:[]}).format.lineSpacing,1.15)
 assert.throws(()=>api.normalizeNewRichParagraph({type:'paragraph',format:{lineRule:'auto',lineRawTwips:0,lineSpacing:1},runs:[]}))
})
test('source-bound redundant italic metadata is a typed reference, never accepted client XML',async()=>{
 const bytes=await buildDocx({bodyXml:'<w:p><w:r><w:rPr><w:i/></w:rPr><w:t>LEFT MIDDLE RIGHT</w:t></w:r></w:p>'}),parsed=await parseDocx(bytes),source=parsed.blocks[0],bindings={sourceRuns:new Map([['p0',{expectedObjectSha256:'sha',runs:source.runs!}]])},paragraph={type:'paragraph',runs:[{text:'RIGHT',italic:true,sourceFormat:{blockId:'p0',expectedObjectSha256:'sha',from:0}}]}
 const spec=api.normalizeNewRichParagraph(paragraph,bindings),block=api.buildNewRichParagraph(spec,bindings)
 assert.equal(block.runs[0].sourceFormat,undefined);assert.equal(block.runs[0].rawRPr,undefined);assert.equal(block.runs[0].italic,true)
 const saved=await saveDocx(parsed,[{kind:'original',docxIndex:source.docxIndex!},{kind:'generated',block}]),zip=await JSZip.loadAsync(saved),xml=await zip.file('word/document.xml')!.async('string')
 assert.ok(xml.includes(source.originalXml!));assert.equal((xml.match(/<w:i\/>/g)??[]).length,2)
 for(const bad of [{...paragraph,runs:[{...paragraph.runs[0],rawRPr:'<w:rPr><w:i/></w:rPr>'}]},{...paragraph,runs:[{...paragraph.runs[0],sourceFormat:{blockId:'p0',expectedObjectSha256:'fake',from:0}}]}])assert.throws(()=>api.normalizeNewRichParagraph(bad,bindings))
 assert.throws(()=>api.normalizeNewRichParagraph({...paragraph,runs:[{...paragraph.runs[0],sourceFormat:{blockId:'p0',expectedObjectSha256:'sha',from:1}}]},bindings))
 const unknown={sourceRuns:new Map([['p0',{expectedObjectSha256:'sha',runs:[{text:'LEFT',italic:true,rawRPr:'<w:rPr><w:i/><w:unknown/></w:rPr>'}]}]])}
 assert.throws(()=>api.normalizeNewRichParagraph(paragraph,unknown))
})
