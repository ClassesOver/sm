import { expect, it } from 'vitest'
import { renameImplicitTableColumns, renameTableColumns, renameTableReferences } from './workbook-table-references'

it.each([
  ['=Staff[Name]', '=Staff[Employee]'],
  ['Staff[[Name]]', 'Staff[[Employee]]'],
  ['=SUM(Staff[[#Data],[Name]])', '=SUM(Staff[[#Data],[Employee]])'],
  ['=Staff[[Name]:[Qty]]', '=Staff[[Employee]:[Qty]]'],
  ['=Staff[@Name]', '=Staff[@Employee]'],
  ['=Staff[Name]&"a\nb"', '=Staff[Employee]&"a\nb"'],
  ['=IF(A1,"a\nb",2)', '=IF(A1,"a\nb",2)'],
  ['=IF(A1="Staff[Name]",Other[Name],staff[Name])', '=IF(A1="Staff[Name]",Other[Name],staff[Employee])'],
])('renames structured references without changing other tokens: %s', (before, after) => {
  expect(renameTableColumns(before, 'Staff', new Map([['name', 'Employee']]))).toBe(after)
})

it('preserves specifiers and escapes special column names', () => {
  expect(renameTableColumns('=Staff[[#Data],[Name]]', 'Staff', new Map([['name', 'A]B']]))).toBe("=Staff[[#Data],[A']B]]")
  expect(renameTableColumns("=Staff[A']B]", 'Staff', new Map([['a]b', 'Employee']]))).toBe('=Staff[Employee]')
  expect(renameTableColumns('=Staff[[#Data],[Name]]', 'Staff', new Map([['#data', 'Other']]))).toBe('=Staff[[#Data],[Name]]')
})

it.each([
  ['=Staff[Name]', '=People[Name]'],
  ['Staff[[Name]]', 'People[[Name]]'],
  ['=SUM(staff[[#Data],[Name]:[Qty]])', '=SUM(People[[#Data],[Name]:[Qty]])'],
  ['=Staff[@Name]+STAFF[Qty]', '=People[@Name]+People[Qty]'],
  ['=IF(A1="Staff[Name]",Other[Name],Staff[Name])', '=IF(A1="Staff[Name]",Other[Name],People[Name])'],
  ['=Staff+Staffing[Name]+_Staff[Name]', '=Staff+Staffing[Name]+_Staff[Name]'],
  ['=SUM(Staff[Name],\r\n Staff[Qty])&"a\r\nb"', '=SUM(People[Name],\r\n People[Qty])&"a\r\nb"'],
  ['=Staff[A\']B]', '=People[A\']B]'],
  ['=SUM([Book.xlsx]Sheet1!Staff[Name],Staff[Name])', '=SUM([Book.xlsx]Sheet1!Staff[Name],People[Name])'],
  ["='[Book.xlsx]Data'!Staff[Name]+Staff[Qty]", "='[Book.xlsx]Data'!Staff[Name]+People[Qty]"],
])('renames explicit table identity and preserves unrelated formula bytes: %s', (before, after) => {
  expect(renameTableReferences(before, 'Staff', 'People')).toBe(after)
})

it('renames Unicode and backslash table names using the official lexer', () => {
  expect(renameTableReferences('=SUM(员工表[姓名],Other[姓名])', '员工表', '客户表')).toBe('=SUM(客户表[姓名],Other[姓名])')
  expect(renameTableReferences('=\\staff[Name]+Staff[Name]', '\\Staff', '\\People')).toBe('=\\People[Name]+Staff[Name]')
})

it.each([
  ['=[@Qty]', '=[@Cost]'],
  ['=SUM([Qty])', '=SUM([Cost])'],
  ['=[[#Data],[Qty]]', '=[[#Data],[Cost]]'],
  ['=SUM([[Qty]:[Name]])', '=SUM([[Cost]:[Name]])'],
  ['=IF(A1="[Qty]",SUM([Qty]),Other[Qty])', '=IF(A1="[Qty]",SUM([Cost]),Other[Qty])'],
  ['=SUM([Qty],\r\n [@Qty])&"a\r\nb"', '=SUM([Cost],\r\n [@Cost])&"a\r\nb"'],
  ['=[Book]Sheet1![Qty]+Sheet1![Qty]+[Qty]', '=[Book]Sheet1![Qty]+Sheet1![Qty]+[Cost]'],
])('renames implicit column nodes without changing explicit or external references: %s', (before, after) => {
  expect(renameImplicitTableColumns(before, new Map([['qty', 'Cost']]))).toBe(after)
})

it('preserves escaped implicit column syntax and specifier identities', () => {
  expect(renameImplicitTableColumns("=[A']B]", new Map([['a]b', 'C#D']]))).toBe("=[C'#D]")
  expect(renameImplicitTableColumns('=[[#Data],[Qty]]', new Map([['#data', 'Changed'], ['qty', 'A]B']]))).toBe("=[[#Data],[A']B]]")
})
