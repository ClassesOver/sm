/** Adapted from fixed GenOffice apps/pdf/src/renderer/paper-sample.ts. */
export function ringMedianColor(data:Uint8ClampedArray,width:number,height:number,rect:{x:number;y:number;w:number;h:number},ring:number):[number,number,number]|null{
 const x0=Math.max(0,Math.floor(rect.x-ring)),y0=Math.max(0,Math.floor(rect.y-ring)),x1=Math.min(width,Math.ceil(rect.x+rect.w+ring)),y1=Math.min(height,Math.ceil(rect.y+rect.h+ring)),ix0=Math.floor(rect.x),iy0=Math.floor(rect.y),ix1=Math.ceil(rect.x+rect.w),iy1=Math.ceil(rect.y+rect.h),r:number[]=[],g:number[]=[],b:number[]=[]
 for(let y=y0;y<y1;y++){const inY=y>=iy0&&y<iy1;for(let x=x0;x<x1;x++){if(inY&&x>=ix0&&x<ix1)continue;const i=(y*width+x)*4;if(data[i+3]!<128)continue;r.push(data[i]!);g.push(data[i+1]!);b.push(data[i+2]!)}}
 if(!r.length)return null;const med=(a:number[])=>a.sort((p,q)=>p-q)[a.length>>1]!;return [med(r),med(g),med(b)]
}
const hex2=(value:number)=>value.toString(16).padStart(2,'0')
export function samplePaperColor(pageEl:Element|null,box:{left:number;top:number;width:number;height:number}):string|null{
 const canvas=pageEl?.querySelector('canvas') as HTMLCanvasElement|null
 if(!canvas||canvas.width===0||canvas.clientWidth===0)return null;const k=canvas.width/canvas.clientWidth,ring=Math.max(2,Math.round(3*k)),pad=Math.round(2*k),rect={x:box.left*k-pad,y:box.top*k-pad,w:box.width*k+pad*2,h:box.height*k+pad*2},x0=Math.max(0,Math.floor(rect.x-ring)),y0=Math.max(0,Math.floor(rect.y-ring)),x1=Math.min(canvas.width,Math.ceil(rect.x+rect.w+ring)),y1=Math.min(canvas.height,Math.ceil(rect.y+rect.h+ring));if(x1<=x0||y1<=y0)return null
 try{const context=canvas.getContext('2d',{willReadFrequently:true});if(!context)return null;const image=context.getImageData(x0,y0,x1-x0,y1-y0),color=ringMedianColor(image.data,image.width,image.height,{x:rect.x-x0,y:rect.y-y0,w:rect.w,h:rect.h},ring);return color?`#${hex2(color[0])}${hex2(color[1])}${hex2(color[2])}`:null}catch{return null}
}
