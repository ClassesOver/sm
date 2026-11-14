import {describe,expect,it,vi} from 'vitest'
import {ThreadStore,type ThreadActor,type CellThread} from './workbook-threaded-comments'
import type {WorkbookModel} from '@sheets-web/xlsx-engine'
const actor:ThreadActor={author:'authorized-user',personId:'{22222222-2222-4222-8222-222222222222}'}
const model=(threads:CellThread[]=[],readOnlyReason?:string):WorkbookModel=>({
 sheets:[{name:'Report',path:'xl/worksheets/sheet1.xml',cells:{},merges:[],rows:[],columns:[],freeze:null,showGridlines:true,zoomScale:100,dimension:null,threads:{threads,sourceIdentity:'source',...(readOnlyReason?{readOnlyReason}:{})}}],
 styles:{numFmts:new Map(),fonts:[],fills:[],borders:[],cellXfs:[]},themePalette:undefined,
})
const tick=()=>new Promise(resolve=>setTimeout(resolve,0))
describe('thread transaction store',()=>{
 it('uses the authorized actor and waits for a committed reload without optimistic edits',async()=>{
  let finish!:()=>void
  const commit=vi.fn((_sheetId:string,_row:number,_column:number,_thread:CellThread|null)=>new Promise<void>(resolve=>{finish=resolve})),error=vi.fn(),store=new ThreadStore(actor,commit,error)
  store.load(model());store.add('sheet-0',3,4,'new root');store.add('sheet-0',5,6,'duplicate while busy')
  expect(commit).toHaveBeenCalledTimes(1);expect(store.sheetThreads('sheet-0')).toEqual([]);expect(store.isBusy()).toBe(true)
  const thread=commit.mock.calls[0]![3]
  if(!thread)throw new Error('Expected a new thread')
  expect(thread).toMatchObject({...actor,row:3,column:4,text:'new root',done:false,replies:[]})
  store.load(model([thread]));finish();await tick()
  expect(store.get('sheet-0',3,4)).toEqual(thread);expect(store.isBusy()).toBe(false);expect(error).not.toHaveBeenCalled()
 })
 it('keeps failed transactions out of the model and prohibits creating an invented actor',async()=>{
  const error=vi.fn(),commit=vi.fn(async()=>{throw new Error('stale identity')}),store=new ThreadStore(actor,commit,error)
  store.load(model());store.add('sheet-0',0,0,'failed');await tick()
  expect(store.sheetThreads('sheet-0')).toEqual([]);expect(store.isBusy()).toBe(false);expect(error).toHaveBeenCalledWith(expect.objectContaining({message:'stale identity'}))
  const missing=new ThreadStore(undefined,commit,error);missing.add('sheet-0',0,0,'unauthorized')
  expect(commit).toHaveBeenCalledTimes(1);expect(error).toHaveBeenLastCalledWith(expect.objectContaining({message:expect.stringContaining('身份不可用')}))
 })
})
it('rejects mutations for preserved read-only thread sources',()=>{
 const error=vi.fn(),commit=vi.fn(async()=>{}),store=new ThreadStore(actor,commit,error)
 store.load(model([],'unknown extension'))
 expect(store.readOnlyReason('sheet-0')).toBe('unknown extension')
 store.add('sheet-0',0,0,'blocked');expect(commit).not.toHaveBeenCalled();expect(error).toHaveBeenCalledWith(expect.objectContaining({message:'unknown extension'}))
})
