import { describe, expect, it } from 'vitest'

import { extendStageLayout, MAX_ROWS, stageLayout, type StageNode } from './evidence-3d-layout'

const node = (id: string, kind: StageNode['kind'], label = id): StageNode => ({ id, kind, label })

describe('stage layout', () => {
  it('lays out the lineage left to right: inputs left of outputs', () => {
    const nodes = [node('s', 'subject'), node('f', 'fact'), node('c', 'computation'), node('d', 'dataset'), node('i', 'fact', '输入')]
    const links = [{ source: 'd', target: 'c' }, { source: 'c', target: 'f' }, { source: 'i', target: 'f' }, { source: 'f', target: 's' }]
    const { positions, stages } = stageLayout(nodes, links)
    for (const link of links) expect(positions.get(link.target)!.x).toBeGreaterThan(positions.get(link.source)!.x)
    expect(stages.map(stage => stage.kinds)).toEqual([['dataset', 'fact'], ['computation'], ['fact'], ['subject']])
    expect(stages.map(stage => stage.count)).toEqual([2, 1, 1, 1])
  })

  it('is deterministic and keeps a stage within the row limit by folding into depth', () => {
    const inputs = Array.from({ length: 20 }, (_, index) => node(`in-${index}`, 'fact'))
    const nodes = [node('root', 'fact'), ...inputs]
    const links = inputs.map(input => ({ source: input.id, target: 'root' }))
    const first = stageLayout(nodes, links)
    const second = stageLayout([...nodes].reverse(), [...links].reverse())
    for (const [id, position] of first.positions) expect(second.positions.get(id)).toEqual(position)
    const stage = first.stages[0]
    const ys = new Set(inputs.map(input => first.positions.get(input.id)!.y.toFixed(1)))
    const zs = new Set(inputs.map(input => first.positions.get(input.id)!.z))
    expect(zs.size).toBe(Math.ceil(20 / MAX_ROWS))
    expect(ys.size).toBeLessThanOrEqual(MAX_ROWS * 2)
    expect(stage.front).toBeGreaterThan(stage.back)
    // 没有两个节点重合。
    const keys = new Set([...first.positions.values()].map(p => `${p.x}|${p.y}|${p.z}`))
    expect(keys.size).toBe(nodes.length)
  })

  it('falls back to kind order when feedback relations form a cycle', () => {
    const nodes = [node('a', 'fact'), node('b', 'computation'), node('d', 'dataset')]
    const { positions } = stageLayout(nodes, [{ source: 'a', target: 'b' }, { source: 'b', target: 'a' }])
    expect(positions.get('d')!.x).toBeLessThan(positions.get('b')!.x)
    expect(positions.get('b')!.x).toBeLessThan(positions.get('a')!.x)
  })
})

describe('incremental stage layout', () => {
  it('keeps existing positions and places a new input beside its output without overlap', () => {
    const nodes = [node('c', 'computation'), node('f', 'fact'), node('s', 'subject')]
    const links = [{ source: 'c', target: 'f' }, { source: 'f', target: 's' }]
    const before = stageLayout(nodes, links).positions
    const grown = extendStageLayout(before, [...nodes, node('i1', 'fact'), node('i2', 'fact')],
      [...links, { source: 'i1', target: 'f' }, { source: 'i2', target: 'f' }])
    for (const [id, position] of before) expect(grown.positions.get(id)).toEqual(position)
    const f = grown.positions.get('f')!
    for (const id of ['i1', 'i2']) expect(grown.positions.get(id)!.x).toBeLessThan(f.x)
    const keys = new Set([...grown.positions.values()].map(p => `${Math.round(p.x)}|${Math.round(p.y)}|${Math.round(p.z)}`))
    expect(keys.size).toBe(5)
    expect(grown.stages.flatMap(stage => stage.members).sort()).toEqual(['c', 'f', 'i1', 'i2', 's'])
  })

  it('falls back to a fresh layout without remembered positions', () => {
    const nodes = [node('a', 'dataset'), node('b', 'fact')]
    const links = [{ source: 'a', target: 'b' }]
    expect(extendStageLayout(undefined, nodes, links)).toEqual(stageLayout(nodes, links))
  })
})
