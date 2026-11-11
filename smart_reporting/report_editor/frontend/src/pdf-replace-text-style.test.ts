import {expect,it} from 'vitest'
import {bindPdfReplacementStyle,isStyledPdfReplacement,validatePdfStyledReplacement} from './pdf-replace-text-style'
import type {PdfPageIdentity} from './pdf-operations'
const sha='a'.repeat(64),pageId='sha256:'+sha+':page:0',objectId='object-a',expectedTextSha256='b'.repeat(64)
const pages:PdfPageIdentity[]=[{pageId,index:0,rotation:0,mediaBox:{x:0,y:0,width:500,height:500},cropBox:{x:0,y:0,width:500,height:500},textObjects:[{objectId,expectedTextSha256,text:'Original',rect:[30,300,130,315],fontSize:14,fontName:'Arial',fontSha256:null}]}]
const operation={kind:'replaceText',sourceSha256:sha,pageId,objectId,expectedTextSha256,newText:'First\n\nSecond',font:'times',bold:true,italic:true,fontSize:18,color:[.2,.4,.6],align:'right',lineLeading:24}
it('validates source bound styled multiline text and refuses mixed or stale operations',()=>{
 expect(()=>validatePdfStyledReplacement(pages,[operation])).not.toThrow()
 for(const patch of [{sourceSha256:'c'.repeat(64)},{objectId:'stale'},{expectedTextSha256:'c'.repeat(64)},{newText:'bad\u0000value'},{font:'unknown'},{fontSize:5},{color:[0,0,2]},{bold:1},{italic:'true'},{align:'justify'},{lineLeading:0}])expect(()=>validatePdfStyledReplacement(pages,[{...operation,...patch}])).toThrow()
 expect(()=>validatePdfStyledReplacement(pages,[operation,operation])).toThrow('重复')
 expect(()=>validatePdfStyledReplacement(pages,[operation,{kind:'rotatePage',pageId,delta:90}])).toThrow('分别保存')
 expect(isStyledPdfReplacement({kind:'replaceText',newText:'legacy'})).toBe(false)
 expect(isStyledPdfReplacement({kind:'replaceText',newText:'new\nline'})).toBe(true)
})
it('style panel keeps old drafts empty and persists only explicit options',()=>{
 const root=document.createElement('section'),panel=bindPdfReplacementStyle(root)
 expect(panel.read()).toEqual({});expect(panel.changed()).toBe(false)
 root.querySelector<HTMLSelectElement>('[aria-label="替换文字字体"]')!.value='times'
 root.querySelector<HTMLInputElement>('[aria-label="替换文字字号"]')!.value='18'
 root.querySelector<HTMLInputElement>('[aria-label="替换文字粗体"]')!.checked=true
 root.querySelector<HTMLInputElement>('[aria-label="替换文字斜体"]')!.checked=true
 root.querySelector<HTMLSelectElement>('[aria-label="替换文字对齐"]')!.value='right'
 root.querySelector<HTMLInputElement>('[aria-label="替换文字行距"]')!.value='24'
 expect(panel.read()).toEqual({font:'times',fontSize:18,bold:true,italic:true,align:'right',lineLeading:24})
 expect(panel.changed()).toBe(true)
 panel.fill(operation);expect(panel.read()).toMatchObject({font:'times',color:[.2,.4,.6],bold:true,italic:true});expect(panel.changed(operation)).toBe(false)
 panel.setDisabled(true);expect([...root.querySelectorAll('input,select')].every(input=>(input as HTMLInputElement).disabled)).toBe(true)
 panel.fill();expect(panel.read()).toEqual({});panel.dispose();expect(root.children).toHaveLength(0)
})
