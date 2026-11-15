import {expect,it,vi} from 'vitest'
import type {PdfPageIdentity} from './pdf-operations'
import type {NativeOperation} from './native-draft'
import {pdfExistingImageThumbnailPlan,pdfExistingImageThumbnailPixels,pdfExistingImageThumbnailBackground,mountPdfExistingImageThumbnail} from './pdf-existing-image-thumbnail'

const sha='a'.repeat(64),pageId=`sha256:${sha}:page:0`,imageId='b'.repeat(64),expectedImageSha256='c'.repeat(64)
const page:PdfPageIdentity={pageId,index:0,rotation:0,mediaBox:{x:0,y:0,width:400,height:500},cropBox:{x:10,y:20,width:380,height:460}}
const image={pageId,pageIndex:0,rect:[60,90,160,170] as [number,number,number,number],imageId,expectedImageSha256,aboveText:true,editable:true,replaceable:true,bakeable:true}
const operation:NativeOperation={kind:'transformExistingImage',sourceSha256:sha,pageId,imageId,expectedImageSha256,rect:[80,110,230,210]}
const viewport={width:380,height:460,convertToViewportPoint:(x:number,y:number)=>[x-10,480-y]}
const decodedImage=(png:string,width:number,height:number)=>{const image=document.createElement('img');Object.defineProperties(image,{naturalWidth:{value:width},naturalHeight:{value:height}});image.src=png.startsWith('data:')?png:`data:image/png;base64,${png}`;return image}

it('binds one source-identified image transform and projects both image footprints through the CropBox viewport',()=>{
 const plan=pdfExistingImageThumbnailPlan({sourceSha256:sha,page,operation,images:[image],viewport})!
 expect(plan).toMatchObject({sourceSha256:sha,pageId,imageId,expectedImageSha256,oldRect:[60,90,160,170],rect:[80,110,230,210],layer:'aboveText',image:undefined,bake:undefined})
 expect(plan.oldBox).toEqual({left:50,top:310,width:100,height:80})
 expect(plan.box).toEqual({left:70,top:270,width:150,height:100})
})

it('clips the old thumbnail footprint to the source viewport and derives a bounded background raster width',()=>{
 const clipped=pdfExistingImageThumbnailPlan({sourceSha256:sha,page,operation,images:[image],viewport:{...viewport,width:60}})!
 expect(clipped.clip).toEqual({x:48,y:308,width:12,height:84})
 expect(clipped.pxWidth).toBe(12)
 const wide=pdfExistingImageThumbnailPlan({sourceSha256:sha,page,operation,images:[image],viewport:{width:7600,height:9200,convertToViewportPoint:(x:number,y:number)=>[(x-10)*20, (480-y)*20]}})!
 expect(wide.pxWidth).toBeLessThanOrEqual(720)
 expect(wide.pxHeight).toBe(576)
})

it('accepts a background only when identity, clipped geometry, dimensions and SHA match',async()=>{
 const plan=pdfExistingImageThumbnailPlan({sourceSha256:sha,page,operation,images:[image],viewport})!
 const response={sourceSha256:sha,pageId,imageId,expectedImageSha256,clip:plan.clip,image:'iVBORw0KGgoAAA',width:plan.pxWidth,height:plan.pxHeight,sha256:'d'.repeat(64)}
 await expect(pdfExistingImageThumbnailBackground(plan,response,async()=>response.sha256)).resolves.toBe(response.image)
 await expect(pdfExistingImageThumbnailBackground(plan,{...response,imageId:'e'.repeat(64)},async()=>response.sha256)).resolves.toBeNull()
 await expect(pdfExistingImageThumbnailBackground(plan,{...response,clip:{...plan.clip,x:plan.clip.x+1e-4}},async()=>response.sha256)).resolves.toBeNull()
 await expect(pdfExistingImageThumbnailBackground(plan,{...response,clip:{x:plan.clip.x,y:plan.clip.y,width:plan.clip.width} as any},async()=>response.sha256)).resolves.toBeNull()
 await expect(pdfExistingImageThumbnailBackground(plan,{...response,clip:{...plan.clip,unexpected:1} as any},async()=>response.sha256)).resolves.toBeNull()
 await expect(pdfExistingImageThumbnailBackground(plan,{...response,width:101},async()=>response.sha256)).resolves.toBeNull()
 await expect(pdfExistingImageThumbnailBackground(plan,response,async()=> 'e'.repeat(64))).resolves.toBeNull()
})

