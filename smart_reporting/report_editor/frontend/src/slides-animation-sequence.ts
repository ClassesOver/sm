/**
 * 固定源 animation-actions.ts：整页动画列表覆盖写（commitAnimations）。
 * 动画窗格的移动/删除/计时、“无”、动作路径与“按段”都落到同一份整页序列；
 * `source` 条目引用来源文件中已有的动画（原样保留，含无法建模的预设 XML），其余为新增。
 */
export type SequenceEffect = 'appear' | 'fade' | 'flyIn' | 'wipe' | 'wipeDown' | 'splitIn' | 'bounce' | 'flipIn' | 'zoom' | 'pulse' | 'spin' | 'grow' | 'teeter' | 'disappear' | 'fadeOut' | 'flyOut' | 'wipeOut' | 'shrink' | 'zoomOut' | 'motionPath'
export type SequenceTrigger = 'onClick' | 'withPrev' | 'afterPrev'
export type SequenceDirection = 'top' | 'bottom' | 'left' | 'right'
export interface SourceAnimation { spid?: number; elementId: string; effect: string; trigger: string; durationMs?: number; delayMs?: number; direction?: string; motionPath?: string; paragraph?: number; presetXml?: string }
export interface SequenceSourceItem { source: number; spid: number; effect: string; trigger?: SequenceTrigger; durationMs?: number; delayMs?: number }
export interface SequenceNewItem { elementId: string; effect: SequenceEffect; trigger: SequenceTrigger; durationMs: number; delayMs: number; direction?: SequenceDirection; motionPath?: string; paragraph?: number }
export type SequenceItem = SequenceSourceItem | SequenceNewItem
export interface LegacyAnimationEdit { elementId: string; effect: SequenceEffect; trigger: SequenceTrigger; durationMs: number; delayMs: number; direction?: SequenceDirection; append?: true }

/** 固定源 Ribbon.tsx MOTION_PATHS：坐标相对幻灯片宽高。 */
export const MOTION_PATHS: Record<string, string> = {
  motionPathRight: 'M 0 0 L 0.25 0',
  motionPathDown: 'M 0 0 L 0 0.25',
  motionPathDiagonal: 'M 0 0 L 0.25 0.25',
  motionPathCircle: 'M 0 0 C 0.069 0 0.125 0.056 0.125 0.125 C 0.125 0.194 0.069 0.25 0 0.25 C -0.069 0.25 -0.125 0.194 -0.125 0.125 C -0.125 0.056 -0.069 0 0 0 Z',
  motionPathZigzag: 'M 0 0 L 0.12 -0.12 L 0.24 0.12 L 0.36 0',
}
export const SEQUENCE_EFFECTS: readonly SequenceEffect[] = ['appear', 'fade', 'flyIn', 'wipe', 'wipeDown', 'splitIn', 'bounce', 'flipIn', 'zoom', 'pulse', 'spin', 'grow', 'teeter', 'disappear', 'fadeOut', 'flyOut', 'wipeOut', 'shrink', 'zoomOut', 'motionPath']
const TRIGGERS: readonly string[] = ['onClick', 'withPrev', 'afterPrev']
const DIRECTIONAL: readonly string[] = ['flyIn', 'flyOut', 'wipe', 'wipeOut']
export const EFFECT_LABELS: Record<string, string> = {
  appear: '出现', fade: '淡入', flyIn: '飞入', wipe: '擦除', wipeDown: '向下擦除', splitIn: '劈裂', bounce: '弹跳', flipIn: '翻转', zoom: '缩放',
  pulse: '脉冲', spin: '陀螺旋', grow: '放大/缩小', teeter: '跷跷板', disappear: '消失', fadeOut: '淡出', flyOut: '飞出', wipeOut: '擦除退出', shrink: '收缩', zoomOut: '缩放退出',
  motionPath: '动作路径', mediaPlay: '播放媒体', mediaPause: '暂停媒体', mediaStop: '停止媒体',
}
export const TRIGGER_LABELS: Record<string, string> = { onClick: '单击时', withPrev: '与上一动画同时', afterPrev: '上一动画之后' }

