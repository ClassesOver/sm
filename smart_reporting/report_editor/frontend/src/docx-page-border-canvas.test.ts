import { expect, it } from 'vitest'
import { renderDocxCanvasPageBorders } from './docx-mixed-columns'
import type { SectionSettings } from '@genoffice/docx-engine'

const settings: SectionSettings = {
  pageWidth: 9000, pageHeight: 12000, marginLeft: 720, marginRight: 720, marginTop: 720, marginBottom: 720,
  orientation: 'portrait', pageBorder: true, columns: 1,
  pageBorderProps: { offsetFrom: 'page', spacePt: 12, widthPt: 1, sides: { top: { val: 'single', widthPt: 1, spacePt: 12, color: '008000' } } },
}

it('renders section page-border data on the continuous canvas paper using the active pagination geometry', () => {
  const wrap = document.createElement('div'), pm = document.createElement('div'), paper = document.createElement('div')
  wrap.className = 'page-wrap'; pm.className = 'ProseMirror'; paper.className = 'doc-page'
  pm.append(paper); wrap.append(pm); document.body.append(wrap)
  wrap.getBoundingClientRect = () => ({ left: 0, top: 0, right: 900, bottom: 1600, width: 900, height: 1600, x: 0, y: 0, toJSON() {} })
  paper.getBoundingClientRect = () => ({ left: 100, top: 0, right: 700, bottom: 800, width: 600, height: 800, x: 100, y: 0, toJSON() {} })

  renderDocxCanvasPageBorders(wrap, settings, 1)

  const overlay = wrap.querySelector<HTMLElement>('.page-border-overlay')
  expect(overlay).not.toBeNull()
  expect(overlay!.style.borderTop).toBe('1px solid rgb(0, 128, 0)')
  expect(overlay!.style.left).toBe('100px')
  expect(overlay!.style.top).toBe('16px')
  renderDocxCanvasPageBorders(wrap, { ...settings, pageBorder: false }, 1)
  expect(wrap.querySelector('.page-border-overlays')).toBeNull()
  wrap.remove()
})
