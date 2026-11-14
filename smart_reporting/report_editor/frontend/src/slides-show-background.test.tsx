import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { expect, it, vi } from 'vitest'
import type { RenderSlide } from '@genoffice/pptx-render'
import { AnimatedSlideStage } from './vendor/genoffice/renderer/AnimatedSlide'

vi.mock('react-konva', async () => {
  const React = await import('react')
  const container = ({ children }: any) => React.createElement('div', null, children)
  return { Stage: container, Layer: container, Group: container, Rect: ({ width, height }: any) => React.createElement('span', { 'data-background-width': width, 'data-background-height': height }) }
})
vi.mock('./vendor/genoffice/renderer/NodeBody', () => ({ StaticNode: () => null }))

it.each([240, 1440])('投影宽%ipx时背景仍使用完整幻灯片模型坐标，交由Layer统一缩放', async width => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true)
  const host = document.body.appendChild(document.createElement('div')), root = createRoot(host)
  const slide = { widthPx: 960, heightPx: 720, background: { kind: 'solid', color: '#fff' }, nodes: [] } as unknown as RenderSlide
  try {
    await act(async () => root.render(<AnimatedSlideStage slide={slide} images={new Map()} width={width} states={new Map()} />))
    expect(host.querySelector('[data-background-width]')?.getAttribute('data-background-width')).toBe('960')
    expect(host.querySelector('[data-background-height]')?.getAttribute('data-background-height')).toBe('720')
  } finally { await act(async () => root.unmount()); host.remove(); vi.unstubAllGlobals() }
})
