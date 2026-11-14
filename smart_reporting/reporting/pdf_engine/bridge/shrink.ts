import {deflateSync,inflateSync} from 'node:zlib'
import {PDFDict,PDFDocument,PDFName,PDFNumber,PDFRawStream,PDFRef} from 'pdf-lib'

const name=(value:string)=>PDFName.of(value)
const integer=(value:unknown)=>{const parsed=Number(String(value??'').replace(/^\//,''));return Number.isFinite(parsed)?parsed:0}
function channels(value:unknown){switch(value instanceof PDFName?value.asString():''){case'/DeviceGray':return 1;case'/DeviceRGB':return 3;case'/DeviceCMYK':return 4;default:return 0}}
function decoded(stream:PDFRawStream){if(stream.dict.get(name('DecodeParms'))!==undefined)return null;try{return new Uint8Array(inflateSync(Buffer.from(stream.contents)))}catch{return null}}
function candidate(doc:PDFDocument,dict:PDFDict){const width=integer(dict.get(name('Width'))),height=integer(dict.get(name('Height'))),cs=doc.context.lookup(dict.get(name('ColorSpace'))),channelCount=channels(cs);if(Math.max(width,height)<=2480||integer(dict.get(name('BitsPerComponent'))??8)!==8||!channelCount||String(dict.get(name('Filter'))) !== '/FlateDecode'||dict.get(name('Matte'))!==undefined)return null;return{width,height,channels:channelCount}}
export function shrinkPdf(content:Uint8Array){
 const docPromise=PDFDocument.load(content,{updateMetadata:false})
 return docPromise.then(async doc=>{
  let streamsRecompressed=0,imagesDownsampled=0
  const baseOfMask=new Map<string,PDFRawStream>(),refKey=(ref:PDFRef)=>`${ref.objectNumber}:${ref.generationNumber}`
  for(const[,object]of doc.context.enumerateIndirectObjects())if(object instanceof PDFRawStream&&String(object.dict.get(name('Subtype')))==='/Image'){const mask=object.dict.get(name('SMask'));if(mask instanceof PDFRef&&doc.context.lookup(mask) instanceof PDFRawStream)baseOfMask.set(refKey(mask),object)}
  const paired=(other:PDFRawStream,mine:NonNullable<ReturnType<typeof candidate>>)=>{const value=candidate(doc,other.dict);return !!value&&value.width===mine.width&&value.height===mine.height}
  for(const[ref,object]of doc.context.enumerateIndirectObjects()){
   if(!(object instanceof PDFRawStream))continue
   const dict=object.dict,isImage=String(dict.get(name('Subtype')))==='/Image',filter=String(dict.get(name('Filter'))??'')
   if(isImage){const value=candidate(doc,dict);if(!value)continue;const mask=dict.get(name('SMask'));if(mask!==undefined){const resolved=mask instanceof PDFRef?doc.context.lookup(mask):null;if(!(resolved instanceof PDFRawStream)||!paired(resolved,value))continue}const base=baseOfMask.get(refKey(ref));if(base&&!paired(base,value))continue
    const pixels=decoded(object);if(!pixels||pixels.length<value.width*value.height*value.channels)continue
    const scale=2480/Math.max(value.width,value.height),width=Math.max(1,Math.floor(value.width*scale)),height=Math.max(1,Math.floor(value.height*scale)),output=new Uint8Array(width*height*value.channels)
    for(let y=0;y<height;y++)for(let x=0;x<width;x++){const src=(Math.min(value.height-1,Math.floor((y+.5)*value.height/height))*value.width+Math.min(value.width-1,Math.floor((x+.5)*value.width/width)))*value.channels,dst=(y*width+x)*value.channels;for(let c=0;c<value.channels;c++)output[dst+c]=pixels[src+c]!}
    const packed=deflateSync(output,{level:9}),next=dict.clone();next.set(name('Width'),PDFNumber.of(width));next.set(name('Height'),PDFNumber.of(height));next.set(name('Length'),PDFNumber.of(packed.length));doc.context.assign(ref,PDFRawStream.of(next,packed));imagesDownsampled++;continue
   }
   if(filter==='/FlateDecode'){const plain=decoded(object);if(!plain)continue;const packed=deflateSync(plain,{level:9});if(packed.length<object.contents.length){doc.context.assign(ref,PDFRawStream.of(dict,packed));streamsRecompressed++}}
  }
  const bytes=await doc.save({useObjectStreams:true});return{bytes,streamsRecompressed,imagesDownsampled}
 })
}
