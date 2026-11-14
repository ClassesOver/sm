import { describe, expect, it } from 'vitest'
import { renderEditorLayoutProvenance } from './editor-layout-provenance'
const provenance = () => ({ version: 1, template: { filename: '<img src=x onerror=alert(1)>.docx', size: 42, sha256: 'a'.repeat(64) }, contentSha256: 'b'.repeat(64), layoutValidation: 'unverified', undeclaredSamples: 'not_assessed', previewSourceFormat: 'word', formats: { word: { artifact: { size: 25, sha256: 'c'.repeat(64) }, layoutSource: 'uploaded_template', signatureSource: 'frozen_revision_preferences', generatedDate: '2026-11-13', dateFormatSource: 'editor_design', descriptionSource: 'editor_reset', placement: 'declared_template_slot', signatureLayoutSource: 'template', templateSampleStatus: 'replaced', signatureReadback: 'passed', bodyReadback: 'structure_verified' }, pdf: { artifact: { size: 26, sha256: 'd'.repeat(64) }, layoutSource: 'uploaded_template', signatureSource: 'frozen_revision_preferences', generatedDate: null, dateFormatSource: 'frozen_revision_preferences', descriptionSource: 'unavailable', placement: 'body_end', signatureLayoutSource: 'generated_fallback', templateSampleStatus: 'no_declared_slot', signatureReadback: 'unverified', bodyReadback: 'sample_only' } } })

describe('editor layout provenance', () => {
  it('renders collapsed safe Word and PDF generation receipts without overstating validation', () => {
    const host = document.createElement('div')
    renderEditorLayoutProvenance(host, { ...provenance(), path: '/private/template.docx' })
    expect(host.querySelector('details')?.open).toBe(false)
    expect(host.hidden).toBe(false)
    expect(host.textContent).toContain('文字文档')
    expect(host.textContent).toContain('PDF')
    expect(host.textContent).toContain('文字抽样')
    expect(host.textContent).toContain('编辑器明确修改')
    expect(host.textContent).toContain('编辑器重置')
    expect(host.textContent).toContain('不随当前默认变化')
    expect(host.textContent).toContain('由文字文档转换')
    expect(host.textContent).toContain('完整布局未验证')
    expect(host.textContent).not.toContain('/private')
    expect(host.querySelector('img')).toBeNull()
  })
  it('clears prior receipts for absent legacy responses and marks malformed receipts for review', () => {
    const host = document.createElement('div')
    renderEditorLayoutProvenance(host, provenance())
    renderEditorLayoutProvenance(host, undefined)
    expect(host.childElementCount).toBe(0)
    expect(host.hidden).toBe(true)
    for (const value of [null, [], { ...provenance(), version: 2 }, { ...provenance(), contentSha256: 'invalid' }]) {
      renderEditorLayoutProvenance(host, value)
      expect(host.textContent).toContain('待复核')
      expect(host.textContent).not.toContain('原生结构已核验')
    }
  })
  it('rejects unknown and inherited enums, invalid identities and impossible dates', () => {
    for (const change of [{ placement: 'toString' }, { bodyReadback: 'unknown' }, { generatedDate: '2026-02-30' }, { artifact: { size: true, sha256: 'c'.repeat(64) } }]) {
      const receipt = provenance()
      Object.assign(receipt.formats.word, change)
      const host = document.createElement('div')
      renderEditorLayoutProvenance(host, receipt)
      expect(host.textContent).toContain('待复核')
      expect(host.textContent).not.toContain('原生结构已核验')
    }
  })
  it('uses neutral source wording when frozen signature or generation date is unavailable', () => {
    const receipt = provenance()
    receipt.formats.word.signatureSource = 'unavailable'
    receipt.formats.word.generatedDate = null as never
    const host = document.createElement('div')
    renderEditorLayoutProvenance(host, receipt)
    expect(host.textContent).not.toContain('署名及生成日期采用当前修订冻结值')
    expect(host.textContent).toContain('署名及生成日期的来源以各格式回执为准')
    expect(host.textContent).toContain('署名来源：待核验；冻结生成日期：待核验')
  })
  it('rejects template filenames containing internal paths or control characters without displaying them', () => {
    for (const filename of ['/private/report.docx', String.raw`C:\private\report.docx`, 'private/report.docx', 'report\nprivate.docx', 'report\tprivate.docx', 'report\u007fprivate.docx']) {
      const receipt = provenance()
      receipt.template.filename = filename
      const host = document.createElement('div')
      renderEditorLayoutProvenance(host, receipt)
      expect(host.textContent).toContain('待复核')
      expect(host.textContent).not.toContain(filename)
      expect(host.textContent).not.toContain('private')
    }
  })

  it('labels semantic template placement as model judgment without claiming author declaration or layout approval', () => {
    const receipt = provenance()
    receipt.formats.word.placement = 'semantic_template_slot'
    const host = document.createElement('div')
    renderEditorLayoutProvenance(host, receipt)
    expect(host.textContent).toContain('语义识别位置（模型判断）')
    expect(host.textContent).not.toContain('模板声明位置')
    expect(host.textContent).toContain('完整布局未验证')
    expect(host.querySelector('details')?.open).toBe(false)
  })

  it.each(['replaced', 'cleared'])('uses semantic sample wording for semantic placement: %s', status => {
    const receipt = provenance()
    receipt.formats.word.placement = 'semantic_template_slot'
    receipt.formats.word.templateSampleStatus = status
    delete (receipt.formats as { pdf?: unknown }).pdf
    const host = document.createElement('div')
    renderEditorLayoutProvenance(host, receipt)
    expect(host.textContent).toContain(status === 'replaced' ? '语义识别样例已替换' : '语义识别样例已清除')
    expect(host.textContent).not.toContain('声明样例已')
  })

})
