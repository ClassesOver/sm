import { expect, it } from 'vitest'
import { buildPivotLayout } from '../src/pivot-layout'

const cases=[['percentOf',2,2],['difference',10,10],['percentDiff',1,1],['percentOfParent',.4,2/3],['runTotal',30,30],['percentOfRunningTotal',.6,1],['rankAscending',2,2],['rankDescending',1,1]] as const
const needsItem=(mode:string)=>['percentOf','difference','percentDiff'].includes(mode)
const grid=[['Group','Item','Period','Amount'],['G1','A','X',10],['G1','B','X',20],['G1','C','X',20],['G2','A','X',100],['G2','B','X',200],['G2','C','X',300]]
// Tabular layouts intentionally suppress repeated outer labels. Fill them
// down only for locating a row; expected arithmetic remains independent.
function filledRows(matrix:readonly(readonly(string|number|null)[])[]){let group:string|number|null=null;return matrix.map(row=>{if(row[0]!==null)group=row[0]!;return [group,...row.slice(1)]})}

it.each(cases)('calculates %s on the row axis with source subtotal and base-item semantics',(showDataAs,expected)=>{
 const layout=buildPivotLayout(grid,{rowFields:['Group','Item'],columnField:'Period',values:[{field:'Amount',agg:'sum',showDataAs,baseField:'Item',...(needsItem(showDataAs)?{baseItem:'A'}:{})}]})
 const at=(group:string,item:string)=>filledRows(layout.matrix).find(row=>row[0]===group&&row[1]===item)![2]
 expect(at('G1','B')).toBeCloseTo(expected)
 if(['difference','percentDiff'].includes(showDataAs))expect(at('G1','A')).toBeNull()
 if(showDataAs==='rankAscending')expect(at('G1','C')).toBe(2)
 if(showDataAs==='rankDescending')expect(at('G1','C')).toBe(1)
 if(showDataAs==='runTotal')expect(at('G2','B')).toBe(300)
 if(showDataAs==='percentOfRunningTotal')expect(at('G2','B')).toBe(.5)
 const subtotal=layout.matrix.find(row=>row[0]==='G1'&&row[1]==='Subtotal')![2]
 if(showDataAs==='percentOfParent')expect(subtotal).toBe(1)
 else expect(subtotal).toBeNull()
 expect(layout.definition.values[0]!.baseFieldIndex).toBe(1)
 if(needsItem(showDataAs))expect(layout.definition.values[0]!.baseItemIndex).toBe(0)
})

it.each(cases)('calculates %s on the column axis and resets accumulation per outer column',(showDataAs,_row,expected)=>{
 const layout=buildPivotLayout([['Region','Year','Item','Amount'],['East','2025','A',10],['East','2025','B',20],['East','2026','A',30],['East','2026','B',40]],{rowFields:'Region',columnField:['Year','Item'],values:[{field:'Amount',agg:'sum',showDataAs,baseField:'Item',...(needsItem(showDataAs)?{baseItem:'A'}:{})}]})
 const row=layout.matrix.find(row=>row[0]==='East')!
 expect(row[2]).toBeCloseTo(expected)
 if(showDataAs==='runTotal')expect(row[5]).toBe(70)
 expect(layout.definition.values[0]!.baseFieldIndex).toBe(2)
})

it('skips hidden base members in running totals and ranks',()=>{
 for(const showDataAs of ['runTotal','rankAscending'] as const){
  const layout=buildPivotLayout(grid,{rowFields:['Group','Item'],values:[{field:'Amount',agg:'sum',showDataAs,baseField:'Item'}]},undefined,{hiddenMembers:{row:[[],['B']]}})
  expect(filledRows(layout.matrix).find(row=>row[0]==='G1'&&row[1]==='C')![2]).toBe(showDataAs==='runTotal'?30:2)
 }
})

it.each([
 {showDataAs:'difference',baseItem:'A'},
 {showDataAs:'difference',baseField:'Amount',baseItem:'A'},
 {showDataAs:'difference',baseField:'Item'},
 {showDataAs:'difference',baseField:'Item',baseItem:'missing'},
] as const)('rejects missing/non-axis/unresolved bases before output: %s',value=>{
 expect(()=>buildPivotLayout(grid,{rowFields:['Group','Item'],values:[{field:'Amount',agg:'sum',...value}]})).toThrow(/base/i)
})
