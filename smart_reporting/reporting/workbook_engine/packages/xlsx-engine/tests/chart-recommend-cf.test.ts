import { describe, expect, it } from 'vitest'

import { applyCellEdits, createBlankWorkbook, recommendCharts, hasNumericYearAxis } from '../src'
import JSZip from 'jszip'
import { applyCfRules, type CfAnyRule } from '../src/rules'
import { createBufferEntrySource, inventoryXlsx } from '../src/zip'

const SHEET = 'xl/worksheets/sheet1.xml'
const STYLES = 'xl/styles.xml'
const BAR: CfAnyRule = {
  kind: 'dataBar', sheet: 'Sheet1', sqref: 'B2:B3',
  min: { type: 'min' }, max: { type: 'max' }, color: '#638EC6',
}

async function patchPackage(bytes: Uint8Array, parts: Record<string, string | Uint8Array | null>): Promise<Uint8Array> {
  const zip = await JSZip.loadAsync(bytes)
  for (const [path, content] of Object.entries(parts)) {
    if (content === null) zip.remove(path)
    else zip.file(path, content, { createFolders: false })
  }
  return zip.generateAsync({ type: 'uint8array' })
}

async function expectOnlyChanged(before: Uint8Array, after: Uint8Array, paths: string[]): Promise<void> {
  const oldEntries = await inventoryXlsx(before)
  const newEntries = await inventoryXlsx(after)
  expect(newEntries.map((entry) => entry.path)).toEqual(oldEntries.map((entry) => entry.path))
  expect(newEntries.filter((entry, i) => entry.sha256 !== oldEntries[i]!.sha256)
    .map((entry) => entry.path).sort()).toEqual([...paths].sort())
}

function ranked(categories: string[], series: number[][]) {
  return recommendCharts([
    ['Category', ...series.map((_, i) => `Value ${i}`)],
    ...categories.map((label, i) => [label, ...series.map((values) => values[i] ?? 1)]),
  ])!.items
}

async function partOf(bytes: Uint8Array, path: string): Promise<string> {
  const source = await createBufferEntrySource(bytes)
  return source.readText(path)
}

async function buildWorkbook(): Promise<Uint8Array> {
  return applyCellEdits(await createBlankWorkbook(), [
    { sheetName: 'Sheet1', row: 0, column: 0, writeValue: true, cell: { value: 'Region' } },
    { sheetName: 'Sheet1', row: 0, column: 1, writeValue: true, cell: { value: 'Sales' } },
    { sheetName: 'Sheet1', row: 1, column: 0, writeValue: true, cell: { value: 'North' } },
    { sheetName: 'Sheet1', row: 1, column: 1, writeValue: true, cell: { value: 10 } },
    { sheetName: 'Sheet1', row: 2, column: 0, writeValue: true, cell: { value: 'South' } },
    { sheetName: 'Sheet1', row: 2, column: 1, writeValue: true, cell: { value: 20 } },
  ])
}

