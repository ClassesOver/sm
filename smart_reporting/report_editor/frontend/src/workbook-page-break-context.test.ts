import { expect, it } from 'vitest'
import type { ShiftSpec } from '@sheets-web/xlsx-engine/structural'
import { createPageSetupJournal, pageBreakPreviewSetup } from './workbook-page-break-context'
const insert: ShiftSpec = { axis: 'row', start: 2, delta: 3 }
const remove: ShiftSpec = { axis: 'row', start: 2, delta: -3 }
it('preserves file header/footer variants and distances when composing print settings', () => {
  const headerFooter = { oddHeader: '&C&P / &N', firstHeader: '', evenFooter: '&A', differentFirst: true, differentOddEven: true, scaleWithDoc: false }
  const file = { headerFooter, margins: { left: .7, right: .7, top: .75, bottom: .75, header: .2, footer: .4 } }
  expect(pageBreakPreviewSetup(file, {})).toMatchObject({ headerFooter, margins: { header: .2, footer: .4 } })
  expect(pageBreakPreviewSetup(file, { margins: 'wide' })).toMatchObject({ headerFooter, margins: { header: .5, footer: .5 } })
})
it('rebases each captured field through later structure and restores deleted boundaries after Undo/Redo', () => {
  let ops: ShiftSpec[] = []
  const journal = createPageSetupJournal(() => ops)
  journal.set('sheet-1', { rowBreaks: [3, 10], printArea: 'A1:D20', printTitles: '3:5' })
  ops = [insert]
  expect(journal.get('sheet-1')).toEqual({ rowBreaks: [6, 13], printArea: 'A1:D23', printTitles: '6:8' })
  ops = [remove]
  expect(journal.get('sheet-1')).toEqual({ rowBreaks: [7], printArea: 'A1:D17', printTitles: '#REF!' })
  ops = []; expect(journal.get('sheet-1')?.rowBreaks).toEqual([3, 10])
  ops = [remove]; expect(journal.get('sheet-1')?.rowBreaks).toEqual([7])
})
it('captures settings after structure and does not recapture old fields when changing an unrelated property', () => {
  let ops: ShiftSpec[] = [insert]
  const journal = createPageSetupJournal(() => ops)
  journal.set('stable-id', { rowBreaks: [6, 13], printArea: 'A1:D23' })
  ops = []; expect(journal.get('stable-id')).toEqual({ rowBreaks: [3, 10], printArea: 'A1:D20' })
  journal.set('stable-id', { ...journal.get('stable-id'), orientation: 'landscape' })
  ops = [insert]; expect(journal.get('stable-id')).toEqual({ rowBreaks: [6, 13], printArea: 'A1:D23', orientation: 'landscape' })
  expect(journal.get('renamed-sheet-name')).toBeUndefined()
})
it('keeps the original capture across a deletion that removes every break and an unrelated setting', () => {
  let ops: ShiftSpec[] = []
  const journal = createPageSetupJournal(() => ops)
  journal.set('s', { rowBreaks: [3] }); ops = [remove]
  expect(journal.get('s')?.rowBreaks).toEqual([])
  journal.set('s', { ...journal.get('s'), paperSize: 1 }); ops = []
  expect(journal.get('s')).toEqual({ rowBreaks: [3], paperSize: 1 })
  ops = [remove]; expect(journal.get('s')?.rowBreaks).toEqual([])
})
it('composes effective custom margins and all journal fields without losing explicit clears or file scale', () => {
  const file = { pageSetup: { scale: 170, fitToPage: true, fitToWidth: 2, fitToHeight: 3 }, margins: { left: 1.2, right: .3, top: .4, bottom: 1.1 }, rowBreaks: [10], colBreaks: [3], printArea: 'A1:D20', printTitles: '1:2' }
  const result = pageBreakPreviewSetup(file, { scale: 90, printArea: null, printTitles: null, rowBreaks: [], margins: 'narrow', fitToPage: false })
  expect(result).toMatchObject({ scale: 90, printArea: null, printTitles: null, rowBreaks: [], colBreaks: [3], fitToPage: false, margins: { left: .25, right: .25 } })
  expect(pageBreakPreviewSetup(file, {}).margins).toEqual(file.margins)
})
it('treats an explicit clear as a new capture even when deletion already made the effective set empty', () => {
  let ops: ShiftSpec[] = []
  const journal = createPageSetupJournal(() => ops)
  journal.set('s', { rowBreaks: [3] }); ops = [remove]
  journal.set('s', { rowBreaks: [] }, ['rowBreaks']); ops = []
  expect(journal.get('s')?.rowBreaks).toEqual([])
})
