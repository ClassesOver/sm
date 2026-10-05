import { describe, expect, it } from 'vitest'
// 包未发布main指向的CommonJS构建，单测明确使用与浏览器相同的ESM入口。
import { layoutGreedy } from '@d3fc/d3fc-label-layout/index.js'

describe('3D名称与固定图标区域', () => {
  it.each([true, false])('固定区域先输入=%s时仍只移动名称', obstacleFirst => {
    const obstacle = { x: 60, y: 60, width: 16, height: 16, fixed: true }
    const name = { x: 70, y: 60, width: 50, height: 20 }
    const input = obstacleFirst ? [obstacle, name] : [name, obstacle]
    const previous = structuredClone(input)
    const result = layoutGreedy().bounds({ x: 0, y: 0, width: 200, height: 140 })(input)
    const fixed = result[obstacleFirst ? 0 : 1]
    const label = result[obstacleFirst ? 1 : 0]
    expect(fixed).toEqual(previous[obstacleFirst ? 0 : 1])
    expect(input).toEqual(previous)
    const overlapWidth = Math.min(fixed.x + fixed.width, label.x + label.width) - Math.max(fixed.x, label.x)
    const overlapHeight = Math.min(fixed.y + fixed.height, label.y + label.height) - Math.max(fixed.y, label.y)
    expect(overlapWidth <= 0 || overlapHeight <= 0).toBe(true)
    expect(label.x).toBeGreaterThanOrEqual(0)
    expect(label.y).toBeGreaterThanOrEqual(0)
    expect(label.x + label.width).toBeLessThanOrEqual(200)
    expect(label.y + label.height).toBeLessThanOrEqual(140)
  })
  it('没有可避让空位时仍保持名称在视口内', () => {
    const obstacle = { x: 0, y: 0, width: 100, height: 100, fixed: true }
    const name = { x: 95, y: 95, width: 20, height: 15 }
    const [fixed, label] = layoutGreedy().bounds(obstacle)([obstacle, name])
    expect(fixed).toEqual(obstacle)
    expect(label.x).toBeGreaterThanOrEqual(0)
    expect(label.y).toBeGreaterThanOrEqual(0)
    expect(label.x + label.width).toBeLessThanOrEqual(100)
    expect(label.y + label.height).toBeLessThanOrEqual(100)
  })
})
