/** Verified static report images; no native Office chart construction. */
import { readFile } from 'node:fs/promises'
import { createHash } from 'node:crypto'
import { basename, isAbsolute } from 'node:path'
import JSZip from 'jszip'
import { z } from 'zod'
import { applyStaticImage, parseRange, readWorkbook } from '@sheets-web/xlsx-engine'

const relativeIdentityPath = z.string().min(1).refine(value => !isAbsolute(value) && !value.includes('\\') && !value.split('/').includes('..'), 'workbook_identity_path_invalid')
const identity = z.object({ path: z.string().min(1), size: z.number().int().positive(), sha256: z.string().regex(/^[a-f0-9]{64}$/), identityPath: relativeIdentityPath.optional() })
const sourceRange = z.object({ sheetName: z.string().min(1), range: z.string().min(1) }).strict()
const imageSchema = identity.extend({
  imageId: z.string().min(1), sheetName: z.string().min(1), range: z.string().min(1),
  chartId: z.string().min(1), snapshotId: z.string().min(1), chartRevision: z.string().min(1),
  sourceRanges: z.array(sourceRange).min(1), sourceFiles: z.array(identity).optional(),
}).strict()
const MAPPING = 'smart-reporting/source-mapping.json'

function storedIdentity(file: z.infer<typeof identity>) {
  // 绝对路径仅用于宿主读取，不能随下载工作簿泄露工作区根目录。
  return { path: file.identityPath ?? (isAbsolute(file.path) ? basename(file.path) : file.path),
    size: file.size, sha256: file.sha256 }
}

async function verifiedBytes(file: z.infer<typeof identity>): Promise<Uint8Array> {
  const bytes = await readFile(file.path)
  if (bytes.length !== file.size || createHash('sha256').update(bytes).digest('hex') !== file.sha256) {
    throw new Error('workbook_image_identity_changed')
  }
  return bytes
}

export async function workbookSourceMapping(bytes: Uint8Array): Promise<any> {
  const zip = await JSZip.loadAsync(bytes)
  const part = zip.file(MAPPING)
  return part ? JSON.parse(await part.async('string')) : { version: 1, sources: {}, images: [] }
}

export async function applyStaticImages(
  input: Uint8Array, images: readonly unknown[], sourceMapping?: Record<string, any>,
  rejectedIssues: Record<string, any>[] = [],
): Promise<{ bytes: Uint8Array; issues: Record<string, any>[] }> {
  let bytes = input
  const mapping = await workbookSourceMapping(bytes)
  const sources = { ...(mapping.sources ?? {}), ...sourceMapping }
  if (mapping.sources?.chartRevisions || sourceMapping?.chartRevisions) {
    sources.chartRevisions = { ...mapping.sources?.chartRevisions, ...sourceMapping?.chartRevisions }
  }
  const stored: any[] = [...(mapping.images ?? [])]
  const issues: Record<string, any>[] = [...rejectedIssues]
  const model = await readWorkbook(bytes)
  const sheetNames = new Set(model.sheets.map(sheet => sheet.name))
  const seen = new Set<string>()
  for (const raw of images) {
    try {
      const image = imageSchema.parse(raw)
      if (seen.has(image.imageId)) throw new Error('workbook_image_id_duplicate')
      seen.add(image.imageId)
      if (sources.snapshotId !== undefined && sources.snapshotId !== image.snapshotId) throw new Error('workbook_image_snapshot_mismatch')
      if (sources.chartRevisions?.[image.chartId] !== undefined && sources.chartRevisions[image.chartId] !== image.chartRevision) {
        throw new Error('workbook_image_chart_revision_mismatch')
      }
      const bounds = parseRange(image.range)
      for (const range of [{ sheetName: image.sheetName, range: image.range }, ...image.sourceRanges]) {
        const area = parseRange(range.range)
        if (!sheetNames.has(range.sheetName) || area.endRow > 1048575 || area.endColumn > 16383) throw new Error('workbook_image_range_invalid')
      }
      const previous = stored.find(item => item.imageId === image.imageId)
      if (previous && (previous.sheetName !== image.sheetName || previous.range !== image.range)) throw new Error('workbook_image_reanchor_unsupported')
      for (const file of image.sourceFiles ?? []) await verifiedBytes(file)
      // Read immediately before use; embedding consumes these verified bytes.
      const content = await verifiedBytes(image)
      const png = Buffer.from(content.subarray(0, 8)).equals(Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]))
      const jpeg = content[0] === 255 && content[1] === 216 && content[2] === 255
      if (!png && !jpeg) throw new Error('workbook_image_format_invalid')
      const result = await applyStaticImage(bytes, {
        worksheetSheetName: image.sheetName, imageId: image.imageId, bytes: content,
        contentType: png ? 'image/png' : 'image/jpeg', replaceMediaPart: previous?.mediaPart,
        anchor: { fromRow: bounds.startRow, fromColumn: bounds.startColumn, fromRowOffset: 0, fromColumnOffset: 0,
          toRow: bounds.endRow + 1, toColumn: bounds.endColumn + 1, toRowOffset: 0, toColumnOffset: 0 },
      })
      bytes = result.bytes
      const { identityPath: _identityPath, sourceFiles: _sourceFiles, ...metadata } = image
      const entry = { ...metadata, ...storedIdentity(image),
        ...(image.sourceFiles ? { sourceFiles: image.sourceFiles.map(storedIdentity) } : {}),
        mediaPart: result.mediaPart, contentType: png ? 'image/png' : 'image/jpeg' }
      const index = stored.findIndex(item => item.imageId === image.imageId)
      if (index < 0) stored.push(entry)
      else stored[index] = entry
    } catch (error) {
      issues.push({ code: 'workbook_image_rejected', imageId: (raw as any)?.imageId ?? '',
        message: error instanceof Error ? error.message : String(error) })
    }
  }
  const zip = await JSZip.loadAsync(bytes)
  zip.file(MAPPING, JSON.stringify({ ...mapping, sources, images: stored, imageIssues: issues }))
  return { bytes: await zip.generateAsync({ type: 'uint8array', compression: 'DEFLATE' }), issues }
}
