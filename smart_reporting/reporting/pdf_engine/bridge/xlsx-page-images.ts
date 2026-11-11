import {PNG} from 'pdf-lib/cjs/utils/png.js'
import {applyStaticImage,type DrawingAnchor} from '../../workbook_engine/packages/xlsx-engine/src/chart-add'
import {applyCellEdits} from '../../workbook_engine/packages/xlsx-engine/src/workbook-write'
import {applyRowHeights} from '../../workbook_engine/packages/xlsx-engine/src/geometry'
import {planPageGroups} from '../vendor/pdf2docx/src/rebuild-xlsx/rebuild'
import type {SheetSpec} from '../vendor/pdf2docx/src/rebuild-xlsx/workbook'
import type {ImageBlock,IrPage} from '../vendor/pdf2docx/src/ir'
import {cropRgba,rotateToDisplay} from '../vendor/pdf2docx/src/extract/index'
import {encodeRgbaPng} from '../vendor/pdf2docx/src/extract/png'

const EMU_PER_PT=12700,ROW_PT=15
const MAX_IMAGES=100,MAX_IMAGE_PIXELS=20_000_000,MAX_TOTAL_PIXELS=100_000_000,MAX_BYTES=32*1024*1024
const issue=(error:unknown)=>error instanceof Error?error.message:String(error)

/** The source XLSX builder reflows cells: pictures get their own labelled area,
 * never a full-page bitmap over editable text. IR image pixels already include
 * object transforms/soft masks/page rotation; boxes are crop-origin normalized. */
export async function embedXlsxPageImages(
 sourceBytes:Uint8Array,pages:IrPage[],sheets:SheetSpec[],writer:typeof applyStaticImage=applyStaticImage,
):Promise<{bytes:Uint8Array;warnings:string[]}>{
 let bytes=sourceBytes,count=0,totalPixels=0,totalBytes=0
 const warnings:string[]=[]
 const groups=planPageGroups(pages)
 for(const [groupIndex,group]of groups.entries()){
  const sheet=sheets[groupIndex]
  if(!sheet){warnings.push('XLSX 图片目标工作表缺失；已保留原工作簿。');continue}
  let lastRow=sheet.cells.reduce((last,cell)=>Math.max(last,cell.row),-1)
  for(const range of sheet.merges??[]){const end=/[A-Z]+([0-9]+)$/.exec(range);if(end)lastRow=Math.max(lastRow,Number(end[1])-1)}
  let nextRow=lastRow+4
  for(const index of group){
   const original=pages[index]!
   const page=displayImagePage(original)
   if(page.scanned||page.degraded)continue
   const images=page.blocks.filter((block):block is ImageBlock=>block.kind==='image'&&!block.synthetic).sort((a,b)=>(a.z??0)-(b.z??0))
   if(!images.length)continue
   const pageLabel='Page '+(page.index+1)
   if(!Number.isFinite(page.widthPt)||!Number.isFinite(page.heightPt)||page.widthPt<=0||page.heightPt<=0){warnings.push(pageLabel+': 图片页面尺寸无效，已跳过。');continue}
   const startRow=nextRow+2,rows=Math.ceil(page.heightPt/ROW_PT)+1
   nextRow=startRow+rows+3
   if(nextRow>=1_048_576){warnings.push(pageLabel+': 图片参考区超出 Excel 行预算，已跳过。');continue}
   try{
    let staged=await applyCellEdits(bytes,[{sheetName:sheet.name,row:startRow-2,column:0,writeValue:true,cell:{value:pageLabel+' 图片位置参考区（位于可编辑单元格之后；不代表原图文相对排版）'}}])
    staged=await applyRowHeights(staged,sheet.name,Array.from({length:rows},(_,row)=>({index:startRow+row,heightPoints:ROW_PT})))
    bytes=staged
   }catch(error){warnings.push(pageLabel+': 图片参考区准备失败，已保留已有工作簿：'+issue(error));continue}
   let added=0
   for(const [imageIndex,image]of images.entries()){
    const prefix=pageLabel+' image '+(imageIndex+1)+': '
    const pixels=image.pixelWidth*image.pixelHeight
    if(++count>MAX_IMAGES||!Number.isSafeInteger(pixels)||pixels<=0||pixels>MAX_IMAGE_PIXELS||totalPixels+pixels>MAX_TOTAL_PIXELS||totalBytes+image.data.length>MAX_BYTES){warnings.push(prefix+'超过图片数量/像素/32 MiB预算，已跳过。');continue}
    totalPixels+=pixels;totalBytes+=image.data.length
    try{
     const clipped=clipPageImage(image,page)
     if(!clipped){warnings.push(prefix+'位于可见页边界之外，已跳过。');continue}
     const anchor=imageAnchor(sheet,startRow,clipped.box,page.heightPt)
     const output=await writer(bytes,{worksheetSheetName:sheet.name,imageId:'pdf-page-'+(page.index+1)+'-image-'+(imageIndex+1),bytes:clipped.data,contentType:clipped.mime,anchor})
     bytes=output.bytes;added++
    }catch(error){warnings.push(prefix+'图片保留失败，已保留已有工作簿：'+issue(error))}
   }
   warnings.push(pageLabel+': '+added+'/'+images.length+' 张源图片保留在单元格后的图片位置参考区；不代表原图文相对排版。')
  }
 }
 return {bytes,warnings}
}

