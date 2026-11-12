/**
 * 固定源 FormatBackgroundPane 的渐变填充、重置背景、隐藏背景图形：
 * 直接调用 pptx-ops 的规范操作 `setBackground`（含全幅底板随背景重绘），不另写 OOXML。
 * 页按来源页序号寻址，执行时转换为稳定的 slide durable id，不受同批新增/重排影响。
 */
import { slideDurableId, type OpenedPptx } from '@genoffice/pptx-engine'
import '../packages/pptx-ops/src/ops/slide-ops.ts'
import { lookup, type OpContext } from '../packages/pptx-ops/src/ops/registry.ts'

type Slide = OpenedPptx['deck']['slides'][number]
export type BackgroundGradient = { slideIndices: number[]; from: string; to: string; angleDeg: 0 | 45 | 90; radial: boolean }
export type BackgroundGraphics = { slideIndex: number; hidden: boolean }
const hex = /^#[0-9A-Fa-f]{6}$/

export function inspectBackgroundState(opened: OpenedPptx, slideIndex: number) {
  const slide = opened.deck.slides[slideIndex]
  const background = slide?.background
  const gradient = background?.type === 'gradient' && background.stops.length === 2 ? background : undefined
  return {
    backgroundOwn: !!slide?.bgOwn,
    backgroundGraphicsHidden: !!slide?.masterSpHidden,
    backgroundGradient: gradient ? { from: `#${gradient.stops[0]!.color.replace(/^#/, '').slice(0, 6).toUpperCase()}`, to: `#${gradient.stops[1]!.color.replace(/^#/, '').slice(0, 6).toUpperCase()}`,
      radial: gradient.path === 'circle', angleDeg: gradient.path === 'circle' ? 0 : Math.round((gradient.angle ?? 0) / 60000) } : null,
  }
}

export function validateBackgroundOps(opened: OpenedPptx, request: { backgroundGradients?: unknown; backgroundResets?: unknown; backgroundGraphics?: unknown },
  conflicts: { removedSlides?: ReadonlySet<number>; fillSlides?: ReadonlySet<number> } = {}) {
  const count = opened.deck.slides.length
  const valid = (index: unknown): index is number => Number.isInteger(index) && (index as number) >= 0 && (index as number) < count && !conflicts.removedSlides?.has(index as number)
  const filled = new Set<number>(conflicts.fillSlides ?? [])
  const claim = (index: unknown) => { if (!valid(index) || filled.has(index)) throw Error('background_target_conflict'); filled.add(index) }
  const gradients = request.backgroundGradients ?? []
  if (!Array.isArray(gradients) || gradients.length > 20) throw Error('background_gradient_request_invalid')
  for (const item of gradients) {
    if (!item || typeof item !== 'object' || Object.keys(item).sort().join() !== 'angleDeg,from,radial,slideIndices,to' || typeof item.from !== 'string' || !hex.test(item.from) || typeof item.to !== 'string' || !hex.test(item.to)
      || typeof item.radial !== 'boolean' || ![0, 45, 90].includes(item.angleDeg) || (item.radial && item.angleDeg !== 0) || !Array.isArray(item.slideIndices) || !item.slideIndices.length) throw Error('background_gradient_invalid')
    for (const index of item.slideIndices) claim(index)
  }
  const resets = request.backgroundResets ?? []
  if (!Array.isArray(resets) || resets.length > count) throw Error('background_reset_request_invalid')
  for (const index of resets) {
    claim(index)
    if (!opened.deck.slides[index]!.bgOwn) throw Error('background_reset_not_own')
  }
  const graphics = request.backgroundGraphics ?? []
  if (!Array.isArray(graphics) || graphics.length > count) throw Error('background_graphics_request_invalid')
  const toggled = new Set<number>()
  for (const item of graphics) {
    if (!item || typeof item !== 'object' || Object.keys(item).sort().join() !== 'hidden,slideIndex' || typeof item.hidden !== 'boolean' || !valid(item.slideIndex) || toggled.has(item.slideIndex)) throw Error('background_graphics_invalid')
    toggled.add(item.slideIndex)
  }
  return { gradients: gradients as BackgroundGradient[], resets: resets as number[], graphics: graphics as BackgroundGraphics[] }
}

export function applyBackgroundOps(opened: OpenedPptx, slides: readonly Slide[], ops: ReturnType<typeof validateBackgroundOps>): void {
  const def = lookup('setBackground')
  const ctx: OpContext = { opened, parts: new Map(), touchedParts: new Set() }
  const run = (slideIndex: number, fields: Record<string, unknown>) => {
    const op = { op: 'setBackground', target: { slide: slideDurableId(slides[slideIndex]!) }, ...fields }
    def.validate(op as never, ctx)
    def.apply(op as never, ctx)
  }
  for (const item of ops.gradients) for (const index of item.slideIndices) run(index, { kind: 'gradient', from: item.from.toUpperCase(), to: item.to.toUpperCase(), angleDeg: item.angleDeg, ...(item.radial ? { radial: true } : {}) })
  for (const index of ops.resets) run(index, { kind: 'reset' })
  for (const item of ops.graphics) run(item.slideIndex, { kind: 'graphics', hidden: item.hidden })
}
