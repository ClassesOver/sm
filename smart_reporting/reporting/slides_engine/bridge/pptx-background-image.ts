/**
 * 固定源 FormatBackgroundPane 的图片填充（stretch / tile）与“应用到全部”：
 * 由 pptx-ops 规范操作 setBackground(kind: image) 写入（含全幅底板改为透明）；同一张图片应用到多页时只落一个媒体部件，其余页复用。
 */
import { slideDurableId, type OpenedPptx } from '@genoffice/pptx-engine'
import '../packages/pptx-ops/src/ops/slide-ops.ts'
import { lookup, type OpContext } from '../packages/pptx-ops/src/ops/registry.ts'
import { assetBytes, type PictureAsset } from './pptx-images.ts'

export type BackgroundImage = PictureAsset & { slideIndices: number[]; tile: boolean }

export function inspectBackgroundImage(opened: OpenedPptx, slideIndex: number): { backgroundImage: { mode: 'stretch' | 'tile' } | null } {
  const background = opened.deck.slides[slideIndex]?.background
  return { backgroundImage: background?.type === 'image' ? { mode: background.mode === 'tile' ? 'tile' : 'stretch' } : null }
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
