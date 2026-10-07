import { describe, expect, it } from 'vitest'
import { layoutEvidenceLabels } from './evidence-label-layout'
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

describe('小图名称避障', () => {
  it('15节点手机旋转投影中名称不遮挡图标', () => {
    // 从失败浏览器回放保留的真实投影；包含靠近名称右上角的另一节点。
    const points = [
      [187.36721071920223, 143.45643117843346, 91.28405529953916, 28.959999999999997, 0],
      [201.0663811021273, 219.44951373104183, 114.020162601626, 16.48, 1],
      [204.0570394468993, 211.38563291986748, 77.44260162601627, 16.48, 1],
      [261.52530663498436, 190.12319639831483, 80.79219512195122, 16.48, 1],
      [116.26891986855648, 182.3953102592099, 108.79479674796747, 16.48, 1],
      [153.50026304683567, 182.14578082217855, 114.020162601626, 16.48, 1],
      [181.23878973107674, 142.30368232007035, 108.79479674796747, 16.48, 1],
      [184.78540777572258, 141.8745145196451, 114.020162601626, 16.48, 1],
      [129.73112414274462, 142.483201645538, 114.020162601626, 16.48, 1],
      [107.51427052758535, 124.39255238880608, 114.020162601626, 16.48, 1],
      [250.33810428490526, 108.19275948672106, 114.020162601626, 16.48, 1],
      [233.5558135410784, 106.83930823332106, 114.020162601626, 16.48, 1],
      [169.98949817826582, 90.67202796314663, 114.020162601626, 16.48, 1],
      [135.82163600732173, 86.64561587564128, 114.020162601626, 16.48, 1],
      [197.81230879184145, 60.715551935840075, 108.79479674796747, 16.48, 1],
    ]
    const icons = points.map(([x, y]) => ({ x: Math.round(x) - 14, y: Math.round(y) - 14, width: 28, height: 28 }))
    const rectangles = layoutEvidenceLabels({
      width: 388, height: 291,
      rectangles: points.map(([x, y, width, height]) => ({ x: Math.round(x), y: Math.round(y), width: width + 6, height: height + 6 })),
      priorities: points.map(point => point[4]), icons,
      obstacles: icons.map(icon => ({ ...icon, fixed: true })),
    }).map(rectangle => ({ x: rectangle.x + 3, y: rectangle.y + 3, width: rectangle.width - 6, height: rectangle.height - 6 }))
    const area = (a: typeof rectangles[number], b: typeof rectangles[number]) =>
      Math.max(0, Math.min(a.x + a.width, b.x + b.width) - Math.max(a.x, b.x)) *
      Math.max(0, Math.min(a.y + a.height, b.y + b.height) - Math.max(a.y, b.y))
    rectangles.forEach((label, index) => {
      rectangles.slice(index + 1).forEach(other => expect(area(label, other)).toBeLessThanOrEqual(1))
      points.forEach(([x, y], nodeIndex) => {
        if (nodeIndex !== index) expect(area(label, { x: x - 7, y: y - 7, width: 14, height: 14 })).toBeLessThanOrEqual(1)
      })
    })
  })
})

describe('密集长名称避障', () => {
  it.each(['labels', 'rotation-1', 'rotation-2', 'registered-preview'])('39节点窄屏%s投影保留全部名称且不遮挡名称和图标', async fixture => {
    const { readFileSync } = await import('node:fs')
    const input = JSON.parse(readFileSync(`src/fixtures/evidence-dense-${fixture}.json`, 'utf8'))
    const previous = structuredClone(input)
    const rectangles = layoutEvidenceLabels(input).map(rectangle => ({ ...rectangle,
      x: rectangle.x + 3, y: rectangle.y + 3, width: rectangle.width - 6, height: rectangle.height - 6 }))
    expect(input).toEqual(previous)
    expect(rectangles).toHaveLength(39)
    const area = (a: typeof rectangles[number], b: typeof rectangles[number]) =>
      Math.max(0, Math.min(a.x + a.width, b.x + b.width) - Math.max(a.x, b.x)) *
      Math.max(0, Math.min(a.y + a.height, b.y + b.height) - Math.max(a.y, b.y))
    rectangles.forEach((label, index) => {
      rectangles.slice(index + 1).forEach(other => expect(area(label, other)).toBeLessThanOrEqual(1))
      input.icons.forEach((icon: typeof rectangles[number], nodeIndex: number) => {
        if (nodeIndex !== index) expect(area(label, { x: icon.x + 7, y: icon.y + 7, width: 14, height: 14 })).toBeLessThanOrEqual(1)
      })
    })
  })
})
