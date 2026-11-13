// Execute the pinned original algorithm, rather than a copied expected-value
// implementation. This read-only probe requires a local GenOffice checkout.
import assert from 'node:assert/strict'
import {execFileSync} from 'node:child_process'
import {readFile,writeFile} from 'node:fs/promises'
import {fileURLToPath} from 'node:url'
import vm from 'node:vm'
import ts from 'typescript'

const sourceDirectory=process.env.GENOFFICE_SOURCE_DIRECTORY??'/workspace/genoffice'
const pinned='f8c17004fb730df11f0f743164ffd8b4281bb38c'
const sourcePath='packages/xlsx-gateway/src/domain/chart-visual.ts'
const git=args=>execFileSync('git',['-C',sourceDirectory,...args],{encoding:'utf8'})
assert.equal(git(['rev-parse','HEAD']).trim(),pinned,'The oracle must use the documented original source revision')
const original=git(['show',`HEAD:${sourcePath}`])
const start=original.indexOf('export function valueAxisScale('),end=original.indexOf('/// Excel inserts charts',start)
assert(start>=0&&end>start,'Cannot locate the bounded original algorithm')
function executeTypescript(text){
 const compiled=ts.transpileModule(text,{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText
 const context={exports:{}}
 vm.runInNewContext(compiled,context,{timeout:1000})
 return context.exports
}
const source=executeTypescript(original.slice(start,end))
const local=executeTypescript(await readFile(fileURLToPath(new URL('../src/workbook-vendor/grid/chart-value-scale.ts',import.meta.url)),'utf8'))
let seed=190,checked=0
const random=()=>{seed=(Math.imul(seed,1664525)+1013904223)>>>0;return seed/2**32}
const corrections=[]
const equal=(a,b)=>Math.abs(a-b)<=Math.max(Number.MIN_VALUE,Math.abs(a),Math.abs(b))*1e-12
for(let index=0;index<250;index++){
 const magnitude=10**Math.floor(random()*16-8)
 const values=[(random()-.5)*magnitude,(random()-.5)*magnitude]
 const low=Math.min(0,...values),high=Math.max(0,...values)
 for(const bounds of [undefined,{min:low-.1*magnitude,max:high+.1*magnitude},{majorUnit:magnitude/10}]){
  const actual=local.barValueScale([values],bounds?{...bounds,reversed:false}:undefined)
  const expected=source.valueAxisScale(high,bounds,low)
  assert(actual,'The local scale must be available for a supported finite domain')
  if(!equal(actual.min,expected.min)||!equal(actual.max,expected.max)){
   assert(high===0&&bounds?.max===undefined&&expected.max>0&&actual.max===0&&equal(actual.min,expected.min),JSON.stringify({values,bounds,actual,expected}))
   corrections.push({values,bounds,source:{min:expected.min,max:expected.max},local:{min:actual.min,max:actual.max},reason:'Keep the all-negative automatic upper bound at the real zero baseline'})
  }
  checked++
 }
}
const evidence={sourceCommit:pinned,sourcePath,seed:190,checked,matched:checked-corrections.length,intentionalAllNegativeZeroTopCorrections:corrections}
if(process.env.WORKBOOK_CHART_SCALE_ORACLE_OUTPUT)await writeFile(process.env.WORKBOOK_CHART_SCALE_ORACLE_OUTPUT,JSON.stringify(evidence,null,2))
console.log(JSON.stringify(evidence,null,2))
