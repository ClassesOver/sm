import { expect, it } from 'vitest'
import { withMeasuredPaginationSnapshot } from './vendor/genoffice-docs/apps/docs/src/renderer/pagination-snapshot'
import type { SectionSettings } from '@genoffice/docx-engine'

const section: SectionSettings = { pageWidth: 3000, pageHeight: 1500, orientation: 'portrait', marginTop: 0, marginBottom: 0, marginLeft: 0, marginRight: 0, pageBorder: false, columns: 1 }

it('shares real snapshot measurement at zoom 1 and restores zoom and neutralizing class on failure', () => {
  const zoom = document.createElement('div'), pm = document.createElement('div')
  zoom.className = 'doc-zoom'; zoom.style.zoom = '0.75'; zoom.append(pm); document.body.append(zoom)
  try {
    expect(() => withMeasuredPaginationSnapshot({ pm, section, sections: [], canvasTop: 0, colMode: 'uniform' }, snapshot => {
      expect(zoom.style.zoom).toBe('1')
      expect(pm.classList.contains('measuring-columns')).toBe(true)
      expect(snapshot.factor).toBe(1)
      expect(snapshot.live).toEqual([])
      throw new Error('consumer failure')
    })).toThrow('consumer failure')
    expect(zoom.style.zoom).toBe('0.75')
    expect(pm.classList.contains('measuring-columns')).toBe(false)
  } finally { zoom.remove() }
})

it('returns the consumer value and remeasures current DOM for each call', () => {
  const pm = document.createElement('div'); document.body.append(pm)
  try {
    const input = { pm, section, sections: [], canvasTop: 0, colMode: 'none' as const }
    expect(withMeasuredPaginationSnapshot(input, snapshot => snapshot.blocks.length)).toBe(0)
    const paragraph = document.createElement('p'); paragraph.textContent = 'new paragraph'; pm.append(paragraph)
    paragraph.getBoundingClientRect = () => ({ top: 0, left: 0, right: 100, bottom: 20, width: 100, height: 20, x: 0, y: 0, toJSON() {} })
    expect(withMeasuredPaginationSnapshot(input, snapshot => snapshot.blocks.length)).toBe(1)
    expect(pm.classList.contains('measuring-columns')).toBe(false)
  } finally { pm.remove() }
})
it('neutralizes section-width placement while measuring single-column documents and restores it afterwards',()=>{
 const pm=document.createElement('div');document.body.append(pm)
 try{
  const wider={...section,pageWidth:section.pageWidth+1440}
  const sections=[{settings:section,firstBlockIndex:0,lastBlockIndex:0,startType:'nextPage' as const,sectPrXml:'',titlePg:false,headerRefs:{},footerRefs:{}},{settings:wider,firstBlockIndex:1,lastBlockIndex:1,startType:'nextPage' as const,sectPrXml:'',titlePg:false,headerRefs:{},footerRefs:{}}]
  withMeasuredPaginationSnapshot({pm,section,sections,canvasTop:0,colMode:'none'},()=>expect(pm.classList.contains('measuring-columns')).toBe(true))
  expect(pm.classList.contains('measuring-columns')).toBe(false)
 }finally{pm.remove()}
})
it('neutralizes mirror placement even with identical single-column section widths',()=>{
 const pm=document.createElement('div');document.body.append(pm)
 try{
  withMeasuredPaginationSnapshot({pm,section,sections:[],canvasTop:0,colMode:'none',mirrorMargins:true},()=>expect(pm.classList.contains('measuring-columns')).toBe(true))
  expect(pm.classList.contains('measuring-columns')).toBe(false)
 }finally{pm.remove()}
})
