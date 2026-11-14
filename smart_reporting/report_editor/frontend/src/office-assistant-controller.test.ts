import {describe,it,expect,vi} from 'vitest'
import {OfficeAssistantController} from './office-assistant-controller'
const deferred=<T>()=>{let resolve!:(value:T)=>void;const promise=new Promise<T>(r=>resolve=r);return {promise,resolve}}
type Job={id:string;status:string}
describe('shared Office task control',()=>{
 it('returns the terminal server state unchanged through shared polling',async()=>{
  const status=vi.fn(async()=>({id:'word',status:'completed'}))
  const controller=new OfficeAssistantController({start:async()=>({id:'word',status:'running'}),status,cancel:async()=>{},cancelRequest:async()=>{},id:(j:Job)=>j.id,running:(j:Job)=>j.status==='running'})
  expect(await controller.run({},'request')).toEqual({id:'word',status:'completed'})
  expect(status).toHaveBeenCalledTimes(1)
 })
 it('cancels both request and late-started task after closing',async()=>{
  const started=deferred<Job>(),cancel=vi.fn(async()=>{}),cancelRequest=vi.fn(async()=>{})
  const controller=new OfficeAssistantController({start:()=>started.promise,status:async()=>({id:'x',status:'completed'}),cancel,cancelRequest,id:(j:Job)=>j.id,running:(j:Job)=>j.status==='running'})
  const result=controller.run({},'request');await controller.cancel();started.resolve({id:'late',status:'running'})
  expect(await result).toBeUndefined();expect(cancelRequest).toHaveBeenCalledWith('request');expect(cancel).toHaveBeenCalledWith('late')
 })
 it('rejects repeated starts while the task is active',async()=>{
  const started=deferred<Job>()
  const controller=new OfficeAssistantController({start:()=>started.promise,status:async()=>({id:'x',status:'completed'}),cancel:async()=>{},cancelRequest:async()=>{},id:(j:Job)=>j.id,running:(j:Job)=>j.status==='running'})
  const result=controller.run({},'one');await expect(controller.run({},'two')).rejects.toThrow('office_task_busy');started.resolve({id:'x',status:'completed'});await result
 })
 it('does not replay acceptance and fences a response after cancellation',async()=>{
  const controller=new OfficeAssistantController({start:async()=>({id:'candidate',status:'completed'}),status:async()=>({id:'candidate',status:'completed'}),cancel:async()=>{},cancelRequest:async()=>{},id:(j:Job)=>j.id,running:(j:Job)=>j.status==='running'})
  await controller.run({},'request')
  const accepted=deferred<string>(),operation=vi.fn(()=>accepted.promise)
  const result=controller.accept(operation)
  await expect(controller.accept(operation)).rejects.toThrow('office_task_busy')
  await controller.cancel();accepted.resolve('operations')
  expect(await result).toBeUndefined();expect(operation).toHaveBeenCalledTimes(1)
 })

 it('cleans a failed start by request identity without replacing the original error',async()=>{
  const cancelRequest=vi.fn().mockRejectedValueOnce(new Error('cleanup unavailable')).mockResolvedValue(undefined)
  const controller=new OfficeAssistantController({start:async()=>{throw new Error('network lost')},status:async()=>({id:'x',status:'completed'}),cancelRequest,id:(j:Job)=>j.id,running:(j:Job)=>j.status==='running'})
  await expect(controller.run({},'request')).rejects.toThrow('network lost')
  expect(cancelRequest).toHaveBeenCalledWith('request')
  await controller.cancel();expect(cancelRequest).toHaveBeenCalledTimes(2)
 })

 it('cleans known tasks after status failure even if a read adapter releases in finally',async()=>{
  const cancel=vi.fn(async()=>{}),cancelRequest=vi.fn(async()=>{})
  const controller=new OfficeAssistantController({start:async()=>({id:'known',status:'running'}),status:async()=>{throw new Error('status network lost')},cancel,cancelRequest,id:(j:Job)=>j.id,running:(j:Job)=>j.status==='running'})
  try {await controller.run({},'read-request')} catch(error) {expect((error as Error).message).toBe('status network lost')} finally {controller.release()}
  expect(cancel).toHaveBeenCalledWith('known');expect(cancelRequest).toHaveBeenCalledWith('read-request')
 })
 it('retains failed cleanup identity despite release so cancellation can retry',async()=>{
  const cancel=vi.fn().mockRejectedValueOnce(new Error('offline')).mockResolvedValue(undefined)
  const controller=new OfficeAssistantController({start:async()=>({id:'known',status:'running'}),status:async()=>{throw new Error('status offline')},cancel,id:(j:Job)=>j.id,running:(j:Job)=>j.status==='running'})
  await expect(controller.run({},'read')).rejects.toThrow('status offline');controller.release()
  await vi.waitFor(()=>expect(cancel).toHaveBeenCalledTimes(1));await controller.cancel()
  expect(cancel).toHaveBeenNthCalledWith(2,'known')
 })
 it.each(['start','status'] as const)('isolates old %s completion from the replacement task',async phase=>{
  const late=deferred<Job>(),replacement=deferred<Job>(),cancel=vi.fn(async()=>{}),cancelRequest=vi.fn(async()=>{})
  const controller=new OfficeAssistantController({start:vi.fn().mockImplementationOnce(()=>phase==='start'?late.promise:Promise.resolve({id:'old',status:'running'})).mockImplementationOnce(()=>replacement.promise),status:()=>late.promise,cancel,cancelRequest,id:(j:Job)=>j.id,running:(j:Job)=>j.status==='running'})
  const old=controller.run({},'old-request');await Promise.resolve();await controller.cancel()
  const next=controller.run({},'new-request');late.resolve({id:'old',status:'completed'});expect(await old).toBeUndefined()
  await expect(controller.run({},'third')).rejects.toThrow('office_task_busy')
  expect(cancelRequest).not.toHaveBeenCalledWith('new-request')
  replacement.resolve({id:'new',status:'completed'});expect(await next).toEqual({id:'new',status:'completed'})
  await controller.cancel();expect(cancel).toHaveBeenLastCalledWith('new')
 })
 it('old accept finally cannot release replacement busy state',async()=>{
  const next=deferred<Job>(),oldAccept=deferred<string>()
  const controller=new OfficeAssistantController({start:vi.fn().mockResolvedValueOnce({id:'old',status:'completed'}).mockImplementationOnce(()=>next.promise),status:async()=>({id:'x',status:'completed'}),cancel:async()=>{},id:(j:Job)=>j.id,running:(j:Job)=>j.status==='running'})
  await controller.run({},'old-request');const accepted=controller.accept(()=>oldAccept.promise);await controller.cancel()
  const running=controller.run({},'new-request');oldAccept.resolve('old-write');expect(await accepted).toBeUndefined()
  await expect(controller.run({},'third')).rejects.toThrow('office_task_busy')
  next.resolve({id:'new',status:'completed'});await running
 })
 it('cleans known task when the progress onStart callback throws',async()=>{
  const cancel=vi.fn(async()=>{})
  const controller=new OfficeAssistantController({start:async()=>({id:'known',status:'running'}),status:async()=>({id:'known',status:'completed'}),cancel,id:(j:Job)=>j.id,running:(j:Job)=>j.status==='running'})
  await expect(controller.run({},'request',()=>{throw new Error('progress unavailable')})).rejects.toThrow('progress unavailable')
  expect(cancel).toHaveBeenCalledWith('known')
 })

 it('late cancellation failure cannot restore old handles over a new run',async()=>{
  let rejectCleanup!:(error:Error)=>void
  const next=deferred<Job>(),cancel=vi.fn().mockImplementationOnce(()=>new Promise((_,reject)=>{rejectCleanup=reject})).mockResolvedValue(undefined)
  const controller=new OfficeAssistantController({start:vi.fn().mockResolvedValueOnce({id:'old',status:'completed'}).mockImplementationOnce(()=>next.promise),status:async()=>({id:'x',status:'completed'}),cancel,id:(j:Job)=>j.id,running:(j:Job)=>j.status==='running'})
  await controller.run({},'old-request');const cleanup=controller.cancel();await Promise.resolve()
  const running=controller.run({},'new-request');rejectCleanup(new Error('old cancel offline'));await expect(cleanup).rejects.toThrow('old cancel offline')
  await expect(controller.run({},'third')).rejects.toThrow('office_task_busy')
  next.resolve({id:'new',status:'completed'});await running;await controller.cancel()
  expect(cancel).toHaveBeenLastCalledWith('new')
 })
 it('does not wait for a hung cleanup endpoint before returning the status error',async()=>{
  const controller=new OfficeAssistantController({start:async()=>({id:'known',status:'running'}),status:async()=>{throw new Error('status error')},cancel:()=>new Promise(()=>{}),id:(j:Job)=>j.id,running:(j:Job)=>j.status==='running'})
  await expect(controller.run({},'request')).rejects.toThrow('status error')
  controller.release()
 })

 it('coalesces repeated cancel while pending and retains the task on failure for retry',async()=>{
  let rejectFirst!:(error:Error)=>void
  const cancel=vi.fn().mockImplementationOnce(()=>new Promise((_,reject)=>{rejectFirst=reject})).mockResolvedValue(undefined)
  const controller=new OfficeAssistantController({start:async()=>({id:'task',status:'completed'}),status:async()=>({id:'task',status:'completed'}),cancel,id:(j:Job)=>j.id,running:(j:Job)=>j.status==='running'})
  await controller.run({},'request')
  const first=controller.cancel(),second=controller.cancel()
  const results=Promise.allSettled([first,second]);rejectFirst(new Error('network lost'))
  expect((await results).map(result=>result.status)).toEqual(['rejected','rejected'])
  await controller.cancel();expect(cancel).toHaveBeenCalledTimes(2);expect(cancel).toHaveBeenLastCalledWith('task')
 })

})
