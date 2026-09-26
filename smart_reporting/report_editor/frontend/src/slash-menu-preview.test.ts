import { describe, expect, it, vi } from 'vitest'

import { installSlashMenuHeadingPreview } from './slash-menu-preview'

describe('slash menu heading preview', () => {
  it('tags heading items with their level and leaves other items untouched', () => {
    document.body.innerHTML = `
      <div class="milkdown-slash-menu"><ul>
        <li><span class="milkdown-icon"></span><span>正文</span></li>
        <li><span class="milkdown-icon"></span><span>一级标题</span></li>
        <li><span class="milkdown-icon"></span><span>三级标题</span></li>
        <li><span class="milkdown-icon"></span><span>六级标题</span></li>
      </ul></div>
    `
    const dispose = installSlashMenuHeadingPreview()
    const items = document.querySelectorAll('.milkdown-slash-menu li')
    expect(items[0].hasAttribute('data-heading-level')).toBe(false)
    expect(items[1].getAttribute('data-heading-level')).toBe('1')
    expect(items[2].getAttribute('data-heading-level')).toBe('3')
    expect(items[3].getAttribute('data-heading-level')).toBe('6')
    dispose()
  })

  it('tags items that appear after installation', async () => {
    const dispose = installSlashMenuHeadingPreview()
    const menu = document.createElement('div')
    menu.className = 'milkdown-slash-menu'
    menu.innerHTML = '<ul><li><span>二级标题</span></li></ul>'
    document.body.append(menu)
    await vi.waitFor(() => {
      expect(menu.querySelector('li')?.getAttribute('data-heading-level')).toBe('2')
    })
    dispose()
    menu.remove()
  })
})
