/** 固定源 zoom-actions：快照图加内部页跳转。身份由服务端 inspect 返回并在写入时重算。 */
export function validateZoomDraft(items:unknown,slides:{slideIdentity?:string}[],deleted:number[]=[]):void{
 if(items===undefined)return
 if(!Array.isArray(items)||items.length>50)throw Error('缩放定位草稿无效；原草稿已保留')
 const identities=new Set(slides.filter((slide,index)=>!deleted.includes(index)&&/^[a-f0-9]{64}$/.test(slide.slideIdentity??'')).map(slide=>slide.slideIdentity)),seen=new Set<string>()
 for(const item of items){
  const key=item?.slideIdentity+':'+item?.targetSlideIdentity
  if(!item||Object.keys(item).sort().join()!=='bytesBase64,geometry,mode,slideIdentity,targetSlideIdentity'||!identities.has(item.slideIdentity)||!identities.has(item.targetSlideIdentity)||!['slide','section'].includes(item.mode)||seen.has(key)||typeof item.bytesBase64!=='string'||item.bytesBase64.length>8*1024*1024||!/^iVBORw0KGgo[A-Za-z0-9+/]*={0,2}$/.test(item.bytesBase64)||!item.geometry||Object.keys(item.geometry).sort().join()!=='height,width,x,y'||Object.values(item.geometry).some(value=>typeof value!=='number'||!Number.isFinite(value)||value<0||value>100000)||item.geometry.width<1||item.geometry.height<1)throw Error('缩放定位草稿无效；原草稿已保留')
  seen.add(key)
 }
}
