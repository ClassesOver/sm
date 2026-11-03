// GenOffice Apache-2.0 integration: preserve the original picture frame and effects.
import { createHash } from 'node:crypto'
import { readFile, writeFile } from 'node:fs/promises'
import { elementSpid, openPptx, replacePictureBytes, savePptx } from '@genoffice/pptx-engine'

type Replacement = {
  slideIndex: number; elementId: string; slidePath?: string; shapeId?: number
  expectedSha256: string; expectedSize: number; bytesBase64: string; extension: 'png' | 'jpg'
}
type Input = { action: 'inspect' | 'replace'; input: string; output?: string; replacements?: Replacement[] }
const request = JSON.parse(await readFile(process.argv[2]!, 'utf8')) as Input
const opened = await openPptx(new Uint8Array(await readFile(request.input)))
const digest = (bytes: Uint8Array) => createHash('sha256').update(bytes).digest('hex')
const pictures = opened.deck.slides.flatMap((slide, slideIndex) => slide.elements.flatMap((element) => {
  if (element.type !== 'picture' || !element.mediaRef) return []
  const content = opened.archive.readBytes(element.mediaRef)
  if (!content) return []
  return [{ slideIndex, slidePath: slide.path, elementId: element.id, shapeId: elementSpid(element),
    size: content.length, sha256: digest(content), name: element.name ?? '' }]
}))
if (request.action === 'inspect') {
  process.stdout.write(JSON.stringify({ pictures }))
} else {
  if (request.action !== 'replace' || !request.output || !Array.isArray(request.replacements) || request.replacements.length > 50) {
    throw new Error('picture_request_invalid')
  }
  const used = new Set<string>()
  // Validate the entire batch before changing the archive.
  const targets = request.replacements.map((item) => {
    const slide = item.slidePath
      ? opened.deck.slides.find((candidate) => candidate.path === item.slidePath)
      : opened.deck.slides[item.slideIndex]
    const element = slide?.elements.find((candidate) => item.shapeId !== undefined
      ? elementSpid(candidate) === item.shapeId : candidate.id === item.elementId)
    if (!slide || !element || element.type !== 'picture' || !element.mediaRef) throw new Error('picture_target_invalid')
    const key = `${slide.path}:${element.id}`
    if (used.has(key)) throw new Error('picture_target_duplicate')
    used.add(key)
    const original = opened.archive.readBytes(element.mediaRef)
    if (!original || original.length !== item.expectedSize || digest(original) !== item.expectedSha256) {
      throw new Error('picture_identity_changed')
    }
    const content = Buffer.from(item.bytesBase64, 'base64')
    const validImage = item.extension === 'png'
      ? content.subarray(0, 8).equals(Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]))
      : item.extension === 'jpg' && content.subarray(0, 3).equals(Buffer.from([255, 216, 255]))
    if (!content.length || content.length > 12 * 1024 * 1024 || content.toString('base64') !== item.bytesBase64 || !validImage) {
      throw new Error('picture_asset_invalid')
    }
    return { slide, element, content, extension: item.extension }
  })
  for (const { slide, element, content, extension } of targets) {
    if (!replacePictureBytes(opened, slide, element.id, new Uint8Array(content), extension)) throw new Error('picture_replace_failed')
  }
  await writeFile(request.output, await savePptx(opened))
  process.stdout.write(JSON.stringify({ replaced: targets.length }))
}
