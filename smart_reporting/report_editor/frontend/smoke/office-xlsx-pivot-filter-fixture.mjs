// 仅准备/读取真实 XLSX 来源；不替换浏览器中的产品控件或引擎。
import {readFile,writeFile} from 'node:fs/promises'
import {createPivotPlan,readWorkbookPivots} from '../src/workbook-pivot'
import {readPivotControls} from '@sheets-web/xlsx-engine/pivot-controls'
import {applyWorkbookOperations} from '../../../reporting/workbook_engine/bridge/operations'
const [mode,source,output]=process.argv.slice(2),bytes=new Uint8Array(await readFile(source))
if(mode==='create'){
 const config={name:'经营收入分析',sourceSheetName:'Data',sourceRange:'A1:C19',targetSheetName:'Pivot',targetCell:'A1',rowFields:['Date'],columnFields:['Region'],values:[{field:'Amount',agg:'sum'}]}
 await writeFile(output,await applyWorkbookOperations(bytes,(await createPivotPlan(bytes,config)).operations))
}else if(mode==='inspect'){
 console.log(JSON.stringify({pivots:await readWorkbookPivots(bytes),controls:await readPivotControls(bytes)}))
}else throw new Error('unknown fixture mode')
