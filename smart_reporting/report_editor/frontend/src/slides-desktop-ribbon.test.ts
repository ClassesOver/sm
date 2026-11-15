import { afterEach, expect, it, vi } from 'vitest'
import { createSlidesNativeRibbon } from './slides-native-ribbon'
import { readFileSync } from 'node:fs'

afterEach(() => document.body.replaceChildren())

it('uses desktop group, clipboard and font row structure while retaining commands', () => {
  const host = document.body.appendChild(document.createElement('main'))
  const onAction = vi.fn()
  const ribbon = createSlidesNativeRibbon(host, { onAction })
  expect(host.querySelector('.slides-native-ribbon.ribbon > .ribbon-tabs')).not.toBeNull()
  const home = host.querySelector('[data-ribbon-panel="home"].ribbon-body')!
  const clipboard = home.querySelector('[data-ribbon-group="Clipboard"]')!
  expect(clipboard.querySelector('.ribbon-group-items > .rb-big[data-command="paste"] > .rb-big-icon')).not.toBeNull()
  expect(clipboard.querySelectorAll('.rb-clip-col > .rb-icon')).toHaveLength(3)
  const font = home.querySelector('[data-ribbon-group="Font"]')!
  expect(font.querySelectorAll('.ribbon-group-items > .rb-col > .rb-row')).toHaveLength(2)
  expect(home.querySelector('[data-ribbon-group="Paragraph"] .rb-big[aria-haspopup="dialog"]')).not.toBeNull()
  const bold = font.querySelector<HTMLButtonElement>('[data-command="bold"]')!
  ribbon.setTextFormatEnabled(true)
  bold.click()
  expect(onAction).toHaveBeenCalledWith('bold', true)
  expect(host.querySelectorAll('.ribbon-sep').length).toBeGreaterThan(0)
  expect(host.querySelector('[data-model-picker]')).toBeNull()
  ribbon.dispose()
})

it('retains pinned desktop CSS and deterministic selector scoping', () => {
  const source = readFileSync('packages/office-desktop-ui/src/slides/ribbon.source.css', 'utf8')
  const scoped = readFileSync('packages/office-desktop-ui/src/slides/ribbon.scoped.css', 'utf8')
  expect(source).toContain('height: 80px;')
  expect(source).toContain('.rb-clip-col {')
  expect(scoped).toContain('.slides-native-ribbon.slides-native-ribbon.slides-native-ribbon .rb-clip-col {')
  expect(scoped).toContain('padding: 4px 7px 6px;')
})

it('keeps desktop paragraph controls in a keyboard-dismissable host popover and closes it on tab changes', () => {
  const host = document.body.appendChild(document.createElement('main'))
  const onAction = vi.fn()
  const ribbon = createSlidesNativeRibbon(host, { onAction })
  ribbon.setTextFormatEnabled(true)
  const trigger = host.querySelector<HTMLButtonElement>('[data-ribbon-group="Paragraph"] .rb-big[aria-haspopup="dialog"]')!
  const menu = host.querySelector<HTMLElement>('[data-ribbon-group="Paragraph"] .rb-para-drop')!
  trigger.click()
  expect(menu.hidden).toBe(false)
  menu.querySelector<HTMLButtonElement>('[data-command="paragraphAlignLeft"]')!.click()
  expect(onAction).toHaveBeenCalledWith('paragraphAlignLeft')
  menu.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
  expect(menu.hidden).toBe(true)
  expect(document.activeElement).toBe(trigger)
  trigger.click()
  host.querySelector<HTMLButtonElement>('[data-ribbon-tab="insert"]')!.click()
  expect(menu.hidden).toBe(true)
  ribbon.dispose()
})