/** 固定源 animDefaultDur。 */
export function defaultAnimationDuration(effect: string): number {
  return effect === 'appear' || effect === 'disappear' ? 0 : ['spin', 'grow', 'bounce', 'motionPath'].includes(effect) ? 2000 : effect === 'pulse' || effect === 'teeter' ? 1000 : 500
}

export const isSourceItem = (item: SequenceItem): item is SequenceSourceItem => 'source' in item

/** 首次整页编辑：来源动画逐条引用，再折叠本页尚未保存的旧式逐条修改（与桥接 animations 语义一致）。 */
export function initialSequence(source: SourceAnimation[], legacy: LegacyAnimationEdit[] = []): SequenceItem[] {
  const items: SequenceItem[] = source.map((animation, index) => ({ source: index, spid: Number(animation.spid), effect: animation.effect }))
  for (const edit of legacy) {
    const { append, ...rest } = edit
    const index = append ? -1 : items.findIndex(item => isSourceItem(item)
      ? source[item.source]!.elementId === edit.elementId && item.effect === edit.effect
      : item.elementId === edit.elementId && item.effect === edit.effect)
    const existing = index >= 0 ? items[index]! : undefined
    if (existing && isSourceItem(existing) && !source[existing.source]!.presetXml) items[index] = { ...existing, trigger: edit.trigger, durationMs: edit.durationMs, delayMs: edit.delayMs }
    else if (existing && !isSourceItem(existing)) items[index] = rest
    else items.push(rest)
  }
  return items
}

export function itemElementId(item: SequenceItem, source: SourceAnimation[]): string {
  return isSourceItem(item) ? source[item.source]?.elementId ?? '' : item.elementId
}

/** 窗格行的显示值：来源值叠加计时修改。 */
export function resolvedItem(item: SequenceItem, source: SourceAnimation[]) {
  const base = isSourceItem(item) ? source[item.source] : undefined
  return {
    elementId: itemElementId(item, source),
    effect: item.effect,
    trigger: (item.trigger ?? base?.trigger ?? 'onClick') as SequenceTrigger,
    durationMs: item.durationMs ?? base?.durationMs ?? 500,
    delayMs: item.delayMs ?? base?.delayMs ?? 0,
    paragraph: isSourceItem(item) ? base?.paragraph : item.paragraph,
    motionPath: isSourceItem(item) ? base?.motionPath : item.motionPath,
    /** 原样保留的预设：只能移动或删除，计时写在原始 XML 内。 */
    readonlyTiming: !!base?.presetXml,
    existing: isSourceItem(item),
  }
}

/** 固定源窗格步骤编号：单击触发递增，同时/之后沿用上一编号（0 = 自动播放）。 */
export function stepNumbers(items: SequenceItem[], source: SourceAnimation[]): number[] {
  let step = 0
  return items.map(item => { if (resolvedItem(item, source).trigger === 'onClick') step++; return step })
}

export function moveSequenceItem(items: SequenceItem[], index: number, direction: -1 | 1): SequenceItem[] {
  const target = index + direction
  if (index < 0 || target < 0 || index >= items.length || target >= items.length) return items
  const next = [...items]
  ;[next[index], next[target]] = [next[target]!, next[index]!]
  return next
}

export function deleteSequenceItem(items: SequenceItem[], index: number): SequenceItem[] {
  return index < 0 || index >= items.length ? items : items.filter((_, position) => position !== index)
}

/** “无”/删除对象：移除该对象的全部动画。 */
export function removeElementAnimations(items: SequenceItem[], source: SourceAnimation[], elementId: string): SequenceItem[] {
  return items.filter(item => itemElementId(item, source) !== elementId)
}

export function patchSequenceTiming(items: SequenceItem[], source: SourceAnimation[], index: number, patch: { trigger?: SequenceTrigger; durationMs?: number; delayMs?: number }): SequenceItem[] {
  const item = items[index]
  if (!item) return items
  if (resolvedItem(item, source).readonlyTiming) throw new Error('该动画为原样保留的预设效果，只能移动或删除，不能修改计时')
  if ((patch.trigger !== undefined && !TRIGGERS.includes(patch.trigger)) || [patch.durationMs, patch.delayMs].some(value => value !== undefined && (!Number.isInteger(value) || value < 0 || value > 120000))) throw new Error('动画计时无效')
  return items.map((candidate, position) => position === index ? { ...candidate, ...patch } : candidate)
}

