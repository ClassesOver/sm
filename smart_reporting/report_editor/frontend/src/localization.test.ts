import { describe, expect, it } from 'vitest'
import { outline } from '@milkdown/kit/utils'

import {
  editorChineseLocale,
  formatRevisionLabel,
} from './localization'
import { createReportEditor } from './editor-features'

describe('editorChineseLocale', () => {
  it('provides Chinese labels for every visible Crepe editing surface', () => {
    expect(editorChineseLocale.blockEdit).toMatchObject({
      textGroup: {
        label: '文本',
        text: { label: '正文' },
        h1: { label: '一级标题' },
        quote: { label: '引用' },
        divider: { label: '分隔线' },
      },
      listGroup: {
        label: '列表',
        bulletList: { label: '项目符号列表' },
        orderedList: { label: '编号列表' },
        taskList: { label: '任务列表' },
      },
      advancedGroup: {
        label: '插入',
        image: { label: '图片' },
        codeBlock: { label: '代码块' },
        table: { label: '表格' },
        math: { label: '数学公式' },
      },
    })
    expect(editorChineseLocale.toolbar).toEqual({
      boldLabel: '加粗',
      italicLabel: '斜体',
      strikethroughLabel: '删除线',
      codeLabel: '行内代码',
      latexLabel: '行内公式',
      linkLabel: '链接',
      aiLabel: 'AI 改写',
    })
    expect(editorChineseLocale.linkTooltip.inputPlaceholder).toBe('粘贴链接…')
    expect(editorChineseLocale.ai).toMatchObject({
      instructionPlaceholder: '请输入对选中内容的修改要求…',
      sendAsPromptHeaderLabel: '自定义要求',
      sendAsPromptLabel: '询问 AI：',
      submitButtonLabel: '发送要求',
    })
  })

  it('formats revision numbers as Chinese version labels', () => {
    expect(formatRevisionLabel(12)).toBe('版本 12')
    expect(formatRevisionLabel('draft')).toBe('版本 draft')
  })

  it('keeps the localized editor usable after all production features mount', async () => {
    const root = document.createElement('div')
    document.body.append(root)
    const crepe = createReportEditor(root, '# 运营报告', {
      ...editorChineseLocale.ai,
      provider: async function* () { yield '' },
    })

    await crepe.create()

    expect(crepe.editor.action(outline())).toEqual([
      expect.objectContaining({ text: '运营报告', level: 1 }),
    ])
    await crepe.destroy()
  })
})
