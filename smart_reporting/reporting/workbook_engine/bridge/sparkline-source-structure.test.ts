import { expect, it } from 'vitest'
import { assemblePackage, createBlankWorkbook, createBufferEntrySource } from '../packages/xlsx-engine/src/index'
import { applyWorkbookOperations } from './operations'
const path = 'xl/worksheets/sheet1.xml'
async function fixture(prefix: 'xm' | 'alias') {
  let bytes = await applyWorkbookOperations(await createBlankWorkbook(), [{ kind: 'applySheetEdits', plan: { renames: [], additions: [{ name: '来源 B' }, { name: 'Unrelated' }], removals: [], order: ['Sheet1', '来源 B', 'Unrelated'] } }])
  const xml = await (await createBufferEntrySource(bytes)).readText(path)
  const tail = `<extLst><ext uri="{05C60535-1F16-4fd2-B633-F4F36F0B64E0}" xmlns:x14="http://schemas.microsoft.com/office/spreadsheetml/2009/9/main" xmlns:${prefix}="http://schemas.microsoft.com/office/excel/2006/main"><x14:sparklineGroups><x14:sparklineGroup><x14:sparklines><x14:sparkline><${prefix}:f>'来源 B'!$A$1:$C$1</${prefix}:f><${prefix}:sqref>D1</${prefix}:sqref></x14:sparkline></x14:sparklines></x14:sparklineGroup></x14:sparklineGroups></ext></extLst>`
  return (await assemblePackage(bytes, { replaced: new Map([[path, xml.replace('</worksheet>', `${tail}</worksheet>`)]]), added: new Map(), addedBinary: new Map(), removedEntries: [], addedEntries: [], touchedEntries: [path] })).buffer
}
const row = (sheetName = '来源 B') => ({ kind: 'applyRowColumnOps', sheetName, ops: [{ kind: 'insert-rows', index: 0, count: 1 }] })
it.each(['xm', 'alias'] as const)('跨表来源页单元格移位在写入前拒绝 %s', async prefix => {
  const bytes = await fixture(prefix)
  await expect(applyWorkbookOperations(bytes, [{ kind: 'applyCellShift', sheetName: '来源 B', range: 'A1:C1', shift: 'down' }])).rejects.toThrow(/迷你图.*来源/)
})
it('canonical跨表来源行列继续同步，别名前缀不能同步时拒绝；无关页与值编辑允许', async () => {
  const canonical = await fixture('xm')
  const moved = await applyWorkbookOperations(canonical, [row()])
  expect(await (await createBufferEntrySource(moved)).readText(path)).toContain("'来源 B'!$A$2:$C$2")
  const alias = await fixture('alias')
  await expect(applyWorkbookOperations(alias, [row()])).rejects.toThrow(/迷你图.*来源/)
  await expect(applyWorkbookOperations(alias, [row('Unrelated')])).resolves.toBeInstanceOf(Uint8Array)
  await expect(applyWorkbookOperations(alias, [{ kind: 'applyCellEdits', edits: [{ sheetName: '来源 B', row: 0, column: 0, writeValue: true, cell: { value: 7 } }] }])).resolves.toBeInstanceOf(Uint8Array)
})
it('来源改名后仍按真实新名称保护，无法可靠读取的来源也拒绝结构移位', async () => {
  const bytes = await applyWorkbookOperations(await fixture('alias'), [{ kind: 'applySheetEdits', plan: { renames: [{ sheetName: '来源 B', newName: "来源 O'Brien" }], additions: [], removals: [], order: ['Sheet1', "来源 O'Brien", 'Unrelated'] } }])
  await expect(applyWorkbookOperations(bytes, [row("来源 O'Brien")])).rejects.toThrow(/迷你图.*来源/)
  const original = await fixture('xm'), xml = await (await createBufferEntrySource(original)).readText(path)
  const unknown = (await assemblePackage(original, { replaced: new Map([[path, xml.replace("'来源 B'!$A$1:$C$1", "INDIRECT(A1)")]]), added: new Map(), addedBinary: new Map(), removedEntries: [], addedEntries: [], touchedEntries: [path] })).buffer
  await expect(applyWorkbookOperations(unknown, [row()])).rejects.toThrow(/迷你图.*来源/)
})
