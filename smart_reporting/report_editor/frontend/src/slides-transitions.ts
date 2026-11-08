/** Pinned GenOffice transition kinds; Apply to All copies effects, not timing preferences. */
export const SLIDE_TRANSITIONS = ['none', 'morph', 'fade', 'push', 'wipe', 'split', 'circle', 'cover', 'pull', 'dissolve', 'zoom', 'random'] as const
export type SlideTransition = typeof SLIDE_TRANSITIONS[number]
export type TransitionEdit = { slideIndex: number; kind: SlideTransition }
export function restoredTransitions(value: unknown, slideCount: number): TransitionEdit[] {
  if (value === undefined) return []
  if (!Array.isArray(value) || value.length > 500) throw new Error('转场草稿数量无效；原草稿已保留')
  return value.map(item => {
    if (!item || typeof item !== 'object' || Array.isArray(item) || Object.keys(item).some(key => !['slideIndex', 'kind'].includes(key))
      || !Number.isInteger(item.slideIndex) || item.slideIndex < 0 || item.slideIndex >= slideCount
      || !SLIDE_TRANSITIONS.includes(item.kind)) throw new Error('转场草稿的来源页或效果无效；原草稿已保留')
    return { slideIndex: item.slideIndex, kind: item.kind }
  })
}
export function applyTransitionToAll(order: number[], kind: SlideTransition, changes: Map<number, SlideTransition>): boolean {
  if (!order.length || order.length > 500 || new Set(order).size !== order.length || order.some(index => !Number.isInteger(index) || index < 0) || !SLIDE_TRANSITIONS.includes(kind)) throw new Error('无法将当前转场应用到这些页面')
  if (changes.size === order.length && order.every(index => changes.get(index) === kind)) return false
  changes.clear()
  for (const index of order) changes.set(index, kind)
  return true
}
