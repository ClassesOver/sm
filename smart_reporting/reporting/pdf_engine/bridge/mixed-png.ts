/** Bounded browser-normalized PNG inspection; decoding/writing stays in pdf-lib. */
import {createHash} from 'node:crypto'
import * as zlib from 'node:zlib'
import {PDFArray,PDFDict,PDFDocument,PDFName,PDFNumber,PDFRawStream,PDFRef,decodePDFRawStream} from 'pdf-lib'
import {PNG} from 'pdf-lib/cjs/utils/png.js'
export interface MixedPngBudget {pixels:number;bytes:number}
export interface MixedPngImage {width:number;height:number;rgbSha256:string;alphaSha256?:string}
const hash=(bytes:Uint8Array)=>createHash('sha256').update(bytes).digest('hex')
const fail=(reason:string):never=>{throw Error('pdf_text_png_'+reason)}
export function prepareMixedPng(image:string,budget:MixedPngBudget):MixedPngImage{
 if(typeof image!=='string'||image.length>6_000_000||image.length%4!==0||!/^[A-Za-z0-9+/]*={0,2}$/.test(image))return fail('invalid_base64')
 const bytes=Buffer.from(image,'base64')
 if(bytes.toString('base64')!==image||bytes.length<45||!bytes.subarray(0,8).equals(Buffer.from([137,80,78,71,13,10,26,10])))return fail('invalid_signature')
 if(bytes.readUInt32BE(8)!==13||bytes.toString('ascii',12,16)!=='IHDR')return fail('invalid_ihdr')
 const width=bytes.readUInt32BE(16),height=bytes.readUInt32BE(20),depth=bytes[24],color=bytes[25]
 if(!width||!height||width>2000||height>2000||width*height>4_000_000)throw Error('PNG 单图像素预算超限（每边最多 2000、最多 400 万像素）')
 if(depth!==8||![2,6].includes(color!)||bytes[26]!==0||bytes[27]!==0||bytes[28]!==0)return fail('unsupported_ihdr')
 if(budget.pixels+width*height>8_000_000||budget.bytes+bytes.length>12*1024*1024)throw Error('PNG 批量像素或字节预算超限（最多 800 万像素、12 MiB）')
 // Node 22.15+/24 provides CRC32. Older deployments reject only this new path.
 if(typeof zlib.crc32!=='function')return fail('checksum_runtime_unavailable')
 const idat:Uint8Array[]=[];let end=false,endedData=false
 for(let offset=8;offset<bytes.length;){
  if(offset+12>bytes.length)return fail('truncated_chunk')
  const length=bytes.readUInt32BE(offset),type=bytes.toString('ascii',offset+4,offset+8),next=offset+12+length
  if(next>bytes.length||zlib.crc32(bytes.subarray(offset+4,next-4))!==bytes.readUInt32BE(next-4))return fail('invalid_chunk_crc')
  if(type==='IHDR'){if(offset!==8||length!==13)return fail('duplicate_ihdr')}
  else if(type==='IDAT'){if(endedData||!length)return fail('invalid_idat');idat.push(bytes.subarray(offset+8,next-4))}
  else if(type==='IEND'){if(length||!idat.length||next!==bytes.length)return fail('invalid_iend');end=true}
  else {if(idat.length)endedData=true;const lengths:Record<string,number>={sRGB:1,gAMA:4,pHYs:9,cHRM:32};if(lengths[type]!==length)return fail('unsupported_chunk_'+type)}
  offset=next
 }
 if(!end)return fail('missing_iend')
 const expectedLength=(width*(color===6?4:3)+1)*height
 const scanlines=zlib.inflateSync(Buffer.concat(idat),{maxOutputLength:expectedLength}),stride=width*(color===6?4:3)+1
 if(scanlines.length!==expectedLength)return fail('invalid_scanline_size')
 for(let row=0;row<height;row++)if(scanlines[row*stride]!>4)return fail('invalid_scanline_filter')
 const decoded=PNG.load(bytes)
 if(decoded.width!==width||decoded.height!==height||decoded.bitsPerComponent!==8||decoded.rgbChannel.length!==width*height*3||decoded.alphaChannel&&decoded.alphaChannel.length!==width*height)return fail('decoded_dimensions_changed')
 budget.pixels+=width*height;budget.bytes+=bytes.length
 return {width,height,rgbSha256:hash(decoded.rgbChannel),...(decoded.alphaChannel?{alphaSha256:hash(decoded.alphaChannel)}:{})}
}
const keys=(dict:PDFDict,allowed:string[])=>{if(dict.keys().some(key=>!allowed.includes(key.decodeText())))fail('output_unexpected_metadata')}
const numbers=(dict:PDFDict,key:string,expected:number[])=>{const value=dict.lookup(PDFName.of(key));if(!(value instanceof PDFArray)||value.size()!==expected.length||value.asArray().some((value,index)=>!(value instanceof PDFNumber)||value.asNumber()!==expected[index]))fail('output_'+key+'_changed')}
export function reviewMixedPngStamp(document:PDFDocument,pageIndex:number,annotation:PDFDict,rect:[number,number,number,number],image:MixedPngImage,rotation:number){
 const page=document.getPage(pageIndex),round=(value:number)=>Math.round(value*100)/100,[x1,y1,x2,y2]=rect,width=x2-x1,height=y2-y1
 keys(annotation,['Type','Subtype','Rect','F','P','AP','T'])
 if(String(annotation.get(PDFName.of('Type')))!=='/Annot'||String(annotation.get(PDFName.of('Subtype')))!=='/Stamp'||String(annotation.get(PDFName.of('F')))!=='4'||String(annotation.get(PDFName.of('P')))!==String(page.ref)||page.getRotation().angle!==rotation)fail('output_stamp_identity_changed')
 numbers(annotation,'Rect',rect.map(round))
 const appearance=annotation.lookup(PDFName.of('AP'),PDFDict);keys(appearance,['N'])
 const ap=appearance.lookup(PDFName.of('N'));if(!(ap instanceof PDFRawStream))return fail('output_appearance_unreadable')
 keys(ap.dict,['Type','Subtype','BBox','Resources','Matrix','Length','Filter'])
 if(String(ap.dict.get(PDFName.of('Type')))!=='/XObject'||String(ap.dict.get(PDFName.of('Subtype')))!=='/Form')fail('output_appearance_type_changed')
 numbers(ap.dict,'BBox',[0,0,round(width),round(height)])
 if(ap.dict.has(PDFName.of('Matrix')))numbers(ap.dict,'Matrix',[1,0,0,1,0,0])
 const turn=((rotation%360)+360)%360,cm=turn===90?[0,height,-width,0,width,0]:turn===180?[-width,0,0,-height,width,height]:turn===270?[0,-height,width,0,0,height]:[width,0,0,height,0,0]
 const tokens=Buffer.from(decodePDFRawStream(ap).decode()).toString('ascii').trim().split(/\s+/)
 if(tokens.length!==11||tokens[0]!=='q'||tokens[7]!=='cm'||tokens[8]!=='/Im0'||tokens[9]!=='Do'||tokens[10]!=='Q'||cm.some((number,index)=>!/^[-+]?(?:\d+(?:\.\d*)?|\.\d+)$/.test(tokens[index+1]!)||Number(tokens[index+1])!==round(number)))fail('output_appearance_cm_changed')
 const resources=ap.dict.lookup(PDFName.of('Resources'),PDFDict);keys(resources,['XObject'])
 const xObjects=resources.lookup(PDFName.of('XObject'),PDFDict);keys(xObjects,['Im0'])
 if(!(xObjects.get(PDFName.of('Im0')) instanceof PDFRef))fail('output_image_reference_changed')
 const rgb=xObjects.lookup(PDFName.of('Im0'));if(!(rgb instanceof PDFRawStream))return fail('output_image_unreadable')
 const pixels=(stream:PDFRawStream,alpha:boolean)=>{
  keys(stream.dict,['Type','Subtype','BitsPerComponent','Width','Height','ColorSpace','Length','Filter',...(alpha?['Decode']:['SMask'])])
  if(String(stream.dict.get(PDFName.of('Type')))!=='/XObject'||String(stream.dict.get(PDFName.of('Subtype')))!=='/Image'||String(stream.dict.get(PDFName.of('BitsPerComponent')))!=='8'||String(stream.dict.get(PDFName.of('ColorSpace')))!==(alpha?'/DeviceGray':'/DeviceRGB')||String(stream.dict.get(PDFName.of('Width')))!==String(image.width)||String(stream.dict.get(PDFName.of('Height')))!==String(image.height)||String(stream.dict.get(PDFName.of('Filter')))!=='/FlateDecode')fail('output_image_properties_changed')
  if(alpha)numbers(stream.dict,'Decode',[0,1])
  const data=decodePDFRawStream(stream).decode()
  if(data.length!==image.width*image.height*(alpha?1:3)||hash(data)!==(alpha?image.alphaSha256:image.rgbSha256))fail('output_image_pixels_changed')
 }
 pixels(rgb,false)
 if(image.alphaSha256){if(!(rgb.dict.get(PDFName.of('SMask')) instanceof PDFRef))fail('output_alpha_reference_changed');const alpha=rgb.dict.lookup(PDFName.of('SMask'));if(!(alpha instanceof PDFRawStream))return fail('output_alpha_unreadable');pixels(alpha,true)}
 else if(rgb.dict.has(PDFName.of('SMask')))fail('output_unexpected_alpha')
}