function columnMarker(sheet:SheetSpec,positionPt:number):[number,number]{
 let remaining=positionPt
 for(let column=0;column<16_384;column++){
  // Same 96-DPI / seven-pixel default-digit convention used by the existing
  // XLSX builder and workbook renderer. Widths serialize to two decimals.
  const width=sheet.colWidths?.[column]
  const points=(width===undefined?64:Math.max(1,Math.round(Number(width.toFixed(2))*7+5)))*0.75
  if(remaining<points)return [column,Math.round(remaining*EMU_PER_PT)]
  remaining-=points
 }
 throw Error('图片参考区超出 Excel 列预算')
}
function imageAnchor(sheet:SheetSpec,startRow:number,box:ImageBlock['box'],heightPt:number):DrawingAnchor{
 const [fromColumn,fromColumnOffset]=columnMarker(sheet,box.x0),[toColumn,toColumnOffset]=columnMarker(sheet,box.x1)
 const top=(heightPt-box.y1)/ROW_PT,bottom=(heightPt-box.y0)/ROW_PT
 const from=Math.floor(top),to=Math.floor(bottom)
 return {fromRow:startRow+from,fromRowOffset:Math.round((top-from)*ROW_PT*EMU_PER_PT),fromColumn,fromColumnOffset,toRow:startRow+to,toRowOffset:Math.round((bottom-to)*ROW_PT*EMU_PER_PT),toColumn,toColumnOffset}
}

/** Preserve the visible CropBox intersection, never squeeze the full bitmap
 * into a clipped box. Only boundary-crossing PNGs need decoding; an unsupported
 * JPEG crop is explicitly skipped rather than silently distorted. */
function clipPageImage(image:ImageBlock,page:IrPage):ImageBlock|null{
 const b=image.box
 if(![b.x0,b.x1,b.y0,b.y1].every(Number.isFinite)||b.x1<=b.x0||b.y1<=b.y0)throw Error('图片几何无效')
 const box={x0:Math.max(0,b.x0),y0:Math.max(0,b.y0),x1:Math.min(page.widthPt,b.x1),y1:Math.min(page.heightPt,b.y1)}
 if(box.x1<=box.x0||box.y1<=box.y0)return null
 if(box.x0===b.x0&&box.y0===b.y0&&box.x1===b.x1&&box.y1===b.y1)return image
 if(image.mime!=='image/png')throw Error('跨可见页边界的 JPEG 暂不能安全裁剪')
 const png=PNG.load(image.data)
 if(png.width!==image.pixelWidth||png.height!==image.pixelHeight)throw Error('图片实际像素身份不一致')
 const rgba=new Uint8Array(png.width*png.height*4)
 for(let i=0;i<png.width*png.height;i++){rgba[i*4]=png.rgbChannel[i*3]!;rgba[i*4+1]=png.rgbChannel[i*3+1]!;rgba[i*4+2]=png.rgbChannel[i*3+2]!;rgba[i*4+3]=png.alphaChannel?.[i]??255}
 const cropped=cropRgba({rgba,width:png.width,height:png.height},{left:(box.x0-b.x0)/(b.x1-b.x0),right:(b.x1-box.x1)/(b.x1-b.x0),top:(b.y1-box.y1)/(b.y1-b.y0),bottom:(box.y0-b.y0)/(b.y1-b.y0)})
 if(!cropped)throw Error('图片可见像素裁剪失败')
 return {...image,box,data:encodeRgbaPng(cropped.rgba,cropped.width,cropped.height),pixelWidth:cropped.width,pixelHeight:cropped.height}
}

function displayImagePage(page:IrPage):IrPage{
 if(page.cellDataRotation===undefined)return page
 // Cell-data extraction turns geometry upright without rotating encoded image
 // pixels. Undo ONLY that exact recorded turn; original /Rotate pixels stay.
 const widthPt=page.heightPt,heightPt=page.widthPt
 const inverse=rotateToDisplay(page.cellDataRotation===1?3:1,widthPt,heightPt)
 return {...page,widthPt,heightPt,blocks:page.blocks.map(block=>{
  if(block.kind!=='image')return block
  const box={...block.box};inverse.rect(box);return {...block,box}
 })}
}