it.each([0,90,180,270])('projects old and final footprints with page rotation %i',rotation=>{
 const view={...viewport,width:rotation%180?460:380,height:rotation%180?380:460,convertToViewportPoint:(x:number,y:number)=>{
  const px=x-10,py=y-20
  if(rotation===90)return [py,px]
  if(rotation===180)return [380-px,460-py]
  if(rotation===270)return [460-py,380-px]
  return [px,460-py]
 }}
 const plan=pdfExistingImageThumbnailPlan({sourceSha256:sha,page:{...page,rotation},operation,images:[image],viewport:view})!
 expect(plan.oldBox.width).toBeCloseTo(rotation%180?80:100);expect(plan.oldBox.height).toBeCloseTo(rotation%180?100:80)
 expect(plan.box.width).toBeCloseTo(rotation%180?100:150);expect(plan.box.height).toBeCloseTo(rotation%180?150:100)
})

it('rejects foreign, stale, ambiguous and out-of-CropBox pending image targets',()=>{
 const args={sourceSha256:sha,page,operation,images:[image],viewport}
 expect(pdfExistingImageThumbnailPlan({...args,sourceSha256:'d'.repeat(64)})).toBeNull()
 expect(pdfExistingImageThumbnailPlan({...args,operation:{...operation,pageId:`sha256:${sha}:page:1`}})).toBeNull()
 expect(pdfExistingImageThumbnailPlan({...args,operation:{...operation,expectedImageSha256:'d'.repeat(64)}})).toBeNull()
 expect(pdfExistingImageThumbnailPlan({...args,images:[image,image]})).toBeNull()
 expect(pdfExistingImageThumbnailPlan({...args,operation:{...operation,rect:[0,110,230,210]}})).toBeNull()
})

it('keeps a replacement PNG without fetching source pixels and preserves the source z band',()=>{
 const plan=pdfExistingImageThumbnailPlan({sourceSha256:sha,page,operation:{...operation,image:'iVBORw0KGgoAAA'},images:[{...image,aboveText:false}],viewport})!
 expect(plan.image).toBe('iVBORw0KGgoAAA');expect(plan.layer).toBe('belowText')
})

it('rejects pixels whose target identity, image digest, or dimensions changed',async()=>{
 const plan=pdfExistingImageThumbnailPlan({sourceSha256:sha,page,operation,images:[image],viewport})!
 const pixels={sourceSha256:sha,pageId,imageId,expectedImageSha256,width:2,height:1,image:'iVBORw0KGgoAAA',sha256:'d'.repeat(64)}
 await expect(pdfExistingImageThumbnailPixels(plan,{...pixels,sourceSha256:'e'.repeat(64)},async()=>pixels.sha256)).resolves.toBeNull()
 await expect(pdfExistingImageThumbnailPixels(plan,pixels,async()=> 'f'.repeat(64))).resolves.toBeNull()
 await expect(pdfExistingImageThumbnailPixels(plan,{...pixels,width:0},async()=>pixels.sha256)).resolves.toBeNull()
 await expect(pdfExistingImageThumbnailPixels(plan,pixels,async()=>pixels.sha256)).resolves.toBe(pixels.image)
})

