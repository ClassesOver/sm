import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { test } from 'node:test'
import { buildDocx } from '../../packages/docx-engine/tests/helpers/build-docx.ts'
import JSZip from 'jszip'
import { parseDocx } from '../../packages/docx-engine/src/parse.ts'
import { patchDocxToc } from '../docx-toc.ts'

const hash = (value: string | Uint8Array) => createHash('sha256').update(value).digest('hex')
const normal = '<w:p w:rsidR="ABCDEF01"><w:r><w:t>Untouched</w:t></w:r></w:p>'
const h1 = '<w:p><w:pPr><w:outlineLvl w:val="0"/></w:pPr><w:r><w:t>Income &amp; Costs</w:t></w:r></w:p>'
const h2 = '<w:p><w:pPr><w:outlineLvl w:val="1"/></w:pPr><w:r><w:t>Detail</w:t></w:r></w:p>'
const styles = '<w:style w:type="paragraph" w:styleId="CustomHeading"><w:name w:val="Custom Heading"/><w:pPr><w:outlineLvl w:val="2"/><w:numPr><w:ilvl w:val="0"/><w:numId w:val="1"/></w:numPr></w:pPr></w:style>'
const styled = '<w:p><w:pPr><w:pStyle w:val="CustomHeading"/></w:pPr><w:r><w:t>Styled title</w:t></w:r></w:p>'
const op = async (bytes: Uint8Array, index: number) => {
  const block = (await parseDocx(bytes)).blocks[index]!
  return { blockId: hash(`${hash(bytes)}:block:${block.docxIndex}`), expectedObjectSha256: hash(block.originalXml!) }
}

test('insert generates a native dirty Word field, preserves other XML, and reopens', async () => {
  const source = await buildDocx({ bodyXml: normal + h1 + h2 + styled, extraStylesXml: styles,
    headerXml: '<w:p><w:pPr><w:pStyle w:val="Normal"/><w:pStyle w:val="Header"/></w:pPr><w:r><w:t>Raw header</w:t></w:r></w:p>' })
  const output = await patchDocxToc(source, { kind: 'insertToc', ...(await op(source, 0)), position: 'after' })
  const reopened = await parseDocx(output), xml = reopened.internal.documentXml
  assert.match(xml, /w:fldCharType="begin" w:dirty="true"/)
  assert.ok(xml.indexOf(normal) < xml.indexOf('TOC \\o') && xml.indexOf('TOC \\o') < xml.indexOf(h1))
  assert.deepEqual(reopened.blocks.filter(block => block.fieldDisplay?.kind === 'tocLine').map(block => block.fieldDisplay?.left), ['Income & Costs', 'Detail', 'Styled title'])
  const before = await JSZip.loadAsync(source), after = await JSZip.loadAsync(output)
  for (const file of Object.keys(before.files)) if (!before.files[file]!.dir && file !== 'word/document.xml') {
    assert.deepEqual(await before.file(file)!.async('uint8array'), await after.file(file)!.async('uint8array'), file)
  }
  const refreshed = await patchDocxToc(output, { kind: 'updateToc', ...(await op(output, 1)) })
  assert.equal((await parseDocx(refreshed)).internal.documentXml, xml)
  await assert.rejects(patchDocxToc(output, { kind: 'insertToc', ...(await op(source, 0)), position: 'after' }), /anchor/)
})

const begin = '<w:p><w:r><w:fldChar w:fldCharType="begin"/></w:r><w:r><w:instrText> TOC \\o "1-3" </w:instrText></w:r><w:r><w:fldChar w:fldCharType="separate"/></w:r></w:p>'
const entry = '<w:p><w:pPr><w:pStyle w:val="TOC1"/></w:pPr><w:hyperlink w:anchor="_Toc1"><w:r><w:t>Old title</w:t></w:r></w:hyperlink><w:r><w:fldChar w:fldCharType="begin"/></w:r><w:r><w:instrText> PAGEREF _Toc1 \\h </w:instrText></w:r><w:r><w:fldChar w:fldCharType="separate"/></w:r><w:r><w:t>1</w:t></w:r><w:r><w:fldChar w:fldCharType="end"/></w:r></w:p>'
const end = '<w:p><w:r><w:fldChar w:fldCharType="end"/></w:r><w:r><w:br w:type="page"/></w:r></w:p>'
test('update replaces only the complete TOC, including nested PAGEREF and a trailing page break', async () => {
  const source = await buildDocx({ bodyXml: normal + begin + entry + end + h1 + h2 })
  const output = await patchDocxToc(source, { kind: 'updateToc', ...(await op(source, 1)) })
  const reopened = await parseDocx(output), xml = reopened.internal.documentXml
  assert.equal(xml.match(/TOC \\o/g)?.length, 1)
  assert.doesNotMatch(xml, /Old title|PAGEREF/)
  assert.ok(xml.includes(normal) && xml.includes(h1) && xml.includes(h2))
  assert.ok(xml.includes('<w:p><w:r><w:br w:type="page"/></w:r></w:p>' + h1))
  assert.deepEqual(reopened.blocks.filter(block => block.fieldDisplay?.kind === 'tocLine').map(block => block.fieldDisplay?.left), ['Income & Costs', 'Detail'])
})

test('a malformed or mixed directory is never rewritten', async () => {
  for (const region of [
    begin + entry, begin + entry + normal + end,
    begin + entry.replace('<w:r><w:t>1', '<w:r><w:drawing/><w:t>1') + end,
    begin.replace('<w:p>', '<w:p><w:r><w:t>Prose before TOC</w:t></w:r>') + entry + end,
    begin + entry + end.replace('</w:p>', '<w:r><w:t>Prose after TOC</w:t></w:r></w:p>').replace('<w:p>', '<w:p><w:pPr><w:pStyle w:val="TOC1"/></w:pPr>'),
  ]) {
    const source = await buildDocx({ bodyXml: normal + region + h1 })
    await assert.rejects(patchDocxToc(source, { kind: 'updateToc', ...(await op(source, 1)) }), /toc/)
  }
  const source = await buildDocx({ bodyXml: normal })
  await assert.rejects(patchDocxToc(source, { kind: 'insertToc', ...(await op(source, 0)), position: 'before' }), /heading/)
})

test('a standard Word TOC content control retains its title and wrapper', async () => {
  const open = '<w:sdt><w:sdtPr><w:docPartObj><w:docPartGallery w:val="Table of Contents"/><w:docPartUnique/></w:docPartObj></w:sdtPr><w:sdtContent>'
  const close = '</w:sdtContent></w:sdt>'
  const source = await buildDocx({ bodyXml: open + normal + begin + entry + end + close + h1 })
  const parsed = await parseDocx(source)
  const first = parsed.blocks.findIndex(block => block.originalXml?.includes(' TOC '))
  assert.ok(first >= 0)
  const saved = await patchDocxToc(source, { kind: 'updateToc', ...(await op(source, first)) })
  const xml = (await parseDocx(saved)).internal.documentXml
  assert.ok(xml.includes(open + normal))
  assert.ok(xml.includes(close + h1))
  assert.match(xml, /Income &amp; Costs/)
  assert.doesNotMatch(xml, /Old title/)
  const locked = await buildDocx({ bodyXml: open.replace('<w:docPartObj>', '<w:lock w:val="sdtContentLocked"/><w:docPartObj>') + normal + begin + entry + end + close + h1 })
  await assert.rejects(patchDocxToc(locked, { kind: 'updateToc', ...(await op(locked, first)) }), /toc_region/)
})
