import { expect, it } from 'vitest'
import { previewAnimationItems } from './slides-animation-preview-model'
import { initialSequence } from './slides-animation-sequence'

const source = [
  { spid: 2, elementId: 'title', effect: 'wipe', trigger: 'onClick', durationMs: 500, delayMs: 20, direction: 'top', paragraph: 1 },
  { spid: 3, elementId: 'box', effect: 'motionPath', trigger: 'afterPrev', durationMs: 800, delayMs: 0, motionPath: 'M 0 0 L 0.25 0' },
]
it('来源和草稿整页序列保持顺序/对象身份/方向/段落/路径，来源引用的计时覆盖生效', () => {
  const items = [{ ...initialSequence(source)[0]!, durationMs: 900 }, { elementId: 'title', effect: 'fadeOut' as const, trigger: 'withPrev' as const, durationMs: 200, delayMs: 15 }, initialSequence(source)[1]!]
  const before = JSON.stringify({ source, items })
  expect(previewAnimationItems(items, source, ['title', 'box'])).toEqual({ items: [
    { sourceId: 'title', targetName: 'title', effect: 'wipe', trigger: 'onClick', durationMs: 900, delayMs: 20, direction: 'top', paragraph: 1 },
    { sourceId: 'title', targetName: 'title', effect: 'fadeOut', trigger: 'withPrev', durationMs: 200, delayMs: 15 },
    { sourceId: 'box', targetName: 'box', effect: 'motionPath', trigger: 'afterPrev', durationMs: 800, delayMs: 0, motionPath: 'M 0 0 L 0.25 0' },
  ], warnings: [] })
  expect(JSON.stringify({ source, items })).toBe(before)
})

it('缺失对象、未建模原始预设和媒体明确跳过，不把静态画面宣称动画完成', () => {
  const unsupported = [
    source[0]!, { ...source[1]!, presetXml: '<p:par/>' },
    { elementId: 'audio', spid: 4, effect: 'mediaPlay', trigger: 'onClick' },
  ]
  const result = previewAnimationItems(initialSequence(unsupported), unsupported, ['box', 'audio'])
  expect(result.items).toEqual([])
  expect(result.warnings).toHaveLength(3)
  expect(result.warnings.join('；')).toContain('未建模')
  expect(result.warnings.join('；')).toContain('音视频')
  expect(result.warnings.join('；')).toContain('对象')
})
