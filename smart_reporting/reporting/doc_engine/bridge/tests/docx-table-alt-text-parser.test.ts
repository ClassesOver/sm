import assert from 'node:assert/strict'
import {test} from 'node:test'
import {parseDocx} from '../../packages/docx-engine/src/index.ts'
import {buildDocx} from '../../packages/docx-engine/tests/helpers/build-docx.ts'
test('alt attributes decode decimal hex XML symbols and literal numeric-looking strings exactly once',async()=>{
 for(const [raw,expected] of [['a&#10;b','a\nb'],['a&#xA;b','a\nb'],['中文 &amp; &lt;A&gt; &quot;B&quot;','中文 & <A> "B"'],['&amp;#10; &amp;#xA;','&#10; &#xA;']]){
  const bytes=await buildDocx({bodyXml:`<w:tbl><w:tblPr><w:tblCaption w:val="${raw}"/><w:tblDescription w:val="${raw}"/></w:tblPr><w:tblGrid><w:gridCol w:w="2000"/></w:tblGrid><w:tr><w:tc><w:p/></w:tc></w:tr></w:tbl>`}),block=(await parseDocx(bytes)).blocks.find(b=>b.type==='table')!
  assert.equal(block.table!.caption,expected);assert.equal(block.table!.description,expected)
 }
})

test('raw alt attributes support single quotes whitespace paired tags empty values and greater-than characters',async()=>{
 for(const tag of ["<w:tblCaption w:val = 'a > b&#10;c'></w:tblCaption>",'<w:tblCaption w:val = "a > b&#10;c"/>']){
  const bytes=await buildDocx({bodyXml:`<w:tbl><w:tblPr>${tag}<w:tblDescription w:val = ''/></w:tblPr><w:tblGrid><w:gridCol w:w="2000"/></w:tblGrid><w:tr><w:tc><w:p/></w:tc></w:tr></w:tbl>`}),block=(await parseDocx(bytes)).blocks.find(b=>b.type==='table')!
  assert.equal(block.table!.caption,'a > b\nc');assert.equal(block.table!.description,undefined)
 }
})
