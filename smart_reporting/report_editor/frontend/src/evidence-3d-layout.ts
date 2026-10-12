import type { EvidenceObjectKind } from './evidence-state'

/**
 * 3D 关系图的分层流水布局：溯源阶段从左到右排列（输入在左、产出在右），
 * 每个阶段的节点自上而下排成一列；一列放不下时向右后方斜着展开新列（每列后退一段纵深），
 * 卡片互不遮挡，同时保留空间层次。坐标完全由登记关系决定，同一关系图每次打开位置一致。
 */
export interface StageNode { id: string; kind: EvidenceObjectKind; label: string }
export interface StageLink { source: string; target: string }
export interface Stage {
  index: number
  /** 阶段首列的 x，标题放在阶段范围中央上方。 */
  x: number
  centerX: number
  /** 阶段内出现的对象类型，按溯源顺序。 */
  kinds: EvidenceObjectKind[]
  count: number
  /** 阶段内节点身份。 */
  members: string[]
  top: number
  bottom: number
  front: number
  back: number
}
export interface StageLayout { positions: Map<string, { x: number; y: number; z: number }>; stages: Stage[] }

/** 溯源顺序：快照 → 计算 → 事实 → 图表/正文引用。存在环时按此顺序分层。 */
const KIND_ORDER: Record<EvidenceObjectKind, number> = { dataset: 0, computation: 1, fact: 2, chart: 3, subject: 3 }
/** 相邻阶段之间的水平间距（不含阶段自身宽度）。 */
export const STAGE_GAP = 230
export const ROW_GAP = 50
/** 同阶段相邻列：向右展开并向后退。 */
export const COLUMN_GAP = 168
export const COLUMN_DEPTH = 40
/** 每列最多节点数；超出后展开新列，保持列高可读。 */
export const MAX_ROWS = 10

function ranks(nodes: StageNode[], links: StageLink[]): Map<string, number> {
  const ids = new Set(nodes.map(node => node.id))
  const edges = links.filter(link => ids.has(link.source) && ids.has(link.target) && link.source !== link.target)
  const incoming = new Map(nodes.map(node => [node.id, 0]))
  for (const edge of edges) incoming.set(edge.target, (incoming.get(edge.target) ?? 0) + 1)
  const rank = new Map(nodes.map(node => [node.id, 0]))
  const queue = nodes.filter(node => incoming.get(node.id) === 0).map(node => node.id)
  let visited = 0
  while (queue.length) {
    const id = queue.shift()!
    visited++
    for (const edge of edges.filter(item => item.source === id)) {
      rank.set(edge.target, Math.max(rank.get(edge.target)!, rank.get(id)! + 1))
      incoming.set(edge.target, incoming.get(edge.target)! - 1)
      if (incoming.get(edge.target) === 0) queue.push(edge.target)
    }
  }
  if (visited === nodes.length) return rank
  // 反馈关系无法拓扑排序：按对象类型的溯源顺序分层。
  return new Map(nodes.map(node => [node.id, KIND_ORDER[node.kind]]))
}

export function stageLayout(nodes: StageNode[], links: StageLink[]): StageLayout {
  const rank = ranks(nodes, links)
  // 压缩空层，阶段编号连续。
  const levels = [...new Set(rank.values())].sort((a, b) => a - b)
  const positions = new Map<string, { x: number; y: number; z: number }>()
  const stages: Stage[] = []
  let cursor = 0
  for (let index = 0; index < levels.length; index++) {
    const members = nodes.filter(node => rank.get(node.id) === levels[index])
      .sort((a, b) => KIND_ORDER[a.kind] - KIND_ORDER[b.kind] || a.label.localeCompare(b.label, 'zh-CN') || a.id.localeCompare(b.id))
    const columns = Math.ceil(members.length / MAX_ROWS)
    // 各列行数尽量均衡，避免最后一列只剩一两张卡片。
    const rows = Math.ceil(members.length / columns)
    members.forEach((node, order) => {
      const column = Math.floor(order / rows)
      const row = order % rows
      positions.set(node.id, { x: cursor + column * COLUMN_GAP, y: ((rows - 1) / 2 - row) * ROW_GAP, z: -column * COLUMN_DEPTH })
    })
    const half = ((rows - 1) / 2) * ROW_GAP
    const width = (columns - 1) * COLUMN_GAP
    stages.push({
      index, x: cursor, centerX: cursor + width / 2,
      kinds: [...new Set(members.map(node => node.kind))].sort((a, b) => KIND_ORDER[a] - KIND_ORDER[b]),
      count: members.length,
      members: members.map(node => node.id),
      top: half + ROW_GAP / 2,
      bottom: -half - ROW_GAP / 2,
      front: 0,
      back: -(columns - 1) * COLUMN_DEPTH,
    })
    cursor += width + STAGE_GAP
  }
  // 整体水平居中。
  const shift = (cursor - STAGE_GAP) / 2
  for (const position of positions.values()) position.x -= shift
  for (const stage of stages) {
    stage.x -= shift
    stage.centerX -= shift
  }
  return { positions, stages }
}

/**
 * 展开分支时的增量布局：已布局节点保持原坐标（用户已熟悉的位置不跳动），新节点就近放在
 * 与之相连的已有节点旁——作为输入放左侧、作为产出放右侧，竖直方向找最近的空位。
 * 阶段标题按最终坐标重新定位。没有可保留坐标时等同 stageLayout。
 */
export function extendStageLayout(previous: Map<string, { x: number; y: number; z: number }> | undefined,
  nodes: StageNode[], links: StageLink[]): StageLayout {
  const plan = stageLayout(nodes, links)
  if (!previous || !nodes.some(node => previous.has(node.id))) return plan
  const positions = new Map<string, { x: number; y: number; z: number }>()
  for (const node of nodes) {
    const kept = previous.get(node.id)
    if (kept) positions.set(node.id, { ...kept })
  }
  const occupied = (point: { x: number; y: number; z: number }) => [...positions.values()].some(other =>
    Math.abs(other.x - point.x) < COLUMN_GAP * 0.6 && Math.abs(other.y - point.y) < ROW_GAP * 0.8 && Math.abs(other.z - point.z) < COLUMN_DEPTH * 0.5)
  for (const node of nodes) {
    if (positions.has(node.id)) continue
    const output = links.find(link => link.source === node.id && positions.has(link.target))
    const input = links.find(link => link.target === node.id && positions.has(link.source))
    const anchor = output ? positions.get(output.target)! : input ? positions.get(input.source)! : undefined
    let point = anchor
      ? { x: anchor.x + (output ? -1 : 1) * STAGE_GAP, y: anchor.y, z: anchor.z }
      : { ...plan.positions.get(node.id)! }
    for (let step = 1; occupied(point) && step < 200; step++) {
      const offset = Math.ceil(step / 2) * ROW_GAP * (step % 2 ? 1 : -1)
      point = { ...point, y: (anchor?.y ?? plan.positions.get(node.id)!.y) + offset }
    }
    positions.set(node.id, point)
  }
  const stages = plan.stages.map(stage => {
    const points = stage.members.map(id => positions.get(id)!)
    const xs = points.map(point => point.x)
    return { ...stage, x: Math.min(...xs), centerX: (Math.min(...xs) + Math.max(...xs)) / 2,
      top: Math.max(...points.map(point => point.y)) + ROW_GAP / 2, bottom: Math.min(...points.map(point => point.y)) - ROW_GAP / 2,
      front: Math.max(...points.map(point => point.z)), back: Math.min(...points.map(point => point.z)) }
  })
  return { positions, stages }
}
