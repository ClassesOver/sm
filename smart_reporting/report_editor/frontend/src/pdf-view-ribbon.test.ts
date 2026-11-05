import { expect, it } from 'vitest'
import { PDF_VIEW_RIBBON_GROUPS, resolvePdfOutline } from './pdf-view-ribbon'

it('keeps the source View navigation and page zoom commands in order with verified capabilities', () => {
  expect(PDF_VIEW_RIBBON_GROUPS.map(group => group.commands.map(command => command.id))).toEqual([
    ['genoffice.pdf.view.navigation.thumbnails', 'genoffice.pdf.view.navigation.outline', 'genoffice.pdf.view.navigation.search', 'genoffice.pdf.view.navigation.pageSpread', 'genoffice.pdf.view.navigation.nightMode'],
    ['genoffice.pdf.view.pageZoom.goToPage', 'genoffice.pdf.view.pageZoom.zoomOut', 'genoffice.pdf.view.pageZoom.zoomIn', 'genoffice.pdf.view.pageZoom.fitWidth', 'genoffice.pdf.view.pageZoom.fitPage'],
  ])
  expect(PDF_VIEW_RIBBON_GROUPS.flatMap(group => group.commands.filter(command => command.enabled).map(command => command.id))).toEqual([
    'genoffice.pdf.view.navigation.thumbnails', 'genoffice.pdf.view.navigation.outline', 'genoffice.pdf.view.navigation.search', 'genoffice.pdf.view.navigation.pageSpread',
    'genoffice.pdf.view.pageZoom.goToPage', 'genoffice.pdf.view.pageZoom.zoomOut', 'genoffice.pdf.view.pageZoom.zoomIn',
    'genoffice.pdf.view.pageZoom.fitWidth', 'genoffice.pdf.view.pageZoom.fitPage',
  ])
})

it('resolves nested PDF named and explicit outline destinations to immutable source page indexes', async () => {
  const items = [
    { title: 'Summary', dest: 'intro', items: [{ title: 'Details', dest: [{ num: 4, gen: 0 }], items: [] }] },
    { title: 'External link', dest: null, url: 'https://example.com', items: [] },
  ]
  const rows = await resolvePdfOutline(items, {
    getDestination: async () => [{ num: 2, gen: 0 }],
    getPageIndex: async (ref: { num: number }) => ref.num - 1,
  })
  expect(rows).toEqual([
    { title: 'Summary', depth: 0, pageIndex: 1 },
    { title: 'Details', depth: 1, pageIndex: 3 },
  ])
})
