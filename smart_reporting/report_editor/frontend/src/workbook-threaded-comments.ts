// UI contract ported from genoffice f8c17004 threaded-comments.ts; editor-local persistence adapter.
import type {CellThread,SheetThreadsModel,WorkbookModel} from '@sheets-web/xlsx-engine'
export type {CellThread}
export type ThreadReply = CellThread['replies'][number]
export type ThreadActor = {personId:string;author:string}
export const cellKey = (row:number,column:number) => `${row}:${column}`
export const threadTimestamp = () => new Date().toISOString().slice(0,22)
export function parseThreadTimestamp(dT:string):Date|null { const d = new Date(/[zZ]|[+-]\d\d:\d\d$/.test(dT)?dT:`${dT}Z`);return Number.isNaN(d.getTime())?null:d }
type Listener = () => void
export class ThreadStore {
  private threads = new Map<string,CellThread[]>()
  private reasons = new Map<string,string>()
  private listeners = new Set<Listener>()
  private version = 0
  private busy = false
  constructor(private actor:ThreadActor|undefined,private commit:(sheetId:string,row:number,column:number,thread:CellThread|null)=>Promise<void>,private error:(error:unknown)=>void) {}
  subscribe = (listener:Listener) => {this.listeners.add(listener);return () => {this.listeners.delete(listener)}}
  getVersion = () => this.version
  load(model:WorkbookModel):void { this.reasons=new Map(model.sheets.flatMap((s,i)=>s.threads?.readOnlyReason?[[`sheet-${i}`,s.threads.readOnlyReason] as [string,string]]:[]));this.threads = new Map(model.sheets.map((s,i)=>[`sheet-${i}`,s.threads?.threads ?? []]));this.bump() }
  sheetThreads(sheetId:string|null):CellThread[] {return [...(this.threads.get(sheetId ?? '') ?? [])].sort((a,b)=>a.row-b.row||a.column-b.column)}
  readOnlyReason(sheetId:string|null):string|undefined{return this.reasons.get(sheetId??'')}
  get(sheetId:string,row:number,column:number):CellThread|null {return this.sheetThreads(sheetId).find(t=>t.row===row&&t.column===column)??null}
  private bump(){this.version++;for(const f of this.listeners)f()}
  private change(sheetId:string,row:number,column:number,thread:CellThread|null):void {
    if(this.busy)return
    const reason=this.readOnlyReason(sheetId);if(reason){this.error(new Error(reason));return}
    this.busy=true;this.bump()
    void this.commit(sheetId,row,column,thread).catch(this.error).finally(()=>{this.busy=false;this.bump()})
  }
  isBusy(){return this.busy}
  private identity(){if(!this.actor)throw new Error('当前授权用户身份不可用，无法新增批注');return {id:`{${crypto.randomUUID().toUpperCase()}}`,...this.actor,dT:threadTimestamp()}}
  add(sheetId:string,row:number,column:number,text:string):void {try{this.change(sheetId,row,column,{...this.identity(),row,column,text,done:false,replies:[]})}catch(e){this.error(e)}}
  reply(sheetId:string,row:number,column:number,text:string):void {try{const t=this.get(sheetId,row,column);if(t&&!t.done)this.change(sheetId,row,column,{...t,replies:[...t.replies,{...this.identity(),text}]})}catch(e){this.error(e)}}
  setDone(sheetId:string,row:number,column:number,done:boolean){const t=this.get(sheetId,row,column);if(t)this.change(sheetId,row,column,{...t,done})}
  editText(sheetId:string,row:number,column:number,id:string,text:string){const t=this.get(sheetId,row,column);if(t&&!t.done)this.change(sheetId,row,column,id===t.id?{...t,text}:{...t,replies:t.replies.map(r=>r.id===id?{...r,text}:r)})}
  deleteReply(sheetId:string,row:number,column:number,id:string){const t=this.get(sheetId,row,column);if(t&&!t.done)this.change(sheetId,row,column,{...t,replies:t.replies.filter(r=>r.id!==id)})}
  remove(sheetId:string,row:number,column:number){this.change(sheetId,row,column,null)}
}
export interface ThreadPaneState {open:boolean;draft:{sheetId:string;row:number;column:number}|null;focus:{sheetId:string;row:number;column:number}|null}
export class ThreadPaneController {
 private state:ThreadPaneState={open:false,draft:null,focus:null};private listeners=new Set<Listener>()
 subscribe=(listener:Listener)=>{this.listeners.add(listener);return()=>{this.listeners.delete(listener)}}
 getState=()=>this.state
 private set(state:ThreadPaneState){this.state=state;for(const f of this.listeners)f()}
 toggle(){this.set({open:!this.state.open,draft:null,focus:null})}
 close(){this.set({open:false,draft:null,focus:null})}
 openAt(sheetId:string,row:number,column:number,compose:boolean){const cell={sheetId,row,column};this.set({open:true,draft:compose?cell:null,focus:compose?null:cell})}
 clearDraft(){this.set({...this.state,draft:null})}
}