describe('chart recommendation', () => {
  it('recommends pie/doughnut for a single small all-positive series', () => {
    const result = recommendCharts([
      ['Region', 'Sales'],
      ['North', 10],
      ['South', 20],
      ['East', 30],
    ])
    expect(result).not.toBeNull()
    expect(result!.parsed.hasCategoryColumn).toBe(true)
    expect(result!.parsed.categories).toEqual(['North', 'South', 'East'])
    expect(result!.parsed.series[0]?.name).toBe('Sales')
    const kinds = result!.items.map((item) => item.kind)
    expect(kinds).toContain('pie')
    expect(kinds).toContain('doughnut')
    expect(result!.items.length).toBeLessThanOrEqual(5)
  })

  it('recommends line for time categories and detects numeric year axes', () => {
    const monthly = recommendCharts([
      ['Month', 'Sales'],
      ['Jan', 1],
      ['Feb', 2],
      ['Mar', 3],
      ['Apr', 4],
    ])
    expect(monthly!.items[0]).toEqual({ kind: 'line', reason: 'time' })

    // years as a bare numeric column → scatter-shaped parse rescued into a
    // category axis before ranking
    const yearly = recommendCharts([
      [2021, 100],
      [2022, 120],
      [2023, 140],
      [2024, 160],
    ])
    expect(hasNumericYearAxis({
      byRow: false,
      hasHeaderRow: false,
      hasCategoryColumn: false,
      categories: ['1', '2', '3', '4'],
      series: [
        { name: 'Series 1', values: [2021, 2022, 2023, 2024], column: 0 },
        { name: 'Series 2', values: [100, 120, 140, 160], column: 1 },
      ],
    })).toBe(true)
    expect(yearly!.parsed.categories).toEqual(['2021', '2022', '2023', '2024'])
    expect(yearly!.items[0]?.kind).toBe('line')
  })

  it('covers time, proportion, mixed-scale, label, many-point and radar ranking branches', () => {
    expect(ranked(['Jan', 'Feb', 'Mar', 'Apr'], [[1, 2, 3, 4], [2, 3, 4, 5]])).toEqual([
      { kind: 'line', reason: 'time' }, { kind: 'area', reason: 'time' },
      { kind: 'column', reason: 'time' }, { kind: 'bar', reason: 'comparison' },
    ])
    const longLabels = ['North district', 'South district', 'West district', 'East district']
    expect(ranked(longLabels, [[1, 2, 3, 4], [-11, -22, -33, -44]])).toEqual([
      { kind: 'combo', reason: 'mixedScales' }, { kind: 'bar', reason: 'longLabels' },
      { kind: 'column', reason: 'comparison' }, { kind: 'radar', reason: 'comparison' },
      { kind: 'line', reason: 'comparison' },
    ])
    const many = Array.from({ length: 21 }, (_, i) => `Region ${i}`)
    expect(ranked(many, [many.map(() => 1)])[0]).toEqual({ kind: 'line', reason: 'manyPoints' })
    expect(ranked(many.slice(0, 6), Array.from({ length: 4 }, () => [1, 2, 3, 4, 5, 6]))).toEqual([
      { kind: 'line', reason: 'manyPoints' }, { kind: 'column', reason: 'comparison' },
      { kind: 'bar', reason: 'comparison' },
    ])
    expect(ranked(['Q1', 'Q2', 'Q3'], [[-1, 2, 3]])[0]).toEqual({ kind: 'line', reason: 'time' })
    expect(ranked(['A', 'B', 'C'], [[1, 2, 3]])[0]).toEqual({ kind: 'pie', reason: 'proportion' })
  })

  it('covers localized date rejection and numeric-year boundaries', () => {
    for (const categories of [['JAN.', 'february', 'March'], ['1月', '2月', '3月'], ['2026/01/01', '2026/02/01', '2026/03/01']]) {
      expect(ranked(categories, [[1, 2, 3]])[0]).toEqual({ kind: 'line', reason: 'time' })
    }
    for (const categories of [['Jan', '', 'Mar'], ['Jan', '2025', 'Mar'], ['2025', '2024', '2026'], ['1899', '1900', '1901'], ['2199', '2200', '2201']]) {
      const result = recommendCharts([['Year', 'Value'], ...categories.map((label) => [label, 1])])!
      expect(result.items.some((item) => item.reason === 'time')).toBe(false)
    }
    for (const count of [2, 8]) {
      expect(ranked(Array.from({ length: count }, () => 'Region'), [Array(count).fill(0)])[0])
        .toEqual({ kind: 'pie', reason: 'proportion' })
    }
    expect(ranked(Array.from({ length: 9 }, () => 'Region'), [Array(9).fill(1)])
      .some((item) => item.reason === 'proportion')).toBe(false)
  })
  it('recommends scatter for two unlabeled numeric vectors and returns null otherwise', () => {
    const scatter = recommendCharts([
      [1, 2.5], [2, 3.1], [3, 4.2], [4, 3.9], [5, 5.2], [6, 5.9],
    ])
    expect(scatter!.items[0]).toEqual({ kind: 'scatter', reason: 'correlation' })
    expect(recommendCharts([['only text']])).toBeNull()
    expect(recommendCharts([])).toBeNull()
  })

  it('covers ranking boundaries, exclusions, deduplication and the five-result cap', () => {
    const labels = Array.from({ length: 21 }, (_, i) => `District ${i}`)
    expect(ranked(labels.slice(0, 20), [Array(20).fill(1)])[0])
      .toEqual({ kind: 'column', reason: 'comparison' })
    expect(ranked(['A', 'B', 'C'], [[0, 0, 0], [100, 200, 300]])
      .some((item) => item.kind === 'combo')).toBe(false)
    expect(ranked(['A', 'B', 'C'], [[1, 2, 3], [10, 20, 30]])
      .some((item) => item.kind === 'combo')).toBe(false)
    expect(ranked(['A', 'B', 'C'], [[-1, 2, 3]])
      .some((item) => item.reason === 'proportion')).toBe(false)
    expect(ranked(['Jan', 'Feb', 'Mar'], [[-1, 2, 3], [2, 3, 4]])
      .some((item) => item.kind === 'area')).toBe(false)
    const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec', 'Jan']
    expect(ranked(months.slice(0, 12), [Array(12).fill(1)])
      .find((item) => item.kind === 'column')?.reason).toBe('time')
    expect(ranked(months, [Array(13).fill(1)])
      .find((item) => item.kind === 'column')?.reason).toBe('comparison')
    expect(ranked(['ABCDEFGHIJKL', 'MNOPQRSTUVWX'], [[1, 2]])
      .find((item) => item.kind === 'bar')?.reason).toBe('comparison')
    for (const count of [2, 9]) {
      expect(ranked(labels.slice(0, count), [Array(count).fill(1), Array(count).fill(2)])
        .some((item) => item.kind === 'radar')).toBe(false)
    }
    const capped = ranked(['January', 'February', 'March'], [[1, 2, 3], [11, 22, 33]])
    expect(capped).toEqual([
      { kind: 'line', reason: 'time' }, { kind: 'area', reason: 'time' },
      { kind: 'column', reason: 'time' }, { kind: 'combo', reason: 'mixedScales' },
      { kind: 'bar', reason: 'comparison' },
    ])
    expect(new Set(capped.map((item) => item.kind)).size).toBe(capped.length)
  })
})

