import Konva from 'konva'

export type MarqueePoint = { x: number; y: number }
export type MarqueeBounds = MarqueePoint & { width: number; height: number }

/** 起终点均为画布坐标，反向拖动也生成正宽高矩形。 */
export function slidesMarqueeRect(start: MarqueePoint, end: MarqueePoint): MarqueeBounds {
  return { x: Math.min(start.x, end.x), y: Math.min(start.y, end.y), width: Math.abs(end.x - start.x), height: Math.abs(end.y - start.y) }
}

/** 阈值使用屏幕像素；相交判断沿用 Konva，旋转包围框由调用方提供。 */
export function slidesMarqueeIds(start: MarqueePoint, end: MarqueePoint, scale: number, candidates: { id: string; bounds: MarqueeBounds }[]): string[] | null {
  if (Math.hypot(end.x - start.x, end.y - start.y) * scale < 4) return null
  const rect = slidesMarqueeRect(start, end)
  return [...new Set(candidates.filter(item => Konva.Util.haveIntersection(rect, item.bounds)).map(item => item.id))]
}
