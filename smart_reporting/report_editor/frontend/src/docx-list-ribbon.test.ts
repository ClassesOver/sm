import { expect, it } from 'vitest'
import { Editor } from '@tiptap/core'
import { editorExtensions } from './vendor/genoffice-docs/apps/docs/src/renderer/editor/extensions'
import { NativeDocxCustomList } from './docx-custom-list'
import { NativeRibbonStyle } from './docx-style-majority'
import { NativeDocxRulerIndent } from './docx-ruler-indent'
import { NativeDocxTabStops } from './docx-tab-stops'
import { createDocxRibbon } from './docx-ribbon'
import { docxOperations } from './docx-operations'

it.each([['bullets', 'bullet'], ['numbering', 'ordered']] as const)(
  '真实扩展下 %s 保留来源身份、段落布局和文字，并可还原普通段落', (action, kind) => {
    const host = document.createElement('div'); document.body.append(host)
    const editor = new Editor({ element: host,
      extensions: [...editorExtensions, NativeRibbonStyle, NativeDocxRulerIndent, NativeDocxTabStops, NativeDocxCustomList],
      editorProps: { handleScrollToSelection: () => true },
      content: { type: 'doc', content: [{ type: 'docParagraph', attrs: { docxIndex: 7, align: 'center', spaceBefore: 240 },
        content: [{ type: 'text', text: '来源正文', marks: [{ type: 'bold' }] }] }] },
    })
    const anchor = { docxIndex: 7, blockId: 'source-body', expectedObjectSha256: 'source-sha', editable: true }
    const ribbon = createDocxRibbon(editor, true, undefined, undefined, undefined, [anchor])
    document.body.append(ribbon)
    try {
      const baseline = editor.getJSON()
      editor.commands.setTextSelection(2)
      ribbon.querySelector<HTMLButtonElement>(`[data-action="${action}"]`)!.click()
      const current = editor.getJSON()
      expect(current.content![0].type).toBe('docListItem')
      expect(current.content![0].attrs).toMatchObject({ docxIndex: 7, align: 'center', spaceBefore: 240 })
      expect(current.content![0].content).toEqual(baseline.content![0].content)
      expect(docxOperations(baseline, current, [anchor])).toEqual([
        { kind: 'setParagraphNumberingValue', blockId: 'source-body', expectedObjectSha256: 'source-sha', binding: current.content![0].attrs!.nativeNumberingBinding, ilvl: 0, listKind: kind },
      ])
      ribbon.querySelector<HTMLButtonElement>(`[data-action="${action}"]`)!.click()
      expect(editor.getJSON()).toEqual(baseline)
    } finally { editor.destroy(); host.remove(); ribbon.remove() }
  },
)

it.each([
  ['nativeCoverPage', true],
  ['nativeRibbonStyle', true],
  ['nativeRulerIndent', { leftTwips: 240 }],
  ['nativeTabStops', []],
] as const)('列表转换不能忽略非空 %s 意图', (key, value) => {
  const paragraph = { type: 'docParagraph', attrs: { docxIndex: 7, [key]: value }, content: [{ type: 'text', text: '来源正文' }] }
  const current = { ...paragraph, type: 'docListItem', attrs: { docxIndex: 7, kind: 'bullet', numId: 'native-bullet', ilvl: 0 } }
  const anchor = { docxIndex: 7, blockId: 'source-body', expectedObjectSha256: 'source-sha', editable: true }
  expect(() => docxOperations({ type: 'doc', content: [paragraph] }, { type: 'doc', content: [current] }, [anchor]))
    .toThrow('暂不支持改变段落布局')
})
