import {expect,it} from 'vitest'
import {PDF_VIEW_RIBBON_GROUPS} from './pdf-view-ribbon'

it('opens the compare command for a saved PDF',()=>{
 expect(PDF_VIEW_RIBBON_GROUPS.flatMap(group=>group.commands).find(command=>command.id==='genoffice.pdf.view.navigation.compare')?.enabled).toBe(true)
})

it('keeps source page alignment, normalized LCS counts, extras and truncation',async()=>{
 const path='./vendor/genoffice-pdf/renderer/compare-text'
 const module=await import(/* @vite-ignore */path).catch(()=>null)
 expect(module,'the fixed-source text comparison is available').not.toBeNull()
 if(!module)return
 const result=module.compareDocuments([{pageIndex:0,text:' stable  line\nold\nlast'},{pageIndex:1,text:'same'}],[{pageIndex:0,text:'stable line\nnew\nlast'},{pageIndex:1,text:'same'},{pageIndex:2,text:'extra'}])
 expect(result.equal).toBe(false)
 expect(result.pages.map((page:{pageIndex:number;addedCount:number;removedCount:number})=>[page.pageIndex,page.addedCount,page.removedCount])).toEqual([[0,1,1],[1,0,0],[2,1,0]])
 expect(result.pages[0].added).toEqual([{line:'new',index:1}])
 expect(module.compareDocuments([{pageIndex:0,text:'a\n'.repeat(4001)}],[{pageIndex:0,text:'b'}]).pages[0]).toMatchObject({addedCount:1,removedCount:4001,truncated:true})
 expect(module.compareDocuments([{pageIndex:0,text:' same  line '}],[{pageIndex:0,text:'same line'}]).equal).toBe(true)
})
