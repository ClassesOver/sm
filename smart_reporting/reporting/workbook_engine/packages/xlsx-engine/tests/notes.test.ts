import { describe, expect, it } from 'vitest'

import { applyCellEdits, createBlankWorkbook, readWorkbook } from '../src'
import { applySheetNotes, patchSheetNotes } from '../src/notes'
import { createBufferEntrySource } from '../src/zip'

async function hasPart(bytes: Uint8Array, path: string): Promise<boolean> {
  const source = await createBufferEntrySource(bytes)
  return source.has(path)
}

async function partOf(bytes: Uint8Array, path: string): Promise<string> {
  const source = await createBufferEntrySource(bytes)
  return source.readText(path)
}

describe('sheet notes', () => {
  it('adds notes: comments part + VML shapes + rels + legacyDrawing + content types', async () => {
    const bytes = await createBlankWorkbook()
    const edited = await applySheetNotes(bytes, 'Sheet1', [
      { row: 2, column: 1, author: 'AI', text: '这个数字需要核对' },
      { row: 4, column: 0, author: '用户', text: 'Line1\nLine2' },
    ])
    // comments part with author dedupe and CRLF-safe text
    expect(await hasPart(edited, 'xl/comments1.xml')).toBe(true)
    const comments = await partOf(edited, 'xl/comments1.xml')
    expect(comments).toContain('<comment ref="B3" authorId="0">')
    expect(comments).toContain('<comment ref="A5" authorId="1">')
    expect(comments).toContain('<author>AI</author>')
    expect(comments).toContain('Line1\nLine2')
    // VML drawing with two note shapes anchored at their cells
    expect(await hasPart(edited, 'xl/drawings/vmlDrawing1.vml')).toBe(true)
    const vml = await partOf(edited, 'xl/drawings/vmlDrawing1.vml')
    expect(vml.match(/ObjectType="Note"/g)?.length).toBe(2)
    expect(vml).toContain('<x:Row>2</x:Row><x:Column>1</x:Column>')
    // wiring
    expect(await partOf(edited, 'xl/worksheets/_rels/sheet1.xml.rels')).toContain(
      'relationships/comments',
    )
    expect(await partOf(edited, 'xl/worksheets/sheet1.xml')).toContain('<legacyDrawing r:id=')
    expect(await partOf(edited, '[Content_Types].xml')).toContain('comments+xml')
    // the workbook still opens
    expect((await readWorkbook(edited)).sheets[0]?.name).toBe('Sheet1')
  })

  it('replaces the full set: a later call rewrites shapes in place', async () => {
    const bytes = await createBlankWorkbook()
    const first = await applySheetNotes(bytes, 'Sheet1', [
      { row: 0, column: 0, author: 'A', text: 'old' },
      { row: 1, column: 1, author: 'A', text: 'old2' },
    ])
    const second = await applySheetNotes(first, 'Sheet1', [
      { row: 3, column: 2, author: 'B', text: 'new' },
    ])
    const comments = await partOf(second, 'xl/comments1.xml')
    expect(comments).toContain('<comment ref="C4" authorId="0">')
    expect(comments).not.toContain('old')
    const vml = await partOf(second, 'xl/drawings/vmlDrawing1.vml')
    expect(vml.match(/ObjectType="Note"/g)?.length).toBe(1)
  })

  it('removes all notes and cleans up parts, rels, and content types', async () => {
    const bytes = await createBlankWorkbook()
    const withNotes = await applySheetNotes(bytes, 'Sheet1', [
      { row: 0, column: 0, author: 'A', text: 'bye' },
    ])
    const cleaned = await applySheetNotes(withNotes, 'Sheet1', [])
    expect(await hasPart(cleaned, 'xl/comments1.xml')).toBe(false)
    expect(await hasPart(cleaned, 'xl/drawings/vmlDrawing1.vml')).toBe(false)
    const rels = await partOf(cleaned, 'xl/worksheets/_rels/sheet1.xml.rels')
    expect(rels).not.toContain('comments')
    expect(await partOf(cleaned, 'xl/worksheets/sheet1.xml')).not.toContain('<legacyDrawing')
    expect((await readWorkbook(cleaned)).sheets[0]?.name).toBe('Sheet1')
  })

  it('preserves non-note VML shapes across a rewrite', async () => {
    const bytes = await createBlankWorkbook()
    const first = await applySheetNotes(bytes, 'Sheet1', [
      { row: 0, column: 0, author: 'A', text: 'note1' },
    ])
    // inject a foreign (non-note) shape into the VML part
    const vml = await partOf(first, 'xl/drawings/vmlDrawing1.vml')
    const foreign =
      '<v:shape id="_x0000_s9001" style="position:absolute"><v:textbox><div>button</div></v:textbox></v:shape>'
    const patched = vml.replace('</xml>', `${foreign}</xml>`)
    const { assemblePackage } = await import('../src/zip')
    const withForeign = await assemblePackage(first, {
      replaced: new Map([['xl/drawings/vmlDrawing1.vml', patched]]),
      added: new Map(),
      addedBinary: new Map(),
      removedEntries: [],
      addedEntries: [],
      touchedEntries: ['xl/drawings/vmlDrawing1.vml'],
    })
    const rewritten = await applySheetNotes(withForeign.buffer, 'Sheet1', [
      { row: 5, column: 5, author: 'A', text: 'note2' },
    ])
    const after = await partOf(rewritten, 'xl/drawings/vmlDrawing1.vml')
    expect(after).toContain('button') // foreign shape survived
    expect(after).toContain('<x:Row>5</x:Row><x:Column>5</x:Column>') // new note anchor
    expect(after).not.toContain('<x:Row>0</x:Row><x:Column>0</x:Column>') // old note gone
    const comments = await partOf(rewritten, 'xl/comments1.xml')
    expect(comments).toContain('note2')
    expect(comments).not.toContain('note1')
  })

  it('rejects unknown sheets', async () => {
    const bytes = await createBlankWorkbook()
    await expect(
      applySheetNotes(bytes, 'Nope', [{ row: 0, column: 0, author: 'A', text: 'x' }]),
    ).rejects.toThrow(/不存在/)
  })
})
