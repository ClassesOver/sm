import { afterEach, expect, it } from 'vitest'
import { createHash } from 'node:crypto'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { createPdfRibbon } from './pdf-ribbon'

const packageFile = (path: string) => readFileSync(resolve(process.cwd(), 'packages/office-desktop-ui/src/pdf', path), 'utf8')
afterEach(() => document.body.replaceChildren())

it('retains the exact pinned upstream PDF sources and license', () => {
  const manifest = JSON.parse(packageFile('vendor/manifest.json'))
  expect(manifest.revision).toBe('f8c17004fb730df11f0f743164ffd8b4281bb38c')
  for (const [file, info] of Object.entries(manifest.files)) {
    expect(createHash('sha256').update(packageFile(`vendor/${file}`)).digest('hex')).toBe((info as { sha256: string }).sha256)
  }
})

it('changes only selectors in the imported desktop ribbon CSS', () => {
  const source = packageFile('vendor/styles.css')
  const sections = [
    source.slice(source.indexOf('/* ================= ribbon'), source.indexOf('/* ---- Compact ribbon')),
    source.slice(source.indexOf('.rb-icon {'), source.indexOf('.tb-save-error {')),
  ]
  const declarations = (css: string) => [...css.matchAll(/\{([^{}]*)\}/g)].map(match => match[1])
  expect(declarations(packageFile('source.css'))).toEqual(declarations(sections.join('\n')))
  expect(packageFile('source.css')).toContain('height: 80px;')
  expect(packageFile('source.css')).toContain('overflow-x: scroll;')
})

it('adopts desktop group/button/icon DOM while preserving original command authority', async () => {
  const host = document.body.appendChild(document.createElement('main'))
  const ribbon = createPdfRibbon(host)
  const group = ribbon.group('home', 'Markup')
  const command = document.createElement('button')
  command.disabled = true
  command.hidden = true
  command.setAttribute('aria-pressed', 'true')
  command.innerHTML = '<svg viewBox="0 0 24 24"></svg><span>Highlight</span>'
  const svg = command.querySelector('svg')
  let clicks = 0
  command.addEventListener('click', () => clicks++)
  group.append(command)
  await Promise.resolve()

  expect(host.querySelector('.ribbon > .ribbon-body > .ribbon-group > .ribbon-group-items')).toBe(group)
  expect(command.matches('.rb-big.active')).toBe(true)
  expect(command.querySelector('.rb-big-icon > svg')).toBe(svg)
  expect(command.disabled).toBe(true)
  expect(command.hidden).toBe(true)
  expect(group.querySelector('h2')?.className).toBe('pdf-desktop-group-title')
  command.disabled = false
  command.hidden = false
  command.click()
  expect(clicks).toBe(1)
  command.setAttribute('aria-pressed', 'false')
  await Promise.resolve()
  expect(command.classList.contains('active')).toBe(false)
  ribbon.dispose()
})

it('uses source separators and desktop group order without adding model controls', () => {
  const host = document.body.appendChild(document.createElement('main'))
  const ribbon = createPdfRibbon(host)
  for (const name of ['Search, Print & Properties', 'Page & Zoom', 'Convert & Export', 'Edit', 'Markup', 'AI']) ribbon.group('home', name)
  const panel = host.querySelector('[data-pdf-ribbon-panel=home]')!
  expect([...panel.querySelectorAll(':scope > section')].map(section => (section as HTMLElement).dataset.ribbonGroup))
    .toEqual(['AI', 'Markup', 'Edit', 'Convert & Export', 'Page & Zoom', 'Search, Print & Properties'])
  expect(panel.querySelectorAll(':scope > .ribbon-sep')).toHaveLength(5)
  expect(host.querySelector('[data-model-picker], [data-model-id]')).toBeNull()
  ribbon.dispose()
})

it('renders original upstream glyph geometry for a source command', async () => {
  const host = document.body.appendChild(document.createElement('main'))
  const ribbon = createPdfRibbon(host)
  const command = document.createElement('button')
  command.dataset.sourceCommandId = 'genoffice.pdf.home.markup.underline'
  command.innerHTML = '<svg><path d="M0 0" /></svg><span>Underline</span>'
  ribbon.group('home', 'Markup').append(command)
  await Promise.resolve()
  const icon = command.querySelector<SVGSVGElement>('.rb-big-icon > svg')!
  expect(icon.dataset.desktopIcon).toBe('underline')
  expect(icon.getAttribute('width')).toBe('28')
  expect(icon.querySelector('path')?.getAttribute('d')).toBe('M7.56 4.5 L7.56 11.17 A 4.44 4.44 0 0 0 16.44 11.17 L16.44 4.5')
  expect(command.querySelectorAll('svg')).toHaveLength(1)
  ribbon.dispose()
})

it('arranges original page/zoom controls in the desktop column without replacing inputs', async () => {
  const host = document.body.appendChild(document.createElement('main'))
  const ribbon = createPdfRibbon(host)
  const group = ribbon.group('home', 'Page & Zoom')
  const row = document.createElement('label'); row.className = 'pdf-view-page-row'
  const input = document.createElement('input'); input.className = 'pdf-view-page-input'; row.append(input)
  const select = document.createElement('select'); select.className = 'pdf-zoom'
  group.append(row, select)
  for (const key of ['zoomOut', 'zoomIn', 'fitWidth', 'fitPage']) {
    const button = document.createElement('button'); button.dataset.sourceCommandId = `genoffice.pdf.home.pageZoom.${key}`
    button.textContent = key; group.append(button)
  }
  await Promise.resolve()
  expect(group.querySelector('.rb-col > .rb-row > input')).toBe(input)
  expect(group.querySelector('.pdf-desktop-zoom-row > select')).toBe(select)
  expect([...group.querySelectorAll('.rb-icon .pdf-desktop-zoom-symbol')].map(symbol => symbol.textContent)).toEqual(['−', '+'])
  expect(group.querySelectorAll(':scope > .rb-big')).toHaveLength(2)
  ribbon.dispose()
})
