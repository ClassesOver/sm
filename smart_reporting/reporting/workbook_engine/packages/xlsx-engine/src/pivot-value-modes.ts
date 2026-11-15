/// Aggregation subset of fixed GenOffice domain/pivot-value-modes.ts.
/// Shared by layout, state validation and OOXML serialization.
export const PIVOT_AGGREGATIONS = [
  'sum', 'count', 'average', 'max', 'min', 'product', 'countNums',
  'stdDev', 'stdDevp', 'var', 'varp',
] as const
export type PivotAggregation = (typeof PIVOT_AGGREGATIONS)[number]

/// Fixed-source Show Values As envelope. Office2010 extensions are serialized
/// separately from the core ST_ShowDataAs spellings.
export const PIVOT_SHOW_DATA_AS = [
  'percentOfTotal', 'percentOfRow', 'percentOfCol',
  'percentOfParentRow', 'percentOfParentCol', 'index',
  'percentOf', 'percentOfParent', 'difference', 'percentDiff', 'runTotal',
  'percentOfRunningTotal', 'rankAscending', 'rankDescending',
] as const
export type PivotShowDataAs = (typeof PIVOT_SHOW_DATA_AS)[number]
export const PIVOT_X14_SHOW_DATA_AS: readonly PivotShowDataAs[] = [
  'percentOfParentRow','percentOfParentCol','percentOfParent',
  'percentOfRunningTotal','rankAscending','rankDescending',
]
export function showDataAsNeedsBaseField(mode: PivotShowDataAs | undefined): boolean {
  return mode !== undefined && ['percentOf','percentOfParent','difference','percentDiff','runTotal','percentOfRunningTotal','rankAscending','rankDescending'].includes(mode)
}
export function showDataAsNeedsBaseItem(mode: PivotShowDataAs | undefined): boolean {
  return mode !== undefined && ['percentOf','difference','percentDiff'].includes(mode)
}
export function showDataAsIsPercent(mode: PivotShowDataAs | undefined): boolean {
  return mode !== undefined && !['difference','runTotal','rankAscending','rankDescending','index'].includes(mode)
}

export const AGG_CAPTIONS: Record<PivotAggregation, string> = {
  sum: 'Sum', count: 'Count', average: 'Average', max: 'Max', min: 'Min',
  product: 'Product', countNums: 'Count', stdDev: 'StdDev', stdDevp: 'StdDevp',
  var: 'Var', varp: 'Varp',
}
