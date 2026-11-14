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
      { id: 'genoffice.pdf.page.extract', label: '提取页面', enabled: true },
      { id:'genoffice.pdf.page.insertPdf',label:'插入 PDF',enabled:true },
      { id:'genoffice.pdf.page.shrink',label:'压缩 PDF',enabled:true },
      { id: 'genoffice.pdf.page.insertBlank', label: '插入空白页', enabled: true },
      { id: 'genoffice.pdf.page.bates', label: 'Bates 编号', enabled: true },
      { id:'genoffice.pdf.page.replace',label:'替换页面',enabled:true },
    ],
  },
  {
    title: 'Crop & Resize',
    commands: [
      { id: 'genoffice.pdf.page.crop', label: '裁切页面', enabled: true },
      { id: 'genoffice.pdf.page.size', label: '页面尺寸', enabled: true },
    ],
  },
  {
    title: 'Combine & Split',
    commands: [
      { id: 'genoffice.pdf.page.reverse', label: '反转页面', enabled: true },
      { id: 'genoffice.pdf.page.splitPdf', label: '拆分 PDF', enabled: true },
      {id:'genoffice.pdf.page.mergePdf',label:'合并 PDF',enabled:true},
      { id: 'genoffice.pdf.page.mergePages', label: '合并页面', enabled: true },
      { id: 'genoffice.pdf.page.splitPages', label: '拆分页面', enabled: true },
    ],
  },
]
