import type {NativeDraft,NativeOperation} from './native-draft'
import {buildPdfStampsOperation,pdfPageState,type PdfPageIdentity} from './pdf-operations'
import {DEFAULT_HEADER_FOOTER,DEFAULT_WATERMARK,type HeaderFooterConfig,type WatermarkConfig} from './vendor/genoffice-pdf/renderer/stamps'
/** 完整源对话框仅提交现有setStamps；取消和异步变化不写入。 */
export function bindPdfStampDialog(options:{root:HTMLElement;draft:NativeDraft;pages:()=>PdfPageIdentity[];unavailable:()=>string|null;refresh:()=>Promise<void>;status:(text:string)=>void;build?:typeof buildPdfStampsOperation}){
 let disposed=false,generation=0,dialog:{dispose:()=>void;setError?:(message:string)=>void}|undefined,opening=false
 const close=()=>{generation++;opening=false;dialog?.dispose();dialog=undefined}
 return {async open(){
  if(disposed||opening||dialog)return
  const blocked=options.unavailable();if(blocked){options.status(blocked);return}
  const epoch=++generation,snapshot=JSON.stringify(options.draft.operations),pages=JSON.stringify(options.pages())
  const active=()=>!disposed&&epoch===generation
  const reason=()=>options.unavailable()??(snapshot!==JSON.stringify(options.draft.operations)||pages!==JSON.stringify(options.pages())?'草稿或页面来源已变化，请重新打开水印设置':null)
  opening=true
  try{const {showPdfStampDialog}=await import('./pdf-stamp-dialog-source');if(!active())return;const changed=reason();if(changed)throw Error(changed)
   const existing=options.draft.operations.find(op=>op.kind==='setStamps') as (NativeOperation&{watermark?:WatermarkConfig|null;headerFooter?:HeaderFooterConfig|null})|undefined
   const report=(error:unknown)=>{const message=error instanceof Error?error.message:String(error);options.status(message);dialog?.setError?.(message);return message}
   const commit=(operation?:NativeOperation)=>{
    if(!active())return
    try{const changed=reason();if(changed)throw Error(changed);const base=options.draft.operations.filter(op=>op.kind!=='setStamps'),next=operation?[...base,operation]:base
     pdfPageState(options.pages(),next);options.draft.setOperations(next);close();void options.refresh().catch(error=>options.status('水印修改已暂存，预览刷新失败：'+report(error)))
    }catch(error){throw Error(report(error))}
   }
   dialog=showPdfStampDialog({owner:options.root.ownerDocument,initialWatermark:existing?.watermark??DEFAULT_WATERMARK,initialHeaderFooter:existing?existing.headerFooter??{...DEFAULT_HEADER_FOOTER,pageNumber:false}:DEFAULT_HEADER_FOOTER,canClear:!!existing,onCancel:close,onClear(){if(active())try{commit()}catch(error){report(error)}},onApply(wm,hf){if(!active())return;const changed=reason();if(changed){report(Error(changed));return}try{const base=options.draft.operations.filter(op=>op.kind!=='setStamps');commit((options.build??buildPdfStampsOperation)(pdfPageState(options.pages(),base),wm,hf))}catch(error){report(error)}}})
  }catch(error){if(active())options.status(error instanceof Error?error.message:String(error))}finally{if(active())opening=false}
 },cancel:close,incompleteReason(){return opening||dialog?'请先完成或取消水印与页眉页脚设置':null},refresh(){if(dialog&&options.unavailable())close()},dispose(){disposed=true;close()}}
}
