// 纯XML outline读取；不依赖writer或workbook reader，保持导入路径无环。
import { readXmlAttribute } from './xml'

export function readOutlineSummary(worksheetXml: string) {
  const outlinePr = worksheetXml.match(/<outlinePr\b[^>]*>/)?.[0] ?? ''
  return {
    outlineSummaryBelow: readXmlAttribute(outlinePr, 'summaryBelow') !== '0',
    outlineSummaryRight: readXmlAttribute(outlinePr, 'summaryRight') !== '0',
  }
}

export function readOutlineLine(attributes: string) {
  return {
    ...(readXmlAttribute(attributes, 'outlineLevel') !== undefined ? {outlineLevel: Number(readXmlAttribute(attributes, 'outlineLevel'))} : {}),
    ...(readXmlAttribute(attributes, 'collapsed') === '1' ? {collapsed: true} : {}),
  }
}
