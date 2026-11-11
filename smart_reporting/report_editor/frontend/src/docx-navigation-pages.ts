import type { Editor } from '@tiptap/core'
import { TextSelection } from '@tiptap/pm/state'
import type { SectionInfo, SectionSettings } from '@genoffice/docx-engine'
import type { PageCut } from './vendor/genoffice-docs/apps/docs/src/renderer/pagination-cuts'
import type { BlockBox, SectionGeom, RowSplitPatch } from './vendor/genoffice-docs/apps/docs/src/renderer/pagination-types'

export interface DocxNavigationPagination {
  cuts: PageCut[]; geoms: SectionGeom[]; blocks: BlockBox[]
  section: SectionSettings; sections: SectionInfo[]
  rowSplits?: RowSplitPatch[]; mirrorMargins?: boolean; colMode?: 'none' | 'uniform' | 'mixed'
}
export interface DocxNavigationPagesOptions {
  editor: Editor
  getPagination(stillCurrent: () => boolean): Promise<DocxNavigationPagination>
  getZoom(): number
  prepare?(): void
  onError?(error: unknown): void
}
interface ThumbBlock { el: HTMLElement; top: number; left: number; width: number }
interface ThumbPage { width: number; height: number; blocks: ThumbBlock[]; target?: HTMLElement }
const px = (twips: number) => twips / 15

// 固定源 NavPageThumbs 的克隆呈现思想；宿主无 page-wrap/gap ledger，不能直接复用其纸张坐标。
// 页数和范围只读取同源分页 cuts；不按 DOM 总高估页，不把段内/表格拆页伪装成块分页。
export function buildContinuousPageSnapshot(pm: HTMLElement, zoom: number, data: DocxNavigationPagination): { pages?: ThumbPage[]; reason?: string } {
  const unsupported = (reason: string) => ({ reason: '页面缩略图暂不支持：' + reason })
  const { cuts, geoms, blocks, section, sections } = data
  if (!(zoom > 0) || !Number.isFinite(zoom) || !pm.isConnected || !cuts.length) return unsupported('当前布局尚未完成测量')
  if (data.mirrorMargins) return unsupported('镜像页边距')
  if (data.colMode && data.colMode !== 'none' || geoms.some(g => (g.cols ?? 1) > 1 || g.vertical)) return unsupported('分栏或竖排布局')
  if (sections.some(s => s.settings.pageWidth !== section.pageWidth || s.settings.pageHeight !== section.pageHeight)) return unsupported('混合纸张尺寸')
  if ([section, ...sections.map(s => s.settings)].some(s => s.vAlign === 'center' || s.vAlign === 'bottom')) return unsupported('纵向对齐')
  if (sections.some(s => s.settings.marginLeft !== section.marginLeft || s.settings.marginRight !== section.marginRight)) return unsupported('多节不同页边距')
  if (data.rowSplits?.length || cuts.some(c => !['block', 'tail'].includes(c.lead.kind) || c.repeatHeader || c.leadTable || c.cutTable || c.tailTable)) return unsupported('表格跨页或段内拆分页')
  if (cuts.some(c => c.regions?.length || c.floats?.length || c.liftTop || c.leadSpill) || blocks.some(b => b.floated || b.floatTable || b.floatPicture || b.anchorOnly)) return unsupported('浮动对象或复杂页面区域')
  const width = px(section.pageWidth), height = px(section.pageHeight)
  if (!(width > 0 && height > 0)) return unsupported('纸张尺寸无效')
  const pmRect = pm.getBoundingClientRect()
  if (pmRect.width <= 0) return unsupported('当前正文不可见')
  const contentLeft = pmRect.left + (parseFloat(getComputedStyle(pm).paddingLeft) || 0) * zoom
  const pages: ThumbPage[] = []
  for (const cut of cuts) {
    const geom = geoms[cut.section] ?? geoms[0]
    if (!geom || !Number.isFinite(cut.start) || !Number.isFinite(cut.end) || cut.end < cut.start) return unsupported('分页几何信息不完整')
    const page: ThumbPage = { width, height, blocks: [] }
    if (cut.blank) { pages.push(page); continue }
    const lead = blocks[cut.lead.block]
    if (!lead?.el || !pm.contains(lead.el) || Math.abs(lead.top - cut.start) > 1) return unsupported('无法准确对应页面起始块')
    const leadRect = lead.el.getBoundingClientRect()
    const settings = sections[cut.section]?.settings ?? section
    const leadSpace = cut.leadDropsSpaceBefore ? (cut.leadMtPx ?? 0) : (lead.leadFoldPx ?? 0)
    const top = (geom.topPx ?? px(settings.marginTop)) + leadSpace
    const left = px(settings.marginLeft)
    for (const block of blocks) {
      if (block.top < cut.start - 0.5 || block.top >= cut.end - 0.5) continue
      if (!block.el || !pm.contains(block.el)) return unsupported('缺少真实正文块')
      if (block.top + (block.domHeight ?? block.height) > cut.end + 1) return unsupported('表格或段内拆分页')
      const rect = block.el.getBoundingClientRect()
      if (rect.width <= 0 || rect.height <= 0) continue
      page.blocks.push({ el: block.el, top: top + (rect.top - leadRect.top) / zoom, left: left + (rect.left - contentLeft) / zoom, width: rect.width / zoom })
    }
    if (!page.blocks.length) return unsupported('无法准确对应页面正文')
    page.target = lead.el; pages.push(page)
  }
  return { pages }
}

