import type { AnimationItem, AnimEffectKind } from './vendor/genoffice/animation-types'
import { isSourceItem, resolvedItem, SEQUENCE_EFFECTS, type SequenceItem, type SourceAnimation } from './slides-animation-sequence'

/** 来源对象身份与当前整页草稿序列复用同一解析；不写入动画或文件草稿。 */
export function previewAnimationItems(sequence: SequenceItem[], source: SourceAnimation[], elementIds: string[], allowMedia = false) {
  const items: AnimationItem[] = [], warnings: string[] = []
  for (const item of sequence) {
    const resolved = resolvedItem(item, source), original = isSourceItem(item) ? source[item.source] : item
    if (resolved.effect.startsWith('media') && !allowMedia) { warnings.push('编辑动画预览跳过音视频动作；请在放映中核验媒体播放。'); continue }
    if ((isSourceItem(item) && source[item.source]?.presetXml) || !SEQUENCE_EFFECTS.some(effect => effect === resolved.effect)) { warnings.push('未建模的来源预设保留在文件中，本次不模拟其效果。'); continue }
    if (!elementIds.includes(resolved.elementId)) { warnings.push('动画对象不在当前渲染快照中，本次跳过该效果。'); continue }
    const { elementId, effect, trigger, durationMs, delayMs, paragraph, motionPath } = resolved
    const direction = original?.direction
    items.push({ sourceId: elementId, targetName: elementId, effect: effect as AnimEffectKind, trigger, durationMs, delayMs,
      ...(paragraph !== undefined ? { paragraph } : {}), ...(motionPath ? { motionPath } : {}),
      ...(direction && ['top', 'bottom', 'left', 'right'].includes(direction) ? { direction: direction as AnimationItem['direction'] } : {}) })
  }
  return { items, warnings: [...new Set(warnings)] }
}
