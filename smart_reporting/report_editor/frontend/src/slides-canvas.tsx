import React, { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { createRoot } from 'react-dom/client'
import Konva from 'konva'
import { Group, Layer, Line, Rect, Stage, Transformer } from 'react-konva'
import type { RenderNode, RenderSlide } from '@genoffice/pptx-render'
import { StaticNode } from './vendor/genoffice/renderer/NodeBody'
import { boxPivotProps, fillToKonva } from './vendor/genoffice/renderer/konva-adapter'
import { applyCanvasEdits, canvasEditable, canvasGeometryEdit, type CanvasEdit, type CanvasGeometry } from './slides-canvas-model'
import { clampZoom, ZOOM_MIN } from './slides-view-zoom'
import { slidesMarqueeIds, slidesMarqueeRect, type MarqueePoint } from './slides-marquee'
import { defaultDrawSize, isLineDrawKind, resolveDrawRect, type DrawRect } from './vendor/genoffice-slides/draw-shape'

/** Konva 不能解析 CSS 变量：从统一视觉 token（office-theme.css）读取当前强调色。 */
export function officeSelectionStroke(root: Element = document.documentElement): string {
  return getComputedStyle(root).getPropertyValue('--office-accent').trim() || '#0b4f8a'
}

export type SlidesCanvasState = {
  slide: RenderSlide
  selectedId: string
  selectedIds?: string[]
  editableIds: Set<string>
  selectableIds?: Set<string>
  edits: CanvasEdit[]
  shapeDrawing?: { kind: string; commit: (rect: DrawRect) => void }
  onMediaPlayback?: (id:string) => void
  onSelect: (id: string, additive?: boolean) => void
  onSelectMany?: (ids: string[], additive?: boolean) => void
  onGeometry: (id: string, geometry: CanvasGeometry) => void
}

function collectImages(value: unknown, urls = new Set<string>()): Set<string> {
  if (typeof value === 'string' && value.startsWith('data:image/')) urls.add(value)
  else if (value && typeof value === 'object') for (const child of Object.values(value)) collectImages(child, urls)
  return urls
}

function SlideCanvas({ state, width, onLayout }: { state: SlidesCanvasState; width: number; onLayout(): void }) {
  const [images, setImages] = useState(new Map<string, HTMLImageElement>())
  const transformer = useRef<Konva.Transformer>(null)
  const nodes = useRef(new Map<string, Konva.Group>())
  const selectableNodes = useRef(new Map<string, Konva.Group>())
  const layer = useRef<Konva.Layer>(null)
  const marquee = useRef<{ start: MarqueePoint; end: MarqueePoint; additive: boolean } | null>(null)
  const [marqueeBox, setMarqueeBox] = useState<ReturnType<typeof slidesMarqueeRect> | null>(null)
  const drawStart = useRef<MarqueePoint | null>(null)
  const [drawPreview, setDrawPreview] = useState<DrawRect | null>(null)
  const drawing = state.shapeDrawing
  const suppressClick = useRef(false)
  const slide = applyCanvasEdits(state.slide, state.edits)
  const scale = width / slide.widthPx
  const selectionStroke = officeSelectionStroke()
  const selectedIds = state.selectedIds ?? (state.selectedId ? [state.selectedId] : [])
  const selected = new Set(selectedIds)
  const multiple = selectedIds.length > 1
  useLayoutEffect(onLayout)
  const cancelMarquee = () => { marquee.current = null; setMarqueeBox(null) }
  const clearDrawing = () => { drawStart.current = null; setDrawPreview(null) }
  // 切页、更新几何或缩放时丢弃拖动，避免旧画布坐标提交到新状态。
  useLayoutEffect(cancelMarquee, [state.slide, state.edits, state.selectableIds, width])
  useLayoutEffect(clearDrawing, [drawing, width])
  useEffect(() => {
    const cancelGesture = () => { cancelMarquee(); clearDrawing() }
    window.addEventListener('blur', cancelGesture)
    window.addEventListener('pointercancel', cancelGesture)
    return () => { window.removeEventListener('blur', cancelGesture); window.removeEventListener('pointercancel', cancelGesture) }
  }, [])
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
    const node = !drawing && !multiple && selectedIds[0] ? nodes.current.get(selectedIds[0]) : undefined
    transformer.current?.nodes(node ? [node] : [])
    transformer.current?.getLayer()?.batchDraw()
  }, [drawing, state.selectedId, state.selectedIds, state.editableIds, state.slide, state.edits])
  const commit = (node: RenderNode, target: Konva.Group) => {
    if (multiple || node.background || !canvasEditable(node, state.editableIds)) return
    const geometry = canvasGeometryEdit(node, { x: target.x(), y: target.y(), scaleX: target.scaleX(), scaleY: target.scaleY() })
    target.scaleX(1); target.scaleY(1)
    state.onGeometry(node.sourceId, geometry)
  }
  const pointer = (event: Konva.KonvaEventObject<MouseEvent>) => {
    const point = event.target.getStage()?.getPointerPosition()
    return point ? { x: point.x / scale, y: point.y / scale } : null
  }
  return <Stage width={width} height={slide.heightPx * scale} style={{ cursor: drawing ? 'crosshair' : undefined }}
    onMouseDown={event => {
      suppressClick.current = false
      if (drawing) {
        if (event.evt.button === 0) drawStart.current = pointer(event)
        return
      }
      if (event.target !== event.target.getStage() || event.evt?.button !== 0) {
        // 未接入框选的旧调用方保留空白按下即清空的约定。
        if (!state.onSelectMany && event.target === event.target.getStage() && event.evt?.button !== 2) state.onSelect('')
        return
      }
      if (!state.onSelectMany) { state.onSelect(''); return }
      const start = pointer(event)
      if (start) marquee.current = { start, end: start, additive: !!(event.evt.ctrlKey || event.evt.metaKey || event.evt.shiftKey) }
    }}
    onMouseMove={event => {
      if (drawing) {
        const start = drawStart.current, end = pointer(event)
        if (start && end) {
          const dragged = Math.hypot(end.x - start.x, end.y - start.y) * scale > 3
          setDrawPreview(dragged ? resolveDrawRect(drawing.kind, start.x, start.y, end.x, end.y, event.evt.shiftKey) : null)
        }
        return
      }
      const active = marquee.current, end = pointer(event)
      if (!active || !end) return
      active.end = end
      setMarqueeBox(Math.hypot(end.x - active.start.x, end.y - active.start.y) * scale >= 4 ? slidesMarqueeRect(active.start, end) : null)
    }}
    onMouseUp={event => {
      if (drawing) {
        const start = drawStart.current, end = pointer(event)
        clearDrawing()
        if (!start || !end || event.evt.button !== 0) return
        const clicked = Math.hypot(end.x - start.x, end.y - start.y) * scale <= 3
        drawing.commit(clicked
          ? { ...start, ...defaultDrawSize(drawing.kind), click: true }
          : resolveDrawRect(drawing.kind, start.x, start.y, end.x, end.y, event.evt.shiftKey))
        return
      }
      const active = marquee.current
      if (!active) return
      const end = pointer(event) ?? active.end
      const candidates = [...selectableNodes.current].map(([id, node]) => ({ id, bounds: node.getClientRect({ relativeTo: layer.current!, skipStroke: true, skipShadow: true }) }))
      const ids = slidesMarqueeIds(active.start, end, scale, candidates)
      cancelMarquee()
      if (ids === null) state.onSelect('')
      else { suppressClick.current = true; state.onSelectMany?.(ids, active.additive) }
    }}
    onMouseLeave={() => { cancelMarquee(); clearDrawing() }}
    onTouchStart={event => { cancelMarquee(); if (!drawing && event.target === event.target.getStage()) state.onSelect('') }}>
    <Layer ref={layer} scaleX={scale} scaleY={scale}>
      <Rect width={slide.widthPx} height={slide.heightPx} {...fillToKonva(slide.background, slide.widthPx, slide.heightPx, images)} listening={false} />
      {slide.nodes.map(node => {
        const editable = canvasEditable(node, state.editableIds)
        const selectable = !node.background && canvasEditable(node, state.selectableIds ?? state.editableIds)
        return <Group key={node.id} {...boxPivotProps(node.box)} ref={value => {
          if (value && editable && !node.background) nodes.current.set(node.sourceId, value); else nodes.current.delete(node.sourceId)
          if (value && selectable) selectableNodes.current.set(node.sourceId, value); else selectableNodes.current.delete(node.sourceId)
        }}
          name={editable ? 'editable-slide-object' : 'readonly-slide-object'} draggable={!drawing && editable && !node.background && !multiple} listening={!drawing && (selectable || (node.type==='picture' && !!node.media && !!state.onMediaPlayback))}
          onDblClick={() => {if(node.type==='picture'&&node.media)state.onMediaPlayback?.(node.sourceId)}}
          onDblTap={() => {if(node.type==='picture'&&node.media)state.onMediaPlayback?.(node.sourceId)}}
          onClick={event => { if (!suppressClick.current && event.evt.button === 0) state.onSelect(node.sourceId, !!(event.evt.ctrlKey || event.evt.metaKey || event.evt.shiftKey)) }} onTap={() => state.onSelect(node.sourceId)}
          onDragStart={() => state.onSelect(node.sourceId)} onDragEnd={event => commit(node, event.target as Konva.Group)}
          onTransformEnd={event => commit(node, event.target as Konva.Group)}>
          <Rect width={node.box.w} height={node.box.h} fill="rgba(0,0,0,0)" stroke={selected.has(node.sourceId) && (multiple || !editable) ? selectionStroke : undefined} strokeWidth={1.5 / scale} />
          <Group x={-node.box.x} y={-node.box.y}>
            <StaticNode node={{ ...node, box: { ...node.box, rotationDeg: 0, flipH: false, flipV: false } }} images={images} />
          </Group>
        </Group>
      })}
      {marqueeBox && <Rect {...marqueeBox} fill="rgba(11,79,138,0.08)" stroke={selectionStroke} strokeWidth={1 / scale} listening={false} />}
      {drawing && drawPreview && (isLineDrawKind(drawing.kind)
        ? <Line points={[
          drawPreview.x + (drawPreview.flipH ? drawPreview.w : 0), drawPreview.y + (drawPreview.flipV ? drawPreview.h : 0),
          drawPreview.x + (drawPreview.flipH ? 0 : drawPreview.w), drawPreview.y + (drawPreview.flipV ? 0 : drawPreview.h),
        ]} stroke={selectionStroke} strokeWidth={1 / scale} listening={false} />
        : <Rect x={drawPreview.x} y={drawPreview.y} width={drawPreview.w} height={drawPreview.h}
          fill="rgba(11,79,138,0.08)" stroke={selectionStroke} strokeWidth={1 / scale} listening={false} />)}
      <Transformer ref={transformer} rotateEnabled={false} flipEnabled={false} keepRatio={false} enabledAnchors={['top-left', 'top-right', 'bottom-left', 'bottom-right']} anchorSize={12} borderStroke={selectionStroke} anchorStroke={selectionStroke} boundBoxFunc={(oldBox, newBox) => newBox.width < 8 || newBox.height < 8 ? oldBox : newBox} />
    </Layer>
  </Stage>
}

