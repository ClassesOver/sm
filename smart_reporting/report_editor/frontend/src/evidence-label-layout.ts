import { layoutGreedy } from '@d3fc/d3fc-label-layout/index.js'
import { totalCollisionArea } from '@d3fc/d3fc-label-layout/src/util/collision.js'

export interface LabelRectangle { x: number; y: number; width: number; height: number; fixed?: boolean }
export interface LabelLayoutInput {
  rectangles: LabelRectangle[]
  obstacles: LabelRectangle[]
  icons: LabelRectangle[]
  priorities: number[]
  width: number
  height: number
}

// 主线程小图与后台密集图共用原生 Greedy 策略和同一评分顺序。
export function layoutEvidenceLabels({ rectangles, obstacles, icons, priorities, width, height }: LabelLayoutInput): LabelRectangle[] {
  const strategy = layoutGreedy().bounds({ x: 4, y: 4,
    width: width - 8, height: height - 8 })
  const outward = rectangles.map(rectangle => ({ ...rectangle,
    x: rectangle.x < width / 2 ? rectangle.x - rectangle.width - 18 : rectangle.x + 18,
    y: rectangle.y - rectangle.height / 2 }))
  const perimeter = rectangles.map(rectangle => ({ ...rectangle,
    x: rectangle.x < width / 2 ? 4 : width - rectangle.width - 4,
    y: rectangle.y - rectangle.height / 2 }))
  const seeds = [rectangles, outward, perimeter]
  // 上下边缘起点为密集小图提供额外的成熟 Greedy 候选，保留全部名称。
  seeds.push(rectangles.map(rectangle => ({ ...rectangle,
    x: rectangle.x - rectangle.width / 2,
    y: rectangle.y < height / 2 ? 4 : height - rectangle.height - 4 })))
  // 小屏边界候选可能把优先标签吸到同一侧；补充有限的四向偏移，仍由 Greedy 负责最终避障。
  for (const offset of [24, 48]) {
    for (const [dx, dy] of [[offset, 0], [-offset, 0], [0, offset], [0, -offset]]) {
      seeds.push(rectangles.map(rectangle => ({ ...rectangle, x: rectangle.x + dx, y: rectangle.y + dy })))
    }
  }
  // 密集图投影集中时补充均匀分布起点，仍由原生Greedy移动名称并按原有评分择优。
  const distributedSeedStart = seeds.length
  if (rectangles.length > 15) {
    for (const columns of [6, 7, 8, 9, 10, 11, 12]) {
      for (const reverse of [false, true]) {
        seeds.push(rectangles.map((rectangle, index) => {
          const slot = reverse ? rectangles.length - index - 1 : index
          const rows = Math.ceil(rectangles.length / columns)
          return { ...rectangle, x: 4 + (width - rectangle.width - 8) * (slot % columns) / (columns - 1),
            y: 4 + (height - rectangle.height - 8) * Math.floor(slot / columns) / Math.max(1, rows - 1) }
        }))
      }
    }
  }
  // 28px固定图标区域与布局障碍保持一致；名称与自身图标的正常锚点相交不计遮挡。
  const iconBounds = icons
  // 实际绘制的图标为14px；28px 留白区无零碰撞解时，先保证名称不压住可见图标，再比较留白。
  // 可见图标每边再留 2px：相机阻尼末尾的亚像素差异会让“恰好贴边”的方案在绘制时压住 1px。
  const visibleIconBounds = icons.map(icon => ({ x: icon.x + 5, y: icon.y + 5, width: 18, height: 18 }))
  const iconOverlap = (drawn: Array<{ x: number; y: number; width: number; height: number }>,
    icons: Array<{ x: number; y: number; width: number; height: number }>) =>
    totalCollisionArea([...drawn, ...icons]) - totalCollisionArea(drawn) - totalCollisionArea(icons)
      - drawn.reduce((sum, rectangle, index) => sum + totalCollisionArea([rectangle, icons[index]]), 0)
  let bestNameCollision = Infinity
  let bestVisibleIconCollision = Infinity
  let bestIconCollision = Infinity
  let bestPadding = Infinity
  const minimumPadding = totalCollisionArea(obstacles)
  // 节点、外侧和画布两侧起点均由原生策略避让；复用组件总碰撞计分。
  const passes = [obstacles]
  for (const weightedObstacles of passes) {
    // 密集图加权复查精修最佳布局和网格起点，小图保留原有全部候选。
    for (const seed of weightedObstacles === obstacles || priorities.length <= 15 ? seeds : [rectangles, ...seeds.slice(distributedSeedStart)]) {
      let candidate = seed
      for (let round = 0; round < 16; round++) {
        const mirrorX = round < 12 ? round % 2 === 1 : round % 2 === 0
        const mirrorY = round % 2 === 1
        const mirror = (rectangle: { x: number; y: number; width: number; height: number }) => ({ ...rectangle,
          x: mirrorX ? width - rectangle.x - rectangle.width : rectangle.x,
          y: mirrorY ? height - rectangle.y - rectangle.height : rectangle.y })
        // 28px固定图标区域参与原生评分但不参与移动；只应用名称的位置。
        // 末四轮反向处理同优先级名称，避免单一顺序困在局部重叠中。
        const order = priorities.map((_, index) => index).sort((a, b) =>
          priorities[a] - priorities[b] || (round >= 12 ? b - a : a - b))
        const input = [...order.map(index => candidate[index]), ...weightedObstacles]
        const placed = strategy(input.map(mirror)).slice(0, priorities.length).map(mirror)
        candidate = priorities.map((_, index) => placed[order.indexOf(index)])
        const padding = totalCollisionArea([...candidate, ...obstacles])
        const drawn = candidate.map(rectangle => ({ ...rectangle,
          x: rectangle.x + 3, y: rectangle.y + 3, width: rectangle.width - 6, height: rectangle.height - 6 }))
        const nameCollision = totalCollisionArea(drawn)
        const visibleIconCollision = iconOverlap(drawn, visibleIconBounds)
        const iconCollision = iconOverlap(drawn, iconBounds)
        const better = nameCollision !== bestNameCollision ? nameCollision < bestNameCollision
          : visibleIconCollision !== bestVisibleIconCollision ? visibleIconCollision < bestVisibleIconCollision
            : iconCollision !== bestIconCollision ? iconCollision < bestIconCollision
              : padding < bestPadding
        if (better) {
          rectangles = candidate
          bestNameCollision = nameCollision
          bestVisibleIconCollision = visibleIconCollision
          bestIconCollision = iconCollision
          bestPadding = padding
        }
        // 固定图标之间的碰撞不可改变；其余碰撞全部为零时已达到评分下界。
        if (bestNameCollision === 0 && bestVisibleIconCollision === 0 && bestIconCollision === 0 && bestPadding === minimumPadding) return rectangles
      }
    }
    // 名称已避开彼此但仍遮挡图标时，加重原生策略的图标碰撞代价。
    // 最终仍按原有评分选择，仅在确有残余遮挡时增加一次候选搜索。
    if (passes.length === 1 && bestNameCollision === 0 && bestVisibleIconCollision > 0) {
      passes.push([...obstacles, ...obstacles])
    }
  }
  return rectangles
}
