import {createRoot} from 'react-dom/client'
import {ThreadedCommentsPane,ThreadHoverCard,ThreadsContext} from './workbook-threaded-comments-pane'
import {ThreadStore,ThreadPaneController,type ThreadActor,type CellThread} from './workbook-threaded-comments'
import {installThreadedCommentAffordances,type ThreadHover} from './workbook-threaded-comment-marker'
import type {WorkbookModel} from '@sheets-web/xlsx-engine'
import type {createUniver} from './workbook-vendor/grid/create-univer'
import './workbook-threaded-comments.css'
export function mountWorkbookThreads(host:HTMLElement,options:{runtime:ReturnType<typeof createUniver>;actor?:ThreadActor;editable:()=>boolean;commit:(sheetId:string,row:number,column:number,thread:CellThread|null)=>Promise<void>;error:(e:unknown)=>void;model:WorkbookModel;jump?:(sheetId:string,row:number,column:number)=>void}) {
 const threadStore=new ThreadStore(options.actor,options.commit,options.error),threadPane=new ThreadPaneController()
 const buttonRow=document.createElement('div'),toggle=document.createElement('button'),add=document.createElement('button'),paneHost=document.createElement('div')
 host.classList.add('workbook-threads-host');toggle.type=add.type='button';toggle.textContent='显示批注';add.textContent='新建批注';toggle.className=add.className='workbook-threads-toggle'
 buttonRow.append(toggle,add);host.append(buttonRow,paneHost)
 const root=createRoot(paneHost);let hover:ThreadHover|null=null,disposed=false
 const getRuntime=()=>disposed?null:options.runtime
 const render=()=>{if(!disposed)root.render(<ThreadsContext.Provider value={{threadStore,threadPane,editable:options.editable}}><ThreadedCommentsPane getRuntime={getRuntime} onJump={options.jump}/><ThreadHoverCard hover={hover}/></ThreadsContext.Provider>)}
 toggle.onclick=()=>threadPane.toggle()
 add.onclick=()=>{try{if(!options.editable()||!options.actor)throw new Error('当前授权用户或工作表不支持新增线程批注');const sheet=options.runtime.univerAPI.getActiveWorkbook()?.getActiveSheet(),range=sheet?.getSelection()?.getActiveRange();if(!sheet||!range)throw new Error('请先选择单元格');const reason=options.model.sheets.find(s=>s.name===sheet.getSheetName())?.threads?.readOnlyReason;if(reason)throw new Error(reason);threadPane.openAt(sheet.getSheetId(),range.getRow(),range.getColumn(),!threadStore.get(sheet.getSheetId(),range.getRow(),range.getColumn()))}catch(e){options.error(e)}}
 const unsubscribe=threadStore.subscribe(render),unsubscribePane=threadPane.subscribe(render)
 const affordances=installThreadedCommentAffordances(options.runtime,{threadStore,theme:()=> 'light',onHover:value=>{hover=value;render()}})
 threadStore.load(options.model);render()
 return {load(model:WorkbookModel){options.model=model;hover=null;threadStore.load(model);render()},dispose(){disposed=true;affordances.dispose();unsubscribe();unsubscribePane();root.unmount();buttonRow.remove();paneHost.remove()}}
}
