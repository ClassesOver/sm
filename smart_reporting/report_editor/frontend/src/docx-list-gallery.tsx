import './docx-list-gallery.css'
import { createElement } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { flushSync } from 'react-dom'
import { formatNumber, type CustomNumberingLevel, type NumberingDef, type StyleInfo } from '@genoffice/docx-engine'
import { DefineBulletDialog, DefineMultilevelDialog, DefineNumberFormatDialog } from './vendor/genoffice-docs/apps/docs/src/renderer/components/ListDialogs'
import { IconCaret, IconMultilevel } from './vendor/genoffice-docs/apps/docs/src/renderer/components/icons'
import { getLang, LocaleProvider, t } from './vendor/genoffice-docs/apps/docs/src/renderer/i18n/locale'
import { BULLET_LIBRARY, NUMBER_LIBRARY, MULTILEVEL_LIBRARY, bulletPresetLevels, numberPresetLevels, previewLevelText, recentListPresets, rememberListPreset, documentListPresets, type ListPresetKind } from './vendor/genoffice-docs/apps/docs/src/renderer/list-presets'
import { normalizeDocxCustomList } from '../../../reporting/doc_engine/bridge/docx-custom-list'

type Options = {
  kind?: ListPresetKind
  reason: () => string | null
  styles: () => StyleInfo[]
  current: () => CustomNumberingLevel[] | undefined
  apply: (levels: CustomNumberingLevel[]) => void
  clear: () => void
  report: (error: unknown) => void
  definitions?: () => Iterable<NumberingDef>
  level?: () => { current: number; available: boolean[] }
  changeLevel?: (ilvl: number) => void
}

