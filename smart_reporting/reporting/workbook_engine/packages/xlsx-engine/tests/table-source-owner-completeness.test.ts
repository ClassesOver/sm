import {expect,it} from 'vitest'
import {applyTableAdditions,createBlankWorkbook,readWorkbook} from '../src'
import {assemblePackage,createBufferEntrySource} from '../src/zip'

it.each(['all','second'])('withholds deletion identities when %s tablePart registrations are missing',async missing=>{
 const original=await applyTableAdditions(await createBlankWorkbook(),[
  {worksheetSheetName:'Sheet1',name:'First',area:{startRow:0,startColumn:0,endRow:2,endColumn:0},columnNames:['Amount'],bandedRows:true},
  {worksheetSheetName:'Sheet1',name:'Second',area:{startRow:0,startColumn:2,endRow:2,endColumn:2},columnNames:['Count'],bandedRows:true},
 ])
 const source=await createBufferEntrySource(original),path='xl/worksheets/sheet1.xml',xml=await source.readText(path)
 const incomplete=missing==='all'?xml.replace(/<tableParts\b[\s\S]*?<\/tableParts>/,''):xml.replace('count="2"','count="1"').replace(/<tablePart r:id="rId2"\/>/,'')
 const broken=(await assemblePackage(original,{replaced:new Map([[path,incomplete]]),added:new Map(),addedBinary:new Map(),removedEntries:[],addedEntries:[],touchedEntries:[path]})).buffer
 const sheet=(await readWorkbook(broken)).sheets[0]!
 expect(sheet.tableSources).toBeUndefined()
 expect(sheet.tableSourcesReadOnlyReason).toContain('登记')
 // 读取与拒绝均不能改写源包或删除任何实际表part。
 expect(await(await createBufferEntrySource(broken)).readText('xl/tables/table2.xml')).toBe(await source.readText('xl/tables/table2.xml'))
})
