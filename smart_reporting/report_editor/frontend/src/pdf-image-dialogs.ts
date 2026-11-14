import {createElement} from 'react'
import {createRoot} from 'react-dom/client'
import {CropDialog,CutoutDialog} from './vendor/genoffice-pdf/renderer/ImageDialogs'
import type {CropFractions} from './vendor/genoffice-pdf/renderer/image-bake'
import {installFocusTrap} from './focus-trap'
import './pdf-image-dialogs.css'
const strings:Record<string,string>={imageCrop:'裁剪图像',imageCutout:'去除背景',imageCutoutTolerance:'容差',imageCutoutHint:'已移除 {pct}% 像素；调整容差核对透明背景。',imageCropHint:'拖动手柄或框内区域选择保留范围；Enter 应用，Esc 取消。',imageApply:'应用',imageProcessing:'处理中…',imageLoading:'加载中…',imageLoadFail:'图片加载失败',imageProcessFail:'图片处理失败',cancel:'取消'}
/** 固定源对话框挂载到浏览器顶层，沿用宿主草稿身份与保存链路。 */
export function showPdfImageDialog(options:{owner:Document;kind:'crop'|'cutout';image:string;onApply:(png:string,crop?:CropFractions)=>void;onCancel:()=>void}){
 const dialog=options.owner.createElement('dialog');dialog.className='pdf-image-source-dialog';dialog.setAttribute('aria-label',options.kind==='crop'?'可视裁剪图像':'去除图像背景')
 const opener=options.owner.activeElement as HTMLElement|null
 options.owner.body.append(dialog);const root=createRoot(dialog);let active=true
 const release=installFocusTrap(dialog)
 function dispose(){if(!active)return;active=false;release();root.unmount();if(dialog.open)dialog.close();dialog.remove();if(opener?.isConnected)opener.focus({preventScroll:true})}
 function cancel(){if(!active)return;dispose();options.onCancel()}
 dialog.addEventListener('cancel',event=>{event.preventDefault();cancel()})
 const t=(key:string,args?:Record<string,string|number>)=>Object.entries(args??{}).reduce((text,[name,value])=>text.replace('{'+name+'}',String(value)),strings[key]??key)
 const onApply=(png:string,crop?:CropFractions)=>{if(!active)return;dispose();options.onApply(png,crop)}
 dialog.showModal()
 root.render(options.kind==='crop'?createElement(CropDialog,{t,image:options.image,onApply,onCancel:cancel}):createElement(CutoutDialog,{t,image:options.image,onApply,onCancel:cancel}))
 return {dispose}
}
