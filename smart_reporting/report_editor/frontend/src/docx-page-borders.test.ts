import { afterEach, describe, expect, it, vi } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { PAGE_BORDER_ART_NAMES, PAGE_BORDER_LINE_STYLES, PAGE_BORDER_WIDTHS, effectiveDocxPageBorder, pageBorderModelOf, pageBorderPropsOf, samePageBorder, validDocxPageBorderValues, withDocxPageBorder, type DocxPageBorderProps } from './docx-page-borders'
import { restoredDocxSectionOperation, type DocxSectionAnchor } from './docx-operations'
import { openDocxPageBorderDialog } from './docx-page-border-dialog'
import { Editor, Node } from '@tiptap/core'
import { createDocxRibbon } from './docx-ribbon'

const presets = JSON.parse(readFileSync(resolve(__dirname, '../../../reporting/doc_engine/bridge/page-border-presets.json'), 'utf8'))
const side = (val: string, widthPt: number, spacePt: number, extra = {}) => ({ val, widthPt, spacePt, ...extra })
const shadow: DocxPageBorderProps = { offsetFrom: 'text', spacePt: 4, widthPt: 3, color: '1F4E79', sides: Object.fromEntries((['top', 'bottom', 'left', 'right'] as const).map(name => [name, side('single', 3, 4, { color: '1F4E79', shadow: true })])) }
const anchor = (sectionId: string, settings = {}): DocxSectionAnchor => ({ sectionId, expectedSectionSha256: 'a'.repeat(64), settings: { pageWidth: 11906, pageHeight: 16838, marginTop: 1440, marginRight: 1800, marginBottom: 1440, marginLeft: 1800, orientation: 'portrait', columns: 1, pageBorder: false, ...settings } } as never)
afterEach(() => { document.body.replaceChildren() })

