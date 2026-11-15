// @vitest-environment jsdom
import {it,expect,vi} from 'vitest'
import {act} from 'react'
import {createRoot} from 'react-dom/client'
import {DocxMailMergePanel} from './docx-mail-merge-panel'
vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true)
it('exports actual per-record and configured label requests from enabled controls',async()=>{
 const host=document.createElement('div');document.body.append(host);const root=createRoot(host),onExport=vi.fn(),onMerge=vi.fn()
 const editor={getJSON:()=>({type:'doc',content:[]})} as never,source={name:'Recipients.csv',path:'',sourceSha256:'s',sourceBase64:'',fields:['Name'],records:[{Name:'Ada'}],recordCount:1}
 try{
  await act(async()=>root.render(<DocxMailMergePanel editor={editor} source={source} reason={()=>null} onClose={()=>{}} onPickSource={()=>{}} onInsertField={()=>{}} onMerge={onMerge} onExport={onExport}/>))
  const choose=async(value:string)=>{await act(async()=>{(host.querySelector(`input[value="${value}"]`) as HTMLInputElement).click()})}
  const submit=async()=>{await act(async()=>{Array.from(host.querySelectorAll('button')).find(button=>button.textContent==='导出合并文件')!.click()})}
  await choose('perRecord');await submit();expect(onExport).toHaveBeenLastCalledWith({mode:'perRecord',namePattern:''})
  await choose('labels');await submit();expect(onExport).toHaveBeenLastCalledWith({mode:'labels',namePattern:'',layout:{stock:'avery5160'}})
  expect(onMerge).not.toHaveBeenCalled()
 }finally{await act(async()=>root.unmount());host.remove()}
})
