import type { RenderNode, RenderSlide } from '@genoffice/pptx-render'

export type CanvasGeometry = { x: number; y: number; width: number; height: number }
export type CanvasEdit = { elementId: string; geometry?: CanvasGeometry; text?: string }

export function canvasEditable(node: RenderNode, editable: ReadonlySet<string>) {
  return !node.decoration && editable.has(node.sourceId)
}

export function canvasGeometryEdit(node: RenderNode, target: { x: number; y: number; scaleX: number; scaleY: number }): CanvasGeometry {
  return {
    x: Math.max(0, Math.round(target.x - node.box.w * Math.abs(target.scaleX) / 2)),
    y: Math.max(0, Math.round(target.y - node.box.h * Math.abs(target.scaleY) / 2)),
    width: Math.max(1, Math.round(node.box.w * Math.abs(target.scaleX))),
    height: Math.max(1, Math.round(node.box.h * Math.abs(target.scaleY))),
  }
}

export function applyCanvasEdits(slide: RenderSlide, edits: CanvasEdit[]): RenderSlide {
  return { ...slide, nodes: slide.nodes.map(node => {
    const edit = edits.find(item => item.elementId === node.sourceId)
    if (!edit?.geometry) return node
    const geometry = edit.geometry
    return { ...node, box: { ...node.box, x: geometry.x, y: geometry.y, w: geometry.width, h: geometry.height } }
  }) }
}
