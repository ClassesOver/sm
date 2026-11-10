import { describe, expect, it } from 'vitest'
import { MOTION_PATHS, appendAnimation, defaultAnimationDuration, deleteSequenceItem, initialSequence, motionPathAnimation, moveSequenceItem, patchSequenceTiming, removeElementAnimations, resolvedItem, sequenceUnchanged, stepNumbers, validateSequence, type SourceAnimation } from './slides-animation-sequence'

const source: SourceAnimation[] = [
  { spid: 4, elementId: 'body', effect: 'fade', trigger: 'onClick', durationMs: 500, delayMs: 0 },
  { spid: 5, elementId: 'title', effect: 'zoom', trigger: 'withPrev', durationMs: 600, delayMs: 100 },
  { spid: 5, elementId: 'title', effect: 'fade', trigger: 'afterPrev', durationMs: 700, delayMs: 0, presetXml: '<p:par/>' },
]
const elements = [{ id: 'body', type: 'text', paragraphs: 3 }, { id: 'title', type: 'shape', paragraphs: 1 }, { id: 'pic', type: 'picture', paragraphs: 0 }]

describe('PPTX animation sequence (pinned animation-actions.ts)', () => {
  it('derives the page list from source animations and folds legacy per-item edits like the bridge', () => {
    const base = initialSequence(source)
    expect(base).toEqual([{ source: 0, spid: 4, effect: 'fade' }, { source: 1, spid: 5, effect: 'zoom' }, { source: 2, spid: 5, effect: 'fade' }])
    expect(sequenceUnchanged(base, source)).toBe(true)
    const folded = initialSequence(source, [
      { elementId: 'body', effect: 'fade', trigger: 'afterPrev', durationMs: 900, delayMs: 50 },
      { elementId: 'body', effect: 'pulse', trigger: 'onClick', durationMs: 1000, delayMs: 0, append: true },
    ])
    expect(folded[0]).toEqual({ source: 0, spid: 4, effect: 'fade', trigger: 'afterPrev', durationMs: 900, delayMs: 50 })
    expect(folded[3]).toEqual({ elementId: 'body', effect: 'pulse', trigger: 'onClick', durationMs: 1000, delayMs: 0 })
    expect(sequenceUnchanged(folded, source)).toBe(false)
  })

  it('moves, deletes, retimes, removes by element and numbers click steps', () => {
    let items = initialSequence(source)
    items = moveSequenceItem(items, 1, -1)
    expect(items.map(item => 'source' in item && item.source)).toEqual([1, 0, 2])
    expect(moveSequenceItem(items, 0, -1)).toBe(items)
    expect(stepNumbers(items, source)).toEqual([0, 1, 1])
    items = patchSequenceTiming(items, source, 0, { trigger: 'onClick', durationMs: 1200 })
    expect(resolvedItem(items[0]!, source)).toMatchObject({ elementId: 'title', trigger: 'onClick', durationMs: 1200, delayMs: 100, readonlyTiming: false, existing: true })
    expect(stepNumbers(items, source)).toEqual([1, 2, 2])
    expect(() => patchSequenceTiming(items, source, 2, { delayMs: 10 })).toThrow('原样保留')
    expect(() => patchSequenceTiming(items, source, 0, { durationMs: -1 })).toThrow('计时无效')
    expect(deleteSequenceItem(items, 1).length).toBe(2)
    expect(removeElementAnimations(items, source, 'title').map(item => 'source' in item && item.source)).toEqual([0])
  })

  it('appends motion paths and per-paragraph animations with the pinned defaults', () => {
    expect(Object.keys(MOTION_PATHS)).toEqual(['motionPathRight', 'motionPathDown', 'motionPathDiagonal', 'motionPathCircle', 'motionPathZigzag'])
    expect(motionPathAnimation('title', 'motionPathZigzag')).toEqual({ elementId: 'title', effect: 'motionPath', trigger: 'onClick', durationMs: 2000, delayMs: 0, motionPath: 'M 0 0 L 0.12 -0.12 L 0.24 0.12 L 0.36 0' })
    expect([defaultAnimationDuration('appear'), defaultAnimationDuration('spin'), defaultAnimationDuration('pulse'), defaultAnimationDuration('fade')]).toEqual([0, 2000, 1000, 500])
    const base = { elementId: 'body', effect: 'flyIn' as const, trigger: 'onClick' as const, durationMs: 500, delayMs: 0, direction: 'left' as const }
    expect(appendAnimation([], base, 3).map(item => 'paragraph' in item && item.paragraph)).toEqual([0, 1, 2])
    expect(appendAnimation([], base, 1)).toEqual([base])
    expect(appendAnimation([], motionPathAnimation('body', 'motionPathRight'), 3)).toHaveLength(1)
    const all = [...initialSequence(source), ...appendAnimation([], base, 3), motionPathAnimation('title', 'motionPathCircle')]
    expect(validateSequence(all, source, elements)).toBe(all)
  })

  it('rejects stale sources, readonly preset retiming and invalid new items', () => {
    const bad: unknown[][] = [
      [{ source: 0, spid: 9, effect: 'fade' }], [{ source: 0, spid: 4, effect: 'zoom' }], [{ source: 5, spid: 4, effect: 'fade' }],
      [{ source: 0, spid: 4, effect: 'fade' }, { source: 0, spid: 4, effect: 'fade' }], [{ source: 2, spid: 5, effect: 'fade', delayMs: 5 }],
      [{ elementId: 'pic', effect: 'fade', trigger: 'onClick', durationMs: 500, delayMs: 0 }],
      [{ elementId: 'body', effect: 'fade', trigger: 'onClick', durationMs: 500, delayMs: 0, paragraph: 3 }],
      [{ elementId: 'body', effect: 'fade', trigger: 'onClick', durationMs: 500, delayMs: 0, direction: 'left' }],
      [{ elementId: 'body', effect: 'motionPath', trigger: 'onClick', durationMs: 500, delayMs: 0, motionPath: 'M 0 0 L 9 9' }],
      [{ elementId: 'body', effect: 'motionPath', trigger: 'onClick', durationMs: 500, delayMs: 0 }],
      [{ elementId: 'body', effect: 'mediaPlay', trigger: 'onClick', durationMs: 0, delayMs: 0 }],
      [{ elementId: 'body', effect: 'fade', trigger: 'onClick', durationMs: 500 }],
    ]
    for (const items of bad) expect(() => validateSequence(items, source, elements), JSON.stringify(items)).toThrow()
  })
})
