import { expect, it } from 'vitest'
import { addPdfCommandIcon } from './pdf-ribbon-command-icons'
it('adds one decorative icon while preserving labels, disabled states and existing source icons', () => {
  for (const id of ['home.edit.insertText','home.markup.underline','home.convert.toWord','home.pageZoom.zoomIn','home.properties.documentProperties','formDesign.addRadioOption']) {
    const button = document.createElement('button'); button.textContent = '命令'; button.disabled = true
    addPdfCommandIcon(button,id); addPdfCommandIcon(button,id)
    expect(button.querySelectorAll('svg')).toHaveLength(1)
    expect(button.querySelector('svg')?.getAttribute('aria-hidden')).toBe('true')
    expect(button.textContent).toBe('命令'); expect(button.disabled).toBe(true)
  }
  const input = document.createElement('input'); addPdfCommandIcon(input,'view.pageZoom.zoomIn'); expect(input.childElementCount).toBe(0)
})
