import { describe, expect, it } from 'vitest'
import { createBlankWorkbook, createBufferEntrySource, assemblePackage, inventoryXlsx, readWorkbook } from '../packages/xlsx-engine/src/index'
import { applyWorkbookOperations } from './operations'

const uri = '{05C60535-1F16-4fd2-B633-F4F36F0B64E0}'
const x14 = 'http://schemas.microsoft.com/office/spreadsheetml/2009/9/main'
const xm = 'http://schemas.microsoft.com/office/excel/2006/main'
const path = 'xl/worksheets/sheet1.xml'
const xmlOf = async (bytes: Uint8Array) => (await createBufferEntrySource(bytes)).readText(path)
const op = (groups: unknown[] = [{ type: 'line', cells: [{ cell: 'D2', sourceRef: 'Sheet1!$A$2:$C$2' }] }]) => ({ kind: 'appendSheetSparklines', sheetName: 'Sheet1', groups })
async function withTail(tail: string) {
  const bytes = await createBlankWorkbook()
  return (await assemblePackage(bytes, { replaced: new Map([[path, (await xmlOf(bytes)).replace('</worksheet>', `${tail}</worksheet>`)]]), added: new Map(), addedBinary: new Map(), removedEntries: [], addedEntries: [], touchedEntries: [path] })).buffer
}
const raw = `<a:sparklineGroup custom="keep"><a:colorNegative theme="2"/><a:sparklines><a:sparkline><m:f>Sheet1!$A$1:$C$1</m:f><m:sqref> $D$1 </m:sqref></a:sparkline></a:sparklines></a:sparklineGroup>`
const existing = `<ext uri="${uri}" xmlns:a="${x14}" xmlns:m="${xm}"><a:sparklineGroups>${raw}</a:sparklineGroups></ext>`

