import { describe, expect, it } from 'vitest'
import { createEvidenceGraph, graphRelations, mergeEvidenceGraph } from './evidence-graph'
import { evidenceRefId, type EvidenceObjectRef } from './evidence-state'
import type { EvidenceRelations } from './evidence-relations'

const fact: EvidenceObjectRef = { kind: 'fact', key: 'total', analysisId: 'a', label: '收入' }
const computation: EvidenceObjectRef = { kind: 'computation', key: 'sum', label: '汇总' }
const dataset: EvidenceObjectRef = { kind: 'dataset', key: 'rows', label: '明细' }
const initial: EvidenceRelations = {
  center: fact, nodes: [computation],
  edges: [{ from: computation, to: fact, label: '产出' }], loadedNote: '局部关系',
}

describe('task graph context', () => {
  it('keeps an obstructed self-reference as a loop with separate boundary ports', () => {
    const graph = createEvidenceGraph()
    graph.nodes.set(evidenceRefId(fact), fact)
    graph.nodes.set(evidenceRefId(computation), computation)
    graph.positions.set(evidenceRefId(fact), { x: 120, y: 120, width: 170, height: 76 })
    graph.positions.set(evidenceRefId(computation), { x: 120, y: 210, width: 170, height: 76 })
    graph.width = 400
    graph.height = 320
    mergeEvidenceGraph(graph, { center: fact, nodes: [],
      edges: [{ from: fact, to: fact, label: '输入' }], loadedNote: '局部关系' })
    const path = [...graph.paths.values()][0]
    expect(graph.edges.size).toBe(1)
    expect(path[0]).not.toEqual(path.at(-1))
    // 连线绕回同一节点，而非同一个端口上的往返线；邻居的矩形不可被穿过。
    for (let index = 1; index < path.length; index++) {
      const start = path[index - 1], end = path[index]
      for (let step = 0; step <= 20; step++) {
        const x = start.x + (end.x - start.x) * step / 20
        const y = start.y + (end.y - start.y) * step / 20
        expect(x > 35 && x < 205 && y > 172 && y < 248).toBe(false)
      }
    }
  })
  it('keeps an existing safe route while separating a later parallel relation', () => {
    const graph = createEvidenceGraph()
    for (const [node, x] of [[dataset, 120], [computation, 360], [fact, 600]] as const) {
      graph.nodes.set(evidenceRefId(node), node)
      graph.positions.set(evidenceRefId(node), { x, y: 120, width: 170, height: 76 })
    }
    graph.width = 720
    graph.height = 300
    mergeEvidenceGraph(graph, { center: fact, nodes: [], edges: [{ from: dataset, to: fact, label: '输入' }], loadedNote: '局部关系' })
    const [existingId, existingPath] = [...graph.paths][0]
    mergeEvidenceGraph(graph, { center: fact, nodes: [], edges: [{ from: dataset, to: fact, label: '引用' }], loadedNote: '局部关系' })
    expect(graph.paths.get(existingId)).toEqual(existingPath)
    expect(graph.edges.size).toBe(2)
    const addedPath = [...graph.paths].find(([id]) => id !== existingId)![1]
    expect(addedPath).not.toEqual(existingPath)
    // 跨过中间障碍的长横向通道要分开，节点旁的短接线允许共享。
    const crossingHeights = (path: typeof existingPath) => path.slice(1).flatMap((end, i) => {
      const start = path[i]
      return start.y === end.y && Math.min(start.x, end.x) < 360 && Math.max(start.x, end.x) > 360 ? [start.y] : []
    })
    expect(crossingHeights(existingPath)).toHaveLength(1)
    expect(crossingHeights(addedPath)).toHaveLength(1)
    expect(crossingHeights(addedPath)).not.toEqual(crossingHeights(existingPath))
  })

  it('spreads direct fan-in relations across stable boundary ports', () => {
    const graph = createEvidenceGraph()
    const sources = Array.from({ length: 3 }, (_, i) => ({ ...dataset, key: `direct-${i}` }))
    const target = { ...fact, key: 'direct-target' }
    graph.nodes.set(evidenceRefId(target), target)
    graph.positions.set(evidenceRefId(target), { x: 600, y: 240, width: 170, height: 76 })
    for (const [i, source] of sources.entries()) {
      graph.nodes.set(evidenceRefId(source), source)
      graph.positions.set(evidenceRefId(source), { x: 120, y: 120 + i * 120, width: 170, height: 76 })
    }
    graph.width = 720
    graph.height = 600
    mergeEvidenceGraph(graph, {
      center: target,
      nodes: sources,
      edges: sources.map(from => ({ from, to: target, label: '输入' })),
      loadedNote: '局部关系',
    })
    const paths = sources.map(source => graph.paths.get(JSON.stringify([
      evidenceRefId(source), evidenceRefId(target), '输入',
    ]))!)
    expect(new Set(paths.map(path => `${path[0].x},${path[0].y}`)).size).toBe(3)
    expect(new Set(paths.map(path => `${path.at(-1)!.x},${path.at(-1)!.y}`)).size).toBe(3)
  })
  it.each(['vertical', 'horizontal', 'horizontal-tight'] as const)('uses safe boundary ports for an obstructed %s edge', direction => {
    const graph = createEvidenceGraph()
    const vertical = direction === 'vertical'
    const tight = direction === 'horizontal-tight'
    const positions = [
      { x: 120, y: 120, width: 170, height: 76 },
      { x: vertical ? 120 : tight ? 480 : 600, y: vertical ? 480 : 120, width: 170, height: 76 },
      { x: vertical ? 120 : tight ? 300 : 360, y: vertical ? 300 : 120, width: 170, height: 76 },
    ]
    for (const [i, node] of [dataset, fact, computation].entries()) {
      graph.nodes.set(evidenceRefId(node), node)
      graph.positions.set(evidenceRefId(node), positions[i])
    }
    graph.width = 720
    graph.height = 600
    mergeEvidenceGraph(graph, { center: fact, nodes: [], edges: [{ from: dataset, to: fact, label: '输入' }], loadedNote: '局部关系' })
    expect([...graph.positions.values()]).toEqual(positions)
    const path = [...graph.paths.values()][0]
    expect(path[0]).toEqual(vertical || tight ? { x: 120, y: 158 } : { x: 205, y: 120 })
    expect(path.at(-1)).toEqual(vertical ? { x: 120, y: 442 } : tight ? { x: 480, y: 158 } : { x: 515, y: 120 })
    for (let i = 1; i < path.length; i++) {
      expect(path[i].x === path[i - 1].x || path[i].y === path[i - 1].y).toBe(true)
      const obstacle = positions[2]
      const midpoint = { x: (path[i].x + path[i - 1].x) / 2, y: (path[i].y + path[i - 1].y) / 2 }
      expect(Math.abs(midpoint.x - obstacle.x) < 85 && Math.abs(midpoint.y - obstacle.y) < 38).toBe(false)
    }
  })
  it('packs an independent batch without inventing business edges or moving earlier nodes', () => {
    const graph = createEvidenceGraph()
    mergeEvidenceGraph(graph, initial)
    const previous = [...graph.positions]
    const previousHeight = graph.height
    const leaves = Array.from({ length: 12 }, (_, i) => ({ ...dataset, key: `leaf-${i}` }))
    mergeEvidenceGraph(graph, {
      center: fact, nodes: leaves, loadedNote: '局部关系',
      edges: leaves.map(from => ({ from, to: fact, label: '输入' as const })),
    })
    for (const [id, position] of previous) expect(graph.positions.get(id)).toEqual(position)
    const positions = leaves.map(node => graph.positions.get(evidenceRefId(node))!)
    expect(new Set(positions.map(node => node.x)).size).toBeGreaterThan(1)
    expect(new Set(positions.map(node => node.y)).size).toBe(4)
    expect(graph.height - previousHeight).toBeLessThan(12 * 104)
    expect(graph.edges.size).toBe(13)
    expect(graph.paths.size).toBe(13)
    expect([...graph.paths.keys()].some(key => key.startsWith('layout:'))).toBe(false)
    for (const [i, node] of positions.entries()) for (const other of positions.slice(i + 1)) {
      expect(Math.abs(node.x - other.x) < 170 && Math.abs(node.y - other.y) < 76).toBe(false)
    }
  })

  it('places a large independent later batch beside the loaded graph', () => {
    const graph = createEvidenceGraph()
    mergeEvidenceGraph(graph, initial)
    graph.height = 1500
    const previous = [...graph.positions.entries()]
    const previousWidth = graph.width
    const leaves = Array.from({ length: 12 }, (_, i) => ({ ...dataset, key: `side-leaf-${i}` }))
    mergeEvidenceGraph(graph, {
      center: fact, nodes: leaves, loadedNote: '局部关系',
      edges: leaves.map(from => ({ from, to: fact, label: '输入' as const })),
    })
    for (const [id, position] of previous) expect(graph.positions.get(id)).toEqual(position)
    expect(Math.min(...leaves.map(node => graph.positions.get(evidenceRefId(node))!.x))).toBeGreaterThan(previousWidth)
    expect(graph.width).toBeGreaterThan(previousWidth)
    expect(graph.height).toBe(1500)
  })
  it('keeps high-fanout ports on the node boundary while routing around an obstacle', () => {
    const graph = createEvidenceGraph()
    const sources = Array.from({ length: 24 }, (_, i) => ({ ...dataset, key: `source-${i}` }))
    const sourcePosition = { x: 120, y: 1100, width: 170, height: 76 }
    const obstacle = { x: 360, y: 1075, width: 170, height: 600 }
    graph.positions.set(evidenceRefId(fact), sourcePosition)
    graph.positions.set(evidenceRefId(computation), obstacle)
    graph.nodes.set(evidenceRefId(fact), fact)
    graph.nodes.set(evidenceRefId(computation), computation)
    for (const [i, target] of sources.entries()) {
      graph.nodes.set(evidenceRefId(target), target)
      graph.positions.set(evidenceRefId(target), { x: 600, y: 500 + i * 100, width: 170, height: 76 })
    }
    graph.width = 720
    graph.height = 3000
    mergeEvidenceGraph(graph, {
      center: fact, nodes: sources, loadedNote: '局部关系',
      edges: sources.map(to => ({ from: fact, to, label: '输入' })),
    })
    expect(graph.paths.size).toBe(sources.length)
    const ports = [...graph.paths.values()].map(path => `${path[0].x},${path[0].y}`)
    expect(new Set(ports).size).toBe(sources.length)
    const rightStarts = [...graph.paths.values()].filter(path => path[0].x === sourcePosition.x + sourcePosition.width / 2)
    expect(new Set(rightStarts.map(path => path[1].x)).size).toBeGreaterThanOrEqual(3)
    for (const path of graph.paths.values()) {
      const start = path[0]
      const onVerticalSide = Math.abs(start.x - sourcePosition.x) === sourcePosition.width / 2 &&
        Math.abs(start.y - sourcePosition.y) <= sourcePosition.height / 2 - 8
      const onHorizontalSide = Math.abs(start.y - sourcePosition.y) === sourcePosition.height / 2 &&
        Math.abs(start.x - sourcePosition.x) <= sourcePosition.width / 2 - 8
      expect(onVerticalSide || onHorizontalSide).toBe(true)
      for (let i = 1; i < path.length; i++) {
        const a = path[i - 1]
        const b = path[i]
        const middle = { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 }
        expect(Math.abs(middle.x - obstacle.x) < obstacle.width / 2 &&
          Math.abs(middle.y - obstacle.y) < obstacle.height / 2).toBe(false)
      }
    }
  })
  it('routes later-batch edges around existing nodes without moving them', () => {
    const graph = createEvidenceGraph()
    mergeEvidenceGraph(graph, initial)
    mergeEvidenceGraph(graph, {
      center: computation, nodes: [dataset], loadedNote: '局部关系',
      edges: [{ from: dataset, to: computation, label: '输入' }],
    })
    const previous = [...graph.positions.entries()]
    const source = { ...dataset, key: 'more-rows' }
    mergeEvidenceGraph(graph, {
      center: fact, nodes: [source], loadedNote: '局部关系',
      edges: [{ from: source, to: fact, label: '输入' }],
    })
    for (const [id, position] of previous) expect(graph.positions.get(id)).toEqual(position)
    for (const [id, edge] of graph.edges) {
      const points = graph.paths.get(id)!
      const obstacles = [...graph.positions.entries()].filter(([key]) =>
        key !== evidenceRefId(edge.from) && key !== evidenceRefId(edge.to))
      for (let i = 1; i < points.length; i++) {
        const start = points[i - 1]
        const end = points[i]
        const steps = Math.ceil(Math.hypot(end.x - start.x, end.y - start.y) / 4)
        for (let step = 0; step <= steps; step++) {
          const x = start.x + (end.x - start.x) * step / steps
          const y = start.y + (end.y - start.y) * step / steps
          for (const [, node] of obstacles) {
            expect(Math.abs(x - node.x) < node.width / 2 && Math.abs(y - node.y) < node.height / 2).toBe(false)
          }
        }
      }
    }
  })

  it('retains loaded nodes and their positions while appending a new branch', () => {
    const graph = createEvidenceGraph()
    mergeEvidenceGraph(graph, initial)
    const positions = [...graph.positions.entries()]
    const height = graph.height
    mergeEvidenceGraph(graph, {
      center: computation, nodes: [dataset, fact],
      edges: [{ from: dataset, to: computation, label: '输入' }, ...initial.edges], loadedNote: '局部关系',
    })
    for (const [id, position] of positions) expect(graph.positions.get(id)).toEqual(position)
    expect(graph.positions.get(evidenceRefId(dataset))!.y - 38).toBeGreaterThan(height)
    const loaded = graphRelations(graph, dataset)
    expect(loaded.nodes).toHaveLength(2)
    expect(loaded.edges).toHaveLength(2)
    expect(loaded.loadedNote).toContain('已加载 3 个节点 · 局部关系')
    mergeEvidenceGraph(graph, initial)
    expect(graph.nodes.size).toBe(3)
    expect(graph.edges.size).toBe(2)
    for (const path of graph.paths.values()) {
      for (const point of path) {
        expect(Number.isFinite(point.x) && Number.isFinite(point.y)).toBe(true)
        expect(point.x).toBeGreaterThanOrEqual(0)
        expect(point.y).toBeGreaterThanOrEqual(0)
      }
    }
  })

  it('merges shared sources while keeping separate edge types, cycles and tasks', () => {
    const graph = createEvidenceGraph()
    const second = { ...fact, key: 'other', label: '另一个产出' }
    mergeEvidenceGraph(graph, initial)
    mergeEvidenceGraph(graph, {
      center: second, nodes: [computation, fact], loadedNote: '局部关系',
      edges: [
        { from: computation, to: second, label: '产出' },
        { from: fact, to: computation, label: '输入' },
        { from: fact, to: fact, label: '输入' },
        { from: computation, to: fact, label: '引用' },
      ],
    })
    expect(graph.nodes.size).toBe(3)
    expect(graph.edges.size).toBe(5)
    expect(graph.paths.size).toBe(5)
    expect(createEvidenceGraph().nodes.size).toBe(0)
    for (const path of graph.paths.values()) for (const point of path) expect(Number.isFinite(point.x + point.y)).toBe(true)
  })

  it('does not create nodes for unknown edge endpoints', () => {
    const graph = createEvidenceGraph()
    mergeEvidenceGraph(graph, { ...initial, nodes: [], edges: initial.edges })
    expect(graph.nodes.size).toBe(1)
    expect(graph.edges.size).toBe(0)
  })
})
