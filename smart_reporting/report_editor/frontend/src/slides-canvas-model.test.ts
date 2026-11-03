import { describe, expect, it } from 'vitest'
import { canvasGeometryEdit, applyCanvasEdits, canvasEditable } from './slides-canvas-model'

const node = {
  id: 'render-1', sourceId: 'original-1', type: 'shape',
  box: { x: 10, y: 20, w: 300, h: 100, rotationDeg: 0 },
  fill: { kind: 'solid', color: '#123456' },
}

describe('slide canvas editing boundary', () => {
  it('converts a centered Konva drag and resize into the original object edit', () => {
    expect(canvasGeometryEdit(node as never, { x: 300, y: 180, scaleX: 1.5, scaleY: 2 })).toEqual({
      x: 75, y: 80, width: 450, height: 200,
    })
  })
  it('previews pending geometry while preserving source identity and original nodes', () => {
    const slide = { widthPx: 960, heightPx: 540, nodes: [node] }
    const next = applyCanvasEdits(slide as never, [{ elementId: 'original-1', geometry: { x: 80, y: 90, width: 450, height: 200 } }])
    expect(next.nodes[0]!.sourceId).toBe('original-1')
    expect(next.nodes[0]!.box).toEqual({ x: 80, y: 90, w: 450, h: 200, rotationDeg: 0 })
    expect(node.box.x).toBe(10)
  })
  it('allows only editable original objects and keeps decoration read-only', () => {
    expect(canvasEditable(node as never, new Set(['original-1']))).toBe(true)
    expect(canvasEditable({ ...node, decoration: true } as never, new Set(['original-1']))).toBe(false)
    expect(canvasEditable(node as never, new Set(['other']))).toBe(false)
  })
})
