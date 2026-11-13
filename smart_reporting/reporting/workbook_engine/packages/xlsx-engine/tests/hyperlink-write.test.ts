import { describe, expect, it } from 'vitest'
import { createBlankWorkbook } from '../src/blank'
import { applySheetHyperlinks, cellHyperlinkState, readPackageSheetHyperlinks, readSheetHyperlinks } from '../src/hyperlink-write'
import { assemblePackage, createBufferEntrySource } from '../src/zip'

const text = async (bytes: Uint8Array, path: string) => (await createBufferEntrySource(bytes)).readText(path)
const has = async (bytes: Uint8Array, path: string) => (await createBufferEntrySource(bytes)).has(path)

describe('applySheetHyperlinks (local adapter over the pinned writer)', () => {
  it('adds external and internal links bound to the empty source state, then edits and removes them', async () => {
    const source = await createBlankWorkbook('数据 表')
    expect(await readPackageSheetHyperlinks(source, '数据 表')).toEqual([])
    const linked = await applySheetHyperlinks(source, '数据 表', [
      { ref: 'A1', expectedTarget: null, target: 'https://example.com/a?b=1&c=2' },
      { ref: 'B2', expectedTarget: null, target: "#'数据 表'!C3" },
      { ref: 'C1', expectedTarget: null, target: 'mailto:team@example.com' },
    ])
    const links = await readPackageSheetHyperlinks(linked, '数据 表')
    expect(links.map(link => [link.ref, link.target, link.readOnlyReason])).toEqual([
      ['A1', 'https://example.com/a?b=1&c=2', null], ['B2', "#'数据 表'!C3", null], ['C1', 'mailto:team@example.com', null],
    ])
    expect(await text(linked, 'xl/worksheets/_rels/sheet1.xml.rels')).toContain('Target="https://example.com/a?b=1&amp;c=2" TargetMode="External"')
    expect(await text(linked, 'xl/worksheets/sheet1.xml')).toContain(`<hyperlink ref="B2" location="'数据 表'!C3"/>`)
    const edited = await applySheetHyperlinks(linked, '数据 表', [
      { ref: 'A1', expectedTarget: 'https://example.com/a?b=1&c=2', target: 'https://example.org/' },
      { ref: 'C1', expectedTarget: 'mailto:team@example.com', target: null },
    ])
    const after = await readPackageSheetHyperlinks(edited, '数据 表')
    expect(after.map(link => [link.ref, link.target])).toEqual([['B2', "#'数据 表'!C3"], ['A1', 'https://example.org/']])
    const rels = await text(edited, 'xl/worksheets/_rels/sheet1.xml.rels')
    expect(rels).not.toContain('example.com'); expect(rels).not.toContain('mailto:')
    const cleared = await applySheetHyperlinks(edited, '数据 表', [
      { ref: 'A1', expectedTarget: 'https://example.org/', target: null }, { ref: 'B2', expectedTarget: "#'数据 表'!C3", target: null },
    ])
    expect(await text(cleared, 'xl/worksheets/sheet1.xml')).not.toContain('<hyperlinks')
    expect(await has(cleared, 'xl/worksheets/_rels/sheet1.xml.rels')).toBe(true)
  })

  it('rejects stale identities, unchanged targets, unsafe or dangling targets and duplicate cells without writing', async () => {
    const source = await createBlankWorkbook('Sheet1')
    const linked = await applySheetHyperlinks(source, 'Sheet1', [{ ref: 'A1', expectedTarget: null, target: 'https://example.com' }])
    const reject = (bytes: Uint8Array, edits: Parameters<typeof applySheetHyperlinks>[2], pattern: RegExp) => expect(applySheetHyperlinks(bytes, 'Sheet1', edits)).rejects.toThrow(pattern)
    await reject(linked, [{ ref: 'A1', expectedTarget: null, target: 'https://other.example' }], /已变化/)
    await reject(linked, [{ ref: 'A1', expectedTarget: 'https://example.com', target: 'https://example.com' }], /没有变化/)
    for (const target of ['javascript:alert(1)', 'file:///etc/passwd', 'https://exa mple.com', '#Missing!A1', '#Sheet1!A0', '#Sheet1', 'x'.repeat(2084)]) {
      await reject(source, [{ ref: 'B1', expectedTarget: null, target }], /链接/)
    }
    await reject(source, [{ ref: 'B1', expectedTarget: null, target: 'https://a.example' }, { ref: 'B1', expectedTarget: null, target: 'https://b.example' }], /重复/)
    await reject(source, [{ ref: 'a1', expectedTarget: null, target: 'https://a.example' }], /无效/)
    await expect(applySheetHyperlinks(source, 'Nope', [{ ref: 'A1', expectedTarget: null, target: 'https://a.example' }])).rejects.toThrow(/不存在/)
    await expect(applySheetHyperlinks(source, 'Sheet1', [])).rejects.toThrow(/1–1000/)
  })

  it('keeps range links and mixed links read-only and refuses edits on cells they cover', async () => {
    const source = await createBlankWorkbook('Sheet1')
    const sheet = await text(source, 'xl/worksheets/sheet1.xml')
    const withRange = sheet.replace('</worksheet>', '<hyperlinks><hyperlink ref="A1:B2" location="Sheet1!D4"/><hyperlink ref="C3" r:id="rId9" location="x"/></hyperlinks></worksheet>')
    const bytes = (await assemblePackage(source, { replaced: new Map([['xl/worksheets/sheet1.xml', withRange]]), added: new Map(), addedBinary: new Map(), removedEntries: [], addedEntries: [], touchedEntries: ['xl/worksheets/sheet1.xml'] })).buffer
    const links = readSheetHyperlinks(withRange, null)
    expect(links.map(link => link.readOnlyReason !== null)).toEqual([true, true])
    expect(() => cellHyperlinkState(links, 1, 1)).toThrow(/区域链接/)
    expect(cellHyperlinkState(links, 5, 5)).toBeNull()
    await expect(applySheetHyperlinks(bytes, 'Sheet1', [{ ref: 'B2', expectedTarget: null, target: 'https://a.example' }])).rejects.toThrow(/区域链接/)
    const added = await applySheetHyperlinks(bytes, 'Sheet1', [{ ref: 'E5', expectedTarget: null, target: 'https://a.example' }])
    const after = await readPackageSheetHyperlinks(added, 'Sheet1')
    expect(after.map(link => link.ref)).toEqual(['A1:B2', 'C3', 'E5'])
  })
})
