import { expect, it } from 'vitest'
import { configureExportButtons, exportOutcome } from './delivery-format'

it.each([
  ['pdf', 'pdf', 'PDF'], ['docx', 'word', 'Word'], ['md', 'md', 'MD'],
  ['xlsx', 'xlsx', 'XLSX'], ['pptx', 'pptx', 'PPTX'],
] as const)('uses the %s target for actual button and status text', (target, format, label) => {
  const primary = document.createElement('button')
  primary.innerHTML = '<svg></svg><span>导出 PDF</span>'
  const secondary = document.createElement('button')
  secondary.innerHTML = '<span>导出 Word</span>'
  expect(configureExportButtons(primary, secondary, target)).toBe(format)
  expect(primary.querySelector('span')?.textContent).toBe(`导出 ${label}`)
  expect(primary.getAttribute('aria-label')).toBe(`导出 ${label}`)
  expect(primary.querySelector('svg')).not.toBeNull()
  expect(primary.hidden).toBe(false)
  expect(secondary.hidden).toBe(true)
  expect(exportOutcome({ revision: 2, [format]: { downloadUrl: '/file' }, validation: { ok: true, issues: [] } }, target).title).toBe(`${label} 导出完成`)
})

it('retains both legacy document buttons and reports a genuinely missing requested format', () => {
  const primary = document.createElement('button'); primary.innerHTML = '<span></span>'
  const secondary = document.createElement('button'); secondary.innerHTML = '<span></span>'
  configureExportButtons(primary, secondary, 'document')
  expect(primary.textContent).toBe('导出 PDF')
  expect(secondary.textContent).toBe('导出 Word')
  expect(secondary.hidden).toBe(false)
  const partial = exportOutcome({ revision: 2, pdf: { downloadUrl: '/pdf' }, validation: { ok: true, issues: [] } }, 'document')
  expect(partial.failed).toBe(true)
  expect(partial.title).toContain('部分格式')
})

it('does not report success with only an editor link', () => {
  const result = exportOutcome({ revision: 2, editor: { openUrl: '/editor' }, validation: { ok: true, issues: [] } }, 'md')
  expect(result.failed).toBe(true)
  expect(result.title).toBe('未生成可下载文件')
})