export function mountSlidesCanvas(host: HTMLElement, onZoomChange?: (zoom: number) => void) {
  const root = createRoot(host)
  let state: SlidesCanvasState | undefined
  let width = host.clientWidth || 960
  let height = host.clientHeight || Number.POSITIVE_INFINITY
  let manualZoom: number | null = null
  const rawFit = () => state ? Math.min(width / state.slide.widthPx, height / state.slide.heightPx) : 1
  type Anchor = { x: number; y: number }
  let pendingAnchor: { point: Anchor; fraction: Anchor } | undefined
  const pageBox = () => host.querySelector<HTMLElement>('.konvajs-content')?.getBoundingClientRect()
  const restoreAnchor = () => {
    const anchor = pendingAnchor
    pendingAnchor = undefined
    if (!anchor) return
    const rect = pageBox()
    if (!rect?.width || !rect.height) return
    host.scrollLeft += rect.left + anchor.fraction.x * rect.width - anchor.point.x
    host.scrollTop += rect.top + anchor.fraction.y * rect.height - anchor.point.y
  }
  const getZoom = () => {
    if (manualZoom !== null) return manualZoom
    if (!state) return 1
    return Math.min(1.5, Math.max(ZOOM_MIN, rawFit()))
  }
  const render = () => {
    if (!state) return
    const zoom = getZoom()
    root.render(<SlideCanvas state={state} width={state.slide.widthPx * zoom} onLayout={restoreAnchor} />)
    onZoomChange?.(zoom)
  }
  const observer = new ResizeObserver(([entry]) => {
    const viewport = entry?.contentRect
    if (!viewport?.width) return
    width = viewport.width
    if (viewport.height > 0) height = viewport.height
    render()
  })
  observer.observe(host)
  return {
    getZoom,
    fitsViewport: () => getZoom() <= rawFit() + 0.001,
    setZoom(next: number | null, anchor?: Anchor) {
      if (next !== null && !Number.isFinite(next)) return
      const previous = getZoom()
      manualZoom = next === null ? null : clampZoom(next)
      const rect = anchor && manualZoom !== previous ? pageBox() : undefined
      pendingAnchor = anchor && rect?.width && rect.height ? {
        point: anchor, fraction: { x: (anchor.x - rect.left) / rect.width, y: (anchor.y - rect.top) / rect.height },
      } : undefined
      if (next === null) host.scrollLeft = host.scrollTop = 0
      render()
    },
    update(next: SlidesCanvasState) { state = next; render() },
    destroy() { observer.disconnect(); root.unmount() },
  }
}
