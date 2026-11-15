import { expect, it } from 'vitest'
import { PIVOT_DATA_FIELD_EXT_URI, PIVOT_X14_NS, readPivotShowAs } from '../src/pivot-show-as'
const wrap=(body:string)=>`<pivotTableDefinition xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:p="${PIVOT_X14_NS}" xmlns:a="urn:foreign">${body}</pivotTableDefinition>`
const extension=(mode:string,uri=PIVOT_DATA_FIELD_EXT_URI)=>`<extLst><ext uri="${uri}"><p:dataField pivotShowAs="${mode}"/></ext></extLst>`

it('reads native and namespace-aliased x14 fields in core field order',()=>{
  expect(readPivotShowAs(wrap(`<dataFields><dataField showDataAs="index"/><dataField showDataAs="normal">${extension('percentOfParentRow')}</dataField><dataField>${extension('percentOfParentCol')}</dataField></dataFields>`))).toEqual(['index','percentOfParentRow','percentOfParentCol'])
})
it.each([
  extension('percentOfParentRow','wrong'),
  extension('percentOfParentRow')+extension('percentOfParentCol'),
  extension('percentOfParentRow').replace('<extLst>','<a:extLst>').replace('</extLst>','</a:extLst>'),
  '<extLst><ext uri="'+PIVOT_DATA_FIELD_EXT_URI+'"><p:dataField/></ext></extLst>',
])('keeps malformed or ambiguous extensions explicit instead of falling back to normal: %s',ext=>{
  expect(readPivotShowAs(wrap(`<dataFields><dataField showDataAs="normal">${ext}</dataField></dataFields>`))[0]).toMatch(/^unsupported:/)
})
it('retains an x14 base-field mode for the host parameter guard',()=>{
  expect(readPivotShowAs(wrap(`<dataFields><dataField showDataAs="normal">${extension('rankAscending')}</dataField></dataFields>`))).toEqual(['rankAscending'])
})
it('normalizes the native percent spelling to percentOf',()=>{
 expect(readPivotShowAs(wrap('<dataFields><dataField showDataAs="percent"/></dataFields>'))).toEqual(['percentOf'])
})
it.each([
 extension('difference'),
 extension('rankAscending').replace('pivotShowAs=', 'sourceField="0" pivotShowAs='),
 extension('rankAscending').replace('pivotShowAs=', 'uniqueName="OLAP" pivotShowAs='),
])('refuses invalid x14 native-mode or OLAP-only metadata: %s',ext=>{
 expect(readPivotShowAs(wrap(`<dataFields><dataField>${ext}</dataField></dataFields>`))[0]).toMatch(/^unsupported:/)
})
it('ignores foreign namespace dataFields containers and dataField lookalikes',()=>{
  expect(readPivotShowAs(wrap('<a:dataFields><dataField showDataAs="index"/></a:dataFields><dataFields><a:dataField showDataAs="index"/></dataFields>'))).toEqual([])
})
