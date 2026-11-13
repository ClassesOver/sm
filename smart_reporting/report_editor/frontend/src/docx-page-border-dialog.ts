/**
 * 固定源 PageBorderDialog.tsx 的原生 DOM 移植：设置（无/方框/阴影/三维/自定义）、样式（24 种线型）、颜色（含自动）、
 * 宽度（Word 宽度表；艺术型为 1–31 pt）、艺术型（170 种）、预览（点四边按钮切换单边）、应用于（整篇/本节/仅首页/除首页外）、
 * 选项（四边距离、测量基准、总在前面显示）。预览与线型示意复用逐字节引入的 pagination-gaps.ts。
 */
import { pageBorderArtStripStyle, pageBorderLineCss, pageBorderStyleOf } from './vendor/genoffice-docs/apps/docs/src/renderer/editor/pagination-gaps'
import { PAGE_BORDER_ART_NAMES, PAGE_BORDER_LINE_STYLES, PAGE_BORDER_SIDES, PAGE_BORDER_WIDTHS, pageBorderArtLabel, pageBorderModelOf, pageBorderPropsOf,
  type DocxPageBorderProps, type PageBorderDisplay, type PageBorderModel, type PageBorderScope, type PageBorderSetting, type PageBorderSideName } from './docx-page-borders'
import type { SectionSettings } from '@genoffice/docx-engine'

const SETTINGS: [PageBorderSetting, string][] = [['none', '无'], ['box', '方框'], ['shadow', '阴影'], ['3d', '三维'], ['custom', '自定义']]
const SIDE_LABELS: Record<PageBorderSideName, string> = { top: '上', bottom: '下', left: '左', right: '右' }
const APPLY: [string, string][] = [['whole:all', '整篇文档'], ['section:all', '本节'], ['section:firstPage', '本节 - 仅首页'], ['section:notFirstPage', '本节 - 除首页外所有页']]

