import { describe, expect, it } from 'vitest'
import { createBlankWorkbook } from '../src/blank'
import { applySparklines, readSparklines } from '../src/sparklines'
import { assemblePackage, createBufferEntrySource } from '../src/zip'

const path = 'xl/worksheets/sheet1.xml'
const worksheetXml = async (bytes: Uint8Array) => (await createBufferEntrySource(bytes)).readText(path)
const withXml = async (bytes: Uint8Array, xml: string) => (await assemblePackage(bytes, {
  replaced: new Map([[path, xml]]), added: new Map(), addedBinary: new Map(),
  removedEntries: [], addedEntries: [], touchedEntries: [path],
})).buffer

describe('sparkline writer regressions', () => {
  it.each(['<extLst><ext uri="foreign"><foreign xmlns="urn:test">keep</foreign></ext></extLst>', '<extLst/>'])(
    'keeps new groups inside an existing root extension list: %s', async (extLst) => {
      const original = await createBlankWorkbook()
      const xml = (await worksheetXml(original)).replace('</worksheet>', `${extLst}</worksheet>`)
      const output = await applySparklines(await withXml(original, xml), 'Sheet1', [
        { kind: 'line', source: 'B2:D2', target: 'E2' },
      ])
      const written = await worksheetXml(output)
      expect(written).toMatch(/<extLst\b[^>]*>[\s\S]*<x14:sparklineGroups>[\s\S]*<\/x14:sparklineGroups><\/ext><\/extLst><\/worksheet>/)
      expect(written.match(/<extLst\b/g)).toHaveLength(1)
      if (extLst.includes('foreign')) expect(written).toContain('<ext uri="foreign"><foreign xmlns="urn:test">keep</foreign></ext>')
    },
  )

  it('keeps each line color, marker, and axis setting after writing the same kind', async () => {
    const specs = [
      { kind: 'line' as const, source: 'B2:D2', target: 'E2', color: '#FF0000', markers: true, showAxis: true },
      { kind: 'line' as const, source: 'B3:D3', target: 'E3', color: '#00FF00' },
      { kind: 'line' as const, source: 'B4:D4', target: 'E4', color: '#FF0000' },
    ]
    const output = await applySparklines(await createBlankWorkbook(), 'Sheet1', specs)
    expect(readSparklines(await worksheetXml(output))).toEqual(specs)
  })

  it('keeps column axis settings separate even when colors agree', async () => {
    const specs = [
      { kind: 'column' as const, source: 'B2:D2', target: 'E2', color: '#376092', showAxis: true },
      { kind: 'column' as const, source: 'B3:D3', target: 'E3', color: '#376092' },
    ]
    const output = await applySparklines(await createBlankWorkbook(), 'Sheet1', specs)
    expect(readSparklines(await worksheetXml(output))).toEqual(specs)
  })
})
