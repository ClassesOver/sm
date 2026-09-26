import { describe, expect, it } from 'vitest'
import { editorViewCtx } from '@milkdown/kit/core'
import { indent } from '@milkdown/kit/plugin/indent'
import { trailing } from '@milkdown/kit/plugin/trailing'

import { createReportEditor } from './editor-features'
import { editorChineseLocale } from './localization'

const aiConfig = {
  ...editorChineseLocale.ai,
  provider: async function* () { yield '' },
}

describe('official editing plugins', () => {
  it('mounts indent and trailing without changing the markdown round-trip', async () => {
    const root = document.createElement('div')
    document.body.append(root)
    const markdown = '# 报告\n\n![成本最高的科室](chart-002.png)\n'
    const crepe = createReportEditor(root, markdown, aiConfig)
    crepe.editor.use(indent)
    crepe.editor.use(trailing)

    await crepe.create()

    expect(crepe.getMarkdown()).toBe(markdown)
    await crepe.destroy()
  })

  it('keeps a writable paragraph after a trailing image', async () => {
    const root = document.createElement('div')
    document.body.append(root)
    const crepe = createReportEditor(root, '![图](a.png)', aiConfig)
    crepe.editor.use(trailing)

    await crepe.create()

    const view = crepe.editor.ctx.get(editorViewCtx)
    expect(view.state.doc.lastChild?.type.name).toBe('paragraph')
    expect(view.state.doc.lastChild?.textContent).toBe('')
    await crepe.destroy()
  })
})
