/**
 * 固定源 Picture Format ▸ Transparency（setPictureOpacity）：整图不透明度写为 <a:blip> 的 alphaModFix。
 * 只接受单一嵌入位图的普通图片；按媒体身份（sha256 + 字节数）绑定来源，整批先验后写。
 */
import { createHash } from 'node:crypto'
import { setPictureOpacity, type OpenedPptx } from '@genoffice/pptx-engine'
import { resolveTarget } from '../packages/pptx-engine/src/zip.ts'

export type PictureOpacity = { slideIndex: number; elementId: string; expectedSha256: string; expectedSize: number; opacity: number }
type Target = { slideIndex: number; elementId: string }
type Conflicts = { deletedSlides?: readonly number[]; deletions?: readonly Target[]; pictureReplacements?: readonly Target[] }
const reason = '仅支持单一嵌入位图的普通图片调整透明度'

export function inspectPictureOpacity(opened: OpenedPptx, slideIndex: number, elementId: string): { pictureOpacityEditable: boolean; pictureOpacityReason: string | null; pictureOpacity: number } {
  const slide = opened.deck.slides[slideIndex], element = slide?.elements.find(item => item.id === elementId)
  if (!slide || element?.type !== 'picture') return { pictureOpacityEditable: false, pictureOpacityReason: reason, pictureOpacity: 1 }
  const current = typeof element.opacity === 'number' ? Math.round(element.opacity * 100) / 100 : 1
  const unavailable = { pictureOpacityEditable: false, pictureOpacityReason: reason, pictureOpacity: current }
  const xml = element.anchor.originalXml
  if (element.placeholder || element.media || element.model3d || /<(?:\w+:)?(?:AlternateContent|oleObj)\b|\br:link=/.test(xml)) return unavailable
  const embeds = [...xml.matchAll(/<a:blip\b[^>]*\br:embed="([^"]+)"/g)]
  if (embeds.length !== 1 || (xml.match(/<a:blip\b/g) ?? []).length !== 1) return unavailable
  const rel = opened.archive.readRels(slide.path).get(embeds[0]![1]!)
  if (!rel || !rel.type.endsWith('/image') || rel.targetMode === 'External' || resolveTarget(slide.path, rel.target) !== element.mediaRef || !opened.archive.readBytes(element.mediaRef)) return unavailable
  return { pictureOpacityEditable: true, pictureOpacityReason: null, pictureOpacity: current }
}

export function validatePictureOpacities(opened: OpenedPptx, input: unknown, conflicts: Conflicts = {}): PictureOpacity[] {
  if (input === undefined) return []
  if (!Array.isArray(input) || input.length > 50) throw Error('picture_opacity_request_invalid')
  const seen = new Set<string>()
  for (const item of input) {
    if (!item || typeof item !== 'object' || Object.keys(item).sort().join() !== 'elementId,expectedSha256,expectedSize,opacity,slideIndex' || !Number.isInteger(item.slideIndex) || item.slideIndex < 0 || item.slideIndex >= opened.deck.slides.length
      || typeof item.elementId !== 'string' || typeof item.opacity !== 'number' || !Number.isFinite(item.opacity) || item.opacity < 0 || item.opacity > 1 || Math.abs(Math.round(item.opacity * 100) - item.opacity * 100) > 1e-9) throw Error('picture_opacity_invalid')
    const key = `${item.slideIndex}:${item.elementId}`
    if (seen.has(key) || conflicts.deletedSlides?.includes(item.slideIndex) || [...(conflicts.deletions ?? []), ...(conflicts.pictureReplacements ?? [])].some(target => target.slideIndex === item.slideIndex && target.elementId === item.elementId)) throw Error('picture_opacity_target_conflict')
    seen.add(key)
    if (!inspectPictureOpacity(opened, item.slideIndex, item.elementId).pictureOpacityEditable) throw Error('picture_opacity_source_unsupported')
    const element = opened.deck.slides[item.slideIndex]!.elements.find(candidate => candidate.id === item.elementId)!
    const bytes = opened.archive.readBytes((element as { mediaRef: string }).mediaRef)!
    if (typeof item.expectedSha256 !== 'string' || !/^[a-f0-9]{64}$/.test(item.expectedSha256) || !Number.isSafeInteger(item.expectedSize) || item.expectedSize !== bytes.length || createHash('sha256').update(bytes).digest('hex') !== item.expectedSha256) throw Error('picture_opacity_identity_changed')
  }
  return input as PictureOpacity[]
}

/** 必须在同批其他图片修改之前调用：引擎把结果直接写入元素原始 XML，之后的裁切/移动在此基础上继续标脏。 */
export function applyPictureOpacities(opened: OpenedPptx, items: PictureOpacity[]): void {
  validatePictureOpacities(opened, items)
  for (const item of items) {
    if (!setPictureOpacity(opened.deck.slides[item.slideIndex]!, item.elementId, item.opacity)) throw Error('picture_opacity_apply_failed')
  }
}
