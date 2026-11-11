import { act } from 'react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { mountSlidesCanvas, type SlidesCanvasState } from './slides-canvas'

const rendered = vi.hoisted(() => ({ groups: [] as Record<string, any>[], stage: {} as Record<string, any>, transformerNodes: vi.fn(), layer: {}, bounds: new Map<number, { x: number; y: number; width: number; height: number }>(), resize: undefined as ((entries: any[]) => void) | undefined }))
vi.mock('react-konva', async () => {
  const React = await import('react')
  const container = ({ children }: any) => React.createElement('div', null, children)
  return {
    Layer: React.forwardRef((props: any, ref) => { React.useImperativeHandle(ref, () => rendered.layer); return container(props) }),
    Stage: (props: any) => { rendered.stage = props; return container(props) },
    Group: React.forwardRef((props: any, ref) => {
      if (props.name) rendered.groups.push(props)
      React.useImperativeHandle(ref, () => ({ marker: props.name, x: () => props.x, y: () => props.y, scaleX: () => 1, scaleY: () => 1,
        getClientRect: () => rendered.bounds.get(props.x) ?? { x: props.x - 20, y: props.y - 15, width: 40, height: 30 } }))
      return container(props)
    }),
    Rect: () => null,
    Transformer: React.forwardRef((_props, ref) => {
      React.useImperativeHandle(ref, () => ({ nodes: rendered.transformerNodes, getLayer: () => ({ batchDraw() {} }) }))
      return null
    }),
  }
})
vi.mock('./vendor/genoffice/renderer/NodeBody', () => ({ StaticNode: () => null }))
vi.mock('./vendor/genoffice/renderer/konva-adapter', () => ({
  boxPivotProps: (box: any) => ({ x: box.x + box.w / 2, y: box.y + box.h / 2 }), fillToKonva: () => ({}),
}))

let canvas: ReturnType<typeof mountSlidesCanvas>
const node = (id: string, type: string, x: number, decoration = false) => ({ id: `render-${id}`, sourceId: id, type,
  box: { x, y: 20, w: 40, h: 30, rotationDeg: 0 }, decoration })
const select = vi.fn(), geometry = vi.fn(), selectMany = vi.fn()
const state = (): SlidesCanvasState => ({
  slide: { widthPx: 960, heightPx: 540, nodes: [node('a', 'shape', 10), node('p', 'picture', 100), node('decor', 'shape', 200, true), { ...node('back', 'shape', 150), background: true }] } as never,
  selectedId: 'a', editableIds: new Set(['a']), selectableIds: new Set(['a', 'p', 'decor', 'back']), edits: [], onSelect: select, onGeometry: geometry,
})
const group = (x: number) => rendered.groups.findLast(props => props.x === x + 20)!
beforeEach(() => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true)
  vi.stubGlobal('ResizeObserver', class { constructor(callback: (entries: any[]) => void) { rendered.resize = callback } observe() {} disconnect() {} })
  rendered.groups = []; rendered.transformerNodes.mockClear(); select.mockClear(); geometry.mockClear()
  rendered.bounds.clear(); selectMany.mockClear()
  canvas = mountSlidesCanvas(document.body.appendChild(document.createElement('div')))
})
afterEach(async () => { await act(async () => canvas.destroy()); document.body.replaceChildren(); vi.unstubAllGlobals() })

it('selects pictures without making them editable, forwards toggle modifiers and ignores decoration', async () => {
  await act(async () => canvas.update(state()))
  expect(group(100).listening).toBe(true)
  expect(group(100).draggable).toBe(false)
  expect(group(200).listening).toBe(false)
  group(100).onClick({ evt: { button: 0, ctrlKey: true } })
  expect(select).toHaveBeenLastCalledWith('p', true)
  group(10).onClick({ evt: { button: 0 } })
  expect(select).toHaveBeenLastCalledWith('a', false)
  group(10).onClick({ evt: { button: 0, shiftKey: true } })
  expect(select).toHaveBeenLastCalledWith('a', true)
  group(10).onClick({ evt: { button: 0, metaKey: true } })
  expect(select).toHaveBeenLastCalledWith('a', true)
  select.mockClear(); group(10).onClick({ evt: { button: 2 } })
  expect(select).not.toHaveBeenCalled()
})

