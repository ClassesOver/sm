import assert from 'node:assert/strict'
import {createHash} from 'node:crypto'
import {test} from 'node:test'
import {parseDocx,generateTableModelXml} from '../../packages/docx-engine/src/index.ts'
import {buildDocx} from '../../packages/docx-engine/tests/helpers/build-docx.ts'
import {editDocxTableCellOperation,tableCellOperationsAvailability} from '../docx-table-cell-operations.ts'
const xml=generateTableModelXml({rows:['A','B','C'].map(r=>[0,1,2].map(c=>({paras:[`${r}${c}`],fill:c===0?'FFFF00':undefined}))),colWidthsTwips:[1201,2400,3600],colWidthsPct:[20,30,50],autoFit:'fixed',rowHeightsTwips:[500,600,700],rowCantSplit:[true,false,false]})
const open=async(bodyXml=xml)=>(await parseDocx(await buildDocx({bodyXml}))).blocks.find(b=>b.type==='table')!
const rect={top:0,left:0,bottom:1,right:1}
async function run(change:any,body=xml){const b=await open(body),ctx={blockId:'t',expectedObjectSha256:createHash('sha256').update(b.originalXml!).digest('hex'),protectedDocument:false,maxWidthTwips:9360},op={kind:'editTableCells',blockId:'t',expectedObjectSha256:ctx.expectedObjectSha256,change};return {b,ctx,op,result:editDocxTableCellOperation(b,op,ctx)}}
test('inserts blank formatted rows preserving existing paragraphs and inherited row flags',async()=>{const {b,result}=await run({type:'insert',rect,where:'above',count:2});const read=await open(result.replacementXml);assert.equal(read.table!.rows.length,5);assert.equal(read.table!.rows[0][0].paras[0],'');assert.equal(read.table!.rows[0][0].fill,'FFFF00');assert.equal(read.table!.rowHeightsTwips![0],500);assert.equal(read.table!.rowCantSplit![0],true);for(const p of b.originalXml!.match(/<w:p\b[\s\S]*?<\/w:p>/g)!)assert.ok(result.replacementXml.includes(p))})
test('inserts columns and fits authoritative width',async()=>{const {result}=await run({type:'insert',rect,where:'right',count:2});const read=await open(result.replacementXml);assert.equal(read.table!.rows[0].length,5);assert.ok(read.table!.colWidthsTwips!.reduce((a,b)=>a+b,0)<=9362);assert.equal(read.table!.rows[0][1].paras[0],'');assert.equal(read.table!.rows[0][1].fill,'FFFF00')})
test('shiftLeft emits native gridAfter and moves cells',async()=>{const {result}=await run({type:'delete',rect,mode:'shiftLeft'});assert.match(result.replacementXml,/<w:gridAfter w:val="1"\/>/);const read=await open(result.replacementXml);assert.equal(read.table!.rows[0][0].paras[0],'A1');assert.equal(read.table!.rows[1][0].paras[0],'B0')})
test('shiftUp moves cells and blank inherits formatting',async()=>{const {result}=await run({type:'delete',rect,mode:'shiftUp'});const read=await open(result.replacementXml);assert.deepEqual(read.table!.rows.map(r=>r[0].paras[0]),['B0','C0','']);assert.equal(read.table!.rows[2][0].fill,'FFFF00')})
test('full row/column removal and shiftLeft empty output',async()=>{for(const mode of ['row','column','shiftLeft']){const {result}=await run({type:'delete',rect:{top:0,left:0,bottom:3,right:3},mode});assert.equal(result.replacementXml,mode==='shiftLeft'?'<w:p/>':'')}})
test('rejects forged references malformed payloads protection and budgets',async()=>{const {b,ctx,op}=await run({type:'delete',rect,mode:'row'});assert.equal(tableCellOperationsAvailability(b,false,9360).tableCellsEditable,true);assert.equal(tableCellOperationsAvailability(b,true,9360).tableCellsEditable,false);for(const bad of [{...op,blockId:'other'},{...op,expectedObjectSha256:'0'.repeat(64)},{...op,clientXml:'x'},{...op,change:{...op.change,rect:{...rect,right:4}}},{...op,change:{type:'insert',rect,where:'left',count:100}},{...op,change:{...op.change,extra:1}}])assert.throws(()=>editDocxTableCellOperation(b,bad,ctx));assert.throws(()=>editDocxTableCellOperation(b,op,{...ctx,protectedDocument:true}))})
test('new shifted blank retains exact first pPr and surviving paragraph/run bytes',async()=>{
 const original=xml.replace('<w:p>','<w:p w:rsidR="AABBCCDD"><w:pPr><w:keepNext/><w:spacing w:after="103"/></w:pPr>').replace('>C0</w:t>','> C0 </w:t>')
 const {result}=await run({type:'delete',rect:{top:0,left:0,bottom:1,right:1},mode:'shiftUp'},original)
 assert.ok(result.replacementXml.includes('<w:t xml:space="preserve"> C0 </w:t>'))
 const lastStyle=xml.replace(/<w:p>(<w:r><w:t[^>]*>C0<\/w:t>)/,'<w:p><w:pPr><w:keepNext/></w:pPr>$1')
 const shifted=await run({type:'delete',rect,mode:'shiftUp'},lastStyle)
 assert.ok(shifted.result.replacementXml.includes('<w:p><w:pPr><w:keepNext/></w:pPr></w:p>'))
})
test('ordinary auto/pct source widths retain table property semantics',async()=>{for(const w of ['<w:tblW w:w="0" w:type="auto"/>','<w:tblW w:w="5000" w:type="pct"/>']){const source=xml.replace(/<w:tblW\b[^>]*\/>/,w).replace(/<w:tblLayout\b[^>]*\/>/,'');const {result}=await run({type:'insert',rect,where:'right',count:1},source);assert.ok(result.replacementXml.includes(w));assert.equal((await open(result.replacementXml)).table!.rows[0].length,4)}})
test('source guard independently rejects revisions nested/merged cells and namespace rebinding',async()=>{for(const tag of ['<w:commentReference w:id="1"/>','<w:ins/>','<w:tbl/>','<w:gridSpan w:val="2"/>','<w:sdt/>']){const b=await open(xml.replace('</w:tcPr>',tag+'</w:tcPr>'));assert.equal(tableCellOperationsAvailability(b,false,9360).tableCellsEditable,false)}const b=await open();for(const originalXml of [b.originalXml!.replace('<w:tbl>','<w:tbl xmlns:w="urn:foreign">'),b.originalXml!.replace('</w:tbl>','</w:wrong>')])assert.equal(tableCellOperationsAvailability({...b,originalXml},false,9360).tableCellsEditable,false)})
test('inserted row/column blank paragraphs do not acquire copied cell aggregate alignment',async()=>{
 const centered=xml.replace(/<w:p>/g,'<w:p><w:pPr><w:jc w:val="center"/></w:pPr>')
 for(const where of ['above','right']){
  const {result}=await run({type:'insert',rect,where,count:1},centered)
  const rows=result.replacementXml.match(/<w:tr>[\s\S]*?<\/w:tr>/g)!
  const row=rows[0],cells=row.match(/<w:tc>[\s\S]*?<\/w:tc>/g)!,inserted=cells[where==='above'?0:1]
  assert.doesNotMatch(inserted,/<w:jc\b/)
  assert.match(inserted,/<w:p><\/w:p>/)
 }
})