describe('appendSheetSparklines 保存协议', () => {
  it('三类型真实追加，原始组与非目标 ZIP 内容保全', async () => {
    const before = await withTail(`<extLst><ext uri="foreign"><keep value="1"/></ext>${existing}</extLst>`)
    const after = await applyWorkbookOperations(before, [op(['line', 'column', 'stacked'].map((type, i) => ({ type, color: ['#FF0000', '#00FF00', '#0000FF'][i], cells: [{ cell: `D${i + 2}`, sourceRef: `Sheet1!$A$${i + 2}:$C$${i + 2}` }] })))])
    const xml = await xmlOf(after)
    expect(xml).toContain(raw)
    expect(xml).toContain('<ext uri="foreign"><keep value="1"/></ext>')
    expect(xml).toContain('type="column"')
    expect(xml).toContain('type="stacked"')
    for (const color of ['FFFF0000', 'FF00FF00', 'FF0000FF']) expect(xml).toContain(`rgb="${color}"`)
    const b = await inventoryXlsx(before), a = await inventoryXlsx(after)
    expect(a.filter(entry => b.find(old => old.path === entry.path)?.sha256 !== entry.sha256).map(entry => entry.path)).toEqual([path])
  })

  it.each([
    [], [{ type: 'line', cells: [] }], [{ type: 'unknown', cells: [{ cell: 'D2', sourceRef: 'Sheet1!$A$2:$C$2' }] }],
    [{ type: 'line', extra: true, cells: [{ cell: 'D2', sourceRef: 'Sheet1!$A$2:$C$2' }] }],
    ...['A1:A1', 'A1:C2', 'C1:A1', 'A1:XFE1', 'A0:C0', 'A1048577:C1048577'].map(range => [{ type: 'line', cells: [{ cell: 'D2', sourceRef: `Sheet1!${range}` }] }]),
    ...['D2:D3', '$D$2', 'd2', 'XFE2', 'D1048577'].map(cell => [{ type: 'line', cells: [{ cell, sourceRef: 'Sheet1!$A$2:$C$2' }] }]),
    ...['Other!$A$2:$C$2', '[book]Sheet1!$A$2:$C$2', 'SUM(A1:C1)', 'Sheet1!A1:C1'].map(sourceRef => [{ type: 'line', cells: [{ cell: 'D2', sourceRef }] }]),
    [{ type: 'line', color: 'red', cells: [{ cell: 'D2', sourceRef: 'Sheet1!$A$2:$C$2' }] }],
    [{ type: 'line', cells: Array.from({ length: 201 }, (_, i) => ({ cell: `D${i + 1}`, sourceRef: `Sheet1!$A$${i + 1}:$C$${i + 1}` })) }],
  ].map(groups => [groups]))('拒绝非法完整 batch %j', async groups => {
    const bytes = await createBlankWorkbook()
    await expect(applyWorkbookOperations(bytes, [op(groups as unknown[])])).rejects.toThrow()
  })

  it('按 namespace 识别已有宿主并拒绝未知对象结构、晚到非法组与重复追加', async () => {
    const bytes = await withTail(`<extLst>${existing}</extLst>`)
    await expect(applyWorkbookOperations(bytes, [op([{ type: 'line', cells: [{ cell: 'D1', sourceRef: 'Sheet1!$A$1:$C$1' }] }])])).rejects.toThrow(/重复|already/)
    await expect(applyWorkbookOperations(bytes, [op(), op()])).rejects.toThrow(/重复|already/)
    await expect(applyWorkbookOperations(bytes, [op([...op().groups, { type: 'line', cells: [{ cell: 'D9', sourceRef: 'Other!$A$9:$C$9' }] }])])).rejects.toThrow()
    const unknown = await withTail(`<extLst>${existing.replace(raw, '<a:futureObject/>')}</extLst>`)
    await expect(applyWorkbookOperations(unknown, [op()])).rejects.toThrow(/结构/)
    const hidden = await withTail(`<extLst>${existing.replace('<a:colorNegative', '<a:futureObject/><a:colorNegative')}</extLst>`)
    await expect(applyWorkbookOperations(hidden, [op()])).rejects.toThrow(/结构/)
    await expect(applyWorkbookOperations(bytes, [{ ...op(), unknown: true }])).rejects.toThrow()
  })

  it('允许先结构后追加；追加后结构操作拒绝且不返回部分输出', async () => {
    const source = await createBlankWorkbook()
    const shift = { kind: 'applyRowColumnOps', sheetName: 'Sheet1', ops: [{ kind: 'insert-rows', index: 0, count: 1 }] }
    expect(await xmlOf(await applyWorkbookOperations(source, [shift, op()]))).toContain('sparklineGroup')
    await expect(applyWorkbookOperations(source, [op(), shift])).rejects.toThrow(/cannot shift|迷你图/)
    const existingBytes = await withTail(`<extLst>${existing}</extLst>`)
    await expect(applyWorkbookOperations(existingBytes, [shift])).rejects.toThrow(/cannot shift|迷你图/)
    await expect(applyWorkbookOperations(source, [op(), { kind: 'applyCellShift', sheetName: 'Sheet1', range: 'A1:C3', shift: 'down' }])).rejects.toThrow(/cannot shift|迷你图/)
  })

  it('新增后改名和撤销改名均同步来源；不同 namespace prefix 的原生引用也同步', async () => {
    const plan = (sheetName: string, newName: string) => ({ kind: 'applySheetEdits', plan: { renames: [{ sheetName, newName }], additions: [], removals: [], order: [newName] } })
    const source = await createBlankWorkbook()
    const renamed = await applyWorkbookOperations(source, [op(), plan('Sheet1', "数据 O'Brien")])
    expect(await xmlOf(renamed)).toContain("'数据 O''Brien'!$A$2:$C$2")
    const restored = await applyWorkbookOperations(renamed, [plan("数据 O'Brien", 'Sheet1')])
    expect(await xmlOf(restored)).toContain('Sheet1!$A$2:$C$2')
    const rawBytes = await withTail(`<extLst>${existing}</extLst>`)
    expect(await xmlOf(await applyWorkbookOperations(rawBytes, [plan('Sheet1', 'Renamed')]))).toContain('<m:f>Renamed!$A$1:$C$1</m:f>')
  })

  it('明确接受200宿主，不截断尾行', async () => {
    const cells = Array.from({ length: 200 }, (_, i) => ({ cell: `D${i + 1}`, sourceRef: `Sheet1!$A$${i + 1}:$C$${i + 1}` }))
    const bytes = await applyWorkbookOperations(await createBlankWorkbook(), [op([{ type: 'column', cells }])])
    expect((await xmlOf(bytes)).match(/<xm:sqref>/g)).toHaveLength(200)
    expect(await xmlOf(bytes)).toContain('<xm:sqref>D200</xm:sqref>')
  })

  it('支持空根列表以及包含空格、中文和单引号的表名', async () => {
    for (const sheetName of ['数据 汇总', "O'Brien"]) {
      const bytes = await createBlankWorkbook()
      const renamed = await applyWorkbookOperations(bytes, [{ kind: 'applySheetEdits', plan: { renames: [{ sheetName: 'Sheet1', newName: sheetName }], additions: [], removals: [], order: [sheetName] } }])
      const after = await applyWorkbookOperations(renamed, [{ ...op([{ type: 'line', cells: [{ cell: 'D2', sourceRef: `'${sheetName.replaceAll("'", "''")}'!$A$2:$C$2` }] }]), sheetName }])
      expect(await xmlOf(after)).toContain('$A$2:$C$2')
    }
    const empty = await withTail('<extLst/>')
    expect((await xmlOf(await applyWorkbookOperations(empty, [op()]))).match(/<extLst\b/g)).toHaveLength(1)
  })
})