describe('conditional-format package regressions', () => {
  it('allocates the lowest free priorities and preserves ordinary CF plus x14 extLst verbatim', async () => {
    const bytes = await buildWorkbook()
    const baseSheet = await partOf(bytes, SHEET)
    const ordinary = '<conditionalFormatting sqref="A1:A3"><cfRule type="expression" priority="1"><formula>A1&gt;0</formula></cfRule></conditionalFormatting>'
    const id = '{00000000-0000-0000-0000-000000000001}'
    const x14 = 'http://schemas.microsoft.com/office/spreadsheetml/2009/9/main'
    const linked = '<conditionalFormatting sqref="B1:B3"><cfRule type="dataBar" priority="3"><dataBar><cfvo type="min"/><cfvo type="max"/><color rgb="FF638EC6"/></dataBar>' +
      `<extLst><ext uri="{B025F937-C7B1-47D3-B67F-A62EFF666E3E}" xmlns:x14="${x14}"><x14:id>${id}</x14:id></ext></extLst></cfRule></conditionalFormatting>`
    const sheetExt = `<extLst><ext uri="{78C0D931-6437-407D-A8EE-F0AAD7539E65}" xmlns:x14="${x14}">` +
      '<x14:conditionalFormattings><x14:conditionalFormatting xmlns:xm="http://schemas.microsoft.com/office/excel/2006/main">' +
      `<x14:cfRule type="dataBar" priority="3" id="${id}"><x14:dataBar minLength="0" maxLength="100"><x14:cfvo type="autoMin"/><x14:cfvo type="autoMax"/><x14:negativeFillColor rgb="FFFF0000"/></x14:dataBar></x14:cfRule>` +
      '<x14:cfRule type="iconSet" priority="4" id="{00000000-0000-0000-0000-000000000002}"><x14:iconSet iconSet="3Stars"><x14:cfvo type="percent"><xm:f>0</xm:f></x14:cfvo><x14:cfvo type="percent"><xm:f>33</xm:f></x14:cfvo><x14:cfvo type="percent"><xm:f>67</xm:f></x14:cfvo></x14:iconSet></x14:cfRule>' +
      '<xm:sqref>B1:B3</xm:sqref></x14:conditionalFormatting></x14:conditionalFormattings></ext>' +
      '<ext uri="opaque" xmlns:custom="urn:custom"><custom:payload priority="2" key="unchanged"/></ext></extLst>'
    const seeded = await patchPackage(bytes, {
      [SHEET]: baseSheet.replace('</worksheet>', `${ordinary}${linked}${sheetExt}</worksheet>`),
      'xl/media/opaque.bin': new Uint8Array([0, 1, 255, 13, 42]),
      'customXml/item1.xml': '<payload xmlns="urn:custom">Untouched &amp; opaque</payload>',
      'customXml/_rels/item1.xml.rels': '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>',
      'xl/worksheets/sheet2.xml': baseSheet,
    })
    const edited = await applyCfRules(seeded, [BAR, {
      sheet: 'Sheet1', sqref: 'C1:C3', operator: 'greaterThan', formula1: '0',
    }])
    const xml = await partOf(edited, SHEET)
    expect(xml).toContain(ordinary)
    expect(xml).toContain(linked)
    expect(xml).toContain(sheetExt)
    expect(xml).toContain('<conditionalFormatting sqref="B2:B3"><cfRule type="dataBar" priority="2">')
    expect(xml).toContain('<conditionalFormatting sqref="C1:C3"><cfRule type="cellIs" priority="5"')
    expect(xml.indexOf(linked) + linked.length).toBe(xml.indexOf('<conditionalFormatting sqref="B2:B3"'))
    await expectOnlyChanged(seeded, edited, [SHEET])
  })

  it('places new CF after sheetData when a cell contains an extLst', async () => {
    const bytes = await buildWorkbook()
    const original = await partOf(bytes, SHEET)
    const withCellExt = await patchPackage(bytes, {
      [SHEET]: original.replace(
        '</c></row></sheetData>',
        '<extLst><ext uri="{cell-extension}"/></extLst></c></row></sheetData>',
      ),
    })
    const edited = await applyCfRules(withCellExt, [BAR])
    const xml = await partOf(edited, SHEET)
    expect(xml.indexOf('</sheetData>')).toBeLessThan(xml.indexOf('<conditionalFormatting'))
    expect(xml).toContain('<c r="B1" t="inlineStr"><is><t xml:space="preserve">Sales</t></is></c>')
    expect(xml).toContain('<extLst><ext uri="{cell-extension}"/></extLst></c></row></sheetData>')
  })

  it('serializes threshold boundaries, formulas, and strict icon comparisons', async () => {
    const bytes = await buildWorkbook()
    const edited = await applyCfRules(bytes, [
      {
        kind: 'colorScale', sheet: 'Sheet1', sqref: 'B2:B3',
        stops: [
          { cfvo: { type: 'num', value: -1 }, color: '#000000' },
          { cfvo: { type: 'percentile', value: 100 }, color: '#FFFFFF' },
        ],
      },
      {
        kind: 'dataBar', sheet: 'Sheet1', sqref: 'A1:A3',
        min: { type: 'formula', value: '=MIN(A1:A3)&"<&"' },
        max: { type: 'num', value: 0 }, color: '#638EC6',
      },
      {
        kind: 'iconSet', sheet: 'Sheet1', sqref: 'B2:B3', iconSet: '3Arrows',
        thresholds: [
          { type: 'percent', value: 0 },
          { type: 'percent', value: 50, greaterThan: true },
          { type: 'percent', value: 100, greaterThan: true },
        ],
      },
    ])
    const xml = await partOf(edited, SHEET)
    expect(xml).toContain('<cfvo type="num" val="-1"/>')
    expect(xml).toContain('<cfvo type="percentile" val="100"/>')
    expect(xml).toContain('type="formula" val="=MIN(A1:A3)&amp;&quot;&lt;&amp;&quot;"')
    expect(xml).toContain('<cfvo type="percent" val="50" gte="0"/>')
    expect(xml).toContain('<cfvo type="percent" val="100" gte="0"/>')
  })
  it('preserves existing dxfs and interns only distinct highlight styles', async () => {
    const bytes = await buildWorkbook()
    const styles = await partOf(bytes, STYLES)
    const seeded = await patchPackage(bytes, {
      [STYLES]: styles.replace('</styleSheet>', '<dxfs count="1"><dxf><font><b/></font></dxf></styleSheet>'),
    })
    const first = await applyCfRules(seeded, [{
      sheet: 'Sheet1', sqref: 'A1', operator: 'equal', formula1: '1', bold: true,
    }])
    const firstStyles = await partOf(first, STYLES)
    expect(firstStyles).toContain('<dxfs count="1"><dxf><font><b/></font></dxf>')
    expect(await partOf(first, SHEET)).toContain('dxfId="0"')
    const second = await applyCfRules(first, [{
      sheet: 'Sheet1', sqref: 'A2', operator: 'equal', formula1: '2', italic: true,
    }])
    const secondStyles = await partOf(second, STYLES)
    expect(secondStyles).toContain('<dxfs count="2"><dxf><font><b/></font></dxf><dxf><font><i/></font></dxf></dxfs>')
    await expectOnlyChanged(first, second, [SHEET, STYLES])
    const visualOnly = await applyCfRules(second, [BAR])
    expect(await partOf(visualOnly, STYLES)).toBe(secondStyles)
    await expectOnlyChanged(second, visualOnly, [SHEET])
  })

  it('rejects invalid threshold values and malformed CF rules before package mutation', async () => {
    const bytes = await buildWorkbook()
    const cases: unknown[] = [
      { ...BAR, min: { type: 'num' } },
      { ...BAR, min: { type: 'num', value: Number.NaN } },
      { ...BAR, min: { type: 'percent', value: -1 } },
      { ...BAR, min: { type: 'percent', value: 101 } },
      { ...BAR, min: { type: 'formula', value: ' ' } },
      { ...BAR, min: { type: 'min', value: 0 } },
      { ...BAR, min: { type: 'num', value: 2 }, max: { type: 'num', value: 1 } },
      { kind: 'colorScale', sheet: 'Sheet1', sqref: 'A1', stops: [
        { cfvo: { type: 'percent', value: 80 }, color: '#ffffff' },
        { cfvo: { type: 'percent', value: 20 }, color: '#000000' },
      ] },
      { kind: 'iconSet', sheet: 'Sheet1', sqref: 'A1', iconSet: '3Arrows', thresholds: [
        { type: 'percent', value: 0 }, { type: 'percent', value: 80 }, { type: 'percent', value: 20 },
      ] },
      { sheet: 'Sheet1', sqref: 'A1', operator: 'between', formula1: '1' },
      { sheet: 'Sheet1', sqref: 'A1', operator: 'equal', formula1: '' },
      { ...BAR, sqref: 'A0' },
      { ...BAR, sqref: 'B2:A1' },
      { ...BAR, sheet: 'Missing' },
    ]
    for (const invalid of cases) {
      const snapshot = bytes.slice()
      await expect(applyCfRules(bytes, [invalid as CfAnyRule])).rejects.toThrow()
      expect(bytes).toEqual(snapshot)
    }
  })

  it('rejects hostile XML declarations before parsing a workbook part', async () => {
    const bytes = await buildWorkbook()
    for (const path of ['xl/workbook.xml', SHEET, STYLES, '[Content_Types].xml']) {
      const original = await partOf(bytes, path)
      const hostile = `<!DOCTYPE worksheet [<!ENTITY blocked "not-a-secret">]>${original}`
      const seeded = await patchPackage(bytes, { [path]: hostile })
      await expect(applyCfRules(seeded, [BAR])).rejects.toThrow(/DOCTYPE 或 ENTITY/)
    }
    const relsPath = 'xl/_rels/workbook.xml.rels'
    const rels = await partOf(bytes, relsPath)
    await expect(applyCfRules(await patchPackage(bytes, {
      [relsPath]: `<!ENTITY blocked SYSTEM "https://example.invalid/blocked">${rels}`,
    }), [BAR])).rejects.toThrow(/DOCTYPE 或 ENTITY/)
  })

  it('writes colorScale, dataBar, and iconSet rules', async () => {
    const bytes = await buildWorkbook()
    const edited = await applyCfRules(bytes, [
      {
        kind: 'colorScale',
        sheet: 'Sheet1',
        sqref: 'B2:B3',
        stops: [
          { cfvo: { type: 'min' }, color: '#FFFFFF' },
          { cfvo: { type: 'max' }, color: '#4472C4' },
        ],
      },
      {
        kind: 'dataBar',
        sheet: 'Sheet1',
        sqref: 'B2:B3',
        min: { type: 'min' },
        max: { type: 'max' },
        color: '#638EC6',
        showValue: false,
      },
      {
        kind: 'iconSet',
        sheet: 'Sheet1',
        sqref: 'B2:B3',
        iconSet: '3TrafficLights1',
        thresholds: [
          { type: 'percent', value: 0 },
          { type: 'percent', value: 33, greaterThan: true },
          { type: 'percent', value: 67 },
        ],
        reverse: true,
      },
    ])
    const worksheet = await partOf(edited, 'xl/worksheets/sheet1.xml')
    expect(worksheet).toContain(
      '<cfRule type="colorScale" priority="1"><colorScale>' +
        '<cfvo type="min"/><cfvo type="max"/>' +
        '<color rgb="FFFFFFFF"/><color rgb="FF4472C4"/></colorScale></cfRule>',
    )
    expect(worksheet).toContain(
      '<cfRule type="dataBar" priority="2"><dataBar showValue="0">' +
        '<cfvo type="min"/><cfvo type="max"/><color rgb="FF638EC6"/></dataBar></cfRule>',
    )
    expect(worksheet).toContain(
      '<cfRule type="iconSet" priority="3">' +
        '<iconSet iconSet="3TrafficLights1" reverse="1">' +
        '<cfvo type="percent" val="0"/>' +
        '<cfvo type="percent" val="33" gte="0"/>' +
        '<cfvo type="percent" val="67"/></iconSet></cfRule>',
    )
  })

  it('serializes formula thresholds and keeps later rules after existing CF blocks', async () => {
    const bytes = await buildWorkbook()
    const first = await applyCfRules(bytes, [
      {
        kind: 'dataBar',
        sheet: 'Sheet1',
        sqref: 'B2:B3',
        min: { type: 'formula', value: 'MIN(B2:B3)&"x"' },
        max: { type: 'max' },
        color: '#638EC6',
      },
    ])
    const second = await applyCfRules(first, [
      {
        sheet: 'Sheet1',
        sqref: 'A1:A3',
        operator: 'greaterThan',
        formula1: '0',
        stopIfTrue: true,
      },
    ])
    const xml = await partOf(second, 'xl/worksheets/sheet1.xml')
    expect(xml).toContain('type="formula" val="MIN(B2:B3)&amp;&quot;x&quot;"')
    expect(xml).toContain('type="cellIs"')
    expect(xml).toContain('stopIfTrue="1"')
    expect(xml.indexOf('<conditionalFormatting sqref="B2:B3"')).toBeLessThan(
      xml.indexOf('<conditionalFormatting sqref="A1:A3"'),
    )
  })
  it('fails closed on bad palettes, stop counts, and unsupported icon sets', async () => {
    const bytes = await buildWorkbook()
    await expect(
      applyCfRules(bytes, [
        {
          kind: 'colorScale',
          sheet: 'Sheet1',
          sqref: 'B2:B3',
          stops: [{ cfvo: { type: 'min' }, color: '#FFFFFF' }],
        },
      ]),
    ).rejects.toThrow(/two or three stops/)
    await expect(
      applyCfRules(bytes, [
        {
          kind: 'colorScale',
          sheet: 'Sheet1',
          sqref: 'B2:B3',
          stops: [
            { cfvo: { type: 'min' }, color: 'nope' },
            { cfvo: { type: 'max' }, color: '#FFFFFF' },
          ],
        },
      ]),
    ).rejects.toThrow(/not a valid #RRGGBB color/i)
    await expect(
      applyCfRules(bytes, [
        {
          kind: 'iconSet',
          sheet: 'Sheet1',
          sqref: 'B2:B3',
          iconSet: '3Emoji' as never,
          thresholds: [
            { type: 'percent', value: 0 },
            { type: 'percent', value: 50 },
            { type: 'percent', value: 80 },
          ],
        },
      ]),
    ).rejects.toThrow(/cannot be saved/)
    await expect(
      applyCfRules(bytes, [
        {
          kind: 'iconSet',
          sheet: 'Sheet1',
          sqref: 'B2:B3',
          iconSet: '5Quarters',
          thresholds: [
            { type: 'percent', value: 0 },
            { type: 'percent', value: 25 },
          ],
        },
      ]),
    ).rejects.toThrow(/needs exactly 5 thresholds/)
  })
})
