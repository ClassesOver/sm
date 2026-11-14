import { expect, it } from 'vitest'
import type { SectionSettings } from '@genoffice/docx-engine'
import { docxSectionSettingsWithPatch } from '../../../reporting/doc_engine/bridge/docx-section-settings'
import { restoredDocxSectionOperation } from './docx-operations'

const settings: SectionSettings = { orientation: 'portrait', pageWidth: 12240, pageHeight: 15840, marginTop: 1440, marginRight: 1440, marginBottom: 1440, marginLeft: 1440, columns: 1, pageBorder: false }
const props: NonNullable<SectionSettings['pageBorderProps']> = { display: 'firstPage', offsetFrom: 'text', zOrder: 'back', widthPt: 2.25, spacePt: 7, sides: { top: { val: 'double', widthPt: 2.25, spacePt: 7, color: '123456', shadow: true }, right: { val: 'single', widthPt: 0.5, spacePt: 4 } } }
it('retains full source dialog props in section preview and restored native draft', () => {
  expect(docxSectionSettingsWithPatch(settings, { pageBorder: true, pageBorderProps: props }).pageBorderProps).toEqual(props)
  const section = { sectionId: 's1', expectedSectionSha256: 'a'.repeat(64), settings }
  const op = { kind: 'setSectionLayout', sectionId: section.sectionId, expectedSectionSha256: section.expectedSectionSha256, values: { pageBorder: true, pageBorderProps: props } }
  expect(restoredDocxSectionOperation([op], section)).toEqual(op)
})

import { afterEach, vi } from 'vitest'
import { createRoot, type Root } from 'react-dom/client'
import { flushSync } from 'react-dom'
import { createElement } from 'react'
import { PageBorderDialog } from './docx-page-border-dialog-source'
import { PAGE_BORDER_ART_NAMES, PAGE_BORDER_LINE_STYLES, assertDocxPageBorderProps } from '../../../reporting/doc_engine/bridge/docx-page-border-props'
let root: Root | undefined
afterEach(() => { root?.unmount(); root = undefined; document.body.replaceChildren() })
function mountDialog() {
  const host = document.createElement('div'); document.body.append(host); root = createRoot(host)
  const apply = vi.fn(), close = vi.fn()
  flushSync(() => root!.render(createElement(PageBorderDialog, { section: settings, onApply: apply, onClose: close })))
  const click = (selector: string) => flushSync(() => host.querySelector<HTMLButtonElement>(selector)!.click())
  return { host, apply, close, click }
}
it('retains every pinned line/art choice and five source settings with native-safe values', () => {
  const { host, click, apply } = mountDialog()
  expect(host.querySelectorAll('[role=option]')).toHaveLength(24)
  expect(host.querySelectorAll('.pb-line > label:last-child option')).toHaveLength(PAGE_BORDER_ART_NAMES.length + 1)
  const settings = host.querySelectorAll<HTMLButtonElement>('.pb-setting')
  expect(settings).toHaveLength(5)
  for (const index of [1, 2, 3, 4, 0]) {
    flushSync(() => settings[index]!.click()); click('button[type=submit]')
    const value = apply.mock.calls.at(-1)![0]
    if (index === 0) expect(value).toBeNull()
    else {
      assertDocxPageBorderProps(value)
      expect(Object.values(value.sides ?? {})).toHaveLength(4)
      for (const side of Object.values(value.sides ?? {}) as Record<string, unknown>[]) {
        expect(side.shadow).toBe(index === 2 ? true : undefined)
        expect(side.frame).toBe(index === 3 ? true : undefined)
      }
    }
  }
  for (const val of [...PAGE_BORDER_LINE_STYLES, ...PAGE_BORDER_ART_NAMES]) {
    const art = PAGE_BORDER_ART_NAMES.includes(val)
    expect(() => assertDocxPageBorderProps({ spacePt: 4, widthPt: art ? 16 : 1, sides: { top: { val, widthPt: art ? 16 : 1, spacePt: 4, ...(art ? { art: true } : {}) } } })).not.toThrow()
  }
})
it('cancels without applying; Escape ignores active composition and closes normally', () => {
  const { host, apply, close, click } = mountDialog()
  click('.modal-actions button[type=button]'); expect(close).toHaveBeenCalledOnce(); expect(apply).not.toHaveBeenCalled()
  const target = host.querySelector('button')!
  target.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, isComposing: true }))
  expect(close).toHaveBeenCalledOnce()
  target.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
  expect(close).toHaveBeenCalledTimes(2)
})
it('rejects unknown/unserializable props and unsafe XML values in restored drafts', () => {
  const section = { sectionId: 's1', expectedSectionSha256: 'a'.repeat(64), settings }
  for (const pageBorderProps of [{}, { ...props, zOrder: 'front' }, { ...props, unknown: 1 }, { ...props, sides: { top: { val: 'single"/><w:evil', widthPt: 1, spacePt: 2 } } }, { ...props, sides: { top: { val: 'single', widthPt: .3, spacePt: 2 } } }]) {
    expect(() => restoredDocxSectionOperation([{ kind: 'setSectionLayout', sectionId: section.sectionId, expectedSectionSha256: section.expectedSectionSha256, values: { pageBorder: true, pageBorderProps } }], section)).toThrow()
  }
  expect(() => restoredDocxSectionOperation([{ kind: 'setSectionLayout', sectionId: section.sectionId, expectedSectionSha256: section.expectedSectionSha256, values: { pageBorder: false, pageBorderProps: props } }], section)).toThrow()
})
