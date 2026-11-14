import {useState} from 'react'
import {DOCX_PROTECTION_MODES,withDocxProtection,type DocxProtectionModel,type DocxProtectionMode} from './docx-protection'
import type {NativeOperation} from './native-draft'
import './docx-protection.css'
const labels={trackedChanges:'仅允许修订',comments:'仅允许批注',readOnly:'只读',forms:'仅允许填写窗体'}
export function DocxProtectionDialog({model,operations,onApply,onClose}:{model:DocxProtectionModel;operations:NativeOperation[];onApply:(ops:NativeOperation[])=>void;onClose:()=>void}){
 const [mode,setMode]=useState<DocxProtectionMode>('readOnly'),[password,setPassword]=useState(''),[confirmation,setConfirmation]=useState(''),[error,setError]=useState('')
 const locked=!!model.protection?.enforced
 const submit=()=>{try{if(!locked&&password!==confirmation)throw Error('两次输入的密码不一致');onApply(withDocxProtection(operations,model,locked?'disable':'enable',mode,password));setPassword('');setConfirmation('');onClose()}catch(e){setError(e instanceof Error?e.message:String(e))}}
 return <div className="docx-protection-backdrop"><section className="docx-protection-dialog" role="dialog" aria-modal="true" aria-labelledby="docx-protection-title"><h2 id="docx-protection-title">保护文档</h2>
 <p>{locked?'解除保护需单独保存并重新打开；保存前正文仍保持只读。':'设置编辑限制后，保存的 Word 文件将包含相应保护。当前编辑器对所有限制模式保持只读；仅修订、批注和窗体编辑需在支持的 Word 客户端进行。'}</p>
 {!locked&&<label>编辑限制<select value={mode} onChange={e=>setMode(e.target.value as DocxProtectionMode)}>{DOCX_PROTECTION_MODES.map(m=><option key={m} value={m}>{labels[m]}</option>)}</select></label>}
 <label>{locked?'当前保护密码':'保护密码（可选）'}<input autoFocus type="password" autoComplete="off" maxLength={255} value={password} onChange={e=>setPassword(e.target.value)}/></label>
 {!locked&&<label>确认密码<input type="password" autoComplete="off" maxLength={255} value={confirmation} onChange={e=>setConfirmation(e.target.value)}/></label>}
 {!model.editable&&<p role="alert">{model.readOnlyReason}</p>}{error&&<p role="alert">{error}</p>}<footer><button type="button" onClick={onClose}>取消</button><button type="button" disabled={!model.editable} onClick={submit}>{locked?'解除保护':'启用保护'}</button></footer></section></div>
}
