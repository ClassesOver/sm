import type {MeasureScale} from './vendor/genoffice-pdf/renderer/measure'
/** 参考线只在确认时由既有宿主提交，取消与迟到加载不改变会话比例。 */
export function bindPdfMeasureDialog(options:{owner:Document;snapshot:()=>string;unavailable:()=>string|null;status:(message:string)=>void}){
 let disposed=false,generation=0,opening=false,dialog:{dispose():void}|undefined
 const close=()=>{generation++;opening=false;dialog?.dispose();dialog=undefined}
 return {async open(drawnPts:number,apply:(scale:MeasureScale)=>Promise<void>,onCancel?:()=>void){
  if(disposed||opening||dialog)return
  const unavailable=options.unavailable();if(unavailable){options.status(unavailable);return}
  const epoch=++generation,snapshot=options.snapshot(),active=()=>!disposed&&epoch===generation
  const validate=()=>{const reason=options.unavailable();if(reason)throw Error(reason);if(options.snapshot()!==snapshot)throw Error('草稿或页面来源已变化，请重新绘制参考线')}
  opening=true
  try{const {showPdfMeasureDialog}=await import('./pdf-measure-dialog-source');if(!active())return;validate()
   dialog=showPdfMeasureDialog({owner:options.owner,drawnPts,onCancel:()=>{close();onCancel?.()},onApply:async scale=>{if(!active())return;validate();await apply(scale);if(active())close()}})
  }catch(error){if(active())options.status(error instanceof Error?error.message:String(error))}
  finally{if(active())opening=false}
 },cancel:close,incompleteReason:()=>opening||dialog?'请先完成或取消测量标定':null,dispose(){disposed=true;close()}}
}
