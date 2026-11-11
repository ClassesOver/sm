import { expect, it } from 'vitest'
import JSZip from 'jszip'
import { createBlankWorkbook } from '../src/blank'
import { readWorkbook } from '../src/workbook-read'
const modulePath = '../src/outline'
it('patches row and split-column outline attributes while retaining unrelated geometry and package parts', async () => {
  const { applySheetOutline } = await import(/* @vite-ignore */ modulePath)
  const zip = await JSZip.loadAsync(await createBlankWorkbook()),
    path = 'xl/worksheets/sheet1.xml'
  const xml = await zip.file(path)!.async('string')
  zip.file(
    path,
    xml.replace(
      '<sheetData/>',
      '<cols><col min="1" max="5" width="18" style="2" customWidth="1"/></cols><sheetData><row r="2" ht="24" s="1" customHeight="1"><c r="A2"><v>7</v></c></row></sheetData>'
    )
  )
  const original = await zip.generateAsync({ type: 'uint8array' })
  const saved = await applySheetOutline(original, 'Sheet1', {
    rows: [
      { index: 1, level: 2, collapsed: false, hidden: true },
      { index: 2, level: 0, collapsed: true }
    ],
    columns: [{ index: 2, level: 1, collapsed: false, hidden: true }]
  })
  const result = await JSZip.loadAsync(saved),
    after = await result.file(path)!.async('string')
  expect(after).toContain('ht="24"')
  expect(after).toContain('s="1"')
  expect(after).toContain('<v>7</v>')
  expect(after).toMatch(/<col min="3" max="3"[^>]*width="18"[^>]*outlineLevel="1"[^>]*hidden="1"/)
  const model = await readWorkbook(saved)
  expect(model.sheets[0]!.rows.find((r) => r.row === 2)).toMatchObject({ outlineLevel: 2, hidden: true })
  expect(model.sheets[0]!.rows.find((r) => r.row === 3)).toMatchObject({ collapsed: true })
  for (const name of Object.keys(zip.files).filter((name) => name !== path))
    expect(await result.file(name)?.async('uint8array')).toEqual(await zip.file(name)?.async('uint8array'))
})
it('clears existing outline and hidden attributes without duplicates and updates outline maxima', async () => {
  const { setSheetOutlineXml } = await import(/* @vite-ignore */ modulePath)
  const xml =
    '<worksheet><sheetFormatPr defaultRowHeight="15" outlineLevelRow="3"/><cols><col min="1" max="2" width="8" outlineLevel="2" hidden="1" collapsed="1"/></cols><sheetData><row r="1" outlineLevel="3" hidden="1" collapsed="1"/></sheetData></worksheet>'
  const saved = setSheetOutlineXml(xml, {
    rows: [{ index: 0, level: 0, collapsed: false, hidden: false }],
    columns: [
      { index: 0, level: 1, collapsed: false, hidden: false },
      { index: 1, level: 0, collapsed: false, hidden: false }
    ]
  })
  expect(saved).not.toContain('outlineLevelRow=')
  expect(saved).toContain('outlineLevelCol="1"')
  expect(saved).not.toContain('hidden=')
  expect(saved).not.toContain('collapsed=')
  expect(saved).not.toContain('outlineLevel="2"')
  expect(saved).not.toContain('outlineLevel="3"')
})
it('patches thousands of existing rows in one pass and preserves explicit empty cols plus comments', async () => {
  const { setSheetOutlineXml } = await import(/* @vite-ignore */ modulePath)
  const rows = Array.from(
    { length: 4000 },
    (_, i) => `<row r="${i + 1}" ht="19"><c r="A${i + 1}"><v>${i}</v></c></row>`
  ).join('')
  const xml = `<worksheet><cols><!--column metadata--><col min="1" max="3" width="9"></col></cols><sheetData>${rows}</sheetData></worksheet>`
  const saved = setSheetOutlineXml(xml, {
    rows: Array.from({ length: 4000 }, (_, index) => ({ index, level: 1, collapsed: false })),
    columns: [{ index: 1, level: 2, collapsed: false }]
  })
  expect([...saved.matchAll(/outlineLevel="1"/g)]).toHaveLength(4000)
  expect(saved).toContain('<!--column metadata-->')
  expect(saved).toContain('width="9" outlineLevel="2"')
  expect(saved).toContain('<c r="A4000"><v>3999</v></c>')
})
it('patches an explicitly closed sheetFormatPr without duplicating it or losing its attributes',async()=>{
 const {setSheetOutlineXml}=await import(/* @vite-ignore */ modulePath)
 const xml='<worksheet><sheetFormatPr defaultRowHeight="20" baseColWidth="12"></sheetFormatPr><sheetData/></worksheet>'
 const saved=setSheetOutlineXml(xml,{rows:[{index:0,level:2,collapsed:false}]})
 expect([...saved.matchAll(/<sheetFormatPr\b/g)]).toHaveLength(1)
 expect(saved).toContain('defaultRowHeight="20"');expect(saved).toContain('baseColWidth="12"');expect(saved).toContain('outlineLevelRow="2"')
})
it('patches summary directions with sheetPr children and every unrelated ZIP part intact', async () => {
  const { applySheetOutline } = await import(/* @vite-ignore */ modulePath)
  const zip = await JSZip.loadAsync(await createBlankWorkbook()), path = 'xl/worksheets/sheet1.xml'
  zip.file(path, (await zip.file(path)!.async('string')).replace('<sheetData/>',
    '<sheetPr codeName="Kept"><tabColor rgb="FF123456"/><outlinePr applyStyles="1" summaryBelow="1"></outlinePr><pageSetUpPr fitToPage="1"/></sheetPr><sheetData/>'))
  const original = await zip.generateAsync({ type: 'uint8array' })
  const saved = await applySheetOutline(original, 'Sheet1', { summaryBelow: false, summaryRight: false })
  const result = await JSZip.loadAsync(saved), xml = await result.file(path)!.async('string')
  expect(xml).toContain('applyStyles="1"')
  expect(xml).toContain('codeName="Kept"')
  expect(xml).toContain('<tabColor rgb="FF123456"/>')
  expect(xml).toContain('<pageSetUpPr fitToPage="1"/>')
  expect([...xml.matchAll(/summaryBelow=/g)]).toHaveLength(1)
  expect((await readWorkbook(saved)).sheets[0]).toMatchObject({ outlineSummaryBelow: false, outlineSummaryRight: false })
  for (const name of Object.keys(zip.files).filter((name) => name !== path))
    expect(await result.file(name)?.async('uint8array')).toEqual(await zip.file(name)?.async('uint8array'))
})
it('creates missing summary properties in schema order and rejects nonboolean summary direction', async () => {
  const { setSheetOutlineXml } = await import(/* @vite-ignore */ modulePath)
  for (const properties of ['', '<sheetPr codeName="X"/>', '<sheetPr><pageSetUpPr fitToPage="1"/></sheetPr>']) {
    const saved = setSheetOutlineXml(`<worksheet>${properties}<sheetViews/><sheetData/></worksheet>`, { summaryBelow: false })
    expect(saved).toContain('<outlinePr summaryBelow="0"/>')
    expect(saved.indexOf('<outlinePr')).toBeLessThan(saved.indexOf('<sheetViews'))
    if (properties.includes('pageSetUpPr')) expect(saved.indexOf('<outlinePr')).toBeLessThan(saved.indexOf('<pageSetUpPr'))
  }
  expect(() => setSheetOutlineXml('<worksheet><sheetData/></worksheet>', { summaryBelow: '0' } as any)).toThrow('方向')
})
