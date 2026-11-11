import {expect,it,vi} from 'vitest'
import * as measurement from './vendor/genoffice-docs/apps/docs/src/renderer/pagination-snapshot'
import {mergeDocxColumnSpecs,layoutMixedDocxColumns} from './docx-mixed-columns'
it('merges source section and column placement without losing section geometry or column wrapping',()=>{
 const el=document.createElement('p')
 const [spec]=mergeDocxColumnSpecs([{el,widthPx:400,contentWPx:400,marginLeftPx:48,marginRightPx:48,pageDx:20,dx:16,dy:0}],[{el,widthPx:180,dx:204,dy:-360}])
 expect(spec).toMatchObject({widthPx:180,contentWPx:400,marginLeftPx:48,marginRightPx:48,pageDx:20,dx:220,dy:-360})
 expect(mergeDocxColumnSpecs([],[])).toEqual([])
})

it('measures source natural flow and restores the caller class even when measurement fails',()=>{
 const pm=document.createElement('div'),section={pageWidth:7200,pageHeight:7200,marginLeft:720,marginRight:720,marginTop:720,marginBottom:720}
 const measured=vi.spyOn(measurement,'withMeasuredPaginationSnapshot').mockImplementation(()=>{expect(pm.classList.contains('measuring-natural')).toBe(true);throw new Error('measure failed')})
 try{
  for(const original of [false,true]){
   pm.classList.toggle('measuring-natural',original)
   expect(()=>layoutMixedDocxColumns({} as never,{pm,section,sections:[],colMode:'mixed'} as never)).toThrow('measure failed')
   expect(pm.classList.contains('measuring-natural')).toBe(original)
  }
 }finally{measured.mockRestore()}
})
