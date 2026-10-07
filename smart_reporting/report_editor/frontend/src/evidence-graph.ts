import { graphlib, layout } from '@dagrejs/dagre'
import PF from 'pathfinding'
import { evidenceRefId, type EvidenceObjectRef } from './evidence-state'
import type { EvidenceRelationEdge, EvidenceRelations } from './evidence-relations'

interface Point { x: number; y: number }
interface NodePosition extends Point { width: number; height: number }

/** 每个任务的运行时图；只累计接口已返回的关系，不持久化权限相关元数据。 */
export interface EvidenceGraph {
  branches: Map<string, { status: 'loading' | 'loaded' | 'error'; message?: string }>
  nodes: Map<string, EvidenceObjectRef>
  edges: Map<string, EvidenceRelationEdge>
  positions: Map<string, NodePosition>
  paths: Map<string, Point[]>
  width: number
  height: number
}

export function createEvidenceGraph(): EvidenceGraph {
  return { branches: new Map(), nodes: new Map(), edges: new Map(), positions: new Map(), paths: new Map(), width: 320, height: 250 }
}

function edgeId(edge: EvidenceRelationEdge): string {
  return JSON.stringify([evidenceRefId(edge.from), evidenceRefId(edge.to), edge.label])
}

function intersectsNode(start: Point, end: Point, node: NodePosition): boolean {
  let enter = 0
  let exit = 1
  for (const axis of ['x', 'y'] as const) {
    const half = (axis === 'x' ? node.width : node.height) / 2 - 0.5
    const delta = end[axis] - start[axis]
    const low = node[axis] - half
    const high = node[axis] + half
    if (!delta) {
      if (start[axis] < low || start[axis] > high) return false
    } else {
      const first = (low - start[axis]) / delta
      const last = (high - start[axis]) / delta
      enter = Math.max(enter, Math.min(first, last))
      exit = Math.min(exit, Math.max(first, last))
    }
  }
  return enter <= exit
}

