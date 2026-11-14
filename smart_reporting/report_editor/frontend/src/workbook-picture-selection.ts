export interface PictureSelectionIdentity {unitId:string;subUnitId:string;drawingId:string}
interface Subscription {unsubscribe():void}
interface SelectionHost<Shape> {
  refreshTransform$:{subscribe(listener:(identities:readonly PictureSelectionIdentity[])=>void):Subscription}
  getShape(identity:PictureSelectionIdentity):Shape|null|undefined
  restore(shapes:readonly Shape[],identities:readonly PictureSelectionIdentity[]):void
}
const same=(a:PictureSelectionIdentity,b:PictureSelectionIdentity)=>
  a.unitId===b.unitId && a.subUnitId===b.subUnitId && a.drawingId===b.drawingId

/** 等待原生图片渲染通知，不增加渲染器、延时或历史记录。 */
export function createWorkbookPictureSelectionController<Shape>(host:SelectionHost<Shape>) {
  let disposed=false
  let pending:{expected:PictureSelectionIdentity[];isCurrent:()=>boolean;subscription?:Subscription}|undefined
  const cancel=()=>{
    const previous=pending;pending=undefined
    previous?.subscription?.unsubscribe()
  }
  const check=()=>{
    const request=pending
    if(!request)return
    if(!request.isCurrent()){cancel();return}
    const shapes:Shape[]=[]
    for(const identity of request.expected){
      const shape=host.getShape(identity)
      if(shape==null)return
      shapes.push(shape)
    }
    // 先解除本次监听，防止恢复原生选区时的同步事件再次恢复。
    cancel()
    host.restore(shapes,request.expected)
  }
  return {
    start(expected:readonly PictureSelectionIdentity[],isCurrent:()=>boolean){
      cancel()
      if(disposed)return
      const request={expected:expected.map(identity=>({...identity})),isCurrent,subscription:undefined as Subscription|undefined}
      pending=request
      const subscription=host.refreshTransform$.subscribe(identities=>{
        if(pending!==request)return
        if(!request.isCurrent()){cancel();return}
        if(identities.some(identity=>request.expected.some(target=>same(identity,target))))check()
      })
      // Observable允许subscribe内同步发出通知，不能留下已完成请求的订阅。
      if(pending===request)request.subscription=subscription
      else subscription.unsubscribe()
      check()
    },
    check,cancel,
    dispose(){disposed=true;cancel()},
  }
}
