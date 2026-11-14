import { expect, it } from 'vitest'
import { extractMasterRichText, masterRichTextHtml } from './slides-master-rich-text'
import { validateMasterTextDraft, type MasterTextPart } from './slides-master-text-model'

it('roundtrips paragraph and run identity, mixed formatting, and text without interpreting markup', () => {
  const source = [
    { srcPara: 4, align: 'center' as const, runs: [{ srcRun: 0, text: '品牌 <&>', bold: true, italic: false, underline: false, strike: false }, { srcRun: 1, text: '说明', bold: false, italic: true, underline: false, strike: false, color: '#123456' }] },
    { srcPara: 5, runs: [{ srcRun: 0, text: '第二段', bold: false, italic: false, underline: true, strike: false }] },
  ]
  const editor = document.createElement('div')
  editor.innerHTML = masterRichTextHtml(source)
  expect(editor.querySelector('script')).toBeNull()
  expect(extractMasterRichText(editor)).toEqual(source)
})

it('keeps source run tracing when a user adds formatting to an edited run', () => {
  const editor = document.createElement('div')
  editor.innerHTML = masterRichTextHtml([{ srcPara: 0, runs: [{ srcRun: 1, text: '旧字', italic: true }] }])
  const span = editor.querySelector('span')!
  span.innerHTML = '<b>新字</b>'
  expect(extractMasterRichText(editor)).toEqual([{ srcPara: 0, runs: [{ srcRun: 1, text: '新字', bold: true, italic: true, underline: false, strike: false }] }])
})

it('validates rich edits against editable part and run limits', () => {
  const parts = [{ partPath: 'ppt/slideMasters/slideMaster1.xml', kind: 'master', name: 'Master', elements: [{ spid: 7, name: 'Title', text: 'Title', editable: true, reason: null }] }] as MasterTextPart[]
  const edit = { partPath: parts[0]!.partPath, spid: 7, paragraphs: [{ srcPara: 0, runs: [{ srcRun: 0, text: '标题', bold: true }] }] }
  expect(validateMasterTextDraft([edit], parts)).toEqual([edit])
  expect(() => validateMasterTextDraft([{ ...edit, paragraphs: [{ runs: [{ srcRun: -1, text: '伪造 run' }] }] }], parts)).toThrow('身份或内容无效')
  expect(() => validateMasterTextDraft([{ ...edit, spid: 8 }], parts)).toThrow('身份或内容无效')
})
