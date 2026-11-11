import { expect, it } from 'vitest'
import { parseDocx } from '../src/index'
import { buildDocx } from './helpers/build-docx'
import { editParagraphRulerIndent, paragraphRulerIndentAvailability, validateParagraphRulerIndent } from '../../../bridge/docx-ruler-indent'
const paragraph = `<w:p w:rsidR="AB"><w:pPr><w:keepNext/><w:ind w:start='31' w:right="521" w:firstLine="90" x:foo='keep'/><w:jc w:val="center"/><x:unknown a='b'/></w:pPr><w:r><w:rPr><w:b/></w:rPr><w:t>正文</w:t></w:r></w:p>`
it('精准替换授权缩进属性，保留右缩进、未知XML与run字节', async () => {
  const block = (await parseDocx(await buildDocx({ bodyXml: paragraph }))).blocks[0]!
  const result = editParagraphRulerIndent(block, { leftTwips: 133, firstLineTwips: -277 })
  expect(result.xml).toContain('w:left="133"')
  expect(result.xml).toContain('w:hanging="277"')
  expect(result.xml).not.toContain('w:firstLine="90"')
  expect(result.xml).not.toContain("w:start='31'")
  expect(result.xml).toContain('w:right="521"')
  expect(result.xml).toContain("x:foo='keep'")
  expect(result.xml.slice(result.xml.indexOf('<w:jc'))).toBe(paragraph.slice(paragraph.indexOf('<w:jc')))
  const reread = (await parseDocx(await buildDocx({ bodyXml: result.xml }))).blocks[0]!
  expect(reread.format).toMatchObject({ indentLeft: 133, indentFirstLine: -277, indentRight: 521 })
})
it('继承首行可清零，省略左缩进不物化样式值', async () => {
  const stylesXml = '<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/><w:pPr><w:ind w:left="450" w:hanging="300"/></w:pPr></w:style></w:styles>'
  const block = (await parseDocx(await buildDocx({ bodyXml: '<w:p><w:r><w:t>正文</w:t></w:r></w:p>', stylesXml }))).blocks[0]!
  const result = editParagraphRulerIndent(block, { firstLineTwips: 0 })
  expect(result.xml).not.toContain('w:left=')
  const reread = (await parseDocx(await buildDocx({ bodyXml: result.xml, stylesXml }))).blocks[0]!
  expect(reread.format?.effective?.indent).toMatchObject({ left: 450, firstLine: 0 })
})
it('字符缩进、RTL及列表只读，严格值校验', async () => {
  const block = (await parseDocx(await buildDocx({ bodyXml: paragraph }))).blocks[0]!
  expect(paragraphRulerIndentAvailability(block).rulerIndentEditable).toBe(true)
  for (const format of [{ charIndents: { firstLine: 200 } }, { charIndents: { left: 100 } }, { bidiInherited: true }]) expect(paragraphRulerIndentAvailability({ ...block, format }).rulerIndentEditable).toBe(false)
  expect(paragraphRulerIndentAvailability({ ...block, type: 'listItem' }).rulerIndentEditable).toBe(false)
  for (const value of [{}, { leftTwips: NaN }, { firstLineTwips: 14401 }, { firstLineTwips: '10' }, { rightTwips: 2 }]) expect(() => validateParagraphRulerIndent(value)).toThrow()
})
it('左缩进单独改变不触碰悬挂及right字符属性，正首行只动special组', async () => {
  const xml = '<w:p><w:pPr><w:ind w:left="150" w:rightChars="200" w:hanging="301" x:keep="yes"/></w:pPr><w:r><w:t>x</w:t></w:r></w:p>'
  const block = (await parseDocx(await buildDocx({ bodyXml: xml }))).blocks[0]!
  const left = editParagraphRulerIndent(block, { leftTwips: 137 })
  expect(left.xml).toContain('w:hanging="301"')
  expect(left.xml).toContain('w:rightChars="200"')
  const special = editParagraphRulerIndent(block, { firstLineTwips: 213 })
  expect(special.xml).toContain('w:left="150"')
  expect(special.xml).toContain('w:firstLine="213"')
  expect(special.xml).not.toContain('w:hanging="301"')
  expect((await parseDocx(await buildDocx({ bodyXml: special.xml }))).blocks[0]!.format?.indentFirstLine).toBe(213)
})
it('继承字符缩进与属性修订只读，不能借原始XML绕过', async () => {
  const stylesXml = '<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:pPr><w:ind w:firstLineChars="200"/></w:pPr></w:style></w:styles>'
  const inherited = (await parseDocx(await buildDocx({ bodyXml: '<w:p><w:r><w:t>正文</w:t></w:r></w:p>', stylesXml }))).blocks[0]!
  expect(paragraphRulerIndentAvailability(inherited).rulerIndentEditable).toBe(false)
  expect(() => editParagraphRulerIndent(inherited, { firstLineTwips: 300 })).toThrow()
  const block = (await parseDocx(await buildDocx({ bodyXml: paragraph }))).blocks[0]!
  for (const xml of [paragraph.replace('<w:keepNext/>', '<w:pPrChange w:id="1"><w:pPr/></w:pPrChange>'), paragraph.replace('<w:keepNext/>', '<w:ind w:left="2"/>'), paragraph.replace('w:right="521"', 'w:right="521" w:right="222"')]) {
    expect(paragraphRulerIndentAvailability({ ...block, originalXml: xml }).rulerIndentEditable).toBe(false)
  }
})
