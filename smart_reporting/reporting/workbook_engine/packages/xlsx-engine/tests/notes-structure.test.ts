import { expect, it } from 'vitest'
import { spawnSync } from 'node:child_process'
import { existsSync, mkdtempSync, readFileSync, writeFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { applyRowColumnOps, applySheetNotes, createBlankWorkbook, readWorkbook, patchSheetNotes } from '../src'
import { assemblePackage, createBufferEntrySource } from '../src/zip'

it('shifts adjacent identical comments once, shifts note anchors, and rejects stale identities', async () => {
  const bytes = await applySheetNotes(await createBlankWorkbook(), 'Sheet1', [{ row: 0, column: 0, author: 'A', text: 'same' }, { row: 1, column: 0, author: 'A', text: 'same' }])
  const identity = (await readWorkbook(bytes)).sheets[0]!.notes!.sourceIdentity
  const shifted = await applyRowColumnOps(bytes, 'Sheet1', [{ kind: 'insert-rows', index: 0, count: 1 }])
  const model = (await readWorkbook(shifted)).sheets[0]!.notes!
  expect(model.readOnlyReason).toBeUndefined()
  expect(model.notes.map(n => n.row)).toEqual([1, 2])
  const source = await createBufferEntrySource(shifted)
  expect(await source.readText('xl/drawings/vmlDrawing1.vml')).toContain('<x:Anchor>1,15,1,2,4,15,5,2</x:Anchor>')
  await expect(patchSheetNotes(shifted, 'Sheet1', identity, [{ row: 1, column: 0, text: 'wrong identity' }])).rejects.toThrow('身份')
  const edited = await patchSheetNotes(shifted, 'Sheet1', model.sourceIdentity, [{ row: 1, column: 0, text: 'correct' }])
  expect((await readWorkbook(edited)).sheets[0]!.notes!.notes[0]!.author).toBe('A')
})

it('rejects note shifts outside XLSX row and column limits atomically', async () => {
  for (const note of [{ row: 1048575, column: 0, kind: 'insert-rows' }, { row: 0, column: 16383, kind: 'insert-cols' }]) {
    const bytes = await applySheetNotes(await createBlankWorkbook(), 'Sheet1', [{ row: note.row, column: note.column, author: 'A', text: 'limit' }])
    const before = bytes.slice()
    await expect(applyRowColumnOps(bytes, 'Sheet1', [{ kind: note.kind as 'insert-rows', index: 0, count: 1 }])).rejects.toThrow('边界')
    expect(bytes).toEqual(before)
  }
})

it('real openpyxl row/column insert and delete preserve authors, foreign VML, other sheets and source bytes', async () => {
  const dir = mkdtempSync(join(tmpdir(), 'notes-structure-'))
  // venv 位置随运行目录变化：自 process.cwd() 向上探测仓库根的 .venv。
  const python = (() => {
    let dir = process.cwd()
    for (let i = 0; i < 6; i += 1) {
      const candidate = resolve(dir, '.venv/bin/python')
      if (existsSync(candidate)) return candidate
      dir = resolve(dir, '..')
    }
    return 'python3'
  })()
  const sourcePath = join(dir, 'source.xlsx')
  const shiftedPath = join(dir, 'shifted.xlsx')
  const deletedPath = join(dir, 'deleted.xlsx')
  try {
    const created = spawnSync(python, ['-I', '-c', `from openpyxl import Workbook\nfrom openpyxl.comments import Comment\nimport sys\nw=Workbook();s=w.active;s.title='Notes'\ns['A1'].comment=Comment('same','Alice');s['A2'].comment=Comment('same','Alice');s['C4'].comment=Comment('tail','Bob')\nw.create_sheet('Other')['D5'].comment=Comment('keep','Carol')\nw.save(sys.argv[1])`, sourcePath], { encoding: 'utf8' })
    expect(created.status, created.stderr).toBe(0)
    const original = new Uint8Array(readFileSync(sourcePath))
    const originalSource = await createBufferEntrySource(original)
    const vmlPath = (await originalSource.paths()).find(p => p.endsWith('commentsDrawing1.vml'))!
    const drawing = await originalSource.readText(vmlPath)
    const foreign = '<v:shape xmlns:v="urn:schemas-microsoft-com:vml" id="foreign"><v:textbox><div>keep exactly</div></v:textbox></v:shape>'
    const anchor = '<ns2:Anchor xmlns:ns2="urn:schemas-microsoft-com:office:excel">0,1,0,2,3,4,4,5</ns2:Anchor>'
    const withAnchors = drawing.replace(/(<(?:[\w.-]+:)?ClientData\b[^>]*>)/g, '$1' + anchor).replace('</xml>', foreign + '</xml>')
    const bytes = (await assemblePackage(original, { replaced: new Map([[vmlPath, withAnchors]]), added: new Map(), addedBinary: new Map(), removedEntries: [], addedEntries: [], touchedEntries: [vmlPath] })).buffer
    const shifted = await applyRowColumnOps(bytes, 'Notes', [{ kind: 'insert-rows', index: 0, count: 1 }, { kind: 'insert-cols', index: 0, count: 2 }])
    writeFileSync(shiftedPath, shifted)
    const model = (await readWorkbook(shifted)).sheets[0]!.notes!
    expect(model.readOnlyReason).toBeUndefined()
    expect(model.notes).toEqual([{ row: 1, column: 2, author: 'Alice', text: 'same' }, { row: 2, column: 2, author: 'Alice', text: 'same' }, { row: 4, column: 4, author: 'Bob', text: 'tail' }])
    const shiftedSource = await createBufferEntrySource(shifted)
    const vml = await shiftedSource.readText(vmlPath)
    expect(vml).toContain(foreign)
    expect(vml).toContain('>2,1,1,2,5,4,5,5</ns2:Anchor>')
    expect(await shiftedSource.readText('xl/comments/comment2.xml')).toBe(await originalSource.readText('xl/comments/comment2.xml'))
    const deleted = await applyRowColumnOps(shifted, 'Notes', [{ kind: 'remove-rows', index: 1, count: 1 }, { kind: 'remove-cols', index: 4, count: 1 }])
    writeFileSync(deletedPath, deleted)
    expect((await readWorkbook(deleted)).sheets[0]!.notes!.notes).toEqual([{ row: 1, column: 2, author: 'Alice', text: 'same' }])
    const checked = spawnSync(python, ['-I', '-c', `from openpyxl import load_workbook\nimport sys\na=load_workbook(sys.argv[1]);b=load_workbook(sys.argv[2])\nassert a['Notes']['C2'].comment.author=='Alice'\nassert a['Notes']['C3'].comment.text=='same'\nassert a['Notes']['E5'].comment.author=='Bob'\nassert b['Notes']['C2'].comment.author=='Alice'\nassert b['Notes']['E4'].comment is None\nassert b['Other']['D5'].comment.author=='Carol'`, shiftedPath, deletedPath], { encoding: 'utf8' })
    expect(checked.status, checked.stderr).toBe(0)
    expect(new Uint8Array(readFileSync(sourcePath))).toEqual(original)
    const last = await applyRowColumnOps(deleted, 'Notes', [{ kind: 'remove-rows', index: 1, count: 1 }])
    const lastSource = await createBufferEntrySource(last)
    expect(await lastSource.has('xl/comments/comment1.xml')).toBe(false)
    expect(await lastSource.readText(vmlPath)).toContain(foreign)
    expect(await lastSource.readText('[Content_Types].xml')).not.toContain('PartName="/xl/comments/comment1.xml"')
  } finally { rmSync(dir, { recursive: true, force: true }) }
})


it('retains the existing Pict-only VML structural path without requiring a comments collection', async () => {
  const bytes = await createBlankWorkbook()
  const source = await createBufferEntrySource(bytes)
  const drawingPath = 'xl/drawings/controls.vml'
  const drawing = '<xml xmlns:v="urn:schemas-microsoft-com:vml" xmlns:x="urn:schemas-microsoft-com:office:excel"><v:shape id="control"><x:ClientData ObjectType="Pict"><x:Anchor>0,1,0,2,3,4,4,5</x:Anchor></x:ClientData></v:shape></xml>'
  const relsPath = 'xl/worksheets/_rels/sheet1.xml.rels'
  const rels = '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="pict" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/vmlDrawing" Target="../drawings/controls.vml"/></Relationships>'
  const sheet = (await source.readText('xl/worksheets/sheet1.xml')).replace('</worksheet>', '<legacyDrawing r:id="pict"/></worksheet>')
  const patched = (await assemblePackage(bytes, { replaced: new Map([['xl/worksheets/sheet1.xml', sheet]]), added: new Map([[drawingPath, drawing], [relsPath, rels]]), addedBinary: new Map(), removedEntries: [], addedEntries: [drawingPath, relsPath], touchedEntries: ['xl/worksheets/sheet1.xml', drawingPath, relsPath] })).buffer
  const moved = await applyRowColumnOps(patched, 'Sheet1', [{ kind: 'insert-rows', index: 0, count: 1 }, { kind: 'insert-cols', index: 0, count: 2 }])
  const readback = await createBufferEntrySource(moved)
  expect(await readback.readText(drawingPath)).toContain('<x:Anchor>2, 1, 1, 2, 5, 4, 5, 5</x:Anchor>')
  expect(await readback.readText(relsPath)).toBe(rels)
})

it('deleting the final note by structure removes only its parts and content type registration', async () => {
  const bytes = await applySheetNotes(await createBlankWorkbook(), 'Sheet1', [{ row: 1, column: 1, author: 'Author', text: 'last' }])
  const original = bytes.slice()
  const deleted = await applyRowColumnOps(bytes, 'Sheet1', [{ kind: 'remove-cols', index: 1, count: 1 }])
  const source = await createBufferEntrySource(deleted)
  expect(await source.has('xl/comments1.xml')).toBe(false)
  expect(await source.has('xl/drawings/vmlDrawing1.vml')).toBe(false)
  expect(await source.readText('xl/worksheets/sheet1.xml')).not.toContain('<legacyDrawing')
  expect(await source.readText('xl/worksheets/_rels/sheet1.xml.rels')).not.toContain('/comments')
  expect(await source.readText('[Content_Types].xml')).not.toContain('PartName="/xl/comments1.xml"')
  expect((await readWorkbook(deleted)).sheets[0]!.notes!.notes).toEqual([])
  expect(bytes).toEqual(original)
})
