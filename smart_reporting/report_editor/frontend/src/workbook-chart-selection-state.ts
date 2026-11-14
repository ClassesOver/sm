const selections = new Map<string, string>()
export const selectedChartPath = (unitId: string, sheetId: string): string | undefined => selections.get(`${unitId}::${sheetId}`)
export function setSelectedChartPath(unitId: string, sheetId: string, path?: string): void {
  const key = `${unitId}::${sheetId}`
  if (path === undefined) selections.delete(key)
  else selections.set(key, path)
}
