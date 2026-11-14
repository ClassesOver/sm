import { expect, it } from 'vitest'
import { PDF_VIEW_RIBBON_GROUPS, resolvePdfOutline } from './pdf-view-ribbon'

it('keeps the source View navigation and page zoom commands in order with verified capabilities', () => {
  expect(PDF_VIEW_RIBBON_GROUPS.map(group => group.commands.map(command => command.id))).toEqual([
    ['genoffice.pdf.view.navigation.thumbnails', 'genoffice.pdf.view.navigation.outline', 'genoffice.pdf.view.navigation.comments', 'genoffice.pdf.view.navigation.compare', 'genoffice.pdf.view.navigation.attachments', 'genoffice.pdf.view.navigation.search', 'genoffice.pdf.view.navigation.pageSpread', 'genoffice.pdf.view.navigation.nightMode'],
    ['genoffice.pdf.view.pageZoom.goToPage', 'genoffice.pdf.view.pageZoom.zoomOut', 'genoffice.pdf.view.pageZoom.zoomIn', 'genoffice.pdf.view.pageZoom.fitWidth', 'genoffice.pdf.view.pageZoom.fitPage'],
  ])
  expect(PDF_VIEW_RIBBON_GROUPS.flatMap(group => group.commands.filter(command => command.enabled).map(command => command.id))).toEqual([
    'genoffice.pdf.view.navigation.thumbnails', 'genoffice.pdf.view.navigation.outline', 'genoffice.pdf.view.navigation.comments', 'genoffice.pdf.view.navigation.compare', 'genoffice.pdf.view.navigation.attachments', 'genoffice.pdf.view.navigation.search', 'genoffice.pdf.view.navigation.pageSpread', 'genoffice.pdf.view.navigation.nightMode',
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
    { title: 'External link', depth: 0, url: 'https://example.com' },
  ])
})

it('retains safe external bookmark actions in tree order without resolving their internal destination', async () => {
  const resolve = async () => { throw new Error('external action must not resolve a destination') }
  const rows = await resolvePdfOutline([
    { title: 'Website', dest: 'ignored', url: 'https://example.com/report', items: [
      { title: 'Contact', dest: null, url: 'mailto:review@example.com' },
    ] },
    { title: 'HTTP', dest: null, url: 'http://example.com' },
    ...['javascript:alert(1)', 'data:text/html,unsafe', 'file:///tmp/report', 'https:// bad host'].map(url => ({title: 'Unsafe', dest: null, url})),
  ], {getDestination: resolve, getPageIndex: resolve})
  expect(rows).toEqual([
    {title: 'Website', depth: 0, url: 'https://example.com/report'},
    {title: 'Contact', depth: 1, url: 'mailto:review@example.com'},
    {title: 'HTTP', depth: 0, url: 'http://example.com'},
  ])
})

it('renders external bookmarks as native user-activated links and keeps internal identity navigation', async () => {
  const {appendPdfOutlineLinks}=await import('./pdf-view-ribbon')
  const panel=document.createElement('nav'),clicked:string[]=[]
  const items=[
    {title:'First',depth:0,pageIndex:0},
    {title:'Website',depth:1,url:'https://example.com/report'},
    {title:'Removed page',depth:0,pageIndex:1},
    {title:'Second',depth:0,pageIndex:2},
  ]
  const pages=[{index:0,pageId:'source:first'},{index:2,pageId:'source:second'}]
  appendPdfOutlineLinks(panel,items,pages,id=>{clicked.push(id)})
  expect([...panel.children].map(node=>node.textContent)).toEqual(['First','Website','Second'])
  const external=panel.querySelector('a')!
  expect(external.href).toBe('https://example.com/report')
  expect(external.target).toBe('_blank');expect(external.rel).toBe('noopener noreferrer')
  expect(external.dataset.pageId).toBeUndefined()
  expect(external.style.getPropertyValue('--pdf-outline-depth')).toBe('1')
  let href=''
  external.addEventListener('click',event=>{event.preventDefault();href=external.href})
  external.click();expect(href).toBe('https://example.com/report');expect(clicked).toEqual([])
  const buttons=panel.querySelectorAll('button')
  buttons[1].click();expect(clicked).toEqual(['source:second'])
  expect(buttons[0].dataset.pageId).toBe('source:first')
})
