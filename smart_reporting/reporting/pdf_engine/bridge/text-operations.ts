/** Native text edits are resolved exclusively against immutable source PDF objects. */
import { createHash } from 'node:crypto'
import { readFile } from 'node:fs/promises'
import { applyTextEdits, inspectTextObjects, validateTextEdits, norm } from '../src/main/text-edit'
import { pdfiumWasmPath, hbSubsetWasmPath } from '../src/main/wasm-path'
import type { TextEditInput } from '../src/shared/ipc'

const hash = (data: string | Uint8Array) => createHash('sha256').update(data).digest('hex')
export async function inspectNativeText(content: Uint8Array, sourceSha256: string) {
  return (await inspectTextObjects(content)).map((objects, pageIndex) => objects.map(({ objectPath, ...object }) => ({
    ...object, expectedTextSha256: hash(object.text),
    objectId: `sha256:${sourceSha256}:text:${pageIndex}:${hash(JSON.stringify([objectPath, object.text, object.rect]))}`,
  })))
}
export async function textResourcesIdentity() {
  return { pdfium: hash(await readFile(pdfiumWasmPath())), harfbuzz: hash(await readFile(hbSubsetWasmPath())) }
}
export interface ReplaceTextOperation { kind: 'replaceText'; pageId: string; objectId: string; expectedTextSha256: string; newText: string }
export interface SkippedOperation { operationIndex: number; kind: 'replaceText'; pageId: string; reason: string }

export async function prepareTextEdits(content: Uint8Array, pages: { pageId: string; cropBox: {x:number;y:number;width:number;height:number}; textObjects?: Awaited<ReturnType<typeof inspectNativeText>>[number] }[], operations: readonly unknown[]) {
  const edits: TextEditInput[] = [], indices: number[] = [], skipped: SkippedOperation[] = []
  const used = new Set<string>()
  for (const [operationIndex, raw] of operations.entries()) {
    const op = raw as ReplaceTextOperation
    if (op.kind !== 'replaceText') continue
    const skip = (reason: string) => skipped.push({ operationIndex, kind: 'replaceText', pageId: op.pageId, reason })
    const pageIndex = pages.findIndex(page => page.pageId === op.pageId)
    const objects = pages[pageIndex]?.textObjects ?? []
    const target = objects.find(item => item.objectId === op.objectId && item.expectedTextSha256 === op.expectedTextSha256)
    if (!target || !target.text.trim() || used.has(op.objectId)) { skip('pdf_text_identity_invalid_or_repeated'); continue }
    used.add(op.objectId)
    const [x1, y1, x2, y2] = target.rect
    const overlaps = objects.filter(other => {
      const [a,b,c,d] = other.rect
      return Math.max(0, Math.min(c,x2)-Math.max(a,x1)) * Math.max(0,Math.min(d,y2)-Math.max(b,y1)) > (x2-x1)*(y2-y1)*.5
    })
    if (overlaps.length !== 1) { skip('pdf_text_identity_ambiguous'); continue }
    // Single horizontal object only. Reflow, multiline, style/font overrides are out of scope.
    if (/[\r\n]/.test(op.newText)) { skip('pdf_text_overflow_multiline_unsupported'); continue }
    const edit: TextEditInput = { pageIndex, rect: [...target.rect], oldText: target.text, newText: op.newText, fontSize: target.fontSize }
    const [validation] = await validateTextEdits(content, [edit])
    if (validation.reason) { skip(validation.reason); continue }
    try {
      const result = await applyTextEdits(content, [edit])
      if (result.skipped.length) { skip(result.skipped[0].reason); continue }
      if (op.newText.trim()) {
        const rebuilt = (await inspectNativeText(result.bytes, hash(result.bytes)))[pageIndex].filter(item => Math.min(item.rect[3], y2) > Math.max(item.rect[1], y1) && Math.min(item.rect[2], x2) > Math.max(item.rect[0], x1))
        const slack = Math.max(2, target.fontSize * .4)
        const horizontalSlack = Math.max(2, target.fontSize)
        const box = pages[pageIndex].cropBox
        const collision = rebuilt.some(item => objects.some(other => other.objectId !== target.objectId && Math.min(item.rect[2],other.rect[2]) > Math.max(item.rect[0],other.rect[0]) && Math.min(item.rect[3],other.rect[3]) > Math.max(item.rect[1],other.rect[1])))
        const outsidePage = rebuilt.some(item => item.rect[0] < box.x || item.rect[1] < box.y || item.rect[2] > box.x+box.width || item.rect[3] > box.y+box.height)
        if (collision || outsidePage) { skip('pdf_text_overflow_page_or_neighbor'); continue }
        const inBox = rebuilt.filter(item => item.rect[0] >= x1-slack && item.rect[1] >= y1-slack && item.rect[2] <= x2+horizontalSlack && item.rect[3] <= y2+slack)
        if (!inBox.length || inBox.length !== rebuilt.length || norm(inBox.sort((a,b) => a.rect[0]-b.rect[0]).map(item => item.text).join('')) !== norm(op.newText)) { skip('pdf_text_overflow_or_unverifiable_output'); continue }
      }
      edits.push(edit); indices.push(operationIndex)
    } catch (error) {
      skip(error instanceof Error ? error.message : 'pdf_text_edit_failed')
    }
  }
  return { edits, indices, skipped }
}

/** Deployment readiness exercises exactly the font resolution/subset/write path used by edits. */
export async function checkTextResources() {
  try {
    const { PDFDocument, StandardFonts } = await import('pdf-lib')
    const document = await PDFDocument.create()
    const page = document.addPage([400, 300])
    const font = await document.embedFont(StandardFonts.Helvetica)
    const oldText = 'FONT READINESS 123'
    const newText = '报告金额一二三123'
    page.drawText(oldText, { x: 30, y: 230, size: 14, font })
    const source = await document.save()
    const edit: TextEditInput = { pageIndex: 0, rect: [25,220,350,255], oldText, newText, fontSize: 14 }
    const result = await applyTextEdits(source, [edit])
    if (result.skipped.length) throw new Error(result.skipped[0].reason)
    const objects = (await inspectNativeText(result.bytes, hash(result.bytes)))[0]
    if (norm(objects.map(item => item.text).join('')) !== norm(newText)) throw new Error('pdf_text_resource_rebuild_unreadable')
    const fonts = objects.map(({fontName,fontSha256}) => ({fontName,fontSha256}))
    if (fonts.some(font => !font.fontSha256)) throw new Error('pdf_text_resource_font_not_embedded')
    return { ok: true, fonts, resources: await textResourcesIdentity(), issues: [] }
  } catch (error) {
    return { ok: false, fonts: [], issues: [{ code: 'pdf_text_resources_unavailable', message: error instanceof Error ? error.message : 'PDF 字体资源不可用' }] }
  }
}
