// 固定 GenOffice f8c17004 loaded Error Checking：检查当前表已有结果并循环定位，不求值或修改文件。
import {ERROR_TYPE_SET} from '@univerjs/engine-formula'
import {formatAddress} from '@sheets-web/xlsx-engine/cell-address'

interface ErrorSheet {
 getSheet():{getCellMatrix():{forValue(callback:(row:number,column:number,cell:{v?:unknown}|null|void)=>undefined):unknown}}
 getRange(row:number,column:number,rows:number,columns:number):{activate():unknown}
}
interface ErrorWorkbook<Sheet extends ErrorSheet> {
 getWorkbook():object
 getActiveSheet():Sheet|null|undefined
 getActiveRange():{getRow():number;getColumn():number}|null|undefined
}
interface ErrorCheckingDependencies<Sheet extends ErrorSheet> {
 workbook():ErrorWorkbook<Sheet>|null|undefined
 reveal(sheet:Sheet,row:number,column:number,isCurrent:()=>boolean):Promise<boolean|null>
 message(text:string):void
 refreshSelection?():void
}
// 精确匹配官方错误类型及源现代错误；不沿用 loaded 分支的前缀误匹配。
const errors=new Set<string>([...ERROR_TYPE_SET,'#FIELD!','#CONNECT!','#BLOCKED!','#UNKNOWN!'])
export function createWorkbookErrorChecking<Sheet extends ErrorSheet>(deps:ErrorCheckingDependencies<Sheet>){
 let generation=0,pending=false,disposed=false
 const reset=()=>{generation++;pending=false}
 return {
  state:()=>({pending}),
  reset,
  dispose(){disposed=true;reset()},
  async check():Promise<void>{
   if(disposed||pending)return
   const epoch=++generation;pending=true
   let current=()=>!disposed&&generation===epoch
   try{
    const book=deps.workbook(),sheet=book?.getActiveSheet()
    if(!book||!sheet){deps.message('工作表尚未就绪，无法检查错误。');return}
    const core=book.getWorkbook(),sheetCore=sheet.getSheet()
    let target:{row:number;column:number}|undefined
    current=()=>{
     if(disposed||generation!==epoch)return false
     try{const live=deps.workbook(),selection=target?live?.getActiveRange():null;return live?.getWorkbook()===core&&live.getActiveSheet()?.getSheet()===sheetCore&&(!target||selection?.getRow()===target.row&&selection.getColumn()===target.column)}catch{return false}
    }
    const found:{row:number;column:number;value:string}[]=[]
    sheetCore.getCellMatrix().forValue((row,column,cell)=>{
     if(typeof cell?.v==='string'&&errors.has(cell.v))found.push({row,column,value:cell.v})
     return undefined
    })
    if(!current())return
    if(!found.length){deps.message('当前工作表未发现错误（按当前计算结果检查）。');return}
    found.sort((a,b)=>a.row-b.row||a.column-b.column)
    const active=book.getActiveRange(),row=active?.getRow()??-1,column=active?.getColumn()??-1
    const next=found.find(cell=>cell.row>row||cell.row===row&&cell.column>column)??found[0]!
    sheet.getRange(next.row,next.column,1,1).activate()
    target=next
    deps.refreshSelection?.()
    if(!current())return
    const visible=await deps.reveal(sheet,next.row,next.column,current)
    if(!current()||visible===null)return
    const description=`当前工作表发现 ${found.length} 个错误：${formatAddress(next.row,next.column)} ${next.value}（按当前计算结果检查）。`
    deps.message(visible?description:`${description} 未能确认目标在可见区域，请重试定位。`)
   }catch(error){
    if(current())deps.message(`当前工作表错误检查失败：${error instanceof Error?error.message:String(error)}`)
   }finally{if(generation===epoch)pending=false}
  },
 }
}
