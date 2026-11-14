import {readModelSources} from './pptx-model3d.ts'
import { readSlideMedia } from './pptx-media.ts'
import { readFile } from 'node:fs/promises'
import { createHash } from 'node:crypto'
import { openPptx, listMasterParts, parseMasterPart } from '@genoffice/pptx-engine'
import { buildRenderSlide } from '@genoffice/pptx-render'

const request = JSON.parse(await readFile(process.argv[2]!, 'utf8')) as { input: string }
const opened = await openPptx(new Uint8Array(await readFile(request.input)))
const mime: Record<string, string> = { png: 'image/png', jpg: 'image/jpeg', jpeg: 'image/jpeg', gif: 'image/gif', svg: 'image/svg+xml', webp: 'image/webp' }
const media = (ref: string) => {
  const bytes = opened.archive.entries.get(ref)
  const type = mime[ref.split('.').pop()?.toLowerCase() ?? '']
  return bytes && type ? 'data:' + type + ';base64,' + Buffer.from(bytes).toString('base64') : undefined
}
process.stdout.write(JSON.stringify({
  masterTextParts: listMasterParts(opened.archive).flatMap(part => {
    try { const slide = parseMasterPart(opened.archive, part.partPath); return slide ? [{ partPath: part.partPath, slide: buildRenderSlide(slide, opened.deck.size, { fitWidthPx: opened.deck.size.cx / 9525, media }) }] : [] } catch { return [] }
  }),
  slides: opened.deck.slides.map((slide, index) => ({
    slideIndex: index,
    slideIdentity: createHash('sha256').update(slide.path).update('\0').update(slide.originalXml).digest('hex'),
    mediaSources: readSlideMedia(opened, index),
    modelSources: readModelSources(opened,index),
    ...buildRenderSlide(slide, opened.deck.size, { fitWidthPx: opened.deck.size.cx / 9525, media, slideNo: index + 1 }),
  })),
}))
