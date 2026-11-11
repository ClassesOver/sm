import {expect,it} from 'vitest'
import {bindPdfReplacementStyle,validatePdfStyledReplacement} from './pdf-replace-text-style'
import {validatePdfSelectionStyleRuns} from './pdf-text-selection'
it('selected font styles preserve textarea UTF16 range and splice inherited styles through typing',()=>{
 const root=document.createElement('section'),text=document.createElement('textarea');text.setAttribute('aria-label','替换后的文字');text.value='A😀BCDEF';root.append(text);document.body.append(root)
 const panel=bindPdfReplacementStyle(root);text.focus();text.setSelectionRange(1,3);text.dispatchEvent(new Event('select'))
 root.querySelector<HTMLSelectElement>('[aria-label="选区字体"]')!.value='times'
 root.querySelector<HTMLInputElement>('[aria-label="选区字号"]')!.value='18'
 root.querySelector<HTMLSelectElement>('[aria-label="选区粗体"]')!.value='true'
 root.querySelector<HTMLSelectElement>('[aria-label="选区斜体"]')!.value='true'
 root.querySelector<HTMLInputElement>('[aria-label="选区指定颜色"]')!.checked=true
 root.querySelector<HTMLInputElement>('[aria-label="选区颜色"]')!.value='#ff0000'
 root.querySelector<HTMLButtonElement>('[data-pdf-selection-style-apply]')!.click()
 const style={font:'times',size:18,bold:true,italic:true,color:[1,0,0]}
 expect(panel.read()).toEqual({styleRuns:[{start:1,end:3,...style}]});expect(document.activeElement).toBe(text);expect([text.selectionStart,text.selectionEnd]).toEqual([1,3])
 text.value='A😀XYZBCDEF';text.dispatchEvent(new Event('input'))
 expect(panel.read().styleRuns).toEqual([{start:1,end:6,...style}])
 const operation={kind:'replaceText',newText:text.value,...panel.read()};panel.fill(operation);expect(panel.changed(operation)).toBe(false)
 text.setSelectionRange(3,6);text.dispatchEvent(new Event('select'));root.querySelector<HTMLButtonElement>('[data-pdf-selection-style-clear]')!.click()
 expect(panel.read().styleRuns).toEqual([{start:1,end:3,...style}]);expect([text.selectionStart,text.selectionEnd]).toEqual([3,6])
 panel.setDisabled(true);expect(root.querySelector<HTMLButtonElement>('[data-pdf-selection-style-apply]')!.disabled).toBe(true)
 panel.dispose();root.remove()
})
it('selection runs accept complete supplementary scalars and reject overlaps surrogate cuts and invalid fields',()=>{
 expect(()=>validatePdfSelectionStyleRuns('A😀B',[{start:1,end:3,bold:true}])).not.toThrow()
 for(const runs of [[{start:1,end:2,bold:true}],[{start:2,end:3,bold:true}],[{start:0,end:3,bold:true},{start:2,end:4,italic:true}],[{start:0,end:1}],[{start:0,end:1,extra:true}]])expect(()=>validatePdfSelectionStyleRuns('A😀B',runs)).toThrow()
 const sha='a'.repeat(64),pageId='sha256:'+sha+':page:0',target={objectId:'target',expectedTextSha256:'b'.repeat(64),text:'Original',rect:[30,300,130,315] as [number,number,number,number],fontSize:14,fontName:'Arial',fontSha256:null}
 expect(()=>validatePdfStyledReplacement([{pageId,index:0,rotation:0,mediaBox:{x:0,y:0,width:500,height:500},cropBox:{x:0,y:0,width:500,height:500},textObjects:[target]}],[{kind:'replaceText',sourceSha256:sha,pageId,objectId:target.objectId,expectedTextSha256:target.expectedTextSha256,newText:'A😀B',styleRuns:[{start:1,end:3,bold:true}]}])).not.toThrow()
})