export function openDocxPageBorderDialog(host: HTMLElement, section: Pick<SectionSettings, 'pageBorder' | 'pageBorderProps'>,
  onApply: (props: DocxPageBorderProps | null, scope: PageBorderScope) => void, sectionLabel?: string): HTMLDialogElement {
  let m: PageBorderModel = pageBorderModelOf(section)
  const set = (patch: Partial<PageBorderModel>) => { m = { ...m, ...patch }; render() }
  const allOn = { top: true, bottom: true, left: true, right: true }
  const dialog = document.createElement('dialog')
  dialog.className = 'docx-page-border-dialog pb-dialog'; dialog.setAttribute('aria-label', '页面边框')
  const el = <K extends keyof HTMLElementTagNameMap>(tag: K, className?: string, text?: string) => { const node = document.createElement(tag); if (className) node.className = className; if (text !== undefined) node.textContent = text; return node }
  const title = el('h2', undefined, '页面边框')
  const columns = el('div', 'pb-columns')
  // 设置
  const settings = el('fieldset', 'pb-col pb-settings'); settings.append(el('legend', undefined, '设置'))
  const settingButtons = SETTINGS.map(([key, label]) => {
    const button = el('button', 'pb-setting', label); button.type = 'button'; button.dataset.pbSetting = key
    button.addEventListener('click', () => set({ setting: key, ...(key === 'none' || key === 'custom' ? {} : { on: allOn }) }))
    settings.append(button); return button
  })
  // 样式 / 颜色 / 宽度 / 艺术型
  const line = el('fieldset', 'pb-col pb-line'); line.append(el('legend', undefined, '样式'))
  const styleList = el('div', 'pb-style-list'); styleList.setAttribute('role', 'listbox'); styleList.setAttribute('aria-label', '样式')
  const styleButtons = PAGE_BORDER_LINE_STYLES.map(val => {
    const button = el('button', 'pb-style'); button.type = 'button'; button.setAttribute('role', 'option'); button.title = pageBorderArtLabel(val); button.dataset.pbStyle = val
    const sample = el('span'); sample.style.borderTop = pageBorderLineCss(val, 1.5, 'currentColor'); button.append(sample)
    button.addEventListener('click', () => set({ val, art: null, ...(m.art ? { widthPt: 0.5 } : {}) }))
    styleList.append(button); return button
  })
  const colorLabel = el('label', 'fld', '颜色'), colorRow = el('span', 'pb-color-row')
  const color = el('input'); color.type = 'color'; color.setAttribute('aria-label', '边框颜色')
  color.addEventListener('input', () => set({ color: color.value.slice(1).toUpperCase() }))
  const auto = el('button', 'pb-auto', '自动'); auto.type = 'button'; auto.addEventListener('click', () => set({ color: null }))
  colorRow.append(color, auto); colorLabel.append(colorRow)
  const widthLabel = el('label', 'fld', '宽度'), width = el('select'), artWidth = el('input')
  width.setAttribute('aria-label', '边框宽度'); width.addEventListener('change', () => set({ widthPt: Number(width.value) }))
  artWidth.type = 'number'; artWidth.min = '1'; artWidth.max = '31'; artWidth.step = '1'; artWidth.setAttribute('aria-label', '艺术型宽度')
  artWidth.addEventListener('change', () => set({ widthPt: Math.min(31, Math.max(1, Math.round(Number(artWidth.value)) || 1)) }))
  widthLabel.append(width, artWidth)
  const artLabel = el('label', 'fld', '艺术型'), art = el('select'); art.setAttribute('aria-label', '艺术型')
  art.append(new Option('(无)', ''), ...PAGE_BORDER_ART_NAMES.map(name => new Option(pageBorderArtLabel(name), name)))
  art.addEventListener('change', () => set(art.value ? { art: art.value, widthPt: m.art ? m.widthPt : 16 } : { art: null, widthPt: 0.5 }))
  artLabel.append(art)
  line.append(styleList, colorLabel, widthLabel, artLabel)
  // 预览 / 应用于 / 选项
  const previewCol = el('fieldset', 'pb-col pb-preview-col'); previewCol.append(el('legend', undefined, '预览'), el('p', 'modal-desc', '单击示意图或使用按钮应用边框'))
  const preview = el('div', 'pb-preview'), page = el('div', 'pb-preview-page')
  const sideButtons = new Map<PageBorderSideName, HTMLButtonElement>()
  const sideButton = (side: PageBorderSideName) => {
    const button = el('button', `pb-side-btn pb-side-${side}`); button.type = 'button'; button.setAttribute('aria-label', SIDE_LABELS[side]); button.dataset.pbSide = side; button.append(el('span'))
    button.addEventListener('click', () => {
      const none = m.setting === 'none'
      const on = { ...(none ? { top: false, bottom: false, left: false, right: false } : m.on), [side]: none || !m.on[side] }
      set({ on, setting: PAGE_BORDER_SIDES.some(s => on[s]) ? 'custom' : 'none' })
    })
    sideButtons.set(side, button); return button
  }
  const sideCol = el('div', 'pb-preview-side-col'); sideCol.append(sideButton('top'), sideButton('bottom'))
  const pageWrap = el('div', 'pb-preview-page-wrap'), sideRow = el('div', 'pb-preview-side-row'); sideRow.append(sideButton('left'), sideButton('right'))
  pageWrap.append(page, sideRow); preview.append(sideCol, pageWrap)
  const applyLabel = el('label', 'fld', '应用于'), apply = el('select'); apply.setAttribute('aria-label', '应用于')
  for (const [value, label] of APPLY) apply.append(new Option(value === 'section:all' && sectionLabel ? `${label}（${sectionLabel}）` : label, value))
  apply.addEventListener('change', () => { const [scope, display] = apply.value.split(':') as [PageBorderScope, PageBorderDisplay]; set({ scope, display }) })
  applyLabel.append(apply)
  const optionsToggle = el('button', 'pb-options-toggle', '选项…'); optionsToggle.type = 'button'; optionsToggle.setAttribute('aria-expanded', 'false')
  const options = el('div', 'pb-options'); options.hidden = true
  optionsToggle.addEventListener('click', () => { options.hidden = !options.hidden; optionsToggle.setAttribute('aria-expanded', String(!options.hidden)) })
  const grid = el('div', 'pb-margin-grid'), spaceInputs = new Map<PageBorderSideName, HTMLInputElement>()
  for (const side of PAGE_BORDER_SIDES) {
    const label = el('label', 'fld', SIDE_LABELS[side]), input = el('input'); input.type = 'number'; input.min = '0'; input.max = '31'; input.step = '1'; input.setAttribute('aria-label', `距离${SIDE_LABELS[side]}`)
    input.addEventListener('change', () => set({ space: { ...m.space, [side]: Math.min(31, Math.max(0, Math.round(Number(input.value)) || 0)) } }))
    label.append(input); grid.append(label); spaceInputs.set(side, input)
  }
  const measureLabel = el('label', 'fld', '测量基准'), measure = el('select'); measure.setAttribute('aria-label', '测量基准')
  measure.append(new Option('文字', 'text'), new Option('页边', 'page'))
  measure.addEventListener('change', () => { const offsetFrom = measure.value as 'page' | 'text', d = offsetFrom === 'page' ? 24 : 4; set({ offsetFrom, space: { top: d, bottom: d, left: d, right: d } }) })
  measureLabel.append(measure)
  const frontLabel = el('label', 'pb-check'), front = el('input'); front.type = 'checkbox'; front.setAttribute('aria-label', '总在前面显示')
  front.addEventListener('change', () => set({ zOrderBack: !front.checked }))
  frontLabel.append(front, document.createTextNode('总在前面显示'))
  options.append(grid, measureLabel, frontLabel)
  previewCol.append(preview, applyLabel, optionsToggle, options)
  columns.append(settings, line, previewCol)
  const actions = el('div', 'modal-actions'), cancel = el('button', undefined, '取消'), ok = el('button', 'btn-primary', '确定')
  cancel.type = 'button'; ok.type = 'button'; actions.append(cancel, ok)
  dialog.append(title, columns, actions)

  function render() {
    for (const button of settingButtons) { const on = button.dataset.pbSetting === m.setting; button.classList.toggle('active', on); button.setAttribute('aria-pressed', String(on)) }
    for (const button of styleButtons) { const on = !m.art && m.val === button.dataset.pbStyle; button.classList.toggle('active', on); button.setAttribute('aria-selected', String(on)) }
    color.value = `#${(m.color ?? '000000').toLowerCase()}`; color.disabled = !!m.art; auto.disabled = !!m.art; auto.classList.toggle('active', !m.color)
    const widths = ((PAGE_BORDER_WIDTHS as readonly number[]).includes(m.widthPt) ? [...PAGE_BORDER_WIDTHS] : [...PAGE_BORDER_WIDTHS, m.widthPt]).sort((a, b) => a - b)
    width.replaceChildren(...widths.map(w => new Option(`${w} pt`, String(w)))); width.value = String(m.widthPt)
    width.hidden = !!m.art; artWidth.hidden = !m.art; artWidth.value = String(m.widthPt); art.value = m.art ?? ''
    for (const [side, button] of sideButtons) { const on = m.setting !== 'none' && m.on[side]; button.classList.toggle('active', on); button.setAttribute('aria-pressed', String(on)) }
    apply.value = `${m.scope}:${m.display}`; measure.value = m.offsetFrom; front.checked = !m.zOrderBack
    for (const [side, input] of spaceInputs) input.value = String(m.space[side])
    const props = pageBorderPropsOf(m)
    const style = pageBorderStyleOf({ pageBorder: !!props, ...(props ? { pageBorderProps: props } : {}), marginTop: 1440, marginRight: 1440, marginBottom: 1440, marginLeft: 1440 })
    page.replaceChildren()
    if (style) {
      const border = el('div', 'pb-preview-border')
      const inset = (side: PageBorderSideName) => `${Math.min(28, Math.round((style.sides[side]?.insetPx ?? 0) / 3))}px`
      Object.assign(border.style, { top: inset('top'), bottom: inset('bottom'), left: inset('left'), right: inset('right'),
        borderTop: style.sides.top?.css ?? '', borderBottom: style.sides.bottom?.css ?? '', borderLeft: style.sides.left?.css ?? '', borderRight: style.sides.right?.css ?? '', boxShadow: style.boxShadow ?? '' })
      for (const side of PAGE_BORDER_SIDES) {
        const strip = style.sides[side]?.art
        if (!strip) continue
        const artStrip = el('div', 'page-border-art'); Object.assign(artStrip.style, pageBorderArtStripStyle(side, strip)); border.append(artStrip)
      }
      page.append(border)
    }
    page.append(el('div', 'pb-preview-text'))
  }
  render()
  host.append(dialog)
  const close = () => dialog.close()
  dialog.addEventListener('close', () => dialog.remove())
  cancel.addEventListener('click', close)
  ok.addEventListener('click', () => { onApply(pageBorderPropsOf(m), m.scope); close() })
  dialog.showModal()
  return dialog
}
