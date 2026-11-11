import { expect, it } from 'vitest'
import { AddConditionalRuleMutation, DeleteConditionalRuleMutation } from '@univerjs/sheets-conditional-formatting'
const implementation = './workbook-cf-structure-plan'
const ranges = [{ startRow: 0, endRow: 3, startColumn: 1, endColumn: 1 }]
const stop = { cfId: 'high', ranges, stopIfTrue: true, rule: { type: 'highlightCell', subType: 'formula', value: '=TRUE', style: { bg: { rgb: '#FF0000' } } } }
const split = { cfId: 'parent', ranges, stopIfTrue: false, rule: { type: 'highlightCell', subType: 'formula', value: '=Source!A1>0', style: { bg: { rgb: '#00FF00' } } } }
const spec = { axis: 'row' as const, start: 1, delta: 1 }

it('plans cross-sheet partitions in their parent priority slot and restores exact original ids and undo rule bodies', async () => {
  const { planNativeConditionalFormattingStructure } = await import(/* @vite-ignore */ implementation)
  let nextId = 0
  const original = [stop, split], frozen = structuredClone(original)
  const plan = planNativeConditionalFormattingStructure(original, 'u', 'other', 'Other', 'Source', spec, () => `new-${++nextId}`)
  expect(original).toEqual(frozen)
  // Simulate the actual official Add mutation unshift semantics after deletes.
  const apply = (rules: any[], mutations: any[]) => {
    for (const mutation of mutations) {
      if (mutation.id === DeleteConditionalRuleMutation.id) rules = rules.filter(rule => rule.cfId !== mutation.params.cfId)
      else if (mutation.id === AddConditionalRuleMutation.id) rules.unshift(structuredClone(mutation.params.rule))
      else throw Error('unexpected mutation')
    }
    return rules
  }
  const after = apply(structuredClone(original), plan.redos)
  expect(after[0]).toEqual(stop)
  expect(after.slice(1).map(rule => ({ ranges: rule.ranges, value: rule.rule.value, stopIfTrue: rule.stopIfTrue }))).toEqual([
    { ranges: [{ startRow: 0, endRow: 0, startColumn: 1, endColumn: 1 }], value: '=Source!A1>0', stopIfTrue: false },
    { ranges: [{ startRow: 1, endRow: 3, startColumn: 1, endColumn: 1 }], value: '=Source!A3>0', stopIfTrue: false },
  ])
  expect(after[1].cfId).toBe('parent')
  expect(new Set(after.map(rule => rule.cfId)).size).toBe(3)
  expect(apply(after, plan.undos)).toEqual(original)
})

it('validates the whole source plan before returning any structural followers', async () => {
  const { planNativeConditionalFormattingStructure } = await import(/* @vite-ignore */ implementation)
  const unsupported = { ...split, cfId: 'bad', rule: { type: 'highlightCell', subType: 'timePeriod', style: {} } }
  let allocated = 0
  expect(() => planNativeConditionalFormattingStructure([stop, split, unsupported], 'u', 'other', 'Other', 'Source', spec, () => `new-${++allocated}`)).toThrow()
  expect(allocated).toBe(0)
})

it('retains whole-column relative formula coverage with bounded ordered interval partitions', async () => {
  const { planNativeConditionalFormattingStructure } = await import(/* @vite-ignore */ implementation)
  const whole = { ...split, ranges: [{ startRow: 0, endRow: 1048575, startColumn: 1, endColumn: 1 }] }
  const start = performance.now()
  const plan = planNativeConditionalFormattingStructure([whole], 'u', 'other', 'Other', 'Source', spec, () => 'tail')
  const additions = plan.redos.filter((mutation: any) => mutation.id === AddConditionalRuleMutation.id)
  expect(additions.length).toBeGreaterThanOrEqual(2)
  expect(additions.length).toBeLessThan(10)
  expect(performance.now() - start).toBeLessThan(2000)
  expect(additions.flatMap((mutation: any) => mutation.params.rule.ranges).reduce((sum: number, range: any) => sum + range.endRow - range.startRow + 1, 0)).toBe(1048576)
})