/** 追加动画；按段时为每个段落各生成一条（固定源 paraCountOf > 1 才拆分，动作路径不拆分）。 */
export function appendAnimation(items: SequenceItem[], base: SequenceNewItem, paragraphCount = 0): SequenceItem[] {
  if (base.effect === 'motionPath' || paragraphCount <= 1) return [...items, base]
  return [...items, ...Array.from({ length: paragraphCount }, (_, paragraph) => ({ ...base, paragraph }))]
}

export function motionPathAnimation(elementId: string, control: string, trigger: SequenceTrigger = 'onClick'): SequenceNewItem {
  const motionPath = MOTION_PATHS[control]
  if (!motionPath) throw new Error('未知的动作路径')
  return { elementId, effect: 'motionPath', trigger, durationMs: defaultAnimationDuration('motionPath'), delayMs: 0, motionPath }
}

/** 草稿恢复与保存前校验：与桥接 animationSequences 的拒绝条件一致。 */
export function validateSequence(items: unknown, source: SourceAnimation[], elements: { id: string; type: string; paragraphs: number }[]): SequenceItem[] {
  if (!Array.isArray(items) || items.length > 500) throw new Error('动画序列无效')
  const used = new Set<number>()
  const timing = (value: Record<string, unknown>) => (value.trigger === undefined || TRIGGERS.includes(String(value.trigger)))
    && [value.durationMs, value.delayMs].every(entry => entry === undefined || (Number.isInteger(entry) && (entry as number) >= 0 && (entry as number) <= 120000))
  for (const raw of items) {
    if (!raw || typeof raw !== 'object') throw new Error('动画序列无效')
    const item = raw as Record<string, unknown>
    if ('source' in item) {
      const origin = source[item.source as number]
      if (Object.keys(item).some(key => !['source', 'spid', 'effect', 'trigger', 'durationMs', 'delayMs'].includes(key)) || !origin || used.has(item.source as number)
        || origin.spid !== item.spid || origin.effect !== item.effect || !timing(item)) throw new Error('动画序列引用的来源动画已变化')
      if (origin.presetXml && (item.trigger !== undefined || item.durationMs !== undefined || item.delayMs !== undefined)) throw new Error('原样保留的预设动画不能修改计时')
      used.add(item.source as number)
      continue
    }
    const element = elements.find(candidate => candidate.id === item.elementId)
    if (Object.keys(item).some(key => !['elementId', 'effect', 'trigger', 'durationMs', 'delayMs', 'direction', 'motionPath', 'paragraph'].includes(key))
      || !SEQUENCE_EFFECTS.includes(item.effect as SequenceEffect) || item.trigger === undefined || item.durationMs === undefined || item.delayMs === undefined || !timing(item)
      || (item.direction !== undefined && (!['top', 'bottom', 'left', 'right'].includes(String(item.direction)) || !DIRECTIONAL.includes(String(item.effect))))
      || ((item.effect === 'motionPath') !== (item.motionPath !== undefined)) || (item.motionPath !== undefined && !Object.values(MOTION_PATHS).includes(String(item.motionPath)))
      || !element || !['text', 'shape'].includes(element.type)
      || (item.paragraph !== undefined && (!Number.isInteger(item.paragraph) || (item.paragraph as number) < 0 || (item.paragraph as number) >= element.paragraphs || item.effect === 'motionPath'))) throw new Error('动画序列条目无效')
  }
  return items as SequenceItem[]
}

/** 序列与来源完全一致时无需写回。 */
export function sequenceUnchanged(items: SequenceItem[], source: SourceAnimation[]): boolean {
  return items.length === source.length && items.every((item, index) => isSourceItem(item) && item.source === index && item.trigger === undefined && item.durationMs === undefined && item.delayMs === undefined)
}
