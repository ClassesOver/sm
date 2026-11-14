import {expect,it,vi} from 'vitest'
import {resolvePdfOutline} from './pdf-view-ribbon'

it.each([0,2])('accepts the fixed heading builder numeric destination for page index %s',async pageIndex=>{
 const getPageIndex=vi.fn(async()=>{throw Error('numeric page indices are not PDF indirect references')})
 const document={getDestination:async()=>null,getPageIndex}
 await expect(resolvePdfOutline([{title:'Heading',dest:[pageIndex,{name:'XYZ'},null,720,null]}],document)).resolves.toEqual([{title:'Heading',depth:0,pageIndex}])
 expect(getPageIndex).not.toHaveBeenCalled()
})
