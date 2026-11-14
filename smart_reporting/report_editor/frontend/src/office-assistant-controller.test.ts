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
  const cancelRequest=vi.fn(async()=>{throw new Error('cleanup unavailable')})
  const controller=new OfficeAssistantController({start:async()=>{throw new Error('network lost')},status:async()=>({id:'x',status:'completed'}),cancelRequest,id:(j:Job)=>j.id,running:(j:Job)=>j.status==='running'})
  await expect(controller.run({},'request')).rejects.toThrow('network lost')
  expect(cancelRequest).toHaveBeenCalledWith('request')
  await controller.cancel();expect(cancelRequest).toHaveBeenCalledTimes(1)
 })

})