it('disables transform and drag for multi-selection, guards stale callbacks and clears on blank click', async () => {
  await act(async () => canvas.update({ ...state(), selectedIds: ['a', 'p'] }))
  expect(group(10).draggable).toBe(false)
  expect(rendered.transformerNodes).toHaveBeenLastCalledWith([])
  group(10).onTransformEnd({ target: {} })
  group(10).onDragEnd({ target: {} })
  expect(geometry).not.toHaveBeenCalled()
  const stage = {}
  rendered.stage.onMouseDown({ target: { getStage: () => stage } })
  expect(select).not.toHaveBeenCalled()
  rendered.stage.onMouseDown({ target: Object.assign(stage, { getStage: () => stage }) })
  expect(select).toHaveBeenLastCalledWith('')
})

it('keeps legacy single selection transform and rechecks editable permission before committing', async () => {
  await act(async () => canvas.update(state()))
  expect(group(10).draggable).toBe(true)
  expect(rendered.transformerNodes.mock.calls.at(-1)![0]).toHaveLength(1)
  group(10).onDragEnd({ target: { x: () => 100, y: () => 80, scaleX: () => 1, scaleY: () => 1 } })
  expect(geometry).toHaveBeenLastCalledWith('a', { x: 80, y: 65, width: 40, height: 30 })
  geometry.mockClear()
  group(100).onDragEnd({ target: {} })
  expect(geometry).not.toHaveBeenCalled()
})

it('removes an existing transform immediately when edit permission changes without a selection change', async () => {
  const initial = state()
  await act(async () => canvas.update(initial))
  expect(rendered.transformerNodes.mock.calls.at(-1)![0]).toHaveLength(1)
  await act(async () => canvas.update({ ...initial, editableIds: new Set() }))
  expect(rendered.transformerNodes).toHaveBeenLastCalledWith([])
})

function mouse(x: number, y: number, modifiers: Record<string, unknown> = {}) {
  const stage = { getPointerPosition: () => ({ x, y }), getStage: () => stage }
  return { target: stage, evt: { button: 0, ...modifiers } }
}

it('框选按真实当前包围框选中可选对象，忽略装饰并只提交一次', async () => {
  await act(async () => canvas.update({ ...state(), onSelectMany: selectMany }))
  await act(async () => rendered.stage.onMouseDown(mouse(0, 0)))
  expect(select).not.toHaveBeenCalled()
  await act(async () => rendered.stage.onMouseMove(mouse(250, 70)))
  expect(selectMany).not.toHaveBeenCalled()
  await act(async () => rendered.stage.onMouseUp(mouse(250, 70)))
  expect(selectMany).toHaveBeenCalledExactlyOnceWith(['a', 'p'], false)
  group(100).onClick({ evt: { button: 0 } })
  expect(select).not.toHaveBeenCalled()
})

it('反向拖动及修饰键追加使用当前编辑后位置', async () => {
  await act(async () => canvas.update({ ...state(), onSelectMany: selectMany, edits: [{ elementId: 'a', geometry: { x: 300, y: 20, width: 40, height: 30 } }] }))
  await act(async () => rendered.stage.onMouseDown(mouse(350, 70, { metaKey: true })))
  await act(async () => rendered.stage.onMouseMove(mouse(290, 10)))
  await act(async () => rendered.stage.onMouseUp(mouse(290, 10)))
  expect(selectMany).toHaveBeenCalledExactlyOnceWith(['a'], true)
})

