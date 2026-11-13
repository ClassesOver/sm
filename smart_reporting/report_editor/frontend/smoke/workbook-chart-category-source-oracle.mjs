// Execute the original category/series slot expressions, not a reconstructed
// expected-value algorithm. Requires the documented pinned GenOffice checkout.
import assert from 'node:assert/strict'
import {execFileSync} from 'node:child_process'
import {readFile,writeFile} from 'node:fs/promises'
import vm from 'node:vm'
import ts from 'typescript'

const directory=process.env.GENOFFICE_SOURCE_DIRECTORY??'/workspace/genoffice'
const pinned='f8c17004fb730df11f0f743164ffd8b4281bb38c'
const sourcePath='apps/sheets/src/renderer/WorkbookVisuals.tsx'
const git=args=>execFileSync('git',['-C',directory,...args],{encoding:'utf8'})
assert.equal(git(['rev-parse','HEAD']).trim(),pinned)
const original=git(['show',`HEAD:${sourcePath}`])
const bar=original.match(/const rowSlot =[^]*?(?=    const groupTop =)/)?.[0]
const column=original.match(/const catSlot =[^]*?(?=  const groupLeft =)/)?.[0]
assert(bar&&column,'Original slot expressions could not be located')
const local=await readFile(new URL('../src/workbook-vendor/grid/chart-category-axis.ts',import.meta.url),'utf8')
const localFunction=local.slice(local.indexOf('export function chartCategorySlot('),local.indexOf('export function planCategoryAxis('))
function execute(code,globals={}){
 const compiled=ts.transpileModule(code,{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText
 const context={exports:{},...globals}
 vm.runInNewContext(compiled,context,{timeout:1000})
 return context.exports
}
const adapter=execute(localFunction)
let checked=0
for(const kind of ['bar','column'])for(const reversed of [false,true])for(const count of [1,2,3,4,48]){
 const snippet=(kind==='bar'?bar:column).replace(/const (rowSlot|catSlot|seriesSlot)/g,'export const $1')
 const source=execute(snippet,{categoryReversed:reversed,visibleCount:count,seriesList:Array(3)})
 const spec={kind,axes:{category:{reversed}}}
 for(let index=0;index<count;index++){
  assert.equal(adapter.chartCategorySlot(spec,index,count),(source.rowSlot??source.catSlot)(index));checked++
 }
 for(let index=0;index<3;index++){
  assert.equal(adapter.chartCategorySlot(spec,index,3),source.seriesSlot(index));checked++
 }
}
const evidence={sourceCommit:pinned,sourcePath,checked,matched:checked,kinds:['bar','column'],orientations:['minMax','maxMin'],categoryCounts:[1,2,3,4,48],seriesCount:3}
if(process.env.WORKBOOK_CHART_CATEGORY_ORACLE_OUTPUT)await writeFile(process.env.WORKBOOK_CHART_CATEGORY_ORACLE_OUTPUT,JSON.stringify(evidence,null,2))
console.log(JSON.stringify(evidence,null,2))
