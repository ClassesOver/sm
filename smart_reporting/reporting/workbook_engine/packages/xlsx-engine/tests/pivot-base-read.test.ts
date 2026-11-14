import { expect, it } from 'vitest'
import { readPivotMemberOrder, readPivotValueBase } from '../src/pivot-base-read'
const cache='<cacheField><sharedItems><s v="X"/><s v="Y"/></sharedItems></cacheField>'
const field='<pivotField><items><item x="1"/><item x="0"/><item t="default"/></items></pivotField>'
const source={mode:'difference',fieldNames:['Group','Item','Amount'],rows:[0,1],columns:[],cacheFields:['',cache,''],pivotFields:['',field,'']}
it.each([['true','true'],['false','false']] as const)('accepts the legal boolean cache spelling %s', (raw,label)=>{
 expect(readPivotMemberOrder(`<cacheField><sharedItems><b v="${raw}"/></sharedItems></cacheField>`,'<pivotField><items><item x="0"/></items></pivotField>')).toEqual([label])
})
it('resolves baseItem through field item positions rather than cache positions',()=>{
 expect(readPivotValueBase({...source,valueXml:'<dataField baseField="1" baseItem="0"/>'})).toEqual({base:{baseField:'Item',baseItem:'Y'},unsupported:false})
 expect(readPivotMemberOrder(cache,field)).toEqual(['Y','X'])
})
it.each([
 '<dataField baseItem="0"/>','<dataField baseField="2" baseItem="0"/>','<dataField baseField="-1" baseItem="0"/>',
 '<dataField baseField="1"/>','<dataField baseField="1" baseItem="2"/>',
 '<dataField baseField="1" baseItem="1048828"/>','<dataField baseField="1" baseItem="1048829"/>',
])('keeps invalid/sentinel base parameters read-only: %s',valueXml=>{
 expect(readPivotValueBase({...source,valueXml}).unsupported).toBe(true)
})
it('preserves numeric boolean and blank labels without conflating blank with missing',()=>{
 const mixed='<cacheField><sharedItems><n v="2.0"/><b v="1"/><m/></sharedItems></cacheField>',items='<pivotField><items><item x="2"/><item x="0"/><item x="1"/></items></pivotField>'
 expect(readPivotMemberOrder(mixed,items)).toEqual(['','2','true'])
 expect(readPivotValueBase({...source,cacheFields:['',mixed,''],pivotFields:['',items,''],valueXml:'<dataField baseField="1" baseItem="0"/>'}).base.baseItem).toBe('')
})
it.each([
 '<pivotField><items><item x="0"/><item x="0"/></items></pivotField>',
 '<pivotField><items><item x="999"/></items></pivotField>',
 '<pivotField><items><item t="sum"/></items></pivotField>',
])('declines unverifiable display orders instead of inventing one: %s',items=>{
 expect(readPivotMemberOrder(cache,items)).toBeUndefined()
})
it('declines unsupported typed date/error cache projection for order-dependent modes',()=>{
 const typed='<cacheField><sharedItems><d v="2024-01-01T00:00:00"/><e v="#N/A"/></sharedItems></cacheField>'
 expect(readPivotMemberOrder(typed,field)).toBeUndefined()
 expect(readPivotValueBase({...source,cacheFields:['',typed,''],valueXml:'<dataField baseField="1" baseItem="0"/>'}).unsupported).toBe(true)
})
