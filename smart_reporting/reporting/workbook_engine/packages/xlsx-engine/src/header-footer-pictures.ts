import JSZip from 'jszip'
import { SaxesParser } from 'saxes'
import { readWorkbook } from './workbook-read'
import { resolvePivotTarget } from './pivot-add'

const MAX_PICTURES_PER_SHEET = 18
const MAX_PICTURE_BYTES = 2 * 1024 * 1024

export interface HeaderFooterPicture {
  readonly position: string
  readonly widthPt: number
  readonly heightPt: number
  readonly mediaType: string
  readonly bytes: Uint8Array
}

interface Relationship { target: string; type: string; external: boolean }
interface VmlPicture { id: string; style: string; relationshipId: string }

const attribute = (attrs: Record<string, unknown>, wanted: string): string | undefined => {
  for (const [name, value] of Object.entries(attrs)) {
    if ((name.split(':').at(-1) ?? name) === wanted && typeof value === 'string') return value
  }
  return undefined
}

function readRelationships(xml: string | undefined): Map<string, Relationship> {
  const result = new Map<string, Relationship>()
  if (!xml) return result
  const parser = new SaxesParser({ xmlns: false })
  parser.on('opentag', tag => {
    if ((tag.name.split(':').at(-1) ?? tag.name) !== 'Relationship') return
    const id = attribute(tag.attributes, 'Id'), target = attribute(tag.attributes, 'Target')
    if (!id || !target) return
    result.set(id, { target, type: attribute(tag.attributes, 'Type') ?? '', external: attribute(tag.attributes, 'TargetMode') === 'External' })
  })
  try { parser.write(xml).close() } catch { return new Map() }
  return result
}

function readLegacyDrawingRelationshipId(xml: string): string | undefined {
  let id: string | undefined
  const parser = new SaxesParser({ xmlns: false })
  parser.on('opentag', tag => {
    if ((tag.name.split(':').at(-1) ?? tag.name) === 'legacyDrawingHF') id = attribute(tag.attributes, 'id')
  })
  try { parser.write(xml).close() } catch { return undefined }
  return id
}

function readVmlPictures(xml: string): VmlPicture[] {
  const pictures: VmlPicture[] = []
  const parser = new SaxesParser({ xmlns: false })
  let shape: { id: string; style: string; relationshipId?: string } | undefined
  parser.on('opentag', tag => {
    const local = tag.name.split(':').at(-1) ?? tag.name
    if (local === 'shape') shape = { id: attribute(tag.attributes, 'id') ?? '', style: attribute(tag.attributes, 'style') ?? '' }
    else if (local === 'imagedata' && shape) {
      const relationshipId = attribute(tag.attributes, 'relid') ?? attribute(tag.attributes, 'id')
      if (relationshipId) shape.relationshipId = relationshipId
    }
  })
  parser.on('closetag', tag => {
    if ((tag.name.split(':').at(-1) ?? tag.name) !== 'shape' || !shape) return
    if (shape.relationshipId) pictures.push({ id: shape.id, style: shape.style, relationshipId: shape.relationshipId })
    shape = undefined
  })
  try { parser.write(xml).close() } catch { return [] }
  return pictures
}

function slot(id: string): string | undefined {
  const upper = id.trim().toUpperCase()
  return /^[LCR][HF](?:EVEN|FIRST)?$/.test(upper) ? upper : undefined
}

function sizeInPoints(style: string): { widthPt: number; heightPt: number } | undefined {
  const values = new Map<string, number>()
  for (const declaration of style.split(';')) {
    const [rawName, rawValue] = declaration.split(':', 2)
    if (!rawName || !rawValue) continue
    const name = rawName.trim().toLowerCase()
    if (name !== 'width' && name !== 'height') continue
    const match = /^([+]?(?:\d+(?:\.\d*)?|\.\d+))\s*(pt|in|cm|mm|px|pc)?$/i.exec(rawValue.trim())
    if (!match) continue
    const number = Number(match[1]), unit = (match[2] ?? 'pt').toLowerCase()
    const factor = unit === 'in' ? 72 : unit === 'cm' ? 72 / 2.54 : unit === 'mm' ? 72 / 25.4 : unit === 'px' ? 0.75 : unit === 'pc' ? 12 : 1
    const points = number * factor
    if (Number.isFinite(points) && points > 0 && points <= 2000) values.set(name, points)
  }
  const widthPt = values.get('width'), heightPt = values.get('height')
  return widthPt === undefined || heightPt === undefined ? undefined : { widthPt, heightPt }
}

function imageType(path: string): string | undefined {
  const extension = path.split('/').at(-1)?.split('.').at(-1)?.split(';')[0]?.toLowerCase()
  return ({ png: 'image/png', jpg: 'image/jpeg', jpeg: 'image/jpeg', gif: 'image/gif', bmp: 'image/bmp', webp: 'image/webp', svg: 'image/svg+xml' } as Record<string, string>)[extension ?? '']
}

function relationshipsPath(partPath: string): string {
  const index = partPath.lastIndexOf('/')
  return `${partPath.slice(0, index)}/_rels/${partPath.slice(index + 1)}.rels`
}

/** Reads existing &G images from worksheet VML without probing external targets. */
export async function readWorkbookHeaderFooterPictures(bytes: Uint8Array): Promise<Map<string, Map<string, HeaderFooterPicture>>> {
  const zip = await JSZip.loadAsync(bytes, { checkCRC32: true })
  const workbook = await readWorkbook(bytes)
  const result = new Map<string, Map<string, HeaderFooterPicture>>()
  for (const [sheetIndex, sheet] of workbook.sheets.entries()) {
    const worksheetXml = await zip.file(sheet.path)?.async('text')
    if (!worksheetXml) continue
    const drawingId = readLegacyDrawingRelationshipId(worksheetXml)
    if (!drawingId) continue
    const vml = readRelationships(await zip.file(relationshipsPath(sheet.path))?.async('text')).get(drawingId)
    if (!vml || vml.external || !vml.type.endsWith('/vmlDrawing')) continue
    let vmlPath: string
    try { vmlPath = resolvePivotTarget(sheet.path, vml.target) } catch { continue }
    const vmlXml = await zip.file(vmlPath)?.async('text')
    if (!vmlXml) continue
    const mediaRelationships = readRelationships(await zip.file(relationshipsPath(vmlPath))?.async('text'))
    const pictures = new Map<string, HeaderFooterPicture>()
    for (const drawing of readVmlPictures(vmlXml)) {
      const position = slot(drawing.id)
      if (!position || pictures.has(position)) continue
      const relationship = mediaRelationships.get(drawing.relationshipId)
      if (!relationship || relationship.external || !relationship.type.endsWith('/image')) continue
      let mediaPath: string
      try { mediaPath = resolvePivotTarget(vmlPath, relationship.target) } catch { continue }
      const mediaType = imageType(mediaPath), size = sizeInPoints(drawing.style), entry = zip.file(mediaPath)
      if (!mediaType || !size || !entry) continue
      const imageBytes = await entry.async('uint8array')
      if (!imageBytes.length || imageBytes.length > MAX_PICTURE_BYTES) continue
      pictures.set(position, { position, ...size, mediaType, bytes: imageBytes })
      if (pictures.size >= MAX_PICTURES_PER_SHEET) break
    }
    if (pictures.size) result.set(sheet.name, pictures)
  }
  return result
}
