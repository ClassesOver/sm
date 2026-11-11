import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { test } from 'node:test'
import JSZip from 'jszip'
import { buildDocx } from '../../packages/docx-engine/tests/helpers/build-docx.ts'
import { parseDocx } from '../../packages/docx-engine/src/parse.ts'
import { patchDocxCaption } from '../docx-caption.ts'
const hash = (v: string | Uint8Array) => createHash('sha256').update(v).digest('hex')
const normal = '<w:p w:rsidR="ABCDEF01"><w:r><w:t>Anchor</w:t></w:r></w:p>'
const caption = (instruction = ' SEQ 图 \\* ARABIC ', number = '1') => '<w:p><w:r><w:fldChar w:fldCharType="begin"/></w:r><w:r><w:instrText>' + instruction + '</w:instrText></w:r><w:r><w:fldChar w:fldCharType="separate"/></w:r><w:r><w:t>' + number + '</w:t></w:r><w:r><w:fldChar w:fldCharType="end"/></w:r></w:p>'
async function operation(bytes: Uint8Array, index: number, position = 'after') {
 const b = (await parseDocx(bytes)).blocks[index]!
 return {kind: 'insertCaption', blockId: hash(hash(bytes) + ':block:' + b.docxIndex), expectedObjectSha256: hash(b.originalXml!), position, label: '图', text: 'A & <B> 😀'}
}
test('caption derives number from source fields and changes only document.xml', async () => {
 const source = await buildDocx({bodyXml: caption() + normal, headerXml: normal})
 const output = await patchDocxCaption(source, await operation(source, 1))
 const xml = (await parseDocx(output)).internal.documentXml
 assert.ok(xml.includes('SEQ 图 \\* ARABIC'))
 assert.ok(xml.includes('w:fldCharType="begin" w:dirty="true"'))
 assert.ok(xml.includes('<w:t>2</w:t>'))
 assert.ok(xml.includes('A &amp; &lt;B&gt; 😀'))
 assert.ok(xml.includes(normal))
 const before = await JSZip.loadAsync(source), after = await JSZip.loadAsync(output)
 for (const name of Object.keys(before.files)) if (!before.files[name]!.dir && name !== 'word/document.xml') assert.deepEqual(await after.file(name)!.async('uint8array'), await before.file(name)!.async('uint8array'), name)
 await assert.rejects(patchDocxCaption(output, await operation(source, 1)), /anchor/)
})
test('caption refuses uncertain numbering and source boundaries', async () => {
 for (const instruction of [' SEQ 图 \\r 8 ', ' SEQ 图 \\s 1 ', ' SEQ 图 \\c ', ' SEQ 图 \\* ROMAN ']) {
  const source = await buildDocx({bodyXml: caption(instruction) + normal})
  await assert.rejects(patchDocxCaption(source, await operation(source, 1)), /sequence/)
 }
 const middle = await buildDocx({bodyXml: normal + caption()})
 await assert.rejects(patchDocxCaption(middle, await operation(middle, 0)), /sequence_position/)
 const stale = await buildDocx({bodyXml: caption(undefined, '9') + normal})
 await assert.rejects(patchDocxCaption(stale, await operation(stale, 1)), /sequence/)
 const section = await buildDocx({bodyXml: normal.replace('<w:r>', '<w:pPr><w:sectPr/></w:pPr><w:r>')})
 await assert.rejects(patchDocxCaption(section, await operation(section, 0)), /anchor_unsupported/)
})
test('caption rejects client number/XML, invalid text, invalid label and forged hashes', async () => {
 const source = await buildDocx({bodyXml: normal}), op = await operation(source, 0)
 for (const extra of [{number: 55}, {genXml: '<w:p/>'}, {text: 'x'.repeat(1001)}, {text: String.fromCharCode(1)}, {text: String.fromCharCode(0xd800)}, {label: 'Figure'}, {blockId: '0'.repeat(64)}, {expectedObjectSha256: '0'.repeat(64)}]) await assert.rejects(patchDocxCaption(source, {...op, ...extra}), /caption/)
 const table = await buildDocx({bodyXml: '<w:tbl><w:tr><w:tc>' + normal + '</w:tc></w:tr></w:tbl>'})
 await assert.rejects(patchDocxCaption(table, await operation(table, 0)), /anchor_unsupported/)
})
test('caption rejects same-label fields in revisions, text boxes or locked fields but permits unrelated sequences', async () => {
 for (const old of ['<w:del>' + caption() + '</w:del>', '<w:ins>' + caption() + '</w:ins>', '<w:p><w:r><w:pict><w:txbxContent>' + caption() + '</w:txbxContent></w:pict></w:r></w:p>', caption().replace('w:fldCharType="begin"', 'w:fldCharType="begin" w:fldLock="true"')]) {
  const source = await buildDocx({bodyXml: old + normal})
  const anchor = (await parseDocx(source)).blocks.findIndex(block => block.originalXml === normal)
  await assert.rejects(patchDocxCaption(source, await operation(source, anchor)), /sequence/)
 }
 const source = await buildDocx({bodyXml: caption(' SEQ 表 ' + String.fromCharCode(92) + 'r 9 ', '9') + normal})
 const output = await patchDocxCaption(source, await operation(source, 1))
 assert.ok((await parseDocx(output)).internal.documentXml.includes('<w:t>1</w:t>'))
})
test('caption reads split escaped instructions and refuses incomplete or nested target fields', async () => {
 const split = caption().replace('SEQ 图', 'SEQ </w:instrText></w:r><w:r><w:instrText>&#22270;')
 const source = await buildDocx({bodyXml: split + normal})
 assert.ok((await parseDocx(await patchDocxCaption(source, await operation(source, 1)))).internal.documentXml.includes('<w:t>2</w:t>'))
 for (const old of [caption().replace('<w:r><w:fldChar w:fldCharType="end"/></w:r>', ''), caption().replace('<w:t>1</w:t>', '<w:fldChar w:fldCharType="begin"/><w:t>1</w:t><w:fldChar w:fldCharType="end"/>'), '<w:p><w:fldSimple w:instr="SEQ 图"><w:r><w:t>1</w:t></w:r></w:fldSimple></w:p>']) {
  const bytes = await buildDocx({bodyXml: old + normal})
  const anchor = (await parseDocx(bytes)).blocks.findIndex(block => block.originalXml === normal)
  await assert.rejects(patchDocxCaption(bytes, await operation(bytes, anchor)), /sequence/)
 }
})
test('caption refuses protected source and alternate Word namespaces without modifying bytes', async () => {
 const source = await buildDocx({bodyXml: normal})
 const zip = await JSZip.loadAsync(source)
 zip.file('word/settings.xml','<w:settings xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:documentProtection w:edit="readOnly" w:enforcement="1"/></w:settings>')
 const locked = await zip.generateAsync({type:'uint8array'})
 await assert.rejects(patchDocxCaption(locked, await operation(locked, 0)), /source_unsupported/)
 const alias = await buildDocx({bodyXml:normal,docRootExtraAttrs:'xmlns:wx="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'})
 await assert.rejects(patchDocxCaption(alias, await operation(alias, 0)), /unsupported/)
})
test('caption cannot overlook a sequence instruction encoded as CDATA', async () => {
 const source = await buildDocx({bodyXml:caption().replace(' SEQ 图 ', '<![CDATA[ SEQ 图 ]]>') + normal})
 const output = await patchDocxCaption(source, await operation(source, 1))
 assert.ok((await parseDocx(output)).internal.documentXml.includes('<w:t>2</w:t>'))
})
test('caption cannot overlook a sequence instruction with a quoted greater-than attribute', async () => {
 const source = await buildDocx({bodyXml:caption().replace('<w:instrText>', '<w:instrText data-opaque=">">') + normal})
 const output = await patchDocxCaption(source, await operation(source, 1))
 assert.ok((await parseDocx(output)).internal.documentXml.includes('<w:t>2</w:t>'))
})
test('caption reads actual field attributes rather than attribute-like text in metadata', async () => {
 const quote=String.fromCharCode(39)
 const source=await buildDocx({bodyXml:'<w:p><w:fldSimple data-opaque="w:instr='+quote+'SEQ 表'+quote+'" w:instr="SEQ 图"><w:r><w:t>1</w:t></w:r></w:fldSimple></w:p>'+normal})
 await assert.rejects(patchDocxCaption(source, await operation(source,1)),/sequence/)
})
