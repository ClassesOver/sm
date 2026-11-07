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
export interface ResolvedPdfOutlineItem { title: string; depth: number; pageIndex: number }

const unavailable = (id: string, label: string, reason: string): PdfViewRibbonCommand => ({ id: `genoffice.pdf.${id}`, label, enabled: false, reason })

export const PDF_VIEW_RIBBON_GROUPS: PdfViewRibbonGroup[] = [
  {
    title: 'Navigation',
    commands: [
      { id: 'genoffice.pdf.view.navigation.thumbnails', label: '缩略图', enabled: true },
      { id: 'genoffice.pdf.view.navigation.outline', label: '目录大纲', enabled: true },
      unavailable('view.navigation.comments', '批注侧栏', '批注汇总、定位、编辑和回复侧栏尚未接通'),
      unavailable('view.navigation.compare', '比较文档', '第二份 PDF 的来源身份与比较视图尚未接通'),
      unavailable('view.navigation.attachments', '附件', '附件读取、提取和授权交付尚未接通'),
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
      const destination = typeof item.dest === 'string' ? await document.getDestination(item.dest) : item.dest
      if (destination?.[0]) {
        const pageIndex = await document.getPageIndex(destination[0])
        if (Number.isInteger(pageIndex) && pageIndex >= 0) rows.push({ title: item.title, depth, pageIndex })
      }
      if (item.items?.length) await visit(item.items, depth + 1)
    }
  }
  await visit(outline, 0)
  return rows
}
