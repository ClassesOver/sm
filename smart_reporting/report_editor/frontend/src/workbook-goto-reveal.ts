// 固定 GenOffice f8c17004 univer-sync.ts revealCellBelowFreeze；状态限定每个宿主实例。
import type { IRange } from '@univerjs/core'

interface RevealSheet {
  scrollToCell(row: number, column: number): unknown
  getVisibleRange(): IRange | null
  getVisibleRangesOfAllViewports?(): Map<unknown, IRange> | null
  getSheet?(): { getConfig(): { rightToLeft?: number } }
}

/** 使用官方滚动和实际视口校正冻结偏移；null 表示已被新导航或销毁取消。 */
export function createWorkbookReveal() {
  let generation = 0, disposed = false
  let pending: { timer: ReturnType<typeof setTimeout>; finish: (ready: boolean) => void } | undefined
  const cancel = () => {
    generation++
    if (pending) { clearTimeout(pending.timer); pending.finish(false); pending = undefined }
  }
  const wait = () => new Promise<boolean>(finish => {
    const timer = setTimeout(() => { pending = undefined; finish(true) }, 60)
    pending = { timer, finish }
  })
  return {
    cancel,
    dispose() { disposed = true; cancel() },
    async reveal(sheet: RevealSheet, row: number, column: number, isCurrent = () => true): Promise<boolean | null> {
      cancel()
      const targetGeneration = generation
      const current = () => !disposed && generation === targetGeneration && isCurrent()
      const includes = (range: IRange) => row >= range.startRow && row <= range.endRow && column >= range.startColumn && column <= range.endColumn
      const visible = () => {
        const ranges = sheet.getVisibleRangesOfAllViewports?.()
        if (ranges && [...ranges.values()].some(includes)) return true
        const range = sheet.getVisibleRange()
        return !!range && includes(range)
      }
      if (!current()) return null
      // 固定源 RTL 路径先等原生 reveal，避免把已可见目标再次跳到另一边。
      if (sheet.getSheet?.().getConfig().rightToLeft === 1) {
        if (!await wait() || !current()) return null
      }
      if (visible()) return true
      const aimRow = Math.max(0, row - 1)
      let scrollRow = aimRow, scrollColumn = column, lastStartRow = -1, lastStartColumn = -1
      sheet.scrollToCell(scrollRow, scrollColumn)
      for (let attempt = 0; attempt < 4; attempt++) {
        if (!await wait() || !current()) return null
        const range = sheet.getVisibleRange()
        if (!range) return false
        const overRows = Math.max(0, range.startRow - aimRow), underRows = Math.max(0, row - range.endRow)
        const overColumns = Math.max(0, range.startColumn - column), underColumns = Math.max(0, column - range.endColumn)
        if (!overRows && !underRows && !overColumns && !underColumns) return visible()
        if (range.startRow === lastStartRow && range.startColumn === lastStartColumn) return visible()
        if (attempt === 3) return visible()
        lastStartRow = range.startRow; lastStartColumn = range.startColumn
        scrollRow = Math.max(0, scrollRow - overRows + underRows)
        scrollColumn = Math.max(0, scrollColumn - overColumns + underColumns)
        sheet.scrollToCell(scrollRow, scrollColumn)
      }
      return false
    },
  }
}