it('mounts replacement pixels only after the host is connected',()=>{
 const plan=pdfExistingImageThumbnailPlan({sourceSha256:sha,page,operation:{...operation,image:'iVBORw0KGgoAAA'},images:[image],viewport})!,host=document.createElement('div')
 document.body.append(host)
 const background={sourceSha256:sha,pageId,imageId,expectedImageSha256,clip:plan.clip,image:'iVBORw0KGgoAAA',width:plan.pxWidth,height:plan.pxHeight,sha256:'d'.repeat(64)}
 const cleanup=mountPdfExistingImageThumbnail({host,plan,viewport,entry:{ready:callback=>{callback();return vi.fn()}},current:()=>true,loadBackground:async()=>background,loadPixels:async()=>{throw Error('replacement should not load source')},sha256Bytes:async()=>background.sha256,decode:async png=>decodedImage(png,plan.pxWidth,plan.pxHeight)})
 return vi.waitFor(()=>{const img=host.querySelector<HTMLImageElement>('.pdf-existing-image-thumbnail-image');expect(img?.src).toContain('iVBORw0KGgoAAA')})
  .then(()=>{expect(host.querySelector('.pdf-existing-image-thumbnail-ghost')).toBeNull();cleanup();expect(host.querySelector('.pdf-existing-image-thumbnail-layer')).toBeNull();host.remove()})
})

it('supports a synchronous cached ready callback and drops pixels after cancellation',async()=>{
 const plan=pdfExistingImageThumbnailPlan({sourceSha256:sha,page,operation,images:[image],viewport})!,host=document.createElement('div');document.body.append(host)
 const pixels={sourceSha256:sha,pageId,imageId,expectedImageSha256,width:2,height:1,image:'iVBORw0KGgoAAA',sha256:'d'.repeat(64)}
 let resolvePixels!:(value:typeof pixels)=>void
 const loadPixels=vi.fn(()=>new Promise<typeof pixels>(resolve=>{resolvePixels=resolve})),ready=vi.fn((callback:()=>void)=>{callback();return vi.fn()})
 const background={sourceSha256:sha,pageId,imageId,expectedImageSha256,clip:plan.clip,image:'iVBORw0KGgoAAA',width:plan.pxWidth,height:plan.pxHeight,sha256:pixels.sha256}
 const cleanup=mountPdfExistingImageThumbnail({host,plan,viewport,entry:{ready},current:()=>true,loadBackground:async()=>background,loadPixels,sha256Bytes:async()=>pixels.sha256,decode:async png=>decodedImage(png,plan.pxWidth,png===background.image?plan.pxHeight:1)})
 expect(ready).toHaveBeenCalledOnce();expect(loadPixels).toHaveBeenCalledOnce()
 cleanup();resolvePixels(pixels);await Promise.resolve();await Promise.resolve()
 expect(host.querySelector('.pdf-existing-image-thumbnail-image')).toBeNull();expect(host.querySelector('.pdf-existing-image-thumbnail-layer')).toBeNull();host.remove()
})

