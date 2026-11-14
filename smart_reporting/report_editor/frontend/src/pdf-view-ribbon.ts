export interface PdfViewRibbonCommand {
  id: `genoffice.pdf.${string}`
  label: string
  enabled: boolean
  reason?: string
}

export interface PdfViewRibbonGroup {
  title: string
  commands: PdfViewRibbonCommand[]
}

export interface PdfOutlineItem { title: string; dest: string | unknown[] | null; url?: string | null; items?: PdfOutlineItem[] }
export type ResolvedPdfOutlineItem = { title: string; depth: number } & ({ pageIndex: number; url?: never } | { url: string; pageIndex?: never })

export const PDF_VIEW_RIBBON_GROUPS: PdfViewRibbonGroup[] = [
  {
    title: 'Navigation',
    commands: [
      { id: 'genoffice.pdf.view.navigation.thumbnails', label: '缩略图', enabled: true },
      { id: 'genoffice.pdf.view.navigation.outline', label: '目录大纲', enabled: true },
      { id: 'genoffice.pdf.view.navigation.comments', label: '批注侧栏', enabled: true },
      { id: 'genoffice.pdf.view.navigation.compare', label: '比较文档', enabled: true },
      { id: 'genoffice.pdf.view.navigation.attachments', label: '附件', enabled: true },
      { id: 'genoffice.pdf.view.navigation.search', label: '搜索', enabled: true },
      { id: 'genoffice.pdf.view.navigation.pageSpread', label: '双页视图', enabled: true },
      { id: 'genoffice.pdf.view.navigation.nightMode', label: '夜间模式', enabled: true },
    ],
  },
  {
    title: 'Page & Zoom',
    commands: [
      { id: 'genoffice.pdf.view.pageZoom.goToPage', label: '跳转到页面', enabled: true },
      { id: 'genoffice.pdf.view.pageZoom.zoomOut', label: '缩小', enabled: true },
      { id: 'genoffice.pdf.view.pageZoom.zoomIn', label: '放大', enabled: true },
      { id: 'genoffice.pdf.view.pageZoom.fitWidth', label: '适合宽度', enabled: true },
      { id: 'genoffice.pdf.view.pageZoom.fitPage', label: '适合页面', enabled: true },
    ],
  },
]

export async function resolvePdfOutline(
  outline: PdfOutlineItem[],
  document: { getDestination(id: string): Promise<unknown[] | null>; getPageIndex(ref: any): Promise<number> },
): Promise<ResolvedPdfOutlineItem[]> {
  const rows: ResolvedPdfOutlineItem[] = []
  const visit = async (items: PdfOutlineItem[], depth: number): Promise<void> => {
    for (const item of items) {
      if (item.url) {
        // 与已保存链接一致，只为普通网络/邮件动作创建可点击入口。
        try {
          const url = new URL(item.url)
          if (['http:', 'https:', 'mailto:'].includes(url.protocol)) rows.push({ title: item.title, depth, url: item.url })
        } catch { /* 无效外部动作不执行，也不降级为内部跳转。 */ }
      } else {
        const destination = typeof item.dest === 'string' ? await document.getDestination(item.dest) : item.dest
        if (destination?.[0] !== undefined && destination[0] !== null) {
          const pageIndex = typeof destination[0] === 'number' ? destination[0] : await document.getPageIndex(destination[0])
          if (Number.isInteger(pageIndex) && pageIndex >= 0) rows.push({ title: item.title, depth, pageIndex })
        }
      }
      if (item.items?.length) await visit(item.items, depth + 1)
    }
  }
  await visit(outline, 0)
  return rows
}

/** 外链保留为用户激活的原生链接；内部目录仍绑定来源页面身份。 */
export function appendPdfOutlineLinks(
  panel: HTMLElement,
  outline: ResolvedPdfOutlineItem[],
  pages: { index: number; pageId: string }[],
  navigate: (pageId: string) => void,
): void {
  for (const item of outline) {
    const page = item.url === undefined ? pages.find(candidate => candidate.index === item.pageIndex) : undefined
    if (item.url === undefined && !page) continue
    const link: HTMLElement = item.url !== undefined ? panel.ownerDocument.createElement('a') : panel.ownerDocument.createElement('button')
    link.className = 'pdf-outline-link'; link.textContent = item.title
    link.style.setProperty('--pdf-outline-depth', String(item.depth))
    if (item.url !== undefined) {
      const anchor = link as HTMLAnchorElement
      anchor.href = item.url; anchor.target = '_blank'; anchor.rel = 'noopener noreferrer'
    } else {
      const button = link as HTMLButtonElement
      button.type = 'button'; button.dataset.pageId = page!.pageId
      button.addEventListener('click', () => navigate(page!.pageId))
    }
    link.addEventListener('keydown', event => {
      if (event.altKey || event.ctrlKey || event.metaKey || event.shiftKey || !['Home', 'End'].includes(event.key) || link.scrollHeight <= link.clientHeight) return
      event.preventDefault(); link.scrollTop = event.key === 'Home' ? 0 : link.scrollHeight - link.clientHeight
    })
    panel.append(link)
  }
}