describe('removeSheetSparklines 删除协议', () => {
  it('按宿主删除并保留同组其它宿主及 foreign extension', async () => {
    const withForeign = await withTail(`<extLst><ext uri="foreign"><keep/></ext></extLst>`)
    const seeded = await applyWorkbookOperations(withForeign, [op([
      { type: 'line', cells: [
        { cell: 'D2', sourceRef: 'Sheet1!$A$2:$C$2' },
        { cell: 'D3', sourceRef: 'Sheet1!$A$3:$C$3' },
      ] },
    ])])
    const after = await applyWorkbookOperations(seeded, [{ kind: 'removeSheetSparklines', sheetName: 'Sheet1', targets: ['D2'] }])
    const xml = await xmlOf(after)
    expect(xml).not.toContain('<xm:sqref>D2</xm:sqref>')
    expect(xml).toContain('<xm:sqref>D3</xm:sqref>')
    expect(xml).toContain('<ext uri="foreign"><keep/></ext>')
  })

  it('真实 XLSX 仅改写宿主工作表，读取结果只剩未删除宿主', async () => {
    const seeded = await applyWorkbookOperations(await createBlankWorkbook(), [op([
      { type: 'line', cells: [
        { cell: 'D2', sourceRef: 'Sheet1!$A$2:$C$2' },
        { cell: 'D3', sourceRef: 'Sheet1!$A$3:$C$3' },
      ] },
    ])])
    const before = await inventoryXlsx(seeded)
    const after = await applyWorkbookOperations(seeded, [{ kind: 'removeSheetSparklines', sheetName: 'Sheet1', targets: ['D2'] }])
    const changed = (await inventoryXlsx(after)).filter(entry => before.find(old => old.path === entry.path)?.sha256 !== entry.sha256)
    expect(changed.map(entry => entry.path)).toEqual([path])
    const workbook = await import('../packages/xlsx-engine/src/workbook-read').then(module => module.readWorkbook(after))
    expect(workbook.sheets[0]?.sparklines?.map(sparkline => sparkline.target)).toEqual(['D3'])
  })

  it('删除最后一个宿主时移除空迷你图扩展', async () => {
    const seeded = await applyWorkbookOperations(await createBlankWorkbook(), [op()])
    const after = await applyWorkbookOperations(seeded, [{ kind: 'removeSheetSparklines', sheetName: 'Sheet1', targets: ['D2'] }])
    expect(await xmlOf(after)).not.toContain('sparkline')
  })

  it('拒绝重复或不存在的宿主', async () => {
    const seeded = await applyWorkbookOperations(await createBlankWorkbook(), [op()])
    await expect(applyWorkbookOperations(seeded, [{ kind: 'removeSheetSparklines', sheetName: 'Sheet1', targets: ['D2', 'D2'] }])).rejects.toThrow()
    await expect(applyWorkbookOperations(seeded, [{ kind: 'removeSheetSparklines', sheetName: 'Sheet1', targets: ['D9'] }])).rejects.toThrow(/找不到/)
  })
})

describe('editSheetSparklineGroup 编辑协议', () => {
  it('按宿主更新所属组类型和颜色并保留其它组', async () => {
    const seeded = await applyWorkbookOperations(await createBlankWorkbook(), [op([
      { type: 'line', color: '#112233', cells: [{ cell: 'D2', sourceRef: 'Sheet1!$A$2:$C$2' }] },
      { type: 'column', color: '#445566', cells: [{ cell: 'D3', sourceRef: 'Sheet1!$A$3:$C$3' }] },
    ])])
    const after = await applyWorkbookOperations(seeded, [{ kind: 'editSheetSparklineGroup', sheetName: 'Sheet1', target: 'D2', type: 'stacked', color: '#AABBCC', negativeColor: '#010203' }])
    const xml = await xmlOf(after)
    expect(xml).toContain('type="stacked"')
    expect(xml).toContain('rgb="FFAABBCC"')
    expect(xml).toContain('rgb="FF010203"')
    expect(xml).toContain('<xm:sqref>D3</xm:sqref>')
    expect(xml).toContain('rgb="FF445566"')
    expect((await readWorkbook(after)).sheets[0]?.sparklines?.find(sparkline => sparkline.target === 'D2')).toMatchObject({ kind: 'winLoss', color: '#AABBCC', negativeColor: '#010203' })
  })
})
