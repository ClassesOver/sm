/**
 * 固定源 FormatBackgroundPane 的图片填充（stretch / tile）与“应用到全部”：
 * 由 pptx-ops 规范操作 setBackground(kind: image) 写入（含全幅底板改为透明）；同一张图片应用到多页时只落一个媒体部件，其余页复用。
 */
import { slideDurableId, type OpenedPptx } from '@genoffice/pptx-engine'
import '../packages/pptx-ops/src/ops/slide-ops.ts'
import { lookup, type OpContext } from '../packages/pptx-ops/src/ops/registry.ts'
import { assetBytes, type PictureAsset } from './pptx-images.ts'
import { createHash } from 'node:crypto'

export type BackgroundImage = PictureAsset & { slideIndices: number[]; tile: boolean }

export function inspectBackgroundImage(opened: OpenedPptx, slideIndex: number) {
  const background = opened.deck.slides[slideIndex]?.background
  const bytes = background?.type === 'image' ? opened.archive.readBytes(background.mediaRef) : undefined
  return { backgroundImage: background?.type === 'image' ? { mode: background.mode === 'tile' ? 'tile' as const : 'stretch' as const } : null,
    backgroundImageSource: bytes?.length ? { sha256: createHash('sha256').update(bytes).digest('hex'), size: bytes.length } : null }
}

export type BackgroundImageReuse = { sourceSlideIndex: number; expectedSha256: string; expectedSize: number; slideIndices: number[]; tile: boolean }
type BoundReuse = BackgroundImageReuse & { mediaPath: string }
/** 客户端只能提交来源页与字节身份；媒体路径始终从本次实际 PPTX 解析。 */
export function validateBackgroundImageReuses(opened: OpenedPptx, input: unknown, conflicts: { removedSlides?: ReadonlySet<number>; fillSlides?: ReadonlySet<number> } = {}): BoundReuse[] {
  if (input === undefined) return []
  if (!Array.isArray(input) || input.length > 50) throw Error('background_reuse_request_invalid')
  const used = new Set(conflicts.fillSlides ?? []), count = opened.deck.slides.length
  const valid = (index: unknown): index is number => Number.isInteger(index) && (index as number) >= 0 && (index as number) < count && !conflicts.removedSlides?.has(index as number)
  return input.map(item => {
    if (!item || typeof item !== 'object' || Object.keys(item).sort().join() !== 'expectedSha256,expectedSize,slideIndices,sourceSlideIndex,tile'
      || !valid(item.sourceSlideIndex) || typeof item.tile !== 'boolean' || !Array.isArray(item.slideIndices) || !item.slideIndices.length
      || typeof item.expectedSha256 !== 'string' || !/^[a-f0-9]{64}$/.test(item.expectedSha256) || !Number.isSafeInteger(item.expectedSize) || item.expectedSize <= 0) throw Error('background_reuse_invalid')
    const background = opened.deck.slides[item.sourceSlideIndex]!.background, identity = inspectBackgroundImage(opened, item.sourceSlideIndex).backgroundImageSource
    if (background?.type !== 'image' || identity?.sha256 !== item.expectedSha256 || identity?.size !== item.expectedSize) throw Error('background_reuse_source_changed')
    for (const index of item.slideIndices) { if (!valid(index) || used.has(index)) throw Error('background_reuse_target_conflict'); used.add(index) }
    return { ...item, mediaPath: background.mediaRef }
  })
}

export function applyBackgroundImageReuses(opened: OpenedPptx, slides: readonly OpenedPptx['deck']['slides'][number][], items: BoundReuse[]) {
  const def = lookup('setBackground'), ctx: OpContext = { opened, parts: new Map(), touchedParts: new Set() }
  for (const item of items) for (const index of item.slideIndices) {
    const op = { op: 'setBackground', target: { slide: slideDurableId(slides[index]!) }, kind: 'image', source: { mediaPath: item.mediaPath }, tile: item.tile }
    def.validate(op as never, ctx); def.apply(op as never, ctx)
  }
}

export function validateBackgroundImages(opened: OpenedPptx, input: unknown, conflicts: { removedSlides?: ReadonlySet<number>; colorSlides?: ReadonlySet<number> } = {}): BackgroundImage[] {
  if (input === undefined) return []
  if (!Array.isArray(input) || input.length > 10) throw Error('background_image_request_invalid')
  const used = new Set<number>()
  let total = 0
  for (const item of input) {
    if (!item || typeof item !== 'object' || Object.keys(item).sort().join() !== 'bytesBase64,extension,slideIndices,tile' || typeof item.tile !== 'boolean'
      || !Array.isArray(item.slideIndices) || !item.slideIndices.length || item.slideIndices.length > opened.deck.slides.length) throw Error('background_image_invalid')
    for (const index of item.slideIndices) {
      if (!Number.isInteger(index) || index < 0 || index >= opened.deck.slides.length || used.has(index)) throw Error('background_image_target_invalid')
      if (conflicts.removedSlides?.has(index) || conflicts.colorSlides?.has(index)) throw Error('background_image_target_conflict')
      used.add(index)
    }
    total += assetBytes(item).length
    if (total > 8 * 1024 * 1024) throw Error('picture_budget_exceeded')
  }
  return input as BackgroundImage[]
}

export function applyBackgroundImages(opened: OpenedPptx, slides: readonly OpenedPptx['deck']['slides'][number][], items: BackgroundImage[]): void {
  const def = lookup('setBackground')
  const ctx: OpContext = { opened, parts: new Map(), touchedParts: new Set() }
  for (const item of items) {
    const bytes = assetBytes(item)
    let mediaPath: string | null = null
    for (const index of item.slideIndices) {
      const op = { op: 'setBackground', target: { slide: slideDurableId(slides[index]!) }, kind: 'image', source: mediaPath ? { mediaPath } : { bytes, ext: item.extension }, tile: item.tile }
      def.validate(op as never, ctx)
      mediaPath = (def.apply(op as never, ctx).after as { mediaPath?: string } | undefined)?.mediaPath ?? null
      if (!mediaPath) throw Error('background_image_apply_failed')
    }
  }
}
