export type DesignFont = 'sans' | 'serif'
export type CoverRole = 'title' | 'period' | 'signature'
export type TypographyRole = 'body' | 'h1' | 'h2' | 'h3' | 'table' | 'caption'
export interface TextStyle {
  font: DesignFont; size: number; color: string; bold: boolean; lineHeight: number
  spaceBefore: number; spaceAfter: number; indent: number
}
export interface CoverBox extends TextStyle {
  text: string | null; visible: boolean; x: number; y: number; width: number; height: number
  align: 'left' | 'center' | 'right'
}
export interface DesignOptions { cover: boolean; toc: boolean; headerFooter: boolean; pageNumbers: boolean; sources: boolean }
export interface ReportDesign {
  version: 1
  options: DesignOptions
  cover: Record<CoverRole, CoverBox> & { preset: 'formal' | 'minimal'; background: string; showOrganization: boolean; showGeneratedBy: boolean; showDate: boolean }
  watermark: { enabled: boolean; text: string | null; font: DesignFont; size: number; color: string; opacity: number; angle: number; placement: 'center' | 'tile'; cover: boolean }
  typography: Record<TypographyRole, TextStyle>
}
export interface DocumentContext { title: string; periodLabel: string; organizationName: string; generatedByLabel: string; generatedDate: string; watermarkText: string }
export interface DesignDocument { design: ReportDesign; designSha256: string; documentContext: DocumentContext }
export interface DesignTemplate { templateId: string; name: string; design: ReportDesign }
export interface DesignPreview { previewId: string; status: 'running' | 'succeeded' | 'failed'; documentSha256?: string; designSha256?: string; pdfPath?: string; validation?: { ok: boolean; issues: { code?: string; message?: string }[]; layoutProvenance?: unknown }; error?: { code: string; message?: string } }