it('loads the erased background and foreground together after base readiness, outside the multiply layer',async()=>{
 const plan=pdfExistingImageThumbnailPlan({sourceSha256:sha,page,operation,images:[image],viewport})!,host=document.createElement('span');document.body.append(host)
 const pngBackground='iVBORw0KGgoAAAAABg==',pngForeground='iVBORw0KGgoAAAAABw==',signals:AbortSignal[]=[]
 const background={sourceSha256:sha,pageId,imageId,expectedImageSha256,clip:plan.clip,image:pngBackground,width:plan.pxWidth,height:plan.pxHeight,sha256:'d'.repeat(64)}
 const pixels={sourceSha256:sha,pageId,imageId,expectedImageSha256,width:2,height:1,image:pngForeground,sha256:'e'.repeat(64)}
 let ready!:()=>void
 const entry={ready(callback:()=>void){ready=callback;return vi.fn()}}
 let resolveBackground!:(value:typeof background)=>void,resolvePixels!:(value:typeof pixels)=>void
 const loadBackground=vi.fn((_signal:AbortSignal)=>{signals.push(_signal);return new Promise<typeof background>(resolve=>{resolveBackground=resolve})})
 const loadPixels=vi.fn((_signal:AbortSignal)=>{signals.push(_signal);return new Promise<typeof pixels>(resolve=>{resolvePixels=resolve})})
 const cleanup=mountPdfExistingImageThumbnail({host,plan,viewport,entry,current:()=>true,loadBackground,loadPixels,sha256Bytes:async(bytes)=>bytes.at(-1)===6?'d'.repeat(64):'e'.repeat(64),decode:async(png)=>decodedImage(png,png===pngBackground?plan.pxWidth:2,png===pngBackground?plan.pxHeight:1)})
 expect(loadBackground).not.toHaveBeenCalled();expect(loadPixels).not.toHaveBeenCalled()
 ready();await vi.waitFor(()=>expect(loadBackground).toHaveBeenCalledOnce())
 expect(loadPixels).toHaveBeenCalledOnce();expect(host.querySelector('.pdf-existing-image-thumbnail-layer')).toBeNull()
 cleanup();resolveBackground(background);resolvePixels(pixels);await Promise.resolve();await Promise.resolve()
 expect(signals).toHaveLength(2);expect(signals.every(signal=>signal.aborted)).toBe(true)
 expect(host.querySelector('.pdf-existing-image-thumbnail-background')).toBeNull();host.remove()
})

it('atomically mounts a normal-blend background sibling before the original z-band foreground',async()=>{
 const plan=pdfExistingImageThumbnailPlan({sourceSha256:sha,page,operation,images:[image],viewport})!,host=document.createElement('span');document.body.append(host)
 const pngBackground='iVBORw0KGgoAAAAABg==',pngForeground='iVBORw0KGgoAAAAABw=='
 const background={sourceSha256:sha,pageId,imageId,expectedImageSha256,clip:plan.clip,image:pngBackground,width:plan.pxWidth,height:plan.pxHeight,sha256:'d'.repeat(64)}
 const pixels={sourceSha256:sha,pageId,imageId,expectedImageSha256,width:2,height:1,image:pngForeground,sha256:'e'.repeat(64)}
 const ready=(callback:()=>void)=>{callback();return vi.fn()}
 const cleanup=mountPdfExistingImageThumbnail({host,plan,viewport,entry:{ready},current:()=>true,loadBackground:async()=>background,loadPixels:async()=>pixels,sha256Bytes:async bytes=>bytes.at(-1)===6?'d'.repeat(64):'e'.repeat(64),decode:async png=>decodedImage(png,png===pngBackground?plan.pxWidth:2,png===pngBackground?plan.pxHeight:1)})
 await vi.waitFor(()=>expect(host.children).toHaveLength(2))
 expect(host.children[0]).toMatchObject({className:'pdf-existing-image-thumbnail-background'})
 expect((host.children[0] as HTMLElement).style.mixBlendMode).toBe('normal')
 expect((host.children[0] as HTMLElement).style.zIndex).toBe('3')
 expect(host.children[1]).toMatchObject({className:'pdf-existing-image-thumbnail-layer pdf-existing-image-thumbnail-aboveText'})
 expect(host.querySelector('.pdf-existing-image-thumbnail-veil')).toBeNull()
 cleanup();host.remove()
})
it('does not redraw the original foreground as a moved image for a pending deletion',()=>{
 expect(pdfExistingImageThumbnailPlan({sourceSha256:sha,page,operation:{...operation,remove:true,rect:image.rect},images:[{...image,removable:true}],viewport})).toBeNull()
})
it('defers a layer change thumbnail to the actual PDF instead of repainting the old text band',()=>{
 expect(pdfExistingImageThumbnailPlan({sourceSha256:sha,page,operation:{...operation,rect:image.rect,layer:'belowText'},images:[{...image,layerable:true}],viewport})).toBeNull()
})
