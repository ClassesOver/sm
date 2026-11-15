import { expect, it } from 'vitest'
import { workbookSpellEngine } from './workbook-spell-engine'
import affixes from '../node_modules/dictionary-en/index.aff?raw'
import words from '../node_modules/dictionary-en/index.dic?raw'
import { collectWorkbookTextCells, replaceSuggestion, runSheetSpellCheck } from './vendor/genoffice-sheets-spelling/spell-check'
import { planWorkbookSpellingReplacements } from './workbook-spelling'

it('checks visible text locally with Hunspell while skipping formulas and withheld cells', () => {
  const { cells } = collectWorkbookTextCells({ sheets: { first: { cellData: {
    '0': { '0': { v: 'hello wrold' }, '1': { v: 'wrold', f: '"wrold"' }, '2': { v: 'wrold' } },
  } } } }, [{ sheetId: 'first', sheetName: 'Sheet1' }], (_sheet, _row, column) => column === 2)
  const engine = workbookSpellEngine(affixes, words)
  const findings = runSheetSpellCheck(cells, engine, new Set(), new Set())
  expect(findings).toHaveLength(1)
  expect(findings[0]).toMatchObject({ word: 'wrold', cell: { address: 'A1' } })
  expect(findings[0]?.suggestions).toContain('world')
  expect(replaceSuggestion(cells[0]!.text, 'wrold', 'world')).toBe('hello world')
  expect(runSheetSpellCheck(cells, engine, new Set(['wrold']), new Set())).toEqual([])
})

it('only plans writes against the scanned plain text in an editable sheet', () => {
  const finding = { cell: { sheetId: 'first', sheetName: 'Sheet1', address: 'A1', row: 0, column: 0, text: 'hello wrold' },
    word: 'wrold', suggestions: ['world'] }
  const snapshot = { sheets: { first: { name: 'Sheet1', cellData: { '0': { '0': { v: 'hello wrold' } } } } } }
  expect(planWorkbookSpellingReplacements(snapshot, [finding], 'world', () => false)).toEqual([
    { subUnitId: 'first', count: 1, value: { '0': { '0': { v: 'hello world' } } } },
  ])
  expect(() => planWorkbookSpellingReplacements(snapshot, [finding], 'world', () => true)).toThrow('受保护')
  snapshot.sheets.first.cellData['0']['0'].v = 'changed wrold'
  expect(() => planWorkbookSpellingReplacements(snapshot, [finding], 'world', () => false)).toThrow('文本已变化')
})
