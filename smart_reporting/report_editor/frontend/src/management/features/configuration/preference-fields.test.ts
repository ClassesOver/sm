import { expect, it } from 'vitest'
import { preferenceFields } from './preference-fields'

it('落款只显示维护内容，不把底层段落参数铺满页面', () => {
  expect(preferenceFields('signature', { signer: '编制人', dateFormat: 'iso', description: '',
    font: 'sans', size: 11, align: 'right', bold: false, color: '#172033', indent: 0,
    lineHeight: 1.6, spaceBefore: 18, spaceAfter: 6, dateGap: 4 })).toEqual({
    signer: '编制人', dateFormat: 'iso', font: 'sans', size: 11, align: 'right',
  })
})

it('导出不重复展示页眉页脚及纸张，页面不展示全部标题段落属性', () => {
  expect(preferenceFields('export', { cover: true, toc: true, sources: false,
    embedFonts: true, print: { page: { paper: 'A4' }, headerFooter: { enabled: true },
      fitToWidth: 1, repeatTitleRows: 1 } })).toEqual({
    cover: true, toc: true, sources: false, print: { fitToWidth: 1, repeatTitleRows: 1 },
  })
  expect(preferenceFields('page', { page: { paper: 'A4' }, typography: {
    body: { font: 'sans', size: 11, spaceAfter: 6 }, h1: { size: 16, spaceBefore: 12 } },
    rowHeight: null })).toEqual({ page: { paper: 'A4' }, body: { font: 'sans', size: 11 } })
})

it('关闭页眉页脚仅保留开关，未启用的首页和奇偶页参数不展示', () => {
  expect(preferenceFields('headerFooter', { enabled: false, header: { left: '示例' } })).toEqual({ enabled: false })
  expect(preferenceFields('headerFooter', { enabled: true, header: { left: '编制人', center: '', right: '' },
    firstPageDifferent: false, firstHeader: { left: '未生效' }, oddEvenDifferent: false,
    evenHeader: null, style: { size: 9, lineHeight: 1.6 } })).toEqual({
    enabled: true, header: { left: '编制人' }, firstPageDifferent: false, oddEvenDifferent: false,
  })
})

it('页面与表图只呈现业务选择，不透出默认边距和渲染参数', () => {
  expect(preferenceFields('page', { page: { paper: 'A4', orientation: 'portrait', margins: { top: 25, left: 22 } }, body: { size: 11, lineHeight: 1.6 } })).toEqual({ page: { paper: 'A4', orientation: 'portrait' }, body: { size: 11 } })
  expect(preferenceFields('tables', { tables: { repeatHeader: true, splitRows: false, borders: 'light', striped: true, captionNumbering: true }, charts: { imageDpi: 150, keepWithCaption: true, captionNumbering: true } })).toEqual({ tables: { repeatHeader: true, borders: 'light', striped: true, captionNumbering: true } })
})
