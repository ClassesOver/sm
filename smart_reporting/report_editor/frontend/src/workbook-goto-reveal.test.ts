import { afterEach, expect, it, vi } from 'vitest'
import { createWorkbookReveal } from './workbook-goto-reveal'

afterEach(() => vi.useRealTimers())
const range = (startRow: number, endRow: number, startColumn = 0, endColumn = 30) => ({ startRow, endRow, startColumn, endColumn })
it('reveals a distant target through official scroll and measured viewport without writing data', async () => {
  vi.useFakeTimers(); let visible = range(0, 20)
  const sheet = { getVisibleRange: () => visible, scrollToCell: vi.fn((row: number, column: number) => { visible = range(row, row + 20, column, column + 10) }) }
  const reveal = createWorkbookReveal(), result = reveal.reveal(sheet, 25000, 25)
  await vi.runAllTimersAsync()
  expect(await result).toBe(true); expect(sheet.scrollToCell).toHaveBeenCalledWith(24999, 25); reveal.dispose()
})
it('keeps already visible and frozen-viewport targets in place', async () => {
  const sheet = { getVisibleRange: () => range(20, 40), getVisibleRangesOfAllViewports: () => new Map([['frozen', range(0, 1)], ['main', range(20, 40)]]), scrollToCell: vi.fn() }
  const reveal = createWorkbookReveal()
  expect(await reveal.reveal(sheet, 0, 3)).toBe(true); expect(sheet.scrollToCell).not.toHaveBeenCalled(); reveal.dispose()
})
it('corrects measured freeze overshoot rather than assuming standard row heights or zoom', async () => {
  vi.useFakeTimers(); let visible = range(0, 20)
  const scroll = vi.fn((row: number, _column: number) => { visible = range(row + 3, row + 23) })
  const reveal = createWorkbookReveal(), result = reveal.reveal({ getVisibleRange: () => visible, scrollToCell: scroll }, 100, 3)
  await vi.runAllTimersAsync(); expect(await result).toBe(true)
  expect(scroll.mock.calls).toEqual([[99, 3], [96, 3]]); reveal.dispose()
})
it('waits for native RTL reveal and avoids a second jump when it is visible', async () => {
  vi.useFakeTimers(); let visible = range(0, 20)
  const sheet = { getSheet: () => ({ getConfig: () => ({ rightToLeft: 1 }) }), getVisibleRange: () => visible, scrollToCell: vi.fn() }
  const reveal = createWorkbookReveal(), result = reveal.reveal(sheet, 100, 3)
  visible = range(90, 110); await vi.runAllTimersAsync()
  expect(await result).toBe(true); expect(sheet.scrollToCell).not.toHaveBeenCalled(); reveal.dispose()
})
it('reports an unrevealed target and real facade failure instead of claiming visibility', async () => {
  vi.useFakeTimers(); const reveal = createWorkbookReveal()
  const result = reveal.reveal({ getVisibleRange: () => range(0, 20), scrollToCell() {} }, 100, 3)
  await vi.runAllTimersAsync(); expect(await result).toBe(false)
  await expect(reveal.reveal({ getVisibleRange() { throw Error('render unavailable') }, scrollToCell() {} }, 100, 3)).rejects.toThrow('render unavailable'); reveal.dispose()
})
it('new navigation and disposal cancel pending corrections without cross-instance interference', async () => {
  vi.useFakeTimers(); const a = createWorkbookReveal(), b = createWorkbookReveal()
  const sheet = { getVisibleRange: () => range(0, 20), scrollToCell: vi.fn() }
  const old = a.reveal(sheet, 100, 3), other = b.reveal(sheet, 200, 3)
  expect(await a.reveal(sheet, 1, 3)).toBe(true); expect(await old).toBe(null)
  b.dispose(); expect(await other).toBe(null); await vi.runAllTimersAsync()
  expect(sheet.scrollToCell).toHaveBeenCalledTimes(2); expect(vi.getTimerCount()).toBe(0); a.dispose()
})
it('stops on worksheet replacement before the next delayed scroll', async () => {
  vi.useFakeTimers(); const reveal = createWorkbookReveal(); let current = true
  const sheet = { getVisibleRange: () => range(0, 20), scrollToCell: vi.fn() }
  const result = reveal.reveal(sheet, 100, 3, () => current); current = false
  await vi.runAllTimersAsync(); expect(await result).toBe(null); expect(sheet.scrollToCell).toHaveBeenCalledTimes(1); reveal.dispose()
})
