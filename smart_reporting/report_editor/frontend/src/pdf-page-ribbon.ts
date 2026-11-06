export interface PdfPageRibbonCommand {
  id: `genoffice.pdf.${string}`
  label: string
  enabled: boolean
  reason?: string
}

export interface PdfPageRibbonGroup {
  title: string
  commands: PdfPageRibbonCommand[]
}

const unavailable = (id: string, label: string, reason: string): PdfPageRibbonCommand => ({
  id: `genoffice.pdf.${id}`,
  label,
  enabled: false,
  reason,
})

export const PDF_PAGE_RIBBON_GROUPS: PdfPageRibbonGroup[] = [
  {
    title: 'Rotation',
    commands: [
      { id: 'genoffice.pdf.page.rotateLeft', label: '向左旋转', enabled: true },
      { id: 'genoffice.pdf.page.rotateRight', label: '向右旋转', enabled: true },
      { id: 'genoffice.pdf.page.rotateAll', label: '旋转全部页面', enabled: true },
    ],
  },
  {
    title: 'Page Operations',
    commands: [
      { id: 'genoffice.pdf.page.delete', label: '删除页面', enabled: true },
      unavailable('page.extract', '提取页面', '提取页面尚未接入授权下载与新修订登记'),
      unavailable('page.insertPdf', '插入 PDF', '插入外部 PDF 尚未接入来源身份验证和页面写回'),
      unavailable('page.insertBlank', '插入空白页', 'PDF bridge 尚未提供空白页插入操作'),
      unavailable('page.replace', '替换页面', '替换页面尚未接入来源身份验证和页面写回'),
    ],
  },
  {
    title: 'Crop & Resize',
    commands: [
      { id: 'genoffice.pdf.page.crop', label: '裁切页面', enabled: true },
      unavailable('page.size', '页面尺寸', 'PDF bridge 尚未提供页面尺寸变更操作'),
    ],
  },
  {
    title: 'Combine & Split',
    commands: [
      { id: 'genoffice.pdf.page.reverse', label: '反转页面', enabled: true },
      unavailable('page.splitPdf', '拆分 PDF', '拆分输出尚未接入授权下载与新修订登记'),
      unavailable('page.mergePdf', '合并 PDF', '合并输出尚未接入来源身份验证和新修订登记'),
      unavailable('page.mergePages', '合并页面', 'PDF bridge 尚未提供页面合并操作'),
      unavailable('page.splitPages', '拆分页面', 'PDF bridge 尚未提供页面拆分操作'),
    ],
  },
]
