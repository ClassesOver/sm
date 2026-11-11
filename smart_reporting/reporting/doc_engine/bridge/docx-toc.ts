import { createHash } from 'node:crypto'
import JSZip from 'jszip'
import { parseDocx } from '../packages/docx-engine/src/parse.ts'
import { assertZipIdentity } from './docx-comment-source.ts'
import { docxTocEntries, docxTocRegion, docxTocSource, docxTocXml, readDocxTocOperation } from './docx-toc-core.ts'
export { isDocxTocOperation } from './docx-toc-core.ts'

const hash = (value: Uint8Array | string) => createHash('sha256').update(value).digest('hex')
const main = 'word/document.xml'

/** Write the authorized source snapshot without regenerating unrelated package parts. */
export async function patchDocxToc(bytes: Uint8Array, value: unknown, parsed?: Awaited<ReturnType<typeof parseDocx>>) {
  const op = readDocxTocOperation(value)
  parsed ??= await parseDocx(bytes)
  const source = docxTocSource(parsed), sourceHash = hash(bytes)
  if (!source.safe) throw new Error('docx_toc_source_unsupported')
  const block = parsed.blocks.find(item => item.docxIndex != null && hash(`${sourceHash}:block:${item.docxIndex}`) === op.blockId)
  if (!block?.originalXml || block.docxIndex == null || hash(block.originalXml) !== op.expectedObjectSha256) throw new Error('docx_toc_anchor')
  const paragraph = source.paragraphs.get(block.docxIndex)
  const entries = docxTocEntries(parsed)
  if (!entries.length) throw new Error('docx_toc_no_headings')
  let from: number, to: number, keepPageBreak = false
  if (op.kind === 'insertToc') {
    if (!paragraph || !['heading', 'paragraph', 'listItem'].includes(block.type)
      || (op.position === 'after' && /<w:sectPr\b/.test(block.originalXml))) throw new Error('docx_toc_anchor_unsupported')
    from = to = op.position === 'before' ? paragraph.start : paragraph.end
  } else {
    const region = docxTocRegion(parsed, source)
    if (!region.indices || region.indices[0] !== block.docxIndex) throw new Error('docx_toc_region_unsupported')
    ;({ start: from, end: to, keepPageBreak } = region)
  }
  // parseDocx applies the metered ZIP limit before this raw write path.
  assertZipIdentity(bytes)
  const zip = await JSZip.loadAsync(bytes)
  if (await zip.file(main)?.async('string') !== source.xml) throw new Error('docx_toc_main_part_unsupported')
  const outputXml = source.xml.slice(0, from) + docxTocXml(entries, keepPageBreak).join('') + source.xml.slice(to)
  zip.file(main, outputXml, { createFolders: false })
  return zip.generateAsync({ type: 'uint8array', compression: 'DEFLATE' })
}