function safeClone(element: HTMLElement): HTMLElement {
  const clone = element.cloneNode(true) as HTMLElement
  clone.querySelectorAll('script,style,link,meta,iframe,object,embed,base').forEach(node => node.remove())
  for (const node of [clone, ...clone.querySelectorAll<HTMLElement>('*')]) {
    for (const attribute of [...node.attributes]) {
      if (['id', 'contenteditable', 'autofocus', 'tabindex', 'srcdoc'].includes(attribute.name) || attribute.name.startsWith('on') || /^(href|src|action)$/i.test(attribute.name) && /^\s*javascript:/i.test(attribute.value)) node.removeAttribute(attribute.name)
    }
    node.classList.remove('ProseMirror', 'doc-page')
  }
  clone.style.margin = '0'; clone.style.transform = 'none'; clone.style.zoom = '1'
  const style = getComputedStyle(element)
  for (const key of ['font-family', 'font-size', 'font-weight', 'font-style', 'line-height', 'color', 'text-align', 'white-space']) clone.style.setProperty(key, style.getPropertyValue(key))
  return clone
}

export function createDocxNavigationPages(options: DocxNavigationPagesOptions) {
  const { editor } = options
  const element = document.createElement('div'); element.className = 'docx-navigation-pages'; element.dataset.navigationPages = ''; element.hidden = true
  const status = document.createElement('p'); status.className = 'docx-navigation-empty'; status.setAttribute('role', 'status'); status.setAttribute('aria-live', 'polite')
  const list = document.createElement('div'); list.className = 'docx-navigation-page-list'; element.append(status, list)
  let disposed = false, visible = false, request = 0
  let current: { doc: typeof editor.state.doc; zoom: number; pages: ThumbPage[] } | undefined
  const updateActive = () => {
    if (!current || disposed || !visible || editor.isDestroyed) return
    const position = editor.state.selection.from
    let active = 0
    current.pages.forEach((page, index) => { if (page.target && editor.view.posAtDOM(page.target, 0) <= position) active = index })
    list.querySelectorAll<HTMLButtonElement>('[data-navigation-page]').forEach((button, index) => { if (index === active) button.setAttribute('aria-current', 'page'); else button.removeAttribute('aria-current') })
  }
  const refresh = () => {
    const identity = ++request
    current = undefined; list.replaceChildren()
    if (disposed || !visible || editor.isDestroyed) return
    try { options.prepare?.() } catch (error) { status.textContent = '无法准备页面视图'; options.onError?.(error); return }
    const doc = editor.state.doc, zoom = options.getZoom()
    const stillCurrent = () => !disposed && visible && request === identity && !editor.isDestroyed && editor.state.doc === doc && options.getZoom() === zoom
    status.textContent = '正在测量真实分页…'
    void Promise.resolve().then(() => stillCurrent() ? options.getPagination(stillCurrent) : undefined).then(data => {
      if (!data || !stillCurrent()) return
      const snapshot = buildContinuousPageSnapshot(editor.view.dom, zoom, data)
      if (snapshot.reason || !snapshot.pages) { status.textContent = snapshot.reason ?? '无法测量页面'; return }
      current = { doc, zoom, pages: snapshot.pages }; status.textContent = '共 ' + current.pages.length + ' 页（正文缩略图）'
      current.pages.forEach((page, index) => {
        const button = document.createElement('button'); button.type = 'button'; button.className = 'docx-navigation-page'; button.dataset.navigationPage = String(index); button.setAttribute('aria-label', '第 ' + (index + 1) + ' 页')
        const scale = Math.min(180 / page.width, 240 / page.height)
        const paper = document.createElement('div'); paper.className = 'docx-navigation-page-paper'; paper.setAttribute('aria-hidden', 'true'); paper.inert = true
        paper.style.width = page.width + 'px'; paper.style.height = page.height + 'px'; paper.style.transform = 'scale(' + scale + ')'
        const pmStyle = editor.view.dom.style
        for (let i = 0; i < pmStyle.length; i++) { const key = pmStyle.item(i); if (key.startsWith('--')) paper.style.setProperty(key, pmStyle.getPropertyValue(key)) }
        page.blocks.forEach(block => {
          const slot = document.createElement('div'); slot.className = 'docx-navigation-page-slot'; slot.style.top = block.top + 'px'; slot.style.left = block.left + 'px'; slot.style.width = block.width + 'px'; slot.append(safeClone(block.el)); paper.append(slot)
        })
        button.style.width = page.width * scale + 'px'; button.style.height = page.height * scale + 'px'
        const label = document.createElement('span'); label.className = 'docx-navigation-page-number'; label.textContent = String(index + 1)
        button.append(paper, label); list.append(button)
      })
      updateActive()
    }).catch(error => { if (stillCurrent()) { status.textContent = '页面测量失败，请重新打开页面标签'; options.onError?.(error) } })
  }
  const click = (event: MouseEvent) => {
    const button = (event.target as Element).closest<HTMLButtonElement>('[data-navigation-page]')
    if (!button || !element.contains(button)) return
    event.preventDefault()
    if (!current || !visible || disposed || editor.isDestroyed) return
    if (current.doc !== editor.state.doc || current.zoom !== options.getZoom()) { refresh(); return }
    const target = current.pages[Number(button.dataset.navigationPage)]?.target
    if (!target) return
    try {
      const position = editor.view.posAtDOM(target, 0)
      editor.view.dispatch(editor.state.tr.setSelection(TextSelection.near(editor.state.doc.resolve(position))).setMeta('addToHistory', false))
      target.scrollIntoView?.({ block: 'start', inline: 'nearest' }); updateActive()
    } catch (error) { options.onError?.(error) }
  }
  const mousedown = (event: MouseEvent) => { if ((event.target as Element).closest('[data-navigation-page]')) event.preventDefault() }
  const resize = () => { if (visible) refresh() }
  element.addEventListener('click', click); element.addEventListener('mousedown', mousedown); window.addEventListener('resize', resize)
  return { element, refresh, updateActive,
    setVisible(value: boolean) { if (disposed || visible === value) return; visible = value; element.hidden = !value; if (value) refresh(); else { request++; current = undefined; list.replaceChildren() } },
    dispose() { if (disposed) return; disposed = true; request++; current = undefined; element.removeEventListener('click', click); element.removeEventListener('mousedown', mousedown); window.removeEventListener('resize', resize); element.remove() },
  }
}