describe('Word page borders (pinned PageBorderDialog + applySectionSettings)', () => {
  it('keeps the dialog value lists in sync with the bridge allow-list', () => {
    expect([...PAGE_BORDER_LINE_STYLES]).toEqual(presets.lineStyles)
    expect([...PAGE_BORDER_WIDTHS]).toEqual(presets.lineWidths)
    expect([...PAGE_BORDER_ART_NAMES]).toEqual(presets.artNames)
  })

  it('round-trips model ↔ props like the pinned settingOf/modelOf/pageBorderPropsOf', () => {
    expect(pageBorderModelOf({ pageBorder: false })).toMatchObject({ setting: 'none', offsetFrom: 'page', scope: 'whole' })
    expect(pageBorderModelOf({ pageBorder: true })).toMatchObject({ setting: 'box', val: 'single', widthPt: 0.5 })
    const model = pageBorderModelOf({ pageBorder: true, pageBorderProps: shadow })
    expect(model).toMatchObject({ setting: 'shadow', widthPt: 3, color: '1F4E79', offsetFrom: 'text', on: { top: true, bottom: true, left: true, right: true } })
    expect(pageBorderPropsOf(model)).toEqual(shadow)
    const custom = { ...model, setting: 'custom' as const, on: { top: true, bottom: false, left: false, right: false }, display: 'firstPage' as const, scope: 'section' as const }
    expect(pageBorderPropsOf(custom)).toEqual({ display: 'firstPage', offsetFrom: 'text', spacePt: 4, widthPt: 3, color: '1F4E79', sides: { top: side('single', 3, 4, { color: '1F4E79' }) } })
    expect(pageBorderPropsOf({ ...model, setting: 'none' })).toBeNull()
    const art = { ...model, art: 'apples', widthPt: 20, color: null }
    expect(pageBorderPropsOf(art)!.sides!.top).toEqual({ val: 'apples', widthPt: 20, spacePt: 4, art: true })
  })

  it.each(['box', 'shadow', '3d'] as const)('accepts art after a colored %s border and preserves line preferences', setting => {
    const model = { ...pageBorderModelOf({ pageBorder: true, pageBorderProps: shadow }), setting, art: 'apples', widthPt: 16 }
    const props = pageBorderPropsOf(model)!
    expect(validDocxPageBorderValues({ pageBorder: true, pageBorderProps: props })).toBe(true)
    expect(props.color).toBeUndefined()
    expect(props.sides!.top).toEqual({ val: 'apples', widthPt: 16, spacePt: 4, art: true })
    expect(pageBorderPropsOf({ ...model, art: null, widthPt: 3 })!.sides!.top!.color).toBe('1F4E79')
  })

  it('validates like the bridge and builds per-section drafts that revert to the source', () => {
    expect(validDocxPageBorderValues({ pageBorder: true, pageBorderProps: shadow })).toBe(true)
    expect(validDocxPageBorderValues({ pageBorder: true, pageBorderProps: null })).toBe(true)
    for (const bad of [{ pageBorder: 'yes' }, { pageBorder: false, pageBorderProps: shadow }, { pageBorder: true, pageBorderProps: { ...shadow, spacePt: 5 } },
      { pageBorder: true, pageBorderProps: { ...shadow, sides: { top: side('laser', 3, 4) } } }, { pageBorder: true, pageBorderProps: { ...shadow, widthPt: 1.3, sides: { top: side('single', 1.3, 4) } } }]) expect(validDocxPageBorderValues(bad as never), JSON.stringify(bad)).toBe(false)
    const sections = [anchor('s1'), anchor('s2', { pageBorder: true })]
    const build = (sectionId: string, values: Record<string, unknown>) => restoredDocxSectionOperation([{ kind: 'setSectionLayout', sectionId, expectedSectionSha256: 'a'.repeat(64), values }], sections.find(item => item.sectionId === sectionId))
    const margins = build('s1', { marginTop: 2000 })!
    const whole = withDocxPageBorder([margins], sections.map(item => ({ sectionId: item.sectionId, settings: item.settings })), { pageBorder: true, pageBorderProps: shadow }, build)
    expect(whole.map(op => [op.sectionId, op.values])).toEqual([['s1', { marginTop: 2000, pageBorder: true, pageBorderProps: shadow }], ['s2', { pageBorder: true, pageBorderProps: shadow }]])
    // 与来源一致即撤回：s2 来源就是“方框”
    const boxed = withDocxPageBorder(whole, [{ sectionId: 's2', settings: sections[1]!.settings }], { pageBorder: true, pageBorderProps: null }, build)
    expect(boxed.map(op => op.sectionId)).toEqual(['s1'])
    const removed = withDocxPageBorder(boxed, [{ sectionId: 's1', settings: sections[0]!.settings }], { pageBorder: false }, build)
    expect(removed.map(op => op.values)).toEqual([{ marginTop: 2000 }])
    expect(samePageBorder({ pageBorder: false }, { pageBorder: false })).toBe(true)
    expect(effectiveDocxPageBorder({ pageBorder: true, pageBorderProps: shadow }, { pageBorder: false })).toEqual({ pageBorder: false })
    expect(effectiveDocxPageBorder({ pageBorder: false }, { pageBorder: true, pageBorderProps: null })).toEqual({ pageBorder: true })
    expect(() => restoredDocxSectionOperation([{ kind: 'setSectionLayout', sectionId: 's1', expectedSectionSha256: 'a'.repeat(64), values: { pageBorder: true, pageBorderProps: { ...shadow, spacePt: 9 } } }], sections[0])).toThrow('页面边框')
  })

  it('dialog: shadow preset, width, per-side custom toggle, apply-to scope and options', () => {
    const host = document.createElement('div'); document.body.append(host)
    HTMLDialogElement.prototype.showModal ??= function (this: HTMLDialogElement) { this.open = true }
    HTMLDialogElement.prototype.close ??= function (this: HTMLDialogElement) { this.open = false; this.dispatchEvent(new Event('close')) }
    const onApply = vi.fn()
    const dialog = openDocxPageBorderDialog(host, { pageBorder: false }, onApply, '第 1 节')
    const q = <T extends Element>(selector: string) => dialog.querySelector<T>(selector)!
    expect(q<HTMLButtonElement>('[data-pb-setting="none"]').getAttribute('aria-pressed')).toBe('true')
    expect(q('.pb-preview-border')).toBeNull()
    q<HTMLButtonElement>('[data-pb-setting="shadow"]').click()
    const width = q<HTMLSelectElement>('select[aria-label="边框宽度"]'); width.value = '3'; width.dispatchEvent(new Event('change'))
    expect(q('.pb-preview-border')).not.toBeNull()
    q<HTMLButtonElement>('[data-pb-side="left"]').click()
    expect(q<HTMLButtonElement>('[data-pb-setting="custom"]').getAttribute('aria-pressed')).toBe('true')
    const apply = q<HTMLSelectElement>('select[aria-label="应用于"]'); apply.value = 'section:firstPage'; apply.dispatchEvent(new Event('change'))
    expect([...apply.options].map(option => option.text)).toContain('本节（第 1 节）')
    q<HTMLButtonElement>('.btn-primary').click()
    const [props, scope] = onApply.mock.calls[0]!
    expect(scope).toBe('section')
    expect(props.display).toBe('firstPage'); expect(Object.keys(props.sides).sort()).toEqual(['bottom', 'right', 'top'])
    // 固定源：单击单边后设置变为“自定义”，阴影/三维标记不再写出
    expect(props.sides.top).toEqual({ val: 'single', widthPt: 3, spacePt: 24 })
    expect(validDocxPageBorderValues({ pageBorder: true, pageBorderProps: props })).toBe(true)
  })

  it('ribbon: 方框(单实线) / 无 / 页面边框… with the host-provided reason', () => {
    const Doc = Node.create({ name: 'doc', topNode: true, content: 'block+' })
    const P = Node.create({ name: 'docParagraph', group: 'block', content: 'text*', renderHTML: () => ['p', 0] })
    const T = Node.create({ name: 'text', group: 'inline' })
    const host = document.createElement('div'); document.body.append(host)
    const editor = new Editor({ element: host, extensions: [Doc, P, T], content: { type: 'doc', content: [{ type: 'docParagraph', content: [{ type: 'text', text: 'x' }] }] } })
    let reason: string | null = null, current: { pageBorder: boolean } = { pageBorder: false }
    const apply = vi.fn((value: { pageBorder: boolean }) => { current = { pageBorder: value.pageBorder } })
    const args: unknown[] = Array.from({ length: 22 }, () => undefined)
    args[0] = editor; args[1] = true; args[5] = []; args[12] = []
    args[21] = { current: () => current, reason: () => reason, sectionLabel: () => '第 1 节', apply }
    const ribbon = (createDocxRibbon as (...rest: unknown[]) => HTMLElement)(...args); document.body.append(ribbon)
    ribbon.querySelector<HTMLButtonElement>('[data-tab-label="设计"]')!.click()
    const trigger = ribbon.querySelector<HTMLButtonElement>('[data-action="page-borders"]')!
    expect(trigger.disabled).toBe(false)
    trigger.click(); ribbon.querySelector<HTMLButtonElement>('[data-action="page-borders-box"]')!.click()
    expect(apply).toHaveBeenLastCalledWith({ pageBorder: true, pageBorderProps: null }, 'section')
    expect(trigger.classList.contains('active')).toBe(true)
    trigger.click(); ribbon.querySelector<HTMLButtonElement>('[data-action="page-borders-none"]')!.click()
    expect(apply).toHaveBeenLastCalledWith({ pageBorder: false }, 'section')
    reason = '已插入分节符，请先保存，再设置页面边框'
    ribbon.querySelector<HTMLButtonElement>('[data-tab-label="开始"]')!.click(); ribbon.querySelector<HTMLButtonElement>('[data-tab-label="设计"]')!.click()
    const disabled = ribbon.querySelector<HTMLButtonElement>('[data-action="page-borders"]')!
    expect(disabled.disabled).toBe(true); expect(disabled.title).toBe(reason)
    editor.destroy()
  })
})
