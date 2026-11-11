// @vitest-environment jsdom
import { Editor } from '@tiptap/core'
import { describe, expect, it } from 'vitest'
import { parseDocx, readSections } from '@genoffice/docx-engine'
import { buildDocx } from '../../../reporting/doc_engine/packages/docx-engine/tests/helpers/build-docx'
import { assertDocxCaptionBatch, createDocxCaption, NativeDocxCaption, normalizeDocxCaption, replayDocxCaption } from './docx-caption'
import { blocksToPmDoc, pmDocOptions } from './vendor/genoffice-docs/apps/docs/src/renderer/editor/convert'
import { editorExtensions } from './vendor/genoffice-docs/apps/docs/src/renderer/editor/extensions'

describe('native Word caption controls', () => {
  it('disables a caption before an existing same-label sequence', async () => {
    const sequence='<w:p><w:r><w:fldChar w:fldCharType="begin"/></w:r><w:r><w:instrText> SEQ 图 '+String.fromCharCode(92)+'* ARABIC </w:instrText></w:r><w:r><w:fldChar w:fldCharType="separate"/></w:r><w:r><w:t>1</w:t></w:r><w:r><w:fldChar w:fldCharType="end"/></w:r></w:p>'
    const parsed=await parseDocx(await buildDocx({bodyXml:'<w:p><w:r><w:t>Before</w:t></w:r></w:p>'+sequence}))
    const source=createDocxCaption(parsed,[{docxIndex:0,blockId:'a'.repeat(64),expectedObjectSha256:'b'.repeat(64)}])
    const editor=new Editor({extensions:[...editorExtensions,NativeDocxCaption],content:blocksToPmDoc(parsed.blocks,readSections(parsed),pmDocOptions(parsed))})
    try {const controls=source.controls(editor,()=>[],()=>{});expect(controls.reason('图','')).toContain('最后一个题注');expect(controls.reason('表','')).toBeNull()}finally{editor.destroy()}
  })
  it('projects a source-bound caption in one undo transaction and restores a validated draft', async () => {
    const parsed = await parseDocx(await buildDocx({ bodyXml: '<w:p><w:r><w:t>Anchor</w:t></w:r></w:p>' }))
    const anchors = [{docxIndex: 0, blockId: 'a'.repeat(64), expectedObjectSha256: 'b'.repeat(64)}]
    const source = createDocxCaption(parsed, anchors)
    const editor = new Editor({ extensions: [...editorExtensions, NativeDocxCaption], content: blocksToPmDoc(parsed.blocks, readSections(parsed), pmDocOptions(parsed)) })
    try {
      const baseline = editor.getJSON(), errors: unknown[] = []
      const controls = source.controls(editor, () => [], e => errors.push(e))
      expect(controls.reason('图', '收入 & 利润')).toBeNull()
      expect(controls.preview('图', '收入 & 利润')).toEqual({ number: 1, display: '图 1 收入 & 利润' })
      controls.run('图', '收入 & 利润')
      expect(errors).toEqual([])
      const current = editor.getJSON(), generated = current.content?.[0]
      expect(generated?.attrs?.fieldDisplay).toEqual({kind: 'text', left: '图 1 收入 & 利润'})
      expect(generated?.attrs?.genXml).toContain('收入 &amp; 利润')
      const normalized = normalizeDocxCaption(baseline, current, source, editor.schema)
      expect(normalized.current).toEqual(baseline)
      expect(normalized.operations).toEqual([{ kind: 'insertCaption', blockId: 'a'.repeat(64), expectedObjectSha256: 'b'.repeat(64), position: 'before', label: '图', text: '收入 & 利润' }])
      expect(replayDocxCaption(baseline, normalized.operations, source, editor.schema)).toEqual(current)
      expect(editor.commands.undo()).toBe(true)
      expect(editor.getJSON()).toEqual(baseline)
      expect(editor.commands.redo()).toBe(true)
      expect(editor.getJSON()).toEqual(current)
      const tampered = structuredClone(current)
      tampered.content![0]!.attrs!.genXml = '<w:p/>'
      expect(() => normalizeDocxCaption(baseline, tampered, source, editor.schema)).toThrow(/题注结构/)
      expect(() => replayDocxCaption(baseline, [...normalized.operations, {kind:'replaceText'}], source, editor.schema)).toThrow(/单独保存/)
    } finally { editor.destroy() }
  })
  it('refuses mixed operations, stale anchors, locked state and selection in prose', async () => {
    const parsed = await parseDocx(await buildDocx({bodyXml: '<w:p><w:r><w:t>Anchor</w:t></w:r></w:p>'}))
    const source = createDocxCaption(parsed, [{docxIndex: 0, blockId: 'a'.repeat(64), expectedObjectSha256: 'b'.repeat(64)}])
    const editor = new Editor({extensions: [...editorExtensions, NativeDocxCaption], content: blocksToPmDoc(parsed.blocks, readSections(parsed), pmDocOptions(parsed))})
    try {
      const controls = source.controls(editor, () => [{kind:'replaceText'}], () => {})
      expect(controls.reason('图', '')).toContain('单独保存')
      const clean = source.controls(editor, () => [], () => {})
      editor.commands.setTextSelection(2)
      expect(clean.reason('图', '')).toContain('开头或结尾')
      editor.setEditable(false)
      expect(clean.reason('图', '')).toContain('不可编辑')
      expect(() => assertDocxCaptionBatch([{kind:'insertCaption'}, {kind:'insertCaption'}])).toThrow()
      expect(() => replayDocxCaption(editor.getJSON(), [{kind:'insertCaption',blockId:'c'.repeat(64),expectedObjectSha256:'b'.repeat(64),position:'before',label:'图',text:''}], source, editor.schema)).toThrow(/锚点/)
    } finally { editor.destroy() }
  })
})
