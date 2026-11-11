/** Browser-safe icon subset adapted from GenOffice PDF icons.tsx at f8c17004fb730df11f0f743164ffd8b4281bb38c. */
export type PdfRibbonIconName = 'sparkles' | 'download' | 'undo' | 'redo' | 'highlight' | 'note' | 'rotateLeft' | 'rotateRight' | 'deletePage' | 'fitWidth' | 'fitPage' | 'thumbnails' | 'print' | 'search'

const paths: Record<PdfRibbonIconName, string[]> = {
  sparkles: ['m12 3 2.7 6.3L21 12l-6.3 2.7L12 21l-2.7-6.3L3 12l6.3-2.7z', 'M20 2v4', 'M18 4h4'],
  download: ['M12 3v11', 'm7 9 5 5 5-5', 'M5 17v3h14v-3'],
  undo: ['M5.9 4 2.5 7.15l3.4 3.67', 'M4 7.4h11.2A6.3 6.3 0 1 1 15.2 20H6.9'],
  redo: ['M18.1 4 21.5 7.15l-3.4 3.67', 'M20 7.4H8.8A6.3 6.3 0 1 0 8.8 20h8.3'],
  highlight: ['M6 15 13.5 7.6l3.1 3.1L9.1 18.2H6z', 'm13.5 6.7 2.2-2.2 3.1 3.1-2.2 2.2', 'M5.2 19.5h12.4'],
  note: ['M4.5 5.6h15v9.6h-8.6l-4.3 3.2v-3.2H4.5z', 'M8.3 9.3h7.5', 'M8.3 12h4.8'],
  rotateLeft: ['M4.5 10V4.5H10', 'M5 8a7.5 7.5 0 1 1-.5 8'],
  rotateRight: ['M19.5 10V4.5H14', 'M19 8a7.5 7.5 0 1 0 .5 8'],
  deletePage: ['M7 4.5h10v15H7z', 'M4.5 7h15', 'M9.5 10v6', 'M14.5 10v6'],
  fitWidth: ['M4.5 5.6v12.8', 'M19.5 5.6v12.8', 'M7.7 12h8.6', 'm10 9.6-2.3 2.4 2.3 2.4', 'm14 9.6 2.3 2.4-2.3 2.4'],
  fitPage: ['M7 4.5h10v15H7z', 'M12 8v8', 'm9.8 10.2 2.2-2.2 2.2 2.2', 'm9.8 13.8 2.2 2.2 2.2-2.2'],
  thumbnails: ['M4.5 5h6v6.5h-6z', 'M4.5 14h6v5h-6z', 'M14 6h5.5', 'M14 10h5.5', 'M14 15h5.5', 'M14 18h5.5'],
  print: ['M7.7 8.8V4.5h8.6v4.3', 'M5 8.8h14v7H5z', 'M7.7 13.1h8.6v6.4H7.7z'],
  search: ['M16.7 10.6a6.1 6.1 0 1 1-12.2 0 6.1 6.1 0 0 1 12.2 0z', 'm15.3 15.3 4.2 4.2'],
}

export function createPdfRibbonIcon(name: PdfRibbonIconName, size = 20): SVGSVGElement {
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg')
  svg.setAttribute('viewBox', '0 0 24 24')
  svg.setAttribute('width', String(size))
  svg.setAttribute('height', String(size))
  svg.setAttribute('fill', 'none')
  svg.setAttribute('stroke', 'currentColor')
  svg.setAttribute('stroke-width', '1.5')
  svg.setAttribute('stroke-linecap', 'round')
  svg.setAttribute('stroke-linejoin', 'round')
  svg.setAttribute('aria-hidden', 'true')
  for (const path of paths[name]) {
    const element = document.createElementNS('http://www.w3.org/2000/svg', 'path')
    element.setAttribute('d', path)
    svg.append(element)
  }
  return svg
}
