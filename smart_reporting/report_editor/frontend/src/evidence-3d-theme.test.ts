import { describe, expect, it, vi } from 'vitest'

import { CARD_PIXELS, drawEvidenceCard } from './evidence-3d-theme'

function recordingCanvas() {
  const calls: Array<[string, unknown[]]> = []
  const context = new Proxy({ globalAlpha: 1 } as Record<string, unknown>, {
    get(target, key: string) {
      if (key in target) return target[key]
      if (key === 'measureText') return (text: string) => ({ width: text.length * 20 })
      if (key === 'createLinearGradient') return () => ({ addColorStop: () => {} })
      return (...args: unknown[]) => { calls.push([key, args]) }
    },
    set(target, key: string, value) { target[key] = value; return true },
  })
  const canvas = { width: 0, height: 0, getContext: vi.fn(() => context) } as unknown as HTMLCanvasElement
  return { canvas, calls, context }
}

describe('evidence card drawing', () => {
  it('draws without an icon when the icon failed to decode and truncates long names', () => {
    const { canvas, calls } = recordingCanvas()
    drawEvidenceCard(canvas, { kind: 'fact', name: '华东地区门诊收入成本口径调整后的合计金额与上年同期相比的变化情况说明', detail: '事实 · 当前页', state: 'current', icon: null })
    expect(canvas.width).toBe(CARD_PIXELS.width)
    expect(calls.some(([name]) => name === 'drawImage')).toBe(false)
    const texts = calls.filter(([name]) => name === 'fillText').map(([, args]) => args[0] as string)
    expect(texts[0].endsWith('…')).toBe(true)
    expect(texts[1]).toBe('事实 · 当前页')
  })

  it('dims unrelated cards', () => {
    const { canvas, context } = recordingCanvas()
    drawEvidenceCard(canvas, { kind: 'dataset', name: '收入台账', detail: '快照', state: 'dimmed', icon: null })
    expect(context.globalAlpha).toBeLessThan(0.5)
  })
})
