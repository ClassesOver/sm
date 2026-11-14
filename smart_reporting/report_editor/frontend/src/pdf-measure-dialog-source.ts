import {createElement} from 'react'
import {createRoot} from 'react-dom/client'
import {MeasureScaleDialog} from './vendor/genoffice-pdf/renderer/MeasureScaleDialog'
import type {MeasureScale} from './vendor/genoffice-pdf/renderer/measure'
import {installFocusTrap} from './focus-trap'
import './pdf-measure-dialog.css'
const strings:Record<string,string>={measureScaleTitle:'标定测量比例',measureScalePrompt:'输入参考线代表的实际长度；比例仅本次会话有效，保存的测量线保留长度标签。',measureScaleValue:'参考线实际长度',measureScaleUnit:'测量单位',measureScaleErr:'请输入大于 0 的长度和不超过 12 个字符的单位',measureScaleApply:'确定',cancel:'取消'}
/** 完整源控件仅负责校准输入；原生修改由宿主校验并提交。 */
export function showPdfMeasureDialog(options:{owner:Document;drawnPts:number;onApply:(scale:MeasureScale)=>Promise<void>;onCancel:()=>void}){
 const dialog=options.owner.createElement('dialog');dialog.className='pdf-measure-source-dialog';dialog.setAttribute('aria-label',strings.measureScaleTitle);const opener=options.owner.activeElement as HTMLElement|null;options.owner.body.append(dialog);const root=createRoot(dialog),release=installFocusTrap(dialog);let active=true
 function dispose(){if(!active)return;active=false;release();root.unmount();if(dialog.open)dialog.close();dialog.remove();if(opener?.isConnected)opener.focus({preventScroll:true})}
 function cancel(){if(!active)return;dispose();options.onCancel()}
 dialog.addEventListener('cancel',event=>{event.preventDefault();cancel()})
 root.render(createElement(MeasureScaleDialog,{t:key=>strings[key]??key,drawnPts:options.drawnPts,onClose:cancel,onApply:async(unitsPerPt,unit)=>{if(!active)return;await options.onApply({unitsPerPt,unit})}}));dialog.showModal()
 return {dispose}
}
