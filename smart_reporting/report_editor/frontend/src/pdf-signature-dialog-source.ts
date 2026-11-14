import {createElement} from 'react'
import {createRoot} from 'react-dom/client'
import {SignatureDialog} from './vendor/genoffice-pdf/renderer/SignatureDialog'
import type {PdfSignatureData,PdfSignatureStore} from './pdf-signature-store'
import {installFocusTrap} from './focus-trap'
import './pdf-signature-dialog.css'
const strings:Record<string,string>={signTitle:'添加签名',signDraw:'手绘',signType:'输入',signImage:'图片',signAddImage:'添加图片',signBw:'黑白（背景透明）',signTypePlaceholder:'输入姓名',signClear:'清除',signPlace:'放置',signSaved:'我的签名',signSave:'保存签名，下次可直接使用',signSavedDelete:'删除签名',cancel:'取消',signHint:'确认后在页面拖出签名区域；图片签名也可点击放置。Esc 取消。'}
export function showPdfSignatureDialog(options:{owner:Document;color:[number,number,number];store:PdfSignatureStore;onConfirm:(data:PdfSignatureData)=>void;onCancel:()=>void}){
 const dialog=options.owner.createElement('dialog');dialog.className='pdf-signature-source-dialog';dialog.setAttribute('aria-label','添加签名');const opener=options.owner.activeElement as HTMLElement|null;options.owner.body.append(dialog);const root=createRoot(dialog),release=installFocusTrap(dialog);let active=true
 function dispose(){if(!active)return;active=false;release();root.unmount();if(dialog.open)dialog.close();dialog.remove();if(opener?.isConnected)opener.focus({preventScroll:true})}
 function cancel(){if(!active)return;dispose();options.onCancel()}
 dialog.addEventListener('cancel',event=>{event.preventDefault();cancel()})
 root.render(createElement(SignatureDialog,{t:key=>strings[key]??key,color:options.color,store:options.store,onCancel:cancel,onConfirm:data=>{if(active)options.onConfirm(data)}}));dialog.showModal()
 return {dispose}
}