it.each([
  ['down', { axis: 'row', start: 1, delta: 1, band: { start: 1, end: 1 } }, [0, 3, 1, 1], [[0, 0, 1, 1], [2, 4, 1, 1]]],
  ['right', { axis: 'column', start: 1, delta: 1, band: { start: 1, end: 1 } }, [1, 1, 0, 3], [[1, 1, 0, 0], [1, 1, 2, 4]]],
  ['up', { axis: 'row', start: 1, delta: -1, band: { start: 1, end: 1 } }, [0, 3, 1, 1], [[0, 2, 1, 1]]],
  ['left', { axis: 'column', start: 1, delta: -1, band: { start: 1, end: 1 } }, [1, 1, 0, 3], [[1, 1, 0, 2]]],
] as const)('plans %s cell coverage without painting inserted gaps and restores original identity', async (_direction, cellSpec, bounds, expected) => {
  const { planNativeConditionalFormattingStructure } = await import(/* @vite-ignore */ implementation)
  const original = [{ ...stop, cfId: 'own', ranges: [{ startRow: bounds[0], endRow: bounds[1], startColumn: bounds[2], endColumn: bounds[3] }] }]
  const plan = planNativeConditionalFormattingStructure(original, 'u', 's', 'Source', 'Source', cellSpec, () => 'child', { geometry: 'cells' })
  const additions = plan.redos.filter((mutation: any) => mutation.id === AddConditionalRuleMutation.id)
  const actual = additions.flatMap((mutation: any) => mutation.params.rule.ranges).map((range: any) => [range.startRow, range.endRow, range.startColumn, range.endColumn]).sort((a: number[], b: number[]) => a[0]! - b[0]! || a[2]! - b[2]!)
  expect(actual).toEqual(expected)
  expect(additions.at(-1)!.params.rule.cfId).toBe('own')
  expect(plan.undos.filter((mutation: any) => mutation.id === AddConditionalRuleMutation.id).map((mutation: any) => mutation.params.rule)).toEqual(original)
})

it('renames typed expression and threshold formulas through shared semantics while preserving parent ids/order and exact undo', async () => {
  const { planNativeConditionalFormattingRename } = await import(/* @vite-ignore */ implementation)
  const threshold = { cfId: 'threshold', ranges, stopIfTrue: false, rule: { type: 'dataBar', isShowValue: true, config: { min: { type: 'formula', value: '=Source!A1' }, max: { type: 'num', value: 100 }, positiveColor: '#00FF00', nativeColor: '#FF0000', isGradient: true } } }
  const expression = { ...split, rule: { ...split.rule, value: '=IF(source!a1>0,"Source!A1",[remote.xlsx]Source!A1)' } }
  const original = [stop, expression, threshold], frozen = structuredClone(original)
  const plan = planNativeConditionalFormattingRename(original, 'u', 'other', 'Source', "财务 O'Brien")
  const after = plan.redos.filter((mutation: any) => mutation.id === AddConditionalRuleMutation.id).map((mutation: any) => mutation.params.rule).reverse()
  expect(after.map((rule: any) => rule.cfId)).toEqual(original.map(rule => rule.cfId))
  expect(after[0]).toEqual(stop)
  expect(after[1].rule.value).toBe('=IF(\'财务 O\'\'Brien\'!a1>0,"Source!A1",[remote.xlsx]Source!A1)')
  expect(after[2].rule.config.min.value).toBe("='财务 O''Brien'!A1")
  expect(after[2].rule.config.max).toEqual(threshold.rule.config.max)
  expect(plan.undos.filter((mutation: any) => mutation.id === AddConditionalRuleMutation.id).map((mutation: any) => mutation.params.rule).reverse()).toEqual(original)
  expect(original).toEqual(frozen)
})
