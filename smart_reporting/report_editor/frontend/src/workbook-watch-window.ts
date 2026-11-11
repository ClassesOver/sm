// GenOffice f8c17004 WatchWindowPanel/App 的会话监视契约；来源见 workbook-vendor/SOURCE.md。
import './workbook-watch-window.css'
import { formatAddress } from '@sheets-web/xlsx-engine/cell-address'
interface WatchCell {sheetId:string;row:number;column:number}
interface WatchSheet {
 getSheetId():string
 getSheetName():string
 getMaxRows():number
 getMaxColumns():number
 getRange(row:number,column:number,rows:number,columns:number):{getDisplayValue():string;getFormula():string}
}
interface WatchWorkbook {
 getWorkbook():object
 getActiveSheet():WatchSheet|null|undefined
 getActiveRange():{getRange():{startRow:number;endRow:number;startColumn:number;endColumn:number}}|null|undefined
 getSheetBySheetId(id:string):WatchSheet|null|undefined
}
const key=(cell:WatchCell)=>`${cell.sheetId}:${cell.row}:${cell.column}`
export function createWorkbookWatchWindow(host:HTMLElement,workbook:()=>WatchWorkbook|null|undefined,changed?:()=>void){
 let cells:WatchCell[]=[],identity:object|undefined,panel:HTMLElement|undefined,timer:ReturnType<typeof setInterval>|undefined,disposed=false
 const rows=new Map<string,HTMLTableRowElement>()
 const sync=()=>{const current=workbook()?.getWorkbook();if(identity!==current){cells=[];identity=current}return workbook()}
 const close=()=>{if(timer!==undefined)clearInterval(timer);timer=undefined;panel?.remove();panel=undefined;rows.clear();changed?.()}
 const render=()=>{
  if(!panel)return
  const book=sync(),body=panel.querySelector('tbody')!
  const live=new Set(cells.map(key));for(const [id,row] of rows)if(!live.has(id)){row.remove();rows.delete(id)}
  panel.querySelector<HTMLElement>('[data-watch-empty]')!.hidden=cells.length>0
  panel.querySelector<HTMLButtonElement>('[data-watch-add]')!.disabled=!book?.getActiveRange()
  for(const cell of cells){
   const id=key(cell),sheet=book?.getSheetBySheetId(cell.sheetId)
   let resolved:{name:string;value:string;formula:string}|undefined
   // 表缩小或正在替换时不能把越界读取当作有效空值，也不能让轮询连续抛错。
   if(sheet&&cell.row<sheet.getMaxRows()&&cell.column<sheet.getMaxColumns()){
    try{const range=sheet.getRange(cell.row,cell.column,1,1);resolved={name:sheet.getSheetName(),value:range.getDisplayValue()??'',formula:range.getFormula()??''}}catch{ /* 失效来源在下一次刷新可恢复。 */ }
   }
   let row=rows.get(id)
   if(!row){
    row=document.createElement('tr');row.dataset.watchRow=id
    for(let i=0;i<4;i++)row.append(document.createElement('td'))
    const td=document.createElement('td'),remove=document.createElement('button');remove.type='button';remove.dataset.watchRemove=id;remove.textContent='删除';remove.setAttribute('aria-label',`删除监视 ${formatAddress(cell.row,cell.column)}`);remove.addEventListener('click',()=>{cells=cells.filter(item=>key(item)!==id);render()});td.append(remove);row.append(td);rows.set(id,row);body.append(row)
   }
   row.classList.toggle('watch-gone',!resolved)
   const values=[resolved?.name??'—',formatAddress(cell.row,cell.column),resolved?.value??'',resolved?.formula??'']
   values.forEach((value,index)=>{if(row!.cells[index]!.textContent!==value)row!.cells[index]!.textContent=value})
  }
 }
 const add=()=>{
  const book=sync(),sheet=book?.getActiveSheet(),selection=book?.getActiveRange()?.getRange();if(!sheet||!selection)return
  const seen=new Set(cells.map(key)),added:WatchCell[]=[]
  outer:for(let row=selection.startRow;row<=selection.endRow;row++)for(let column=selection.startColumn;column<=selection.endColumn;column++){
   if(added.length>=20)break outer
   const cell={sheetId:sheet.getSheetId(),row,column};if(!seen.has(key(cell)))added.push(cell)
  }
  cells.push(...added);render()
 }
 return {
  state:()=>({active:Boolean(panel)}),
  toggle(){
   if(disposed)return
   if(panel){close();return}
   sync();panel=document.createElement('section');panel.className='workbook-watch-window';panel.dataset.watchWindow='';panel.setAttribute('role','dialog');panel.setAttribute('aria-label','监视窗口')
   panel.innerHTML='<header><strong>监视窗口</strong><button type="button" data-watch-add>添加选区</button><button type="button" data-watch-close aria-label="关闭监视窗口">关闭</button></header><p>按单元格地址监视；每次最多新增 20 格。</p><p data-watch-empty>选择单元格后添加监视。</p><div class="watch-scroll"><table><thead><tr><th>工作表</th><th>单元格</th><th>值</th><th>公式</th><th></th></tr></thead><tbody></tbody></table></div>'
   panel.querySelector('[data-watch-add]')!.addEventListener('click',add);panel.querySelector('[data-watch-close]')!.addEventListener('click',close);host.append(panel);render();timer=setInterval(render,800);changed?.()
  },
  reset(){close();cells=[];identity=undefined},
  dispose(){disposed=true;close();cells=[];identity=undefined},
 }
}