it('旋转对象使用Konva真实包围框并排除无权限对象', async () => {
  rendered.bounds.set(30, { x: 280, y: 100, width: 70, height: 70 })
  await act(async () => canvas.update({ ...state(), onSelectMany: selectMany, selectableIds: new Set(['a']) }))
  await act(async () => rendered.stage.onMouseDown(mouse(270, 90)))
  await act(async () => rendered.stage.onMouseMove(mouse(360, 180)))
  await act(async () => rendered.stage.onMouseUp(mouse(360, 180)))
  expect(selectMany).toHaveBeenCalledExactlyOnceWith(['a'], false)
})

it('未达到阈值的空白点击仍清空，右键不发起框选', async () => {
  await act(async () => canvas.update({ ...state(), onSelectMany: selectMany }))
  await act(async () => rendered.stage.onMouseDown(mouse(0, 0)))
  await act(async () => rendered.stage.onMouseUp(mouse(2, 2)))
  expect(select).toHaveBeenCalledExactlyOnceWith('')
  select.mockClear()
  await act(async () => rendered.stage.onMouseDown(mouse(0, 0, { button: 2 })))
  await act(async () => rendered.stage.onMouseUp(mouse(200, 100)))
  expect(selectMany).not.toHaveBeenCalled()
  expect(select).not.toHaveBeenCalled()
})

it('离开画布、取消和切页均丢弃未完成框选', async () => {
  const initial = { ...state(), onSelectMany: selectMany }
  await act(async () => canvas.update(initial))
  for (const cancel of ['leave', 'cancel', 'slide'] as const) {
    await act(async () => rendered.stage.onMouseDown(mouse(0, 0)))
    await act(async () => rendered.stage.onMouseMove(mouse(160, 70)))
    if (cancel === 'leave') await act(async () => rendered.stage.onMouseLeave())
    else if (cancel === 'cancel') await act(async () => window.dispatchEvent(new Event('pointercancel')))
    else await act(async () => canvas.update({ ...initial, slide: { ...initial.slide } }))
    await act(async () => rendered.stage.onMouseUp(mouse(160, 70)))
  }
  expect(selectMany).not.toHaveBeenCalled()
  expect(select).not.toHaveBeenCalled()
})

it('缩放后仍使用画布坐标，框选阈值保持屏幕像素', async () => {
  await act(async () => canvas.update({ ...state(), onSelectMany: selectMany }))
  await act(async () => rendered.resize!([{ contentRect: { width: 480 } }]))
  await act(async () => rendered.stage.onMouseDown(mouse(0, 0)))
  await act(async () => rendered.stage.onMouseUp(mouse(75, 30)))
  expect(selectMany).toHaveBeenCalledExactlyOnceWith(['a', 'p'], false)
  selectMany.mockClear()
  await act(async () => rendered.stage.onMouseDown(mouse(0, 0)))
  await act(async () => rendered.stage.onMouseUp(mouse(2, 1)))
  expect(select).toHaveBeenLastCalledWith('')
  expect(selectMany).not.toHaveBeenCalled()
})

it('失焦或尺寸变化取消框选，触摸保留空白清空', async () => {
  await act(async () => canvas.update({ ...state(), onSelectMany: selectMany }))
  for (const cancel of ['blur', 'resize'] as const) {
    await act(async () => rendered.stage.onMouseDown(mouse(0, 0)))
    await act(async () => rendered.stage.onMouseMove(mouse(160, 70)))
    if (cancel === 'blur') await act(async () => window.dispatchEvent(new Event('blur')))
    else await act(async () => rendered.resize!([{ contentRect: { width: 480 } }]))
    await act(async () => rendered.stage.onMouseUp(mouse(160, 70)))
  }
  expect(selectMany).not.toHaveBeenCalled()
  expect(select).not.toHaveBeenCalled()
  await act(async () => rendered.stage.onTouchStart(mouse(0, 0)))
  expect(select).toHaveBeenCalledExactlyOnceWith('')
})
