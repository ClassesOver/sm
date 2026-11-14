import { expect, it } from 'vitest'
import { PDF_PAGE_RIBBON_GROUPS } from './pdf-page-ribbon'

it('preserves the source Pages command order, groups, identities, and verified capability boundary', () => {
  expect(PDF_PAGE_RIBBON_GROUPS.map(group => group.commands.map(command => command.id))).toEqual([
    ['genoffice.pdf.page.rotateLeft', 'genoffice.pdf.page.rotateRight', 'genoffice.pdf.page.rotateAll'],
    ['genoffice.pdf.page.delete', 'genoffice.pdf.page.extract', 'genoffice.pdf.page.insertPdf', 'genoffice.pdf.page.shrink', 'genoffice.pdf.page.insertBlank', 'genoffice.pdf.page.bates', 'genoffice.pdf.page.replace'],
    ['genoffice.pdf.page.crop', 'genoffice.pdf.page.size'],
    ['genoffice.pdf.page.reverse', 'genoffice.pdf.page.splitPdf', 'genoffice.pdf.page.mergePdf', 'genoffice.pdf.page.mergePages', 'genoffice.pdf.page.splitPages'],
  ])
  expect(PDF_PAGE_RIBBON_GROUPS.flatMap(group => group.commands.filter(command => command.enabled).map(command => command.id))).toEqual([
    'genoffice.pdf.page.rotateLeft', 'genoffice.pdf.page.rotateRight', 'genoffice.pdf.page.rotateAll', 'genoffice.pdf.page.delete', 'genoffice.pdf.page.extract', 'genoffice.pdf.page.insertPdf', 'genoffice.pdf.page.shrink', 'genoffice.pdf.page.insertBlank', 'genoffice.pdf.page.bates', 'genoffice.pdf.page.replace', 'genoffice.pdf.page.crop', 'genoffice.pdf.page.size', 'genoffice.pdf.page.reverse', 'genoffice.pdf.page.splitPdf', 'genoffice.pdf.page.mergePdf', 'genoffice.pdf.page.mergePages', 'genoffice.pdf.page.splitPages',
  ])
  expect(PDF_PAGE_RIBBON_GROUPS.flatMap(group => group.commands).every(command => command.id.startsWith('genoffice.pdf.'))).toBe(true)
})
