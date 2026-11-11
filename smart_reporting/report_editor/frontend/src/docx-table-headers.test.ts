import { expect, it } from 'vitest'
import { projectTableHeaders, tableHeaderOperation } from './docx-table-headers'
import { patchTableRepeatHeaders } from '../../../reporting/doc_engine/bridge/docx-table-headers'
const source={type:'docTable',attrs:{docxIndex:2},content:[false,true,false].map(repeatHeader=>({type:'docTableRow',attrs:{repeatHeader,repeatHeaderEdited:false,rawTrPr:'keep'},content:[]}))}
const anchor={docxIndex:2,blockId:'table',expectedObjectSha256:'hash',editable:false}
it('replays the final flags without changing other attrs and detects exact table identity',()=>{
 const op={kind:'setTableRepeatHeaders',blockId:'table',expectedObjectSha256:'hash',expectedRowCount:3,prefixRowCount:2,headers:[true,true,false]}
 const projected=projectTableHeaders(source,anchor,op)
 expect(tableHeaderOperation(source,projected,anchor)).toEqual(op)
 expect(projected.content![1]!.attrs!.rawTrPr).toBe('keep')
 expect(()=>projectTableHeaders(source,anchor,{...op,expectedRowCount:2})).toThrow()
 expect(()=>projectTableHeaders(source,anchor,{...op,expectedObjectSha256:'foreign'})).toThrow()
 expect(()=>projectTableHeaders(source,anchor,{...op,headers:[null,true,false]})).toThrow()
})
it('patches direct rows only, preserving nested table, unrelated properties and untouched bytes',()=>{
 const nested='<w:tbl><w:tr><w:tc><w:p/></w:tc></w:tr></w:tbl>'
 const xml='<w:tbl><w:tblPr><w:jc w:val="center"/></w:tblPr><w:tr data="a"><w:trPr><w:cantSplit/><w:trHeight w:val="300"/></w:trPr><w:tc>'+nested+'</w:tc></w:tr><w:tr><w:trPr><w:tblHeader w:val="0"/><w:jc w:val="right"/></w:trPr><w:tc><w:p/></w:tc></w:tr></w:tbl>'
 const changed=patchTableRepeatHeaders(xml,2,[true,false])
 expect(changed).toContain('<w:cantSplit/><w:trHeight w:val="300"/><w:tblHeader/>')
 expect(changed).toContain(nested)
 expect(changed).toContain('<w:tblHeader w:val="0"/>')
 expect(()=>patchTableRepeatHeaders(xml,3,[true,false,true])).toThrow()
 expect(()=>patchTableRepeatHeaders(xml,2,[null,false])).toThrow()
})