/** 固定源图库与完整定义对话框；来源/锁定最终核验由调用方操作桥负责。 */
export function createDocxListGallery(options: Options): { element: HTMLElement; refresh(): void; destroy(): void } {
  const kind = options.kind ?? 'multi'
  const label = () => t(kind === 'multi' ? 'ribbonMultilevelTip' : kind === 'bullets' ? 'ribbonBullets' : 'ribbonNumbering')
  const element = document.createElement('div')
  element.className = 'rb-split-wrap docx-list-control'
  const toggle = document.createElement('button')
  toggle.type = 'button'; toggle.className = kind === 'multi' ? 'rb-icon' : 'rb-caret'
  toggle.dataset.docxListToggle = ''; toggle.dataset.action = toggle.dataset.sourceAction = `list-${kind === 'multi' ? 'multilevel' : kind === 'numbers' ? 'numbering' : 'bullets'}-gallery`
  toggle.setAttribute('aria-label', label()); toggle.setAttribute('aria-haspopup', 'true')
  const iconRoot = createRoot(toggle); flushSync(() => iconRoot.render(createElement(kind === 'multi' ? IconMultilevel : IconCaret)))
  element.append(toggle)
  let gallery: HTMLElement | null = null, modalHost: HTMLElement | null = null, modalRoot: Root | null = null
  let initial: CustomNumberingLevel[] | undefined, opener: HTMLElement | null = null, destroyed = false
  const preserveSelection = (event: MouseEvent) => event.preventDefault()
  toggle.addEventListener('mousedown', preserveSelection)
  const restoreFocus = () => { if (opener?.isConnected) opener.focus({ preventScroll: true }); opener = null }
  const closeGallery = () => { gallery?.remove(); gallery = null; toggle.setAttribute('aria-expanded', 'false') }
  const guardIme = (event: KeyboardEvent) => {
    if (modalHost && event.key === 'Escape' && (event.isComposing || event.keyCode === 229 || event.defaultPrevented)) event.stopImmediatePropagation()
  }
  const closeModal = () => {
    const root = modalRoot; modalRoot = null; root?.unmount(); modalHost?.remove(); modalHost = null
    window.removeEventListener('keydown', guardIme, true); restoreFocus()
  }
  const close = () => { closeGallery(); closeModal(); restoreFocus() }
  const commit = (write: () => void) => {
    if (destroyed) return
    try {
      const reason = options.reason()
      if (reason) throw new Error(reason)
      write(); close()
    } catch (error) { options.report(error) }
  }
  const button = (label: string, className: string, action: () => void) => {
    const control = document.createElement('button'); control.type = 'button'; control.className = className; control.textContent = label
    control.addEventListener('mousedown', preserveSelection); control.addEventListener('click', action)
    return control
  }
  const refresh = () => {
    if (destroyed) return
    const reason = options.reason()
    toggle.disabled = !!reason; toggle.title = reason ?? label()
    gallery?.querySelectorAll('button').forEach(control => { control.disabled = !!reason || control.dataset.levelUnavailable === 'true'; control.title = reason ?? control.getAttribute('aria-label') ?? '' })
    const ok = modalHost?.querySelector<HTMLButtonElement>('.modal-actions .primary')
    if (ok) { ok.disabled = !!reason; ok.title = reason ?? '' }
  }
  const define = () => {
    if (options.reason()) { refresh(); return }
    closeGallery()
    modalHost = document.createElement('div'); modalHost.className = 'docx-native docx-list-dialog-host'; modalHost.lang = getLang(); modalHost.dataset.docxListDialogHost = ''
    document.body.append(modalHost); modalRoot = createRoot(modalHost)
    window.addEventListener('keydown', guardIme, true)
    const apply = (levels: CustomNumberingLevel[]) => commit(() => { options.apply(structuredClone(levels)); rememberListPreset(kind, levels) })
    const ilvl = options.level?.().current ?? 0
    const dialog = kind === 'bullets' ? createElement(DefineBulletDialog, {
      ilvl, onApply: (levels, picture) => picture ? options.report(new Error('图片项目符号的上传与编号资源写回尚未接入')) : apply(levels), onClose: close,
    }) : kind === 'numbers' ? createElement(DefineNumberFormatDialog, { ilvl, onApply: apply, onClose: close }) : createElement(DefineMultilevelDialog, {
      initial: initial ? structuredClone(initial) : undefined, styles: options.styles(), onApply: apply, onClose: close,
    })
    flushSync(() => modalRoot!.render(createElement(LocaleProvider, { initial: getLang(), children: dialog })))
    // 源表单把 Dropdown 放在 label 内；选项选中后取消 label 的默认二次激活，
    // 保留 React 的 onPick/关闭，不让 trigger 再次打开覆盖下方“确定”。
    modalHost.addEventListener('click', event => {
      if (event.target instanceof Element && event.target.closest('.gs-dd-item')?.closest('label')) event.preventDefault()
    }, true)
    // 固定源图片模式需要独立上传/编号资源协议，保留明确禁用状态，不把符号接线冒称图片支持。
    const picture = modalHost.querySelector<HTMLButtonElement>('.list-bullet-dialog [role=tab]:nth-child(2)')
    if (picture) { picture.disabled = true; picture.title = '图片项目符号的上传与编号资源写回尚未接入' }
    modalHost.querySelector('[role=dialog]')?.setAttribute('aria-modal', 'true')
    refresh()
  }
  const open = () => {
    if (destroyed) return
    if (gallery || modalHost) { close(); return }
    if (options.reason()) { refresh(); return }
    try { initial = structuredClone(options.current()); opener = document.activeElement instanceof HTMLElement ? document.activeElement : null }
    catch (error) { options.report(error); return }
    gallery = document.createElement('div'); gallery.className = `layout-menu list-gallery ${kind === 'multi' ? 'list-gallery-multi' : 'list-gallery-word'}`; gallery.dataset.docxListGallery = ''; gallery.dataset.rbPanel = ''
    const preview = (card: HTMLButtonElement, levels: CustomNumberingLevel[]) => {
      if (kind === 'bullets') {
        const glyph = document.createElement('span'); glyph.textContent = levels[0]?.lvlText ?? ''
        glyph.style.fontFamily = levels[0]?.font ?? ''; glyph.style.color = levels[0]?.color && levels[0].color !== 'auto' ? `#${levels[0].color}` : ''
        card.append(glyph); return
      }
      if (kind === 'numbers') {
        for (let k = 0; k < 3; k++) {
          const row = document.createElement('span'); row.className = 'list-gallery-preview-row'
          const prefix = document.createElement('span'); prefix.className = 'list-gallery-preview-prefix'
          prefix.textContent = levels[0]!.lvlText.replace(/%1/g, formatNumber((levels[0]!.start ?? 1) + k, levels[0]!.numFmt))
          const line = document.createElement('span'); line.className = 'list-gallery-preview-line'; row.append(prefix, line); card.append(row)
        }
        return
      }
      for (let i = 0; i < Math.min(3, levels.length); i++) {
        const line = document.createElement('span'); line.style.paddingLeft = `${i * 10}px`
        line.textContent = `${previewLevelText(levels, i)} ———`; card.append(line)
      }
    }
    const cardFor = (levels: CustomNumberingLevel[]) => {
      const card = button('', `list-gallery-card ${kind === 'multi' ? 'list-gallery-card-multi' : kind === 'bullets' ? 'list-gallery-glyph' : 'list-gallery-preview'}`, () => commit(() => { options.apply(structuredClone(levels)); rememberListPreset(kind, levels) }))
      card.setAttribute('aria-label', levels.slice(0, 3).map((_, i) => previewLevelText(levels, i)).join(' / ')); preview(card, levels); return card
    }
    const section = (label: string, presets: CustomNumberingLevel[][], kind: 'Recent' | 'Document') => {
      const valid = presets.flatMap(levels => { try { return [normalizeDocxCustomList({ id: 'gallery', levels }).levels] } catch { return [] } })
      if (!valid.length) return
      const heading = document.createElement('div'); heading.className = 'list-gallery-title'; heading.textContent = label; gallery!.append(heading)
      valid.forEach((levels, index) => {
        const card = cardFor(levels)
        card.dataset[`docxList${kind}`] = String(index)
        card.setAttribute('aria-label', levels.slice(0, 3).map((_, i) => previewLevelText(levels, i)).join(' / '))
        gallery!.append(card)
      })
    }
    section(t(kind === 'multi' ? 'ribbonRecentLists' : kind === 'bullets' ? 'ribbonRecentBullets' : 'ribbonRecentNumbers'), recentListPresets(kind), 'Recent')
    const title = document.createElement('div'); title.className = 'list-gallery-title'; title.textContent = t(kind === 'multi' ? 'ribbonListLibraryTitle' : kind === 'bullets' ? 'ribbonBulletLibTitle' : 'ribbonNumberLibTitle'); gallery.append(title)
    const clear = button(t('ribbonListNone'), 'list-gallery-card list-gallery-none', () => commit(options.clear)); clear.dataset.docxListClear = ''; gallery.append(clear)
    const library = kind === 'multi' ? MULTILEVEL_LIBRARY : kind === 'bullets' ? BULLET_LIBRARY.map(glyph => bulletPresetLevels(glyph)) : NUMBER_LIBRARY.map(n => numberPresetLevels(n.numFmt, n.pattern))
    library.forEach((levels, index) => {
      const card = cardFor(levels)
      card.dataset.docxListPreset = String(index); card.setAttribute('aria-label', levels.slice(0, 3).map((_, i) => previewLevelText(levels, i)).join(' / '))
      gallery!.append(card)
    })
    section(t(kind === 'multi' ? 'ribbonDocumentLists' : kind === 'bullets' ? 'ribbonDocumentBullets' : 'ribbonDocumentNumbers'), documentListPresets(options.definitions?.() ?? [])[kind], 'Document')
    const selectedLevel = options.level?.()
    if (selectedLevel && options.changeLevel) {
      const row = document.createElement('div'); row.className = 'list-gallery-levels'
      const label = document.createElement('span'); label.className = 'list-gallery-title'; label.textContent = t('ribbonChangeListLevel'); row.append(label)
      for (let i = 0; i < 9; i++) {
        const item = button(String(i + 1), `list-gallery-level${selectedLevel.current === i ? ' selected' : ''}`, () => commit(() => options.changeLevel!(i)))
        item.dataset.docxListLevel = String(i); item.dataset.levelUnavailable = String(!selectedLevel.available[i]); item.disabled = !selectedLevel.available[i]; row.append(item)
      }
      gallery.append(row)
    }
    const custom = button(`${t(kind === 'multi' ? 'ribbonDefineNewList' : kind === 'bullets' ? 'ribbonDefineNewBullet' : 'ribbonDefineNewNumber')}…`, 'list-gallery-define', define); custom.dataset.docxListDefine = ''; gallery.append(custom)
    element.append(gallery); toggle.setAttribute('aria-expanded', 'true'); refresh()
  }
  const dismiss = (event: MouseEvent) => { if (gallery && event.target instanceof Node && !element.contains(event.target)) close() }
  const escape = (event: KeyboardEvent) => {
    if (!gallery || event.key !== 'Escape' || event.isComposing || event.keyCode === 229 || event.defaultPrevented) return
    event.preventDefault(); event.stopPropagation(); close()
  }
  toggle.addEventListener('click', open); document.addEventListener('mousedown', dismiss); element.addEventListener('keydown', escape)
  toggle.setAttribute('aria-expanded', 'false'); refresh()
  return { element, refresh, destroy() {
    if (destroyed) return
    close(); destroyed = true; iconRoot.unmount(); toggle.removeEventListener('mousedown', preserveSelection); toggle.removeEventListener('click', open)
    document.removeEventListener('mousedown', dismiss); element.removeEventListener('keydown', escape); element.remove()
  } }
}