/** 只修复被遮挡的边；现成 A* 负责避障，节点与未受影响的连线不重排。 */
function routeObstructedEdges(graph: EvidenceGraph): void {
  const obstructed = [...graph.edges].filter(([id, edge]) => {
    const points = graph.paths.get(id)!
    return [...graph.positions].some(([key, node]) =>
      key !== evidenceRefId(edge.from) && key !== evidenceRefId(edge.to) &&
      points.some((point, i) => i > 0 && intersectsNode(points[i - 1], point, node)))
  })
  if (!obstructed.length) return
  const step = 12
  const grid = new PF.Grid(Math.ceil((graph.width + 48) / step) + 1, Math.ceil((graph.height + 48) / step) + 1)
  for (const node of graph.positions.values()) {
    for (let x = Math.ceil((node.x - node.width / 2 - 6) / step); x <= Math.floor((node.x + node.width / 2 + 6) / step); x++) {
      for (let y = Math.ceil((node.y - node.height / 2 - 6) / step); y <= Math.floor((node.y + node.height / 2 + 6) / step); y++) {
        grid.setWalkableAt(x, y, false)
      }
    }
  }
  const finder = new PF.AStarFinder({ allowDiagonal: false })
  const channels = grid.clone()
  // 增量路由也避让此前已加载的安全通道，避免新批次重新占用旧边。
  const reroutedIds = new Set(obstructed.map(([id]) => id))
  for (const [id, points] of graph.paths) {
    if (reroutedIds.has(id)) continue
    const route = PF.Util.expandPath(points.map(point => [Math.round(point.x / step), Math.round(point.y / step)]))
    for (const [x, y] of route.slice(2, -2)) {
      if (channels.isInside(x, y)) channels.setWalkableAt(x, y, false)
    }
  }
  const incident = new Map<string, string[]>()
  for (const [id, edge] of obstructed) {
    for (const endpoint of [evidenceRefId(edge.from), evidenceRefId(edge.to)]) {
      const ids = incident.get(endpoint) ?? []
      ids.push(id)
      incident.set(endpoint, ids)
    }
  }
  for (const ids of incident.values()) ids.sort()
  for (const [id, edge] of obstructed) {
    const from = graph.positions.get(evidenceRefId(edge.from))!
    const to = graph.positions.get(evidenceRefId(edge.to))!
    const port = (node: NodePosition, other: NodePosition, nodeId: string, avoid?: Point) => {
      const directions = [{ x: 1, y: 0 }, { x: -1, y: 0 }, { x: 0, y: 1 }, { x: 0, y: -1 }]
      const score = (direction: Point) => direction.x * (other.x - node.x) / node.width + direction.y * (other.y - node.y) / node.height
      directions.sort((a, b) => score(b) - score(a))
      const ids = incident.get(nodeId) ?? [id]
      const slot = ids.indexOf(id)
      for (const direction of directions) {
        const halfSide = (direction.x ? node.height : node.width) / 2
        const spacing = ids.length > 1 ? Math.min(8, (halfSide * 2 - 16) / (ids.length - 1)) : 0
        const offset = (slot - (ids.length - 1) / 2) * spacing
        const anchor = {
          x: node.x + direction.x * node.width / 2 + (direction.y ? offset : 0),
          y: node.y + direction.y * node.height / 2 + (direction.x ? offset : 0),
        }
        // 自引用的两端须使用不同边界端口，避免避障后变成同路往返。
        if (avoid && anchor.x === avoid.x && anchor.y === avoid.y) continue
        // 高扇出端口沿外侧错开起始通道；仍由节点/引线避障检查决定是否可用。
        const clearance = 8 + (ids.length > 1 ? slot % 3 : 0) * step
        const x = direction.x ? (direction.x > 0 ? Math.ceil : Math.floor)((anchor.x + direction.x * clearance) / step) : Math.round(anchor.x / step)
        const y = direction.y ? (direction.y > 0 ? Math.ceil : Math.floor)((anchor.y + direction.y * clearance) / step) : Math.round(anchor.y / step)
        if (!grid.isInside(x, y) || !grid.isWalkableAt(x, y)) continue
        const lead = [anchor, direction.x ? { x: x * step, y: anchor.y } : { x: anchor.x, y: y * step }, { x: x * step, y: y * step }]
        if ([...graph.positions.values()].some(obstacle => obstacle !== node && lead.some((point, i) => i > 0 && intersectsNode(lead[i - 1], point, obstacle)))) continue
        return { x, y, lead }
      }
    }
    const start = port(from, to, evidenceRefId(edge.from))
    const end = port(to, from, evidenceRefId(edge.to), from === to ? start?.lead[0] : undefined)
    if (!start || !end) continue
    const { x: startX, y: startY } = start
    const { x: endX, y: endY } = end
    const preferred = channels.clone()
    // 节点端口可共享，中间路段优先分开；无路时仍保留原避障能力。
    preferred.setWalkableAt(startX, startY, grid.isWalkableAt(startX, startY))
    preferred.setWalkableAt(endX, endY, grid.isWalkableAt(endX, endY))
    let route = finder.findPath(startX, startY, endX, endY, preferred)
    if (!route.length) route = finder.findPath(startX, startY, endX, endY, grid.clone())
    if (!route.length) continue
    for (const [x, y] of route.slice(2, -2)) channels.setWalkableAt(x, y, false)
    const points = [
      ...start.lead.slice(0, -1),
      ...PF.Util.compressPath(route).map(([x, y]) => ({ x: x * step, y: y * step })),
      ...end.lead.slice(0, -1).reverse(),
    ]
    graph.paths.set(id, points)
    for (const point of points) {
      graph.width = Math.max(graph.width, point.x + 24)
      graph.height = Math.max(graph.height, point.y + 24)
    }
  }
}

/** 在节点边界上为同一端点的直接关系分配稳定端口，减少共享输入汇聚时的视觉重叠。 */
function directEdgePort(
  node: NodePosition,
  other: NodePosition,
  slot: number,
  count: number,
): Point {
  const directions = [{ x: 1, y: 0 }, { x: -1, y: 0 }, { x: 0, y: 1 }, { x: 0, y: -1 }]
  const score = (direction: Point) => direction.x * (other.x - node.x) / node.width +
    direction.y * (other.y - node.y) / node.height
  directions.sort((a, b) => score(b) - score(a))
  const direction = directions[0]
  const halfSide = (direction.x ? node.height : node.width) / 2
  const spacing = count > 1 ? Math.min(8, Math.max(0, (halfSide * 2 - 16) / (count - 1))) : 0
  const offset = (slot - (count - 1) / 2) * spacing
  return {
    x: node.x + direction.x * node.width / 2 + (direction.y ? offset : 0),
    y: node.y + direction.y * node.height / 2 + (direction.x ? offset : 0),
  }
}

