import { describe, expect, it } from 'vitest'

import { imageDescriptionStatus } from './content-quality'

describe('imageDescriptionStatus', () => {
  it('reports images without descriptions', () => {
    const editor = document.createElement('div')
    editor.innerHTML = '<img src="a.png" alt=""><img src="b.png" alt="收入趋势">'
    expect(imageDescriptionStatus(editor)).toEqual({ label: '图片缺少说明 1 张', warning: true })
  })

  it('reports complete image descriptions', () => {
    const editor = document.createElement('div')
    editor.innerHTML = '<img src="a.png" alt="收入趋势">'
    expect(imageDescriptionStatus(editor)).toEqual({ label: '图片说明完整', warning: false })
  })
})
