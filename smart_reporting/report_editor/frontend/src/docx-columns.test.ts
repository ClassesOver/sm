import {expect,it} from 'vitest'
import type {SectionInfo,SectionSettings} from '@genoffice/docx-engine'
import {docxColumnFacts,applyDocxCanvasColumns,applyDocxCanvasHf} from './docx-columns'
const settings:SectionSettings={pageWidth:7200,pageHeight:7200,marginLeft:720,marginRight:720,marginTop:720,marginBottom:720,orientation:'portrait',pageBorder:false,columns:2,colSpace:360}
const section=(extra:Partial<SectionInfo>={}):SectionInfo=>({settings:{...settings},firstBlockIndex:0,lastBlockIndex:1,startType:'nextPage',sectPrXml:'',titlePg:false,headerRefs:{},footerRefs:{},...extra})
it('uses the first page header variant for the shared canvas origin and reserves the trailing footer',()=>{
 const pm=document.createElement('div'),first=section({titlePg:true}),fallback={...settings,marginTop:1800}
 const heights={headerPx:10,footerPx:70,firstHeaderPx:100,firstFooterPx:200,evenHeaderPx:80,evenFooterPx:90}
 expect(applyDocxCanvasHf(pm,[first],fallback,heights,true)).toBe(148)
 expect(pm.style.paddingTop).toBe('148px');expect(pm.style.paddingBottom).toBe('118px')
 first.titlePg=false;first.pageNumberStart=2
 expect(applyDocxCanvasHf(pm,[first],fallback,heights,true)).toBe(128)
 first.settings={...settings,marginTopFixed:true,marginBottomFixed:true}
 expect(applyDocxCanvasHf(pm,[first],fallback,heights,true)).toBe(48)
 expect(pm.style.paddingBottom).toBe('48px')
})
it('matches source uniform facts and always uses the first section canvas geometry',()=>{
 const sections=[section(),section({firstBlockIndex:2,lastBlockIndex:3})],facts=docxColumnFacts(sections,{...settings,pageWidth:9000})
 expect(facts.sourceMode).toBe('uniform');expect(facts.colMode).toBe('uniform');expect(facts.section).toBe(sections[0].settings)
 expect(facts.colFlow).toMatchObject({cols:2,colWidthPx:180,gapPx:24})
})
it('uses the source mixed mode for continuous, nextColumn and differing layouts',()=>{
 for(const second of [section({startType:'continuous'}),section({startType:'nextColumn'}),section({settings:{...settings,columns:1}}),section({settings:{...settings,pageWidth:9000}})]){
  const facts=docxColumnFacts([section(),second],settings)
  expect(facts.sourceMode).toBe('mixed');expect(facts.colMode).toBe('mixed');expect(facts.colFlow).toBeNull()
 }
})
it('sets source measurement width including padding and clears uniform state when columns are removed',()=>{
 const pm=document.createElement('div');pm.style.width='900px'
 applyDocxCanvasColumns(pm,docxColumnFacts([section()],settings))
 expect(pm.classList.contains('native-uniform-columns')).toBe(true)
 expect(pm.style.width).toBe('480px');expect(pm.style.getPropertyValue('--native-col-measure-width')).toBe('276px')
 applyDocxCanvasColumns(pm,docxColumnFacts([section({settings:{...settings,columns:1}})],settings))
 expect(pm.classList.contains('native-uniform-columns')).toBe(false)
 expect(pm.style.getPropertyValue('--native-cols')).toBe('1')
})
it('keeps a single-column source mode while using the widest shared paper and explicit per-section widths',()=>{
 const first=section({settings:{...settings,columns:1}}),last=section({settings:{...settings,pageWidth:10080,marginLeft:1440,columns:1}})
 const facts=docxColumnFacts([first,last],last.settings),pm=document.createElement('div')
 expect(facts.colMode).toBe('none');expect(facts.section).toBe(first.settings);expect(facts.sectionWidths).toBe(true);expect(facts.paperWidth).toBe(672)
 applyDocxCanvasColumns(pm,facts)
 expect(pm.style.width).toBe('672px');expect(pm.style.paddingLeft).toBe('48px');expect(pm.classList.contains('native-uniform-columns')).toBe(false)
 applyDocxCanvasColumns(pm,docxColumnFacts([first],first.settings))
 expect(pm.style.width).toBe('480px')
})
