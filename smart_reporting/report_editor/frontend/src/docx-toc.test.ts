// @vitest-environment jsdom
import { Editor } from '@tiptap/core'
import { describe, expect, it } from 'vitest'
import { parseDocx } from '@genoffice/docx-engine'
import { buildDocx } from '../../../reporting/doc_engine/packages/docx-engine/tests/helpers/build-docx'
import { createDocxToc, NativeDocxToc, normalizeDocxToc, replayDocxToc } from './docx-toc'
import { blocksToPmDoc, pmDocOptions } from './vendor/genoffice-docs/apps/docs/src/renderer/editor/convert'
import { editorExtensions } from './vendor/genoffice-docs/apps/docs/src/renderer/editor/extensions'
import { readSections } from '@genoffice/docx-engine'

describe('native Word TOC controls', () => {
  it('creates an undoable directory with a source-bound operation that replays exactly', async () => {
    const bodyXml = '<w:p><w:r><w:t>Anchor</w:t></w:r></w:p>'
      + '<w:p><w:pPr><w:outlineLvl w:val="0"/></w:pPr><w:r><w:t>Heading</w:t></w:r></w:p>'
    const parsed = await parseDocx(await buildDocx({ bodyXml }))
    const anchors = parsed.blocks.flatMap(block => block.docxIndex == null ? [] : [{ docxIndex: block.docxIndex, blockId: 'a'.repeat(63) + block.docxIndex, expectedObjectSha256: 'b'.repeat(64) }])
    const source = createDocxToc(parsed, anchors)
    const editor = new Editor({ extensions: [...editorExtensions, NativeDocxToc], content: blocksToPmDoc(parsed.blocks, readSections(parsed), pmDocOptions(parsed)) })
    try {
      const baseline = editor.getJSON()
      const controls = source.controls(editor, () => [], error => { throw error })
      expect(controls.reason('updateToc')).toContain('没有')
      expect(controls.reason('insertToc')).toBeNull()
      controls.run('insertToc')
      const current = editor.getJSON()
      expect(current.content?.[0]?.attrs?.fieldDisplay).toMatchObject({ kind: 'tocLine', left: 'Heading' })
      const normalized = normalizeDocxToc(baseline, current, source, editor.schema)
      expect(normalized.current).toEqual(baseline)
      expect(normalized.operations).toEqual([{ kind: 'insertToc', blockId: 'a'.repeat(63) + '0', expectedObjectSha256: 'b'.repeat(64), position: 'before' }])
      expect(replayDocxToc(baseline, normalized.operations, source, editor.schema)).toEqual(current)
      expect(editor.commands.undo()).toBe(true)
      expect(editor.getJSON()).toEqual(baseline)
    } finally { editor.destroy() }
  })
})
