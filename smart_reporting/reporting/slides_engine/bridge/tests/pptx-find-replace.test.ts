import { describe, expect, it } from 'vitest'
import { createBlankPptx, openPptx, savePptx, type TextElement } from '@genoffice/pptx-engine'
import { findReplaceEditable } from '../pptx-find-replace.ts'
import { splitXmlChildren } from '../../../doc_engine/packages/docx-engine/src/generate.ts'

const slideXml = (sp: string) => `<?xml version="1.0"?><p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><p:cSld><p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr/><p:sp><p:nvSpPr><p:cNvPr id="2" name="Shape"/><p:cNvSpPr/><p:nvPr/></p:nvSpPr><p:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="100" cy="100"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom></p:spPr><p:txBody><a:bodyPr/><a:lstStyle/><a:p><a:pPr/>${sp}</a:p></p:txBody></p:sp></p:spTree></p:cSld></p:sld>`
const run = (text: string, props = '') => `<a:r>${props ? `<a:rPr>${props}</a:rPr>` : '<a:rPr/>'}<a:t>${text}</a:t></a:r>`
async function parse(xml: string) {
  const bytes = await createBlankPptx()
  const opened = await openPptx(bytes)
  const path = opened.deck.slides[0]!.path
  opened.archive.entries.set(path, Buffer.from(xml))
  return openPptx(await savePptx(opened))
}

describe('findReplaceEditable on parsed source text', () => {
  it('allows one ordinary run and rejects formatting, fields, links, soft breaks and unknown extensions', async () => {
    const ordinary = await parse(slideXml(run('plain')))
    const single = ordinary.deck.slides[0]!.elements[0] as TextElement
    expect(findReplaceEditable(single)).toBe(true)
    const cases = [
      run('one') + run('two'),
      `<a:fld id="{ID}" type="slidenum"><a:rPr/><a:t>field</a:t></a:fld>`,
      run('linked', '<a:hlinkClick r:id="rId1"/>'),
      '<a:br/><a:r><a:rPr/><a:t>after</a:t></a:r>',
      `${run('text')}<a:extLst><a:ext uri="{custom}"/></a:extLst>`,
      '<a:unknown><a:t>unknown</a:t></a:unknown>',
    ]
    for (const body of cases) {
      const opened = await parse(slideXml(body))
      const element = opened.deck.slides[0]!.elements[0] as TextElement
      expect(findReplaceEditable(element), body).toBe(false)
    }
  })

  it('allows multiple ordinary paragraphs but rejects unknown paragraph/body children and non-text objects', async () => {
    const multi = await parse(slideXml(`${run('one')}</a:p><a:p>${run('two')}`))
    expect(findReplaceEditable(multi.deck.slides[0]!.elements[0] as TextElement)).toBe(true)
    const unknownPara = await parse(slideXml(`${run('plain')}<a:extLst><a:ext uri="x"/></a:extLst>`))
    expect(findReplaceEditable(unknownPara.deck.slides[0]!.elements[0] as TextElement)).toBe(false)
    expect(findReplaceEditable({ type: 'table' } as TextElement)).toBe(false)
  })
})
