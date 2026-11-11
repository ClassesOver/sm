import { alignRects, distributeRects, type AlignKind } from '@genoffice/pptx-engine/align'

export type SlidesArrangeGeometry = { x: number; y: number; width: number; height: number }
export type SlidesArrangeOp = AlignKind | 'distribute-h' | 'distribute-v'
export interface SlidesArrangeSlide {
  slideIndex: number
  /** Original source coordinates, before any pending slide-size scaling. */
  widthPx: number
  heightPx: number
  elements: { id: string; type: string; arrangeEditable?: boolean; geometry?: SlidesArrangeGeometry }[]
}
export interface SlidesArrangeEdit { slideIndex: number; elementId: string; geometry?: SlidesArrangeGeometry; text?: string }
export interface SlidesArrangePlan { edits: SlidesArrangeEdit[]; count: number }

const operations = new Set(['left', 'center-h', 'right', 'top', 'center-v', 'bottom', 'distribute-h', 'distribute-v'])
function validFrame(frame: SlidesArrangeGeometry | undefined): frame is SlidesArrangeGeometry {
  return !!frame && [frame.x, frame.y, frame.width, frame.height].every(value => Number.isFinite(value) && value >= 0 && value <= 100000)
    && frame.width > 0 && frame.height > 0
}
const sameCoordinate = (left: number, right: number) => Math.round(left * 9525) === Math.round(right * 9525)

/** Pure batch plan: a caller validates and commits its entire operation once, preserving one Undo. */
export function planSlidesArrange(slide: SlidesArrangeSlide, selectedIds: string[], edits: SlidesArrangeEdit[],
  op: SlidesArrangeOp, frameOverrides?: ReadonlyMap<string, SlidesArrangeGeometry>): SlidesArrangePlan {
  if (!operations.has(op) || !selectedIds.length || selectedIds.length > 500 || new Set(selectedIds).size !== selectedIds.length)
    throw new Error('请选择当前页的有效对象；一次最多排列 500 个对象')
  const distribution = op === 'distribute-h' || op === 'distribute-v'
  if (distribution && selectedIds.length < 3) throw new Error('均匀分布至少需要选择三个对象')
  if (![slide.widthPx, slide.heightPx].every(value => Number.isFinite(value) && value > 0 && value <= 100000))
    throw new Error('来源页面尺寸无效，不能排列对象')
  const sources = selectedIds.map(id => {
    const element = slide.elements.find(candidate => candidate.id === id)
    if (!element || element.arrangeEditable !== true || !['text', 'shape', 'picture'].includes(element.type))
      throw new Error('部分选择对象不能安全排列；请重新选择来源对象')
    const pending = edits.findLast(edit => edit.slideIndex === slide.slideIndex && edit.elementId === id)
    const frame = pending?.geometry ?? frameOverrides?.get(id) ?? element.geometry
    if (!validFrame(frame)) throw new Error('部分对象的位置或大小无效，未提交排列修改')
    return { id, frame }
  })
  const rects = sources.map(({ frame }) => ({ x: frame.x, y: frame.y, w: frame.width, h: frame.height }))
  const positions = distribution
    ? distributeRects(rects, op === 'distribute-h' ? 'horizontal' : 'vertical')
    : alignRects(rects, op as AlignKind, selectedIds.length === 1 ? { x: 0, y: 0, w: slide.widthPx, h: slide.heightPx } : null)
  const result = structuredClone(edits)
  let count = 0
  sources.forEach(({ id, frame }, index) => {
    const geometry = { ...frame, ...positions[index]! }
    if (!validFrame(geometry)) throw new Error('排列结果超出支持的位置范围，未提交任何修改')
    if (sameCoordinate(geometry.x, frame.x) && sameCoordinate(geometry.y, frame.y)) return
    const existing = result.findIndex(edit => edit.slideIndex === slide.slideIndex && edit.elementId === id)
    const edit = { ...(existing >= 0 ? result[existing]! : { slideIndex: slide.slideIndex, elementId: id }), geometry }
    if (existing >= 0) result[existing] = edit
    else result.push(edit)
    count++
  })
  if (result.length > 500) throw new Error('原生编辑操作超限，请先保存当前修改')
  return { edits: result, count }
}
