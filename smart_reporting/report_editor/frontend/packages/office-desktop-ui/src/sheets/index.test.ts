import { afterEach, expect, it, vi } from 'vitest'
import { readFileSync } from 'node:fs'
import postcss from 'postcss'
import { composeSheetsDesktopGroup } from './index'
import { mountWorkbookRibbon } from '../../../../src/workbook-ribbon'

afterEach(() => { document.body.replaceChildren() })

it('imports exact upstream ribbon declarations with only a selector scope', () => {
  const base = 'packages/office-desktop-ui/src/sheets/vendor/'
  const source = postcss.parse(readFileSync(base + 'ribbon.css', 'utf8'))
  const scoped = postcss.parse(readFileSync(base + 'ribbon.scoped.css', 'utf8'))
  const a: string[] = [], b: string[] = []
  source.walkDecls(item => { a.push(item.toString()) })
  scoped.walkDecls(item => { b.push(item.toString()) })
  expect(b).toEqual(a)
  scoped.walkRules(rule => { expect(rule.selectors.every(selector => selector.startsWith('.workbook-ribbon '))).toBe(true) })
  expect(readFileSync(base + 'ribbon.css', 'utf8')).toContain('height: 80px;')
  expect(readFileSync(base + 'styles.css', 'utf8')).toContain(readFileSync(base + 'ribbon.css', 'utf8').split('\n\n.check-column {')[0]!.trim())
})

it('moves host nodes into source two-row groups while retaining event listeners and permissions', () => {
  const section = document.createElement('section')
  section.innerHTML = '<h2>命令</h2>'
  const command = vi.fn()
  const buttons = Array.from({length: 11}, (_, index) => {
    const button = document.createElement('button'); button.textContent = `命令 ${index}`
    button.addEventListener('click', command); section.append(button); return button
  })
  buttons[3]!.disabled = true
  composeSheetsDesktopGroup(section, '命令', 'Data')
  expect(section.matches('.ribbon-group[aria-label="命令"]')).toBe(true)
  expect(section.querySelector('h2')).toBeNull()
  expect(section.querySelectorAll('.ribbon-group-content > .ribbon-rows > .inline-tools')).toHaveLength(2)
  expect(section.querySelectorAll('button')).toHaveLength(11)
  buttons[0]!.click(); expect(command).toHaveBeenCalledOnce()
  buttons[3]!.click(); expect(command).toHaveBeenCalledOnce()
  expect(buttons.every(button => section.contains(button))).toBe(true)
})

it('uses source desktop font and clipboard composition and keeps contextual commands mounted', () => {
  const controller = mountWorkbookRibbon(document.body, vi.fn(), {
    editable: () => true, rotation: () => 0,
    table: () => ({id:'t1', name:'Table1', range:'A1:D10'}),
  })
  const font = document.querySelector('.ribbon-group[aria-label="字体"]')!
  expect(font.querySelectorAll('.ribbon-rows > .inline-tools')).toHaveLength(2)
  expect(font.querySelector('.font-name')).not.toBeNull()
  expect(font.querySelector('.font-size')).not.toBeNull()
  const clipboard = document.querySelector('.ribbon-group[aria-label="剪贴板"]')!
  expect(clipboard.querySelectorAll('.tool-stack > button')).toHaveLength(3)
  expect(clipboard.querySelector('[data-ribbon-command="paste"].large > .tool-icon-row')).not.toBeNull()
  expect(clipboard.querySelector('.large > .cover-select')).not.toBeNull()
  for (const tab of ['Insert', 'Data', 'Review', 'View', 'Table Design']) {
    document.querySelector<HTMLButtonElement>(`[data-ribbon-tab="${tab}"]`)!.click()
    expect(document.querySelector('.ribbon-tabs > button.active')?.getAttribute('data-ribbon-tab')).toBe(tab)
    expect(document.querySelectorAll('.ribbon > .ribbon-group > .ribbon-group-content').length).toBeGreaterThan(0)
    expect(document.querySelector('.ribbon-group > h2')).toBeNull()
  }
  expect(document.querySelector('[data-ribbon-control="table-name"]')).not.toBeNull()
  controller.dispose()
})
