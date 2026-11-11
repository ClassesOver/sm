import { createHash } from 'node:crypto'
import JSZip from 'jszip'
import { parseDocx } from '../packages/docx-engine/src/parse.ts'
import { assertZipIdentity } from './docx-comment-source.ts'
import { docxCaptionNumber, docxCaptionPlan, docxCaptionXml, readDocxCaptionOperation } from './docx-caption-core.ts'
export { isDocxCaptionOperation } from './docx-caption-core.ts'
const hash = (value: Uint8Array | string) => createHash('sha256').update(value).digest('hex')
export async function patchDocxCaption(bytes: Uint8Array, value: unknown, parsed?: Awaited<ReturnType<typeof parseDocx>>) {
  const op = readDocxCaptionOperation(value)
  parsed ??= await parseDocx(bytes)
  const source = docxCaptionPlan(parsed, op), sourceHash = hash(bytes)
  const block = parsed.blocks.find(item => item.docxIndex != null && hash(sourceHash + ':block:' + item.docxIndex) === op.blockId)
  if (!block?.originalXml || block.docxIndex == null || hash(block.originalXml) !== op.expectedObjectSha256) throw new Error('docx_caption_anchor')
  const paragraph = source.paragraphs.get(block.docxIndex)
  if (!paragraph || !['heading', 'paragraph', 'listItem'].includes(block.type)
    || (op.position === 'after' && /<w:sectPr\b/.test(block.originalXml))) throw new Error('docx_caption_anchor_unsupported')
  const at = op.position === 'before' ? paragraph.start : paragraph.end
  const number = docxCaptionNumber(source.xml, op.label, at)
  assertZipIdentity(bytes)
  const zip = await JSZip.loadAsync(bytes)
  if (await zip.file('word/document.xml')?.async('string') !== source.xml) throw new Error('docx_caption_main_part_unsupported')
  zip.file('word/document.xml', source.xml.slice(0, at) + docxCaptionXml(op.label, number, op.text) + source.xml.slice(at), { createFolders: false })
  return zip.generateAsync({ type: 'uint8array', compression: 'DEFLATE' })
}
