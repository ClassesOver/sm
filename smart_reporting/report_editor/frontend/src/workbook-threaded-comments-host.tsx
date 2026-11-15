import {createRoot} from 'react-dom/client'
import {ThreadedCommentsPane,ThreadHoverCard,ThreadsContext} from './workbook-threaded-comments-pane'
import {ThreadStore,ThreadPaneController,cellKey,type ThreadActor,type CellThread} from './workbook-threaded-comments'
import {installThreadedCommentAffordances,type ThreadHover} from './workbook-threaded-comment-marker'
import { adjacentNote } from './workbook-notes'
import type {WorkbookModel} from '@sheets-web/xlsx-engine'
import type {createUniver} from './workbook-vendor/grid/create-univer'
import './workbook-threaded-comments.css'
export type ThreadRibbonCommand = 'comment-new' | 'comment-delete' | 'comment-prev' | 'comment-next' | 'comments-pane-toggle'
export function mountWorkbookThreads(host:HTMLElement,options:{runtime:ReturnType<typeof createUniver>;actor?:ThreadActor;editable:()=>boolean;commit:(sheetId:string,row:number,column:number,thread:CellThread|null)=>Promise<void>;error:(e:unknown)=>void;model:WorkbookModel;jump:(sheetId:string,row:number,column:number)=>void}) {
 const threadStore=new ThreadStore(options.actor,options.commit,options.error),threadPane=new ThreadPaneController()
 const paneHost=document.createElement('div')
 host.classList.add('workbook-threads-host');host.append(paneHost)
 const root=createRoot(paneHost);let hover:ThreadHover|null=null,disposed=false
 const getRuntime=()=>disposed?null:options.runtime
 const render=()=>{if(!disposed)root.render(<ThreadsContext.Provider value={{threadStore,threadPane,editable:options.editable}}><ThreadedCommentsPane getRuntime={getRuntime} onJump={options.jump}/><ThreadHoverCard hover={hover}/></ThreadsContext.Provider>)}
 const selection = () => {
   const sheet = getRuntime()?.univerAPI.getActiveWorkbook()?.getActiveSheet()
   const range = sheet?.getSelection()?.getActiveRange()
   if (!sheet || !range) return
   const sheetId = sheet.getSheetId(), row = range.getRow(), column = range.getColumn()
   const threads = threadStore.sheetThreads(sheetId), notes = sheet.getNotes()
   const thread = threads.find(item => item.row === row && item.column === column)
   const note = notes.find(item => item.row === row && item.col === column)
   return { sheetId, row, column, threads, notes, thread, note }
 }
 const reason = (command: ThreadRibbonCommand, target = selection()): string | undefined => {
   if (disposed) return '批注侧栏已关闭'
   if (command === 'comments-pane-toggle') return
   if (!target) return '请先选择单元格'
   if (command === 'comment-prev' || command === 'comment-next') {
     return target.threads.length || target.notes.length ? undefined : '当前工作表没有批注'
   }
   if (command === 'comment-new' && target.thread) return
   if (command === 'comment-new' && target.note) return '当前单元格已有注释'
   if (!options.editable()) return '当前工作簿或工作表不可编辑'
   if (threadStore.isBusy()) return '正在更新批注'
   if (command === 'comment-delete' && !target.thread) return target.note ? undefined : '当前单元格没有批注'
   if (!options.actor) return '当前授权用户身份不可用'
   return threadStore.readOnlyReason(target.sheetId)
 }
 const run = (command: ThreadRibbonCommand) => {
   const target = selection(), blocked = reason(command, target)
   if (blocked) throw new Error(blocked)
   if (command === 'comments-pane-toggle') { threadPane.toggle(); return }
   if (!target) return
   const { sheetId, row, column, thread, threads, notes } = target
   const api = options.runtime.univerAPI
   if (command === 'comment-new') { threadPane.openAt(sheetId, row, column, !thread); return }
   if (command === 'comment-delete') {
     if (thread) threadStore.remove(sheetId, row, column)
     else if (!api.syncExecuteCommand('sheet.command.delete-note')) throw new Error('注释未删除')
     return
   }
   // GenOffice navigates both threads and standalone notes in worksheet order.
   const threadedCells = new Set(threads.map(item => cellKey(item.row, item.column)))
   const positions = [
     ...threads.map(item => ({ row: item.row, col: item.column })),
     ...notes.filter(note => !threadedCells.has(cellKey(note.row, note.col))),
   ]
   const next = adjacentNote(positions, row, column, command === 'comment-next')
   if (!next) return
   options.jump(sheetId, next.row, next.col)
   if (threadedCells.has(cellKey(next.row, next.col))) threadPane.openAt(sheetId, next.row, next.col, false)
   else void api.executeCommand('sheet.operation.add-note-popup').catch(options.error)
 }
 const unsubscribe=threadStore.subscribe(render),unsubscribePane=threadPane.subscribe(render)
 const affordances=installThreadedCommentAffordances(options.runtime,{threadStore,theme:()=> 'light',onHover:value=>{hover=value;render()}})
 threadStore.load(options.model);render()
 return {run,reason,refresh:render,load(model:WorkbookModel){hover=null;threadStore.load(model);render()},dispose(){disposed=true;affordances.dispose();unsubscribe();unsubscribePane();root.unmount();paneHost.remove()}}
}