/** 已有节点不参与重排；Dagre 只布局新增批次，追加到已加载画面的下方。 */
export function mergeEvidenceGraph(graph: EvidenceGraph, relations: EvidenceRelations): void {
  const added = new Set<string>()
  for (const node of [relations.center, ...relations.nodes]) {
    const id = evidenceRefId(node)
    if (!graph.nodes.has(id)) added.add(id)
    graph.nodes.set(id, node)
  }
  for (const edge of relations.edges) {
    if (graph.nodes.has(evidenceRefId(edge.from)) && graph.nodes.has(evidenceRefId(edge.to))) {
      graph.edges.set(edgeId(edge), edge)
    }
  }
  const local = new graphlib.Graph({ multigraph: true })
  local.setGraph({ rankdir: 'LR', nodesep: 28, ranksep: 64, marginx: 24, marginy: 24 })
  local.setDefaultEdgeLabel(() => ({}))
  for (const id of added) local.setNode(id, { width: 170, height: 76 })
  for (const [id, edge] of graph.edges) {
    const from = evidenceRefId(edge.from)
    const to = evidenceRefId(edge.to)
    if (added.has(from) && added.has(to)) local.setEdge(from, to, {}, id)
  }
  if (added.size) {
    // 无内部关系的批次用布局专用链约束压成近方形；不进入业务边或绘制路径。
    const hasInternalEdges = local.edgeCount() > 0
    if (!hasInternalEdges) {
      const ids = [...added]
      const rows = Math.ceil(Math.sqrt(ids.length))
      for (let i = rows; i < ids.length; i++) local.setEdge(ids[i - rows], ids[i], {}, `layout:${i}`)
    }
    layout(local)
    const batchWidth = local.graph().width ?? 0
    const batchHeight = local.graph().height ?? 0
    const rightRatio = (graph.width + 28 + batchWidth) / Math.max(graph.height, batchHeight)
    const belowRatio = Math.max(graph.width, batchWidth) / (graph.height + 28 + batchHeight)
    const sideBySide = graph.positions.size > 0 && added.size >= 4 && !hasInternalEdges &&
      Math.abs(Math.log(rightRatio)) < Math.abs(Math.log(belowRatio))
    const offset = graph.positions.size && !sideBySide ? graph.height + 28 : 0
    const xOffset = sideBySide ? graph.width + 28 : 0
    for (const id of added) {
      const position = local.node(id) as NodePosition
      graph.positions.set(id, { ...position, x: position.x + xOffset, y: position.y + offset })
    }
    graph.width = Math.max(graph.width, xOffset + (local.graph().width ?? 0))
    graph.height = Math.max(graph.height, offset + (local.graph().height ?? 0))
    for (const edge of local.edges()) {
      if (!graph.edges.has(edge.name!)) continue
      const points = local.edge(edge).points as Point[]
      graph.paths.set(edge.name!, points.map(point => ({ x: point.x, y: point.y + offset })))
    }
  }
  // 跨批次的边连接已固定的矩形边界；节点位置与业务边方向不变。
  const incident = new Map<string, string[]>()
  for (const [id, edge] of graph.edges) {
    for (const endpoint of [evidenceRefId(edge.from), evidenceRefId(edge.to)]) {
      const ids = incident.get(endpoint) ?? []
      ids.push(id)
      incident.set(endpoint, ids)
    }
  }
  for (const ids of incident.values()) ids.sort()
  for (const [id, edge] of graph.edges) {
    if (graph.paths.has(id)) continue
    const from = graph.positions.get(evidenceRefId(edge.from))!
    const to = graph.positions.get(evidenceRefId(edge.to))!
    if (evidenceRefId(edge.from) === evidenceRefId(edge.to)) {
      graph.paths.set(id, [
        { x: from.x + from.width / 2, y: from.y },
        { x: from.x + from.width / 2 + 20, y: from.y },
        { x: from.x + from.width / 2 + 20, y: from.y + from.height / 2 + 20 },
        { x: from.x, y: from.y + from.height / 2 + 20 },
        { x: from.x, y: from.y + from.height / 2 },
      ])
    } else {
      const fromIds = incident.get(evidenceRefId(edge.from)) ?? [id]
      const toIds = incident.get(evidenceRefId(edge.to)) ?? [id]
      const start = directEdgePort(from, to,
        fromIds.indexOf(id), fromIds.length)
      const end = directEdgePort(to, from,
        toIds.indexOf(id), toIds.length)
      graph.paths.set(id, [
        start,
        end,
      ])
    }
  }
  routeObstructedEdges(graph)
}

export function graphRelations(graph: EvidenceGraph, center: EvidenceObjectRef): EvidenceRelations {
  return {
    center,
    nodes: [...graph.nodes.values()].filter(node => evidenceRefId(node) !== evidenceRefId(center)),
    edges: [...graph.edges.values()],
    loadedNote: `已加载 ${graph.nodes.size} 个节点 · 局部关系（当前任务已加载）`,
  }
}
