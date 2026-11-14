import {Subject} from 'rxjs'
import {describe,expect,it,vi} from 'vitest'
import {createWorkbookPictureSelectionController,type PictureSelectionIdentity} from './workbook-picture-selection'

const one={unitId:'book',subUnitId:'Other',drawingId:'one'}
const two={...one,drawingId:'two'}
function fixture(){
  const refreshTransform$=new Subject<readonly PictureSelectionIdentity[]>()
  const shapes=new Map<string,{id:string}>(),restore=vi.fn()
  const controller=createWorkbookPictureSelectionController({refreshTransform$,
    getShape:(identity:PictureSelectionIdentity)=>shapes.get(identity.drawingId),restore})
  return {refreshTransform$,shapes,restore,controller}
}
describe('native picture shape selection readiness',()=>{
  it('waits for every native shape and restores exactly once after real refresh notifications',()=>{
    const {controller,shapes,restore,refreshTransform$}=fixture()
    controller.start([one,two],()=>true)
    expect(restore).not.toHaveBeenCalled()
    shapes.set('one',{id:'one'});refreshTransform$.next([one])
    expect(restore).not.toHaveBeenCalled()
    shapes.set('two',{id:'two'});refreshTransform$.next([two])
    expect(restore).toHaveBeenCalledExactlyOnceWith([{id:'one'},{id:'two'}],[one,two])
    refreshTransform$.next([one,two]);expect(restore).toHaveBeenCalledTimes(1)
    expect(refreshTransform$.observed).toBe(false)
  })
  it('checks existing shapes immediately and copies target identities',()=>{
    const {controller,shapes,restore,refreshTransform$}=fixture()
    const expected=[{...one}]
    controller.start(expected,()=>true);expected[0]!.drawingId='changed';expected.length=0
    shapes.set('one',{id:'one'});controller.check()
    expect(restore).toHaveBeenCalledExactlyOnceWith([{id:'one'}],[one])
    expect(refreshTransform$.observed).toBe(false)
  })
  it('restores already available shapes without awaiting an event',()=>{
    const {controller,shapes,restore}=fixture();shapes.set('one',{id:'one'})
    controller.start([one],()=>true)
    expect(restore).toHaveBeenCalledTimes(1)
  })
  it('does not mistake foreign drawing refreshes for the expected native target',()=>{
    const {controller,shapes,restore,refreshTransform$}=fixture()
    controller.start([one],()=>true);shapes.set('one',{id:'one'})
    for(const patch of [{unitId:'foreign'},{subUnitId:'Report'},{drawingId:'other'}])refreshTransform$.next([{...one,...patch}])
    expect(restore).not.toHaveBeenCalled()
    refreshTransform$.next([one]);expect(restore).toHaveBeenCalledTimes(1)
  })
  it('cancels stale generations before a later ready notification can steal focus',()=>{
    const {controller,shapes,restore,refreshTransform$}=fixture();let current=true
    controller.start([one],()=>current);current=false;shapes.set('one',{id:'one'})
    refreshTransform$.next([one]);expect(restore).not.toHaveBeenCalled()
    expect(refreshTransform$.observed).toBe(false)
  })
  it('new requests supersede old requests and explicit cancellation detaches listeners',()=>{
    const {controller,shapes,restore,refreshTransform$}=fixture()
    controller.start([one],()=>true);controller.start([two],()=>true)
    shapes.set('one',{id:'one'});refreshTransform$.next([one]);expect(restore).not.toHaveBeenCalled()
    controller.cancel();shapes.set('two',{id:'two'});refreshTransform$.next([two])
    expect(restore).not.toHaveBeenCalled();expect(refreshTransform$.observed).toBe(false)
  })
  it('clears empty selections immediately and disposal prevents future work',()=>{
    const {controller,restore,refreshTransform$}=fixture()
    controller.start([],()=>true);expect(restore).toHaveBeenCalledExactlyOnceWith([],[])
    controller.start([one],()=>true);controller.dispose();controller.start([],()=>true)
    expect(restore).toHaveBeenCalledTimes(1);expect(refreshTransform$.observed).toBe(false)
  })
  it('unsubscribes when subscribe emits synchronously and restores only once',()=>{
    const unsubscribe=vi.fn(),restore=vi.fn()
    const controller=createWorkbookPictureSelectionController({
      refreshTransform$:{subscribe:(listener:(ids:readonly PictureSelectionIdentity[])=>void)=>{
        listener([one]);listener([one]);return {unsubscribe}
      }},getShape:()=>({id:'one'}),restore})
    controller.start([one],()=>true);controller.check()
    expect(restore).toHaveBeenCalledTimes(1);expect(unsubscribe).toHaveBeenCalledTimes(1)
  })
})
