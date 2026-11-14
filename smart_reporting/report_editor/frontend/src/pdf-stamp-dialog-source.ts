import {createElement} from 'react'
import {createRoot} from 'react-dom/client'
import {StampDialog} from './vendor/genoffice-pdf/renderer/StampDialog'
import type {WatermarkConfig,HeaderFooterConfig} from './vendor/genoffice-pdf/renderer/stamps'
import {installFocusTrap} from './focus-trap'
import './pdf-stamp-dialog.css'
import './vendor/genoffice-slides/ui/color-picker.css'
const strings:Record<string,string>={stampTitle:'水印与页眉页脚',watermark:'水印',watermarkText:'文字',watermarkPlaceholder:'如：机密、样本',watermarkAngle:'角度',watermarkOpacity:'不透明度',watermarkSize:'字号',drawColor:'颜色',headerFooter:'页眉页脚',hfHeaderLeft:'页眉左',hfHeaderCenter:'页眉中',hfHeaderRight:'页眉右',hfFooterLeft:'页脚左',hfFooterCenter:'页脚中',hfFooterRight:'页脚右',hfPageNumber:'页脚居中显示页码',hfStartAt:'起始页码',hfTokenHint:'可用占位符：{page} 当前页、{total} 总页数',ok:'确定',cancel:'取消',stampClear:'清除草稿水印与页眉页脚'}
export function showPdfStampDialog(options:{owner:Document;initialWatermark:WatermarkConfig;initialHeaderFooter:HeaderFooterConfig;canClear:boolean;onApply:(wm:WatermarkConfig|null,hf:HeaderFooterConfig|null)=>void;onClear:()=>void;onCancel:()=>void}){
 const dialog=options.owner.createElement('dialog');dialog.className='pdf-stamp-source-dialog';dialog.setAttribute('aria-label','水印与页眉页脚');options.owner.body.append(dialog)
 const opener=options.owner.activeElement as HTMLElement|null,root=createRoot(dialog),release=installFocusTrap(dialog);let active=true,error:string|undefined
 function dispose(){if(!active)return;active=false;release();root.unmount();if(dialog.open)dialog.close();dialog.remove();if(opener?.isConnected)opener.focus({preventScroll:true})}
 function cancel(){if(!active)return;dispose();options.onCancel()}
 const onApply=(wm:WatermarkConfig|null,hf:HeaderFooterConfig|null)=>{if(!active)return;options.onApply(wm,hf)}
 dialog.addEventListener('cancel',event=>{event.preventDefault();const paletteOpen=!!dialog.querySelector('.pdf-color-popover');queueMicrotask(()=>{if(active&&!paletteOpen)cancel()})})
 function render(){root.render(createElement(StampDialog,{error,t:key=>strings[key]??key,initialWatermark:options.initialWatermark,initialHeaderFooter:options.initialHeaderFooter,onApply,onCancel:cancel,...(options.canClear?{onClear:()=>{if(active)options.onClear()}}:{})}))}
 render();dialog.showModal()
 return {dispose,setError(message:string){if(active){error=message;render()}}}
}
