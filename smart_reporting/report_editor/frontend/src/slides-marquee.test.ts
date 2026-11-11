import Konva from 'konva'
import { expect, it } from 'vitest'
import { slidesMarqueeIds, slidesMarqueeRect } from './slides-marquee'

it('正反向框选相同区域且去重，微小移动不提交', () => {
  const start = { x: 30, y: 40 }, end = { x: 0, y: 0 }
  expect(slidesMarqueeRect(start, end)).toEqual({ x: 0, y: 0, width: 30, height: 40 })
  const item = { id: 'a', bounds: { x: 10, y: 10, width: 5, height: 5 } }
  expect(slidesMarqueeIds(start, end, 1, [item, item])).toEqual(['a'])
  expect(slidesMarqueeIds({ x: 0, y: 0 }, { x: 6, y: 0 }, .5, [item])).toBeNull()
  expect(slidesMarqueeIds(start, end, 1, [])).toEqual([])
})

it('使用Konva真实旋转包围框而非未旋转原框', () => {
  const parent = new Konva.Group()
  const group = new Konva.Group({ x: 100, y: 100, rotation: 45 })
  group.add(new Konva.Rect({ width: 80, height: 20 }))
  parent.add(group)
  const bounds = group.getClientRect({ relativeTo: parent, skipStroke: true, skipShadow: true })
  expect(bounds.x).toBeLessThan(90)
  expect(slidesMarqueeIds({ x: 83, y: 109 }, { x: 91, y: 119 }, 1, [{ id: 'rotated', bounds }])).toEqual(['rotated'])
  parent.destroy()
})
