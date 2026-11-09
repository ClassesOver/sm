import React, { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { createRoot } from 'react-dom/client'
import Konva from 'konva'
import { Group, Layer, Rect, Stage, Transformer } from 'react-konva'
import type { RenderNode, RenderSlide } from '@genoffice/pptx-render'
import { StaticNode } from './vendor/genoffice/renderer/NodeBody'
import { boxPivotProps, fillToKonva } from './vendor/genoffice/renderer/konva-adapter'
import { applyCanvasEdits, canvasEditable, canvasGeometryEdit, type CanvasEdit, type CanvasGeometry } from './slides-canvas-model'

/** Konva 不能解析 CSS 变量：从统一视觉 token（office-theme.css）读取当前强调色。 */
export function officeSelectionStroke(root: Element = document.documentElement): string {
  return getComputedStyle(root).getPropertyValue('--office-accent').trim() || '#0b4f8a'
}

export type SlidesCanvasState = {
  slide: RenderSlide
  selectedId: string
  editableIds: Set<string>
  edits: CanvasEdit[]
  onSelect: (id: string) => void
  onGeometry: (id: string, geometry: CanvasGeometry) => void
}

function collectImages(value: unknown, urls = new Set<string>()): Set<string> {
  if (typeof value === 'string' && value.startsWith('data:image/')) urls.add(value)
  else if (value && typeof value === 'object') for (const child of Object.values(value)) collectImages(child, urls)
  return urls
}

function SlideCanvas({ state, width }: { state: SlidesCanvasState; width: number }) {
  const [images, setImages] = useState(new Map<string, HTMLImageElement>())
  const transformer = useRef<Konva.Transformer>(null)
  const nodes = useRef(new Map<string, Konva.Group>())
  const slide = applyCanvasEdits(state.slide, state.edits)
  const scale = width / slide.widthPx
  const selectionStroke = officeSelectionStroke()
  useEffect(() => {
    let disposed = false
    for (const url of collectImages(state.slide)) {
      const image = new Image()
      image.onload = () => { if (!disposed) setImages(previous => new Map(previous).set(url, image)) }
      image.src = url
    }
    return () => { disposed = true }
  }, [state.slide])
  useLayoutEffect(() => {
    const node = nodes.current.get(state.selectedId)
    transformer.current?.nodes(node ? [node] : [])
    transformer.current?.getLayer()?.batchDraw()
  }, [state.selectedId, state.slide, state.edits])
  const commit = (node: RenderNode, target: Konva.Group) => {
    const geometry = canvasGeometryEdit(node, { x: target.x(), y: target.y(), scaleX: target.scaleX(), scaleY: target.scaleY() })
    target.scaleX(1); target.scaleY(1)
    state.onGeometry(node.sourceId, geometry)
  }
  return <Stage width={width} height={slide.heightPx * scale} onMouseDown={event => { if (event.target === event.target.getStage()) state.onSelect('') }} onTouchStart={event => { if (event.target === event.target.getStage()) state.onSelect('') }}>
    <Layer scaleX={scale} scaleY={scale}>
      <Rect width={slide.widthPx} height={slide.heightPx} {...fillToKonva(slide.background, slide.widthPx, slide.heightPx, images)} listening={false} />
      {slide.nodes.map(node => {
        const editable = canvasEditable(node, state.editableIds)
        return <Group key={node.id} {...boxPivotProps(node.box)} ref={value => { if (value && editable) nodes.current.set(node.sourceId, value); else nodes.current.delete(node.sourceId) }}
          name={editable ? 'editable-slide-object' : 'readonly-slide-object'} draggable={editable && !node.background} listening={editable}
          onClick={() => state.onSelect(node.sourceId)} onTap={() => state.onSelect(node.sourceId)}
          onDragStart={() => state.onSelect(node.sourceId)} onDragEnd={event => commit(node, event.target as Konva.Group)}
          onTransformEnd={event => commit(node, event.target as Konva.Group)}>
          <Rect width={node.box.w} height={node.box.h} fill="rgba(0,0,0,0)" />
          <Group x={-node.box.x} y={-node.box.y}>
            <StaticNode node={{ ...node, box: { ...node.box, rotationDeg: 0, flipH: false, flipV: false } }} images={images} />
          </Group>
        </Group>
      })}
      <Transformer ref={transformer} rotateEnabled={false} flipEnabled={false} keepRatio={false} enabledAnchors={['top-left', 'top-right', 'bottom-left', 'bottom-right']} anchorSize={12} borderStroke={selectionStroke} anchorStroke={selectionStroke} boundBoxFunc={(oldBox, newBox) => newBox.width < 8 || newBox.height < 8 ? oldBox : newBox} />
    </Layer>
  </Stage>
}

export function mountSlidesCanvas(host: HTMLElement) {
  const root = createRoot(host)
  let state: SlidesCanvasState | undefined
  let width = Math.max(1, host.clientWidth || 960)
  const render = () => { if (state) root.render(<SlideCanvas state={state} width={Math.min(width, state.slide.widthPx)} />) }
  const observer = new ResizeObserver(entries => { width = Math.max(1, entries[0]?.contentRect.width ?? host.clientWidth); render() })
  observer.observe(host)
  return { update(next: SlidesCanvasState) { state = next; render() }, destroy() { observer.disconnect(); root.unmount() } }
}
