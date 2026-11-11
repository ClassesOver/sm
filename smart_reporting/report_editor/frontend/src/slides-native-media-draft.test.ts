import { expect, it } from 'vitest'
import { validateNativeMediaDraft } from './slides-native-media-draft'
const png='iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII='
const image={slideIndex:0,bytesBase64:png,extension:'png',geometry:{x:0,y:0,width:1,height:1}}
const picture={slideIndex:0,elementId:'pic',expectedSha256:'a'.repeat(64),expectedSize:68,bytesBase64:png,extension:'png'}
const chart={slideIndex:0,elementId:'chart',categories:['甲'],series:[{name:'数据',values:[1]}]}
const slides=[{elements:[{id:'pic',type:'picture',pictureReplaceable:true,pictureSha256:'a'.repeat(64),pictureSize:68},{id:'chart',type:'chart',chartEditSafe:true,chartKind:'bar',chartCategories:['甲'],chartSeries:[{name:'数据',values:[1]}]}]}]
it('单点配色草稿以最终数据的范围恢复并拒绝散点或越界颜色',()=>{
 const target={slideIndex:0,elementId:'chart'}
 validateNativeMediaDraft({chartEdits:[{...target,pointColors:{0:{0:'#123ABC'}}}]},slides)
 validateNativeMediaDraft({chartEdits:[{...target,pointColors:{0:{1:null}},categories:['甲','乙'],series:[{name:'数据',values:[1,2]}]}]},slides)
 for(const patch of [{pointColors:{}},{pointColors:{0:{0:'red'}}},{pointColors:{0:{1:'#123456'}}},{pointColors:{1:{0:null}}},{pointColors:{0:{0:'#123456'}},kind:'scatter'}])expect(()=>validateNativeMediaDraft({chartEdits:[{...target,...patch}]},slides)).toThrow()
})
it('配色和柱间距草稿可恢复且拒绝未知配色和非整数间距',()=>{
 const target={slideIndex:0,elementId:'chart'}
 validateNativeMediaDraft({chartEdits:[{...target,colorScheme:'warm',gapWidthPct:50}]},slides)
 const partialTheme=[{elements:[{...slides[0]!.elements[1]!,chartColorSchemes:[{key:'default'}]}]}]
 validateNativeMediaDraft({chartEdits:[{...target,colorScheme:'default'}]},partialTheme)
 expect(()=>validateNativeMediaDraft({chartEdits:[{...target,colorScheme:'warm'}]},partialTheme)).toThrow('配色来源不可用')
 for(const patch of [{colorScheme:null},{colorScheme:''},{colorScheme:[]},{colorScheme:'other'},{gapWidthPct:NaN},{gapWidthPct:1.5},{gapWidthPct:true},{gapWidthPct:501}])expect(()=>validateNativeMediaDraft({chartEdits:[{...target,...patch}]},slides)).toThrow()
})
it('交换行列草稿接受显式最终数据，校验布尔类型及交换结果的边界',()=>{
 const target={slideIndex:0,elementId:'chart'}
 validateNativeMediaDraft({chartEdits:[{...target,switchRowCol:true}]},slides)
 validateNativeMediaDraft({chartEdits:[{...target,switchRowCol:true,categories:['数据'],series:[{name:'甲',values:[42]}]}]},slides)
 for(const value of [null,0,1,'true',[],{}])expect(()=>validateNativeMediaDraft({chartEdits:[{...target,switchRowCol:value}]},slides)).toThrow()
 for(const source of [
  {...slides[0]!.elements[1]!,chartKind:'scatter',chartCategories:['1']},
  {...slides[0]!.elements[1]!,chartCategories:Array(21).fill('甲'),chartSeries:[{name:'数据',values:Array(21).fill(1)}]},
 ])expect(()=>validateNativeMediaDraft({chartEdits:[{...target,switchRowCol:true}]},[{elements:[source]}])).toThrow()
})
it('图表纯格式草稿可恢复，严格校验标题、图例、布尔字段和未知字段',()=>{
 const target={slideIndex:0,elementId:'chart'}
 validateNativeMediaDraft({chartEdits:[{...target,title:'收入😀 <&>',catAxisTitle:'',valAxisTitle:'万元',legendPos:'none',dataLabels:false,gridlines:true}]},slides)
 for(const patch of [{title:null},{title:'x'.repeat(1001)},{title:'\ud800'},{title:'\ufffe'},{legendPos:'tr'},{dataLabels:1},{gridlines:null},{unknown:true}])expect(()=>validateNativeMediaDraft({chartEdits:[{...target,...patch}]},slides)).toThrow('原草稿已保留')
})
it('整批校验通过后才能覆盖媒体草稿，后项损坏保留原草稿',()=>{
 let draft={images:[image],chartEdits:[chart]}
 const original=structuredClone(draft)
 const restore=(changes:typeof draft)=>{validateNativeMediaDraft(changes,slides,[],[]);draft=structuredClone(changes)}
 expect(()=>restore({images:[image],chartEdits:[{...chart,series:[{name:'数据',values:[NaN]}]}]})).toThrow('原草稿已保留')
 expect(draft).toEqual(original)
 validateNativeMediaDraft({images:[image],pictureReplacements:[picture],chartEdits:[chart]},slides,[],[])
})
it('拒绝来源身份变化、重复目标、删除冲突与未知字段',()=>{
 for(const changes of [{pictureReplacements:[{...picture,expectedSha256:'b'.repeat(64)}]},{pictureReplacements:[picture,picture]},{images:[{...image,path:'/tmp/image'}]},{chartEdits:[{...chart,kind:'unknown'}]}])expect(()=>validateNativeMediaDraft(changes,slides,[],[])).toThrow()
 expect(()=>validateNativeMediaDraft({images:[image]},slides,[0],[])).toThrow()
 expect(()=>validateNativeMediaDraft({pictureReplacements:[picture]},slides,[],[{slideIndex:0,elementId:'pic'}])).toThrow()
 expect(()=>validateNativeMediaDraft({chartEdits:[chart]},slides,[],[{slideIndex:0,elementId:'chart'}])).toThrow()
})
it('拒绝非规范base64、伪装签名、无效尺寸及图表不完整数据',()=>{
 for(const changes of [{images:[{...image,bytesBase64:png+'\n'}]},{images:[{...image,extension:'jpg'}]},{images:[{...image,geometry:{...image.geometry,width:Infinity}}]},{chartEdits:[{...chart,series:undefined}]},{chartEdits:[{...chart,kind:null}]},{chartEdits:[{...chart,categories:null,series:null}]},{chartEdits:[{slideIndex:0,elementId:'chart',kind:'comboBarLine'}]}])expect(()=>validateNativeMediaDraft(changes,slides,[],[])).toThrow()
})
it('图表标签允许100个Unicode字符，拒绝101字符及所有ASCII控制字符',()=>{
 const validate=(name:string)=>validateNativeMediaDraft({chartEdits:[{...chart,categories:[name],series:[{name,values:[1]}]}]},slides,[],[])
 validate('😀'.repeat(100))
 expect(()=>validate('😀'.repeat(101))).toThrow()
 for(const char of ['\0','\t','\n','\r','\x1f','\x7f'])expect(()=>validate(`数据${char}`)).toThrow()
})
it('图表修改最多50个不同来源目标',()=>{
 const source=slides[0]!.elements[1]!
 const manySlides=[{elements:Array.from({length:51},(_,i)=>({...source,id:`chart${i}`}))}]
 const chartEdits=Array.from({length:51},(_,i)=>({...chart,elementId:`chart${i}`}))
 validateNativeMediaDraft({chartEdits:chartEdits.slice(0,50)},manySlides,[],[])
 expect(()=>validateNativeMediaDraft({chartEdits},manySlides,[],[])).toThrow('批次数量')
})
it('恢复裁切整批验证媒体身份、crop与frame，替换及删除冲突保留原草稿',()=>{
 const cropSlides=[{elements:[{...slides[0]!.elements[0]!,pictureCropEditable:true,srcRect:null}]}]
 const crop={slideIndex:0,elementId:'pic',expectedSha256:'a'.repeat(64),expectedSize:68,srcRect:{l:.1,t:0,r:.2,b:0},geometry:{x:-20,y:10,width:70,height:50}}
 validateNativeMediaDraft({pictureCrops:[crop]},cropSlides,[],[])
 validateNativeMediaDraft({pictureCrops:[{...crop,srcRect:null}]},cropSlides,[],[])
 for(const bad of [{...crop,expectedSize:69},{...crop,srcRect:{l:.5,t:0,r:.5,b:0}},{...crop,srcRect:{l:-.1,t:0,r:0,b:0}},{...crop,geometry:{...crop.geometry,width:0}},{...crop,extra:true}])expect(()=>validateNativeMediaDraft({pictureCrops:[bad]},cropSlides,[],[])).toThrow('原草稿已保留')
 expect(()=>validateNativeMediaDraft({pictureCrops:[crop,crop]},cropSlides,[],[])).toThrow()
 expect(()=>validateNativeMediaDraft({pictureCrops:[crop],pictureReplacements:[picture]},cropSlides,[],[])).toThrow()
 expect(()=>validateNativeMediaDraft({pictureCrops:[crop]},cropSlides,[0],[])).toThrow()
 expect(()=>validateNativeMediaDraft({pictureCrops:[crop]},cropSlides,[],[{slideIndex:0,elementId:'pic'}])).toThrow()
 expect(()=>validateNativeMediaDraft({pictureCrops:[crop]},slides,[],[])).toThrow()
})
