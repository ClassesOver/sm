import assert from 'node:assert/strict'
import {createHash} from 'node:crypto'
import {test} from 'node:test'
import JSZip from 'jszip'
import {buildDocx} from '../../packages/docx-engine/tests/helpers/build-docx.ts'
import {parseDocx} from '../../packages/docx-engine/src/parse.ts'
import {patchDocxChart} from '../docx-chart.ts'
import {patchDocxField} from '../docx-field.ts'
const hash=(v:string|Uint8Array)=>createHash('sha256').update(v).digest('hex')
test('real chart workbook and generic fields survive reopen; unrelated parts unchanged',async()=>{
 const source=await buildDocx({bodyXml:'<w:p><w:r><w:t>Anchor</w:t></w:r></w:p>',headerXml:'<w:p/>'})
 const b=(await parseDocx(source)).blocks[0]!, a={blockId:hash(hash(source)+':block:'+b.docxIndex),expectedObjectSha256:hash(b.originalXml!),position:'after'}
 for(const kind of ['bar','line','pie']){
 const op={kind:'insertChart',...a,chart:{kind,title:'销售 & 😀',categories:['A','B'],series:[{name:'收入',values:[4,null]}]}}
 const output=await patchDocxChart(source,op), z=await JSZip.loadAsync(output),before=await JSZip.loadAsync(source)
 const chart=(await parseDocx(output)).blocks.find(b=>b.chartDisplay)?.chartDisplay
 assert.equal(chart?.kind,kind);assert.deepEqual(chart?.series[0].values,[4,null]);assert.ok(z.file('word/charts/embeddings/workbook1.xlsx'))
 for(const name of Object.keys(before.files))if(!before.files[name]!.dir&&!['word/document.xml','word/_rels/document.xml.rels','[Content_Types].xml'].includes(name))assert.deepEqual(await z.file(name)!.async('uint8array'),await before.file(name)!.async('uint8array'),name)
 await assert.rejects(patchDocxChart(output,op),/anchor/)
 await assert.rejects(patchDocxChart(source,{...op,xml:'<x/>'}),/operation/)
 }
 for(const instruction of ['DATE','TIME','PAGE','NUMPAGES','FILENAME']){
 const out=await patchDocxField(source,{kind:'insertField',...a,instruction,result:'示例 & 😀'}),z=await JSZip.loadAsync(out),before=await JSZip.loadAsync(source)
 const xml=await z.file('word/document.xml')!.async('string');assert.ok(xml.includes(' '+instruction+' '));assert.ok(xml.includes('w:fldCharType="begin"'));assert.ok(xml.includes('示例 &amp; 😀'))
 assert.ok((await parseDocx(out)).blocks.some(b=>b.runs?.some(r=>r.instrField===instruction)))
 for(const name of Object.keys(before.files))if(!before.files[name]!.dir&&name!=='word/document.xml')assert.deepEqual(await z.file(name)!.async('uint8array'),await before.file(name)!.async('uint8array'),name)
 }
 await assert.rejects(patchDocxField(source,{kind:'insertField',...a,instruction:'INCLUDETEXT evil',result:'x'}),/operation/)
})
test('strict semantic chart validation and collision-free insertion preserve first chart workbook',async()=>{
 const source=await buildDocx({bodyXml:'<w:p><w:r><w:t>Anchor</w:t></w:r></w:p>'})
 const anchor=async(bytes:Uint8Array)=>{const b=(await parseDocx(bytes)).blocks.find(b=>b.runs?.some(r=>r.text==='Anchor'))!;return {blockId:hash(hash(bytes)+':block:'+b.docxIndex),expectedObjectSha256:hash(b.originalXml!),position:'before'}}
 const chart={kind:'bar',categories:['a'],series:[{name:'s',values:[1]}]},a=await anchor(source)
 for(const bad of [{...chart,series:[{name:'s',values:[]}]},{...chart,series:[{name:'s',values:[Infinity]}]},{...chart,kind:'scatter'},{...chart,title:'bad\u0001'}])await assert.rejects(patchDocxChart(source,{kind:'insertChart',...a,chart:bad}),/chart_operation/)
 const first=await patchDocxChart(source,{kind:'insertChart',...a,chart}),second=await patchDocxChart(first,{kind:'insertChart',...await anchor(first),chart:{...chart,kind:'pie'}})
 const z1=await JSZip.loadAsync(first),z2=await JSZip.loadAsync(second)
 for(const path of ['word/charts/chart1.xml','word/charts/_rels/chart1.xml.rels','word/charts/embeddings/workbook1.xlsx'])assert.deepEqual(await z2.file(path)!.async('uint8array'),await z1.file(path)!.async('uint8array'),path)
 assert.deepEqual((await parseDocx(second)).blocks.filter(b=>b.chartDisplay).map(b=>b.chartDisplay!.kind),['bar','pie'])
 const xml=await z2.file('word/document.xml')!.async('string'),ids=[...xml.matchAll(/<wp:docPr id="(\d+)"/g)].map(m=>m[1]);assert.equal(new Set(ids).size,2)
})
test('inline field splits a trusted styled text run at UTF16 offset and rejects field interiors',async()=>{
 const raw='<w:p><w:r><w:rPr><w:b/></w:rPr><w:t xml:space="preserve">A 😀 B</w:t></w:r></w:p>',source=await buildDocx({bodyXml:raw}),b=(await parseDocx(source)).blocks[0]!,op={kind:'insertField',blockId:hash(hash(source)+':block:'+b.docxIndex),expectedObjectSha256:hash(b.originalXml!),position:'after',fieldOffset:4,instruction:'PAGE',result:'2'}
 const out=await patchDocxField(source,op),xml=(await parseDocx(out)).internal.documentXml
 assert.ok(xml.includes('<w:rPr><w:b/></w:rPr><w:t xml:space="preserve">A 😀</w:t>'));assert.ok(xml.includes('<w:rPr><w:b/></w:rPr><w:t xml:space="preserve"> B</w:t>'));assert.equal((xml.match(/<w:p>/g)??[]).length,1)
 await assert.rejects(patchDocxField(source,{...op,fieldOffset:3}),/offset/)
})
test('existing chart edit anchors chart SHA, updates caches/workbook and preserves every unrelated part',async()=>{
 const {inspectDocxCharts}=await import('../docx-chart.ts')
 const source=await buildDocx({bodyXml:'<w:p><w:r><w:t>Anchor</w:t></w:r></w:p>'}),b=(await parseDocx(source)).blocks[0]!,a={blockId:hash(hash(source)+':block:'+b.docxIndex),expectedObjectSha256:hash(b.originalXml!),position:'after'}
 const first=await patchDocxChart(source,{kind:'insertChart',...a,chart:{kind:'bar',title:'Before',categories:['A','B'],series:[{name:'S',values:[1,2]}]}}),target=(await inspectDocxCharts(first))[0]!
 const op={kind:'updateChart',blockId:target.blockId,expectedObjectSha256:target.expectedObjectSha256,expectedChartSha256:target.expectedChartSha256,chart:{kind:'bar',title:'After & 😀',categories:['甲','乙'],series:[{name:'收入',values:[42,99]}]}}
 const edited=await patchDocxChart(first,op),before=await JSZip.loadAsync(first),after=await JSZip.loadAsync(edited),chart=(await parseDocx(edited)).blocks.find(b=>b.chartDisplay)!.chartDisplay!
 assert.equal(chart.title,'After & 😀');assert.deepEqual(chart.series[0].values,[42,99]);assert.deepEqual(chart.categories,['甲','乙'])
 for(const n of Object.keys(before.files))if(!before.files[n]!.dir&&!['word/charts/chart1.xml','word/charts/embeddings/workbook1.xlsx'].includes(n))assert.deepEqual(await after.file(n)!.async('uint8array'),await before.file(n)!.async('uint8array'),n)
 const workbook=await JSZip.loadAsync(await after.file('word/charts/embeddings/workbook1.xlsx')!.async('uint8array'));assert.ok((await workbook.file('xl/worksheets/sheet1.xml')!.async('string')).includes('<v>42</v>'))
 await assert.rejects(patchDocxChart(first,{...op,expectedChartSha256:'0'.repeat(64)}),/anchor/)
})
test('five-field refresh preserves instructions, field markup, run properties and unrelated ZIP entries',async()=>{
 const {inspectDocxFields}=await import('../docx-field.ts'),generic=(i:string,v:string)=>`<w:r><w:fldChar w:fldCharType="begin"/></w:r><w:r><w:instrText xml:space="preserve"> ${i} </w:instrText></w:r><w:r><w:fldChar w:fldCharType="separate"/></w:r><w:r><w:rPr><w:i/></w:rPr><w:t>${v}</w:t></w:r><w:r><w:fldChar w:fldCharType="end"/></w:r>`
 const source=await buildDocx({bodyXml:'<w:p><w:r><w:t>Prefix</w:t></w:r>'+['DATE','TIME','PAGE','NUMPAGES','FILENAME'].map(i=>generic(i,'old')).join('')+'<w:r><w:t>Suffix</w:t></w:r></w:p>',headerXml:'<w:p/>'}),targets=await inspectDocxFields(source)
 assert.equal(targets[0]!.fields.length,5)
 const op={kind:'updateFields',updates:targets.map(t=>({blockId:t.blockId,expectedObjectSha256:t.expectedObjectSha256,fields:t.fields.map(f=>({fieldIndex:f.fieldIndex,instruction:f.instruction,result:'new & 😀'}))}))}
 const out=await patchDocxField(source,op),before=await JSZip.loadAsync(source),after=await JSZip.loadAsync(out),xml=await after.file('word/document.xml')!.async('string')
 assert.equal((xml.match(/new &amp; 😀/g)??[]).length,5);assert.equal((xml.match(/<w:rPr><w:i\/><\/w:rPr>/g)??[]).length,5);assert.ok(xml.includes('Prefix'));assert.ok(xml.includes('Suffix'))
 for(const n of Object.keys(before.files))if(!before.files[n]!.dir&&n!=='word/document.xml')assert.deepEqual(await after.file(n)!.async('uint8array'),await before.file(n)!.async('uint8array'),n)
 await assert.rejects(patchDocxField(out,op),/anchor/)
})
test('inline insertion preserves preexisting fields exactly and rejects their cached-result interior',async()=>{
 const field='<w:r><w:fldChar w:fldCharType="begin"/></w:r><w:r><w:instrText> PAGE </w:instrText></w:r><w:r><w:fldChar w:fldCharType="separate"/></w:r><w:r><w:t>88</w:t></w:r><w:r><w:fldChar w:fldCharType="end"/></w:r>',source=await buildDocx({bodyXml:'<w:p><w:r><w:t>Prefix</w:t></w:r>'+field+'<w:r><w:t>Suffix</w:t></w:r></w:p>'}),b=(await parseDocx(source)).blocks[0]!,op={kind:'insertField',blockId:hash(hash(source)+':block:'+b.docxIndex),expectedObjectSha256:hash(b.originalXml!),position:'after',fieldOffset:6,instruction:'TIME',result:'12:00'}
 const out=await patchDocxField(source,op);assert.ok((await parseDocx(out)).internal.documentXml.includes(field));await assert.rejects(patchDocxField(source,{...op,fieldOffset:7}),/offset_inside_field/)
})
test('edit selected instruction preserves split instruction wrappers, styled results and other ZIP parts',async()=>{
 const {inspectDocxFields}=await import('../docx-field.ts')
 const field='<w:r w:rsidR="12345678"><w:fldChar w:fldCharType="begin"/></w:r><w:r><w:rPr><w:i/></w:rPr><w:instrText xml:space="preserve"> PA</w:instrText></w:r><w:r><w:instrText>GE </w:instrText></w:r><w:r><w:fldChar w:fldCharType="separate"/></w:r><w:r><w:rPr><w:b/></w:rPr><w:t>8</w:t></w:r><w:r><w:rPr><w:i/></w:rPr><w:t>8</w:t></w:r><w:r><w:fldChar w:fldCharType="end"/></w:r>'
 const source=await buildDocx({bodyXml:'<w:p><w:r><w:t>Before</w:t></w:r>'+field+'<w:r><w:t>After</w:t></w:r></w:p>',headerXml:'<w:p/>'}),target=(await inspectDocxFields(source))[0]!,f=target.fields[0]!
 const op={kind:'editField',blockId:target.blockId,expectedObjectSha256:target.expectedObjectSha256,...f,newInstruction:' NUMPAGES ',newResult:'12'}
 const out=await patchDocxField(source,op),before=await JSZip.loadAsync(source),after=await JSZip.loadAsync(out),xml=await after.file('word/document.xml')!.async('string')
 assert.ok(xml.includes(field.replace(' PA',' NUMPAGES ').replace('GE </w:instrText>','</w:instrText>').replace('<w:t>8</w:t>','<w:t>1</w:t>').replace('<w:t>8</w:t>','<w:t>2</w:t>')))
 for(const name of Object.keys(before.files).filter(n=>!before.files[n]!.dir&&n!=='word/document.xml'))assert.deepEqual(await after.file(name)!.async('uint8array'),await before.file(name)!.async('uint8array'))
 assert.equal((await inspectDocxFields(out))[0]!.fields[0]!.instruction,' NUMPAGES ')
 await assert.rejects(patchDocxField(out,op),/anchor/)
 await assert.rejects(patchDocxField(source,{...op,result:'stale'}),/anchor/)
 for(const newInstruction of ['INCLUDETEXT "evil"','PAGE garbage','PAGE \\* evil','IF PAGE = 1'])await assert.rejects(patchDocxField(source,{...op,newInstruction}),/instruction/)
 const nested=await buildDocx({bodyXml:'<w:p>'+field.replace('<w:t>8</w:t>',field)+'</w:p>'});assert.deepEqual(await inspectDocxFields(nested),[])
})
